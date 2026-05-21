from __future__ import annotations

import asyncio
from collections import Counter
import json
import logging
import math
import re
import unicodedata
from contextlib import nullcontext
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.schemas.voice_assistant import VoiceAssistantResponse, VoiceAssistantSource
from app.services.classifier import get_classifier_service, install_sklearn_stub
from app.services.classifier_prompt import apply_classifier_chat_template

settings = get_settings()
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parents[1] / "data" / "kpi_faq_knowledge_base.json"
TOKEN_RE = re.compile(r"[0-9a-zа-щьюяґєії']{2,}", re.IGNORECASE)
NON_TOKEN_RE = re.compile(r"[^0-9a-zа-щьюяґєії]+", re.IGNORECASE)
STOP_WORDS = {
    "або",
    "але",
    "без",
    "буде",
    "бути",
    "вам",
    "ваш",
    "вже",
    "для",
    "де",
    "до",
    "за",
    "запитання",
    "звернутися",
    "зробити",
    "із",
    "його",
    "кпі",
    "мене",
    "може",
    "можна",
    "моє",
    "на",
    "не",
    "по",
    "про",
    "та",
    "так",
    "треба",
    "у",
    "чи",
    "що",
    "як",
    "який",
    "яка",
    "якщо",
    "куди",
    "питання",
    "дізнатись",
    "дізнатися",
    "отримати",
    "подати",
    "взяти",
    "оформити",
}

UKRAINIAN_SUFFIXES = (
    "ність",
    "ності",
    "ністю",
    "ання",
    "ення",
    "ами",
    "ями",
    "ого",
    "ему",
    "ому",
    "ими",
    "ої",
    "ою",
    "ею",
    "ах",
    "ях",
    "ам",
    "ям",
    "ом",
    "ем",
    "ів",
    "їв",
    "ий",
    "ій",
    "их",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "є",
    "и",
    "і",
    "о",
)

SEARCH_FIELDS = ("title", "question", "tags", "answer")


@dataclass(frozen=True)
class KnowledgeBaseEntry:
    id: str
    title: str
    question: str
    answer: str
    source_url: str
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "KnowledgeBaseEntry":
        return cls(
            id=str(raw["id"]),
            title=str(raw["title"]),
            question=str(raw["question"]),
            answer=str(raw["answer"]),
            source_url=str(raw["source_url"]),
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
        )

    @property
    def primary_text(self) -> str:
        return " ".join([self.title, self.question, " ".join(self.tags)])

    @property
    def full_text(self) -> str:
        return " ".join([self.primary_text, self.answer])


@dataclass(frozen=True)
class KnowledgeMatch:
    entry: KnowledgeBaseEntry
    score: float


@dataclass(frozen=True)
class EntrySearchIndex:
    entry: KnowledgeBaseEntry
    tokens: dict[str, tuple[str, ...]]
    stems: dict[str, set[str]]
    ngrams: dict[str, set[str]]


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def normalize_for_search(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.casefold().replace("’", "'").replace("`", "'")
    return normalize_text(normalized)


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in TOKEN_RE.findall(normalize_for_search(value))
        if token.casefold() not in STOP_WORDS
    )


def stem_token(token: str) -> str:
    if len(token) < 6:
        return token
    for suffix in UKRAINIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            return token[: -len(suffix)]
    return token


def char_ngrams(value: str, *, size: int = 4) -> set[str]:
    compact = f" {NON_TOKEN_RE.sub(' ', normalize_for_search(value))} "
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def field_tokens(entry: KnowledgeBaseEntry) -> dict[str, str]:
    return {
        "title": entry.title,
        "question": entry.question,
        "tags": " ".join(entry.tags),
        "answer": entry.answer,
    }


def token_match_quality(query_token: str, query_stem: str, field_tokens: set[str], field_stems: set[str]) -> float:
    if query_token in field_tokens or query_stem in field_stems:
        return 1.0
    if len(query_stem) < 7:
        return 0.0
    for field_stem in field_stems:
        if len(field_stem) < 7:
            continue
        common_prefix = 0
        for left, right in zip(query_stem, field_stem):
            if left != right:
                break
            common_prefix += 1
        if common_prefix >= 6 and common_prefix / min(len(query_stem), len(field_stem)) >= 0.72:
            return 0.65
    return 0.0


def ngram_similarity(query_ngrams: set[str], document_ngrams: set[str]) -> float:
    if not query_ngrams or not document_ngrams:
        return 0.0
    return len(query_ngrams & document_ngrams) / len(query_ngrams)


def phrase_match_score(query_stems: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    if len(query_stems) < 2:
        return 0.0
    document_stems = tuple(stem_token(token) for token in document_tokens)
    query_pairs = list(zip(query_stems, query_stems[1:]))
    if not query_pairs:
        return 0.0

    matched_pairs = 0
    for left, right in query_pairs:
        for index in range(len(document_stems) - 1):
            if document_stems[index] == left and document_stems[index + 1] == right:
                matched_pairs += 1
                break
    return matched_pairs / len(query_pairs)


class KnowledgeBaseService:
    def __init__(self, path: Path = KNOWLEDGE_BASE_PATH) -> None:
        raw_entries = json.loads(path.read_text(encoding="utf-8"))
        self.entries = [KnowledgeBaseEntry.from_dict(item) for item in raw_entries]
        self._index = [self._build_index(entry) for entry in self.entries]
        self._idf = self._build_idf(self._index)

    @staticmethod
    def _build_index(entry: KnowledgeBaseEntry) -> EntrySearchIndex:
        fields = field_tokens(entry)
        tokens = {field: tokenize(value) for field, value in fields.items()}
        return EntrySearchIndex(
            entry=entry,
            tokens=tokens,
            stems={field: {stem_token(token) for token in values} for field, values in tokens.items()},
            ngrams={field: char_ngrams(value) for field, value in fields.items()},
        )

    @staticmethod
    def _build_idf(index: list[EntrySearchIndex]) -> dict[str, float]:
        document_frequency: Counter[str] = Counter()
        for item in index:
            document_stems = set().union(*(item.stems[field] for field in SEARCH_FIELDS))
            document_frequency.update(document_stems)

        document_count = len(index)
        return {
            stem: math.log((document_count + 1) / (count + 0.5)) + 1
            for stem, count in document_frequency.items()
        }

    def search(self, question: str, *, limit: int | None = None) -> list[KnowledgeMatch]:
        query_tokens = tokenize(question)
        if not query_tokens:
            return []

        matches = []
        query_stems = tuple(stem_token(token) for token in query_tokens)
        query_ngrams = char_ngrams(question)
        for item in self._index:
            score = self._score_entry(query_tokens, query_stems, query_ngrams, item)
            if score > 0:
                matches.append(KnowledgeMatch(entry=item.entry, score=round(score, 4)))

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[: limit or settings.voice_assistant_max_context_items]

    def _coverage(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        document_tokens: set[str],
        document_stems: set[str],
    ) -> float:
        denominator = sum(self._idf.get(stem, 2.0) for stem in query_stems)
        if denominator <= 0:
            return 0.0

        score = 0.0
        for token, stem in zip(query_tokens, query_stems):
            score += self._idf.get(stem, 2.0) * token_match_quality(
                token,
                stem,
                document_tokens,
                document_stems,
            )
        return score / denominator

    def _score_entry(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        query_ngrams: set[str],
        item: EntrySearchIndex,
    ) -> float:
        primary_tokens = set(item.tokens["title"]) | set(item.tokens["question"]) | set(item.tokens["tags"])
        primary_stems = item.stems["title"] | item.stems["question"] | item.stems["tags"]
        full_tokens = primary_tokens | set(item.tokens["answer"])
        full_stems = primary_stems | item.stems["answer"]

        title_coverage = self._coverage(query_tokens, query_stems, set(item.tokens["title"]), item.stems["title"])
        question_coverage = self._coverage(
            query_tokens,
            query_stems,
            set(item.tokens["question"]),
            item.stems["question"],
        )
        tag_coverage = self._coverage(query_tokens, query_stems, set(item.tokens["tags"]), item.stems["tags"])
        primary_coverage = self._coverage(query_tokens, query_stems, primary_tokens, primary_stems)
        answer_coverage = self._coverage(
            query_tokens,
            query_stems,
            set(item.tokens["answer"]),
            item.stems["answer"],
        )
        full_coverage = self._coverage(query_tokens, query_stems, full_tokens, full_stems)

        primary_ngram_score = max(
            ngram_similarity(query_ngrams, item.ngrams["title"]),
            ngram_similarity(query_ngrams, item.ngrams["question"]),
            ngram_similarity(query_ngrams, item.ngrams["tags"]),
        )
        answer_ngram_score = ngram_similarity(query_ngrams, item.ngrams["answer"])
        primary_phrase_score = max(
            phrase_match_score(query_stems, item.tokens["title"]),
            phrase_match_score(query_stems, item.tokens["question"]),
            phrase_match_score(query_stems, item.tokens["tags"]),
        )
        answer_phrase_score = phrase_match_score(query_stems, item.tokens["answer"])

        field_score = max(
            title_coverage,
            question_coverage * 0.95,
            tag_coverage * 0.9,
            primary_coverage * 0.86,
        )
        score = (
            field_score * 0.55
            + full_coverage * 0.2
            + primary_ngram_score * 0.08
            + answer_ngram_score * 0.04
            + primary_phrase_score * 0.08
            + answer_phrase_score * 0.3
        )

        if primary_coverage < 0.34 and answer_coverage > 0 and answer_phrase_score == 0:
            score *= 0.68
        if len(query_tokens) <= 2 and primary_coverage < 0.75 and answer_phrase_score == 0:
            score *= 0.82

        return min(score, 1.0)


class BaseQwenAssistantService:
    def __init__(self) -> None:
        self.uses_classifier_model = False
        if settings.voice_assistant_reuse_classifier_model:
            try:
                classifier = get_classifier_service()
                self.torch = classifier.torch
                self.tokenizer = classifier.tokenizer
                self.model = classifier.model
                self.model_name = f"{settings.llm_base_model} без LoRA"
                self.uses_classifier_model = True
                self.model.eval()
                return
            except RuntimeError:
                logger.exception("Could not reuse classifier model for voice assistant.")

        try:
            import torch

            install_sklearn_stub()
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("transformers and torch are required for assistant inference.") from exc

        self.torch = torch
        self.model_name = settings.llm_base_model
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.llm_base_model,
            trust_remote_code=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.llm_base_model,
            device_map=settings.llm_device,
            torch_dtype="auto",
            trust_remote_code=True,
        )
        self.model.eval()

    def generate_answer(self, question: str, matches: list[KnowledgeMatch]) -> str:
        messages = self._build_messages(question, matches)
        model_input = apply_classifier_chat_template(
            self.tokenizer,
            messages,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(model_input, return_tensors="pt")
        model_device = getattr(self.model, "device", None)
        if model_device is not None:
            inputs = inputs.to(model_device)

        adapter_context = (
            self.model.disable_adapter()
            if self.uses_classifier_model and hasattr(self.model, "disable_adapter")
            else nullcontext()
        )
        with self.torch.no_grad(), adapter_context:
            generated = self.model.generate(
                **inputs,
                max_new_tokens=settings.voice_assistant_max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated_ids = generated[0][inputs["input_ids"].shape[-1] :]
        raw = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        return self._clean_answer(raw)

    @staticmethod
    def _build_messages(question: str, matches: list[KnowledgeMatch]) -> list[dict[str, str]]:
        context = "\n\n".join(
            (
                f"Джерело {index}: {match.entry.title}\n"
                f"URL: {match.entry.source_url}\n"
                f"Питання FAQ: {match.entry.question}\n"
                f"Інформація: {match.entry.answer}"
            )
            for index, match in enumerate(matches, start=1)
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти голосовий консультант довідкової служби КПІ. "
                    "Відповідай українською, коротко, доброзичливо і природно для усного мовлення. "
                    "Не використовуй режим міркування, не генеруй <think> і не пояснюй хід думок. "
                    "Давай не більше двох коротких речень, щоб відповідь було зручно слухати телефоном. "
                    "Використовуй тільки надані джерела. "
                    "Якщо в джерелах недостатньо інформації, скажи, що краще створити заявку."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    f"Доступні джерела:\n{context}\n\n"
                    "Сформуй одну коротку відповідь для озвучення голосом: максимум два речення і приблизно до 450 символів. "
                    "Не додавай Markdown, URL, списки й службові пояснення."
                ),
            },
        ]

    @staticmethod
    def _clean_answer(raw: str) -> str:
        answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].strip()
        answer = answer.strip("` \n\r\t")
        return normalize_text(answer)


class VoiceAssistantService:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBaseService()

    async def answer(self, question_text: str) -> VoiceAssistantResponse:
        question = normalize_text(question_text)
        return await asyncio.to_thread(self._answer_sync, question)

    def _answer_sync(self, question: str) -> VoiceAssistantResponse:
        matches = self.knowledge_base.search(question)
        if not self._has_reliable_match(matches):
            return self._fallback_response(question)

        best_score = matches[0].score
        used_llm = False
        model_name: str | None = None
        answer_text = ""
        if settings.voice_assistant_use_llm:
            try:
                llm = get_base_qwen_assistant_service()
                answer_text = llm.generate_answer(question, matches)
                used_llm = bool(answer_text)
                model_name = llm.model_name if used_llm else None
            except RuntimeError:
                logger.exception("Voice assistant LLM generation failed.")
                return self._llm_unavailable_response(question, matches)

        if not answer_text:
            if settings.voice_assistant_use_llm:
                return self._llm_unavailable_response(question, matches)
            answer_text = self._extractive_answer(matches[0].entry)

        return VoiceAssistantResponse(
            question_text=question,
            answer_text=answer_text,
            confidence=best_score,
            source="llm" if used_llm else "knowledge_base",
            sources=self._sources(matches),
            can_create_ticket=True,
            used_llm=used_llm,
            model_name=model_name,
        )

    @staticmethod
    def _has_reliable_match(matches: list[KnowledgeMatch]) -> bool:
        if not matches:
            return False
        best_score = matches[0].score
        return best_score >= settings.voice_assistant_min_confidence

    @staticmethod
    def _extractive_answer(entry: KnowledgeBaseEntry) -> str:
        return normalize_text(
            f"{entry.answer} Якщо потрібно, можу створити заявку оператору для уточнення."
        )

    @staticmethod
    def _sources(matches: list[KnowledgeMatch]) -> list[VoiceAssistantSource]:
        return [
            VoiceAssistantSource(
                title=match.entry.title,
                url=match.entry.source_url,
                score=match.score,
            )
            for match in matches
        ]

    def _fallback_response(self, question: str) -> VoiceAssistantResponse:
        return VoiceAssistantResponse(
            question_text=question,
            answer_text=(
                "Я не знайшов точну відповідь в офіційній базі знань КПІ. "
                "Можу створити заявку оператору, щоб ваше питання розглянули вручну."
            ),
            confidence=0,
            source="fallback",
            sources=[],
            can_create_ticket=True,
            used_llm=False,
            model_name=None,
        )

    def _llm_unavailable_response(
        self,
        question: str,
        matches: list[KnowledgeMatch],
    ) -> VoiceAssistantResponse:
        return VoiceAssistantResponse(
            question_text=question,
            answer_text=(
                "ШІ-модель зараз не змогла сформувати автоматичну відповідь. "
                "Можу створити заявку оператору, щоб ваше питання розглянули вручну."
            ),
            confidence=matches[0].score if matches else 0,
            source="llm_unavailable",
            sources=self._sources(matches),
            can_create_ticket=True,
            used_llm=False,
            model_name=None,
        )


@lru_cache
def get_knowledge_base_service() -> KnowledgeBaseService:
    return KnowledgeBaseService()


@lru_cache
def get_base_qwen_assistant_service() -> BaseQwenAssistantService:
    return BaseQwenAssistantService()


@lru_cache
def get_voice_assistant_service() -> VoiceAssistantService:
    return VoiceAssistantService()
