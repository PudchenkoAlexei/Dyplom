from __future__ import annotations

import asyncio
from collections import Counter
import json
import logging
import math
import re
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, cast

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
ANSWER_TEXT_REPLACEMENTS = (
    (
        re.compile(
            r"\b([а-щьюяґєії'’]+)\s+загублен(?:ий|а|е|і),\s+пошкоджен(?:ий|а|е|і)\s+або\s+втрачено\b",
            re.IGNORECASE,
        ),
        r"\1 втрачено або пошкоджено",
    ),
    (re.compile(r"\bбувші\b", re.IGNORECASE), "колишні"),
    (re.compile(r"\bбувших\b", re.IGNORECASE), "колишніх"),
    (re.compile(r"\bбувшим\b", re.IGNORECASE), "колишнім"),
    (re.compile(r"\bбувши студенти\b", re.IGNORECASE), "колишні студенти"),
    (re.compile(r"\bбувших студентів\b", re.IGNORECASE), "колишніх студентів"),
    (re.compile(r"\bбувшим студентам\b", re.IGNORECASE), "колишнім студентам"),
    (re.compile(r"\bархіва\b", re.IGNORECASE), "архіву"),
    (re.compile(r"\bПри собі мати\b"), "Потрібно мати при собі"),
    (re.compile(r"\s*\(\s*корпус\s+(\d+)\s*\)", re.IGNORECASE), r" у корпусі \1"),
    (re.compile(r"\bВ листі\b"), "У листі"),
)
ANSWER_INTRO_DROP_PATTERNS = (
    re.compile(
        r"^\s*(?:як|що|де|коли|куди|з яких|які|який|яка|чи|скільки|кому|хто)\b[^.?!]{8,360}[.?!]\s*",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*Це (?:простий|нескладний) процес[^.?!]*[.?!]\s*", re.IGNORECASE),
)


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
class GuidedSearchPlan:
    queries: tuple[str, ...]
    raw_response: str


class GenerativeModel(Protocol):
    def eval(self) -> Any: ...

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...


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
    def __init__(
        self,
        *,
        model_name: str | None = None,
        reuse_classifier_model: bool | None = None,
        quantization: str | None = None,
    ) -> None:
        target_model_name = model_name or settings.voice_assistant_model
        should_reuse_classifier = (
            settings.voice_assistant_reuse_classifier_model
            if reuse_classifier_model is None
            else reuse_classifier_model
        )
        target_quantization = quantization or settings.voice_assistant_quantization
        self.uses_classifier_model = False
        if should_reuse_classifier:
            try:
                classifier = get_classifier_service()
                self.torch = classifier.torch
                self.tokenizer = classifier.tokenizer
                self.model: GenerativeModel = cast(GenerativeModel, classifier.model)
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
        self.model_name = target_model_name
        self.tokenizer = AutoTokenizer.from_pretrained(
            target_model_name,
            trust_remote_code=True,
        )
        model_kwargs = self._build_model_load_kwargs(
            torch,
            quantization=target_quantization,
        )
        self.model = cast(
            GenerativeModel,
            AutoModelForCausalLM.from_pretrained(
                target_model_name,
                trust_remote_code=True,
                **model_kwargs,
            ),
        )
        if target_quantization != "none":
            self.model_name = f"{target_model_name} ({target_quantization})"
        self.model.eval()

    @staticmethod
    def _build_model_load_kwargs(torch_module: Any, *, quantization: str) -> dict[str, Any]:
        if quantization == "none":
            return {
                "device_map": settings.llm_device,
                "torch_dtype": "auto",
            }

        if not torch_module.cuda.is_available():
            raise RuntimeError("Quantized assistant inference requires CUDA/GPU.")

        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError("bitsandbytes is required for quantized assistant inference.") from exc

        if quantization == "8bit":
            return {
                "device_map": settings.llm_device,
                "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
            }
        if quantization == "4bit":
            return {
                "device_map": settings.llm_device,
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch_module.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                ),
            }

        raise RuntimeError(f"Unsupported assistant quantization mode: {quantization}")

    def _generate_from_messages(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
    ) -> str:
        model_input = apply_classifier_chat_template(
            self.tokenizer,
            messages,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(model_input, return_tensors="pt")
        model_device = getattr(self.model, "device", None)
        if model_device is not None:
            inputs = inputs.to(model_device)

        adapter_context: AbstractContextManager[Any] = nullcontext()
        disable_adapter = getattr(self.model, "disable_adapter", None)
        if self.uses_classifier_model and callable(disable_adapter):
            adapter_context = cast(
                Callable[[], AbstractContextManager[Any]],
                disable_adapter,
            )()
        with self.torch.no_grad(), adapter_context:
            generated = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated_ids = generated[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated_ids, skip_special_tokens=True)

    def plan_search_queries(self, question: str) -> GuidedSearchPlan:
        messages = self._build_search_messages(question)
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=160,
        )
        queries = self._parse_search_queries(raw, fallback_query=question)
        return GuidedSearchPlan(queries=queries, raw_response=raw)

    def generate_answer(
        self,
        question: str,
        matches: list[KnowledgeMatch],
        *,
        allow_related_sources: bool = False,
        max_new_tokens: int | None = None,
        for_phone: bool = False,
    ) -> str:
        if for_phone:
            messages = self._build_phone_answer_messages(question, matches)
        else:
            messages = self._build_answer_messages(
                question,
                matches,
                allow_related_sources=allow_related_sources,
            )
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=max_new_tokens or settings.voice_assistant_max_new_tokens,
        )
        return self._clean_answer(raw)

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise RuntimeError(f"Model did not return JSON: {raw}")
        parsed = json.loads(stripped[start : end + 1])
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Model returned non-object JSON: {raw}")
        return parsed

    @staticmethod
    def _parse_search_queries(raw: str, *, fallback_query: str) -> tuple[str, ...]:
        try:
            parsed = BaseQwenAssistantService._extract_json_object(raw)
        except (RuntimeError, json.JSONDecodeError):
            parsed = {}

        raw_queries = parsed.get("queries")
        if isinstance(raw_queries, str):
            query_values = [raw_queries]
        elif isinstance(raw_queries, list):
            query_values = [item for item in raw_queries if isinstance(item, str)]
        else:
            query_values = []

        normalized_queries: list[str] = []
        seen: set[str] = set()
        for query in [*query_values, fallback_query]:
            normalized = normalize_text(query)[:160]
            dedupe_key = normalize_for_search(normalized)
            if len(normalized) < 3 or dedupe_key in seen:
                continue
            normalized_queries.append(normalized)
            seen.add(dedupe_key)
            if len(normalized_queries) >= settings.voice_assistant_search_query_count:
                break

        return tuple(normalized_queries or [normalize_text(fallback_query)])

    @staticmethod
    def _build_search_messages(question: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Ти планувальник пошуку для голосової довідкової КПІ. "
                    "Твоя єдина дія - викликати інструмент search_kpi_faq через JSON. "
                    "Не відповідай користувачу напряму, не міркуй уголос, не генеруй <think>. "
                    "Сформуй до кількох коротких українських пошукових запитів, які допоможуть "
                    "знайти релевантні FAQ-джерела навіть після помилок розпізнавання мовлення."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    "Поверни тільки JSON без Markdown у форматі: "
                    '{"tool":"search_kpi_faq","queries":["запит 1","запит 2"]}. '
                    "Запити мають бути короткими, без URL і без вигаданих фактів."
                ),
            },
        ]

    @staticmethod
    def _build_answer_messages(
        question: str,
        matches: list[KnowledgeMatch],
        *,
        allow_related_sources: bool,
    ) -> list[dict[str, str]]:
        context = "\n\n".join(
            (
                f"Тема джерела {index}: {match.entry.title}\n"
                f"Довідкова інформація для відповіді: {match.entry.answer}"
            )
            for index, match in enumerate(matches, start=1)
        )
        freedom_rule = (
            "Джерела можуть бути лише частково релевантними. Якщо збіг приблизний, прямо скажи, "
            "що інформація схожа або неповна, і дай обережну відповідь тільки в межах доступних джерел. "
            "Можеш узагальнювати й пояснювати за аналогією з релевантними фрагментами, але не називай "
            "точні дедлайни, суми, телефони чи обов'язкові процедури, якщо їх немає в джерелах."
            if allow_related_sources
            else (
                "Відповідай на основі джерел. Можеш природно перефразовувати, поєднувати релевантні "
                "фрагменти й пояснювати їх простішими словами. Якщо джерела не містять певної деталі, "
                "чесно скажи, що в наданій інформації цього немає."
            )
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти голосовий консультант довідкової служби КПІ. "
                    "Відповідай українською, природно для усного мовлення і тільки з наданих джерел. "
                    "Одразу починай із відповіді; не повторюй питання, FAQ, заголовки, URL, джерела, "
                    "заявку чи оператора. Не генеруй <think> і не пояснюй хід думок. "
                    "Пиши щільно: не обмежуй кількість речень, але кожне речення має додавати "
                    "новий факт, документ, умову, адресу або дію. Прибирай вступи, оцінки й загальні "
                    "фрази без нової інформації. "
                    "Не скорочуй пакети документів: якщо є перелік, двокрапка або пункти через крапку "
                    "з комою, назви кожен пункт. Якщо спільне слово стосується кількох документів, "
                    "повтори його для кожного документа. "
                    "Пиши літературною українською, виправляй русизми, кальки, невдалі відмінки "
                    "й неприродні формулювання. Використовуй однотипні граматичні форми в переліках. "
                    f"{freedom_rule} "
                    "Не вигадуй офіційні правила, контакти, дедлайни, суми або гарантії поза джерелами. "
                    "Не пропонуй створювати заявку, звернення або передавати питання оператору."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    f"Доступні джерела:\n{context}\n\n"
                    "Сформуй одну зв'язну змістовну відповідь для озвучення голосом. "
                    "Почни з конкретної відповіді, без вступної фрази й без загальних міркувань. "
                    "Без Markdown, URL, списків, службових пояснень і згадок про створення заявки."
                ),
            },
        ]

    @staticmethod
    def _build_phone_answer_messages(
        question: str,
        matches: list[KnowledgeMatch],
    ) -> list[dict[str, str]]:
        context = "\n\n".join(
            f"Факти {index}: {BaseQwenAssistantService._clean_answer(match.entry.answer)}"
            for index, match in enumerate(matches, start=1)
        )
        style_rules = (
            "Одразу дай відповідь. Не повторюй питання, FAQ, заголовки, джерела, URL, "
            "заявку чи оператора. Не додавай вступ, підсумок або пояснення без нового факту. "
            "Не обмежуй кількість речень, але кожне речення має додавати новий факт, документ, "
            "умову, адресу або дію. Якщо відповідь проста - скажи її коротко; якщо є пакет "
            "документів - назви всі документи."
        )
        completeness_rules = (
            "Не пропускай документи, корпуси, адреси й умови. Якщо у фактах є перелік, двокрапка "
            "або пункти через крапку з комою, збережи кожен пункт. Не об'єднуй різні документи. "
            "Якщо написано 'копія A та B', скажи 'копія A та копія B'. Умови на кшталт "
            "'якщо немає' пояснюй після основного документа, а не замість нього."
        )
        grammar_rules = (
            "Пиши грамотною українською для озвучення телефоном: 'колишні' замість 'бувші', "
            "'архіву' замість 'архіва', 'потрібно мати при собі' замість 'при собі мати'. "
            "Розшифровуй скорочення: 'м.' - 'місто', 'пр.' - 'проспект', 'ім.' - 'імені'. "
            "У переліках використовуй однотипні граматичні форми."
        )
        group_rules = (
            "Якщо факти мають різні групи людей, не змішуй їх: окремо студенти, окремо випускники "
            "чи колишні студенти. Не перенось документи або умови з однієї групи на іншу."
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти телефонний консультант КПІ. Відповідай українською, усно й тільки з фактів. "
                    f"{style_rules} {completeness_rules} {group_rules} {grammar_rules}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання: {question}\n\n"
                    f"{context}\n\n"
                    "Сформуй одну зв'язну відповідь для телефонного дзвінка. "
                    "Без Markdown, маркованих списків і службових пояснень."
                ),
            },
        ]

    @staticmethod
    def _clean_answer(raw: str) -> str:
        answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].strip()
        answer = answer.strip("` \n\r\t")
        answer = re.sub(r"\*\*(.*?)\*\*", r"\1", answer)
        for pattern in ANSWER_INTRO_DROP_PATTERNS:
            answer = pattern.sub("", answer, count=1)
        for pattern, replacement in ANSWER_TEXT_REPLACEMENTS:
            answer = pattern.sub(replacement, answer)
        if answer and answer[-1] not in ".!?…":
            complete_answer = re.sub(r"\s+[^.!?…]*$", "", answer)
            if len(complete_answer) >= 40:
                answer = complete_answer
        return normalize_text(answer)


class OpenAICompatibleAssistantService:
    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        temperature: float,
    ) -> None:
        self.model_name = f"{model_name} via OpenAI-compatible"
        self._model_id = model_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature

    def _generate_from_messages(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for OpenAI-compatible inference.") from exc

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model_id,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": self._temperature,
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible assistant inference failed.") from exc

        if not isinstance(content, str):
            raise RuntimeError("OpenAI-compatible assistant returned non-text content.")
        return content

    def plan_search_queries(self, question: str) -> GuidedSearchPlan:
        messages = BaseQwenAssistantService._build_search_messages(question)
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=160,
        )
        queries = BaseQwenAssistantService._parse_search_queries(raw, fallback_query=question)
        return GuidedSearchPlan(queries=queries, raw_response=raw)

    def generate_answer(
        self,
        question: str,
        matches: list[KnowledgeMatch],
        *,
        allow_related_sources: bool = False,
        max_new_tokens: int | None = None,
        for_phone: bool = False,
    ) -> str:
        if for_phone:
            messages = BaseQwenAssistantService._build_phone_answer_messages(question, matches)
        else:
            messages = BaseQwenAssistantService._build_answer_messages(
                question,
                matches,
                allow_related_sources=allow_related_sources,
            )
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=max_new_tokens or settings.voice_assistant_max_new_tokens,
        )
        return BaseQwenAssistantService._clean_answer(raw)


AssistantService = BaseQwenAssistantService | OpenAICompatibleAssistantService


class VoiceAssistantService:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBaseService()

    async def answer(self, question_text: str, *, for_phone: bool = False) -> VoiceAssistantResponse:
        question = normalize_text(question_text)
        return await asyncio.to_thread(self._answer_sync, question, for_phone=for_phone)

    def _answer_sync(self, question: str, *, for_phone: bool = False) -> VoiceAssistantResponse:
        direct_matches = self.knowledge_base.search(question)
        matches = direct_matches
        guided_retrieval_used = False
        llm: AssistantService | None = None
        llm_enabled = settings.voice_assistant_use_llm and (
            settings.voice_assistant_phone_use_llm if for_phone else True
        )
        guided_retrieval_enabled = (
            settings.voice_assistant_phone_ai_guided_retrieval
            if for_phone
            else settings.voice_assistant_ai_guided_retrieval
        )

        if llm_enabled and guided_retrieval_enabled:
            try:
                llm = (
                    get_phone_qwen_assistant_service()
                    if for_phone
                    else get_base_qwen_assistant_service()
                )
                search_plan = llm.plan_search_queries(question)
                guided_matches = self._search_with_guided_queries(
                    question,
                    search_plan.queries,
                )
                if self._best_score(guided_matches) >= self._best_score(direct_matches):
                    matches = guided_matches
                    guided_retrieval_used = True
            except RuntimeError:
                logger.exception("Voice assistant guided retrieval failed.")

        reliable_match = self._has_reliable_match(matches)
        soft_match = self._has_soft_match(matches)
        if not reliable_match and not (llm_enabled and soft_match):
            return self._fallback_response(question)

        best_score = matches[0].score if matches else 0
        context_matches = self._filter_context_matches(
            matches,
            reliable_match=reliable_match,
        )
        if for_phone:
            context_matches = context_matches[: settings.voice_assistant_phone_max_context_items]
        used_llm = False
        model_name: str | None = None
        answer_text = ""

        if llm_enabled:
            try:
                if llm is None:
                    llm = (
                        get_phone_qwen_assistant_service()
                        if for_phone
                        else get_base_qwen_assistant_service()
                    )
                generation_kwargs: dict[str, Any] = {
                    "allow_related_sources": not reliable_match,
                }
                if for_phone:
                    if settings.voice_assistant_phone_max_new_tokens > 0:
                        generation_kwargs["max_new_tokens"] = (
                            settings.voice_assistant_phone_max_new_tokens
                        )
                    generation_kwargs["for_phone"] = True
                answer_text = llm.generate_answer(question, context_matches, **generation_kwargs)
                used_llm = bool(answer_text)
                model_name = llm.model_name if used_llm else None
            except RuntimeError:
                logger.exception("Voice assistant LLM generation failed.")
                if for_phone:
                    answer_text = self._extractive_answer(context_matches[0].entry)
                else:
                    return self._llm_unavailable_response(question, context_matches)

        if not answer_text:
            if llm_enabled:
                return self._llm_unavailable_response(question, context_matches)
            answer_text = self._extractive_answer(context_matches[0].entry)

        if used_llm and guided_retrieval_used:
            source = "llm_guided"
        elif used_llm:
            source = "llm"
        else:
            source = "knowledge_base"

        return VoiceAssistantResponse(
            question_text=question,
            answer_text=answer_text,
            confidence=best_score,
            source=source,
            sources=self._sources(context_matches),
            can_create_ticket=False,
            used_llm=used_llm,
            model_name=model_name,
        )

    def _search_with_guided_queries(
        self,
        question: str,
        queries: tuple[str, ...],
    ) -> list[KnowledgeMatch]:
        groups = [
            self.knowledge_base.search(query, limit=settings.voice_assistant_search_candidates)
            for query in (*queries, question)
        ]
        return self._merge_matches(groups, limit=settings.voice_assistant_max_context_items)

    @staticmethod
    def _merge_matches(
        groups: list[list[KnowledgeMatch]],
        *,
        limit: int,
    ) -> list[KnowledgeMatch]:
        best_by_entry: dict[str, KnowledgeMatch] = {}
        for group in groups:
            for match in group:
                existing = best_by_entry.get(match.entry.id)
                if existing is None or match.score > existing.score:
                    best_by_entry[match.entry.id] = match

        matches = list(best_by_entry.values())
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    @staticmethod
    def _best_score(matches: list[KnowledgeMatch]) -> float:
        return matches[0].score if matches else 0.0

    @staticmethod
    def _filter_context_matches(
        matches: list[KnowledgeMatch],
        *,
        reliable_match: bool,
    ) -> list[KnowledgeMatch]:
        if not matches:
            return []

        top_score = matches[0].score
        absolute_floor = (
            settings.voice_assistant_min_confidence
            if reliable_match
            else settings.voice_assistant_soft_min_confidence
        )
        min_score = max(
            absolute_floor,
            top_score * settings.voice_assistant_context_score_ratio,
        )
        filtered = [match for match in matches if match.score >= min_score]
        return filtered[: settings.voice_assistant_max_context_items] or matches[:1]

    @staticmethod
    def _has_reliable_match(matches: list[KnowledgeMatch]) -> bool:
        if not matches:
            return False
        best_score = matches[0].score
        return best_score >= settings.voice_assistant_min_confidence

    @staticmethod
    def _has_soft_match(matches: list[KnowledgeMatch]) -> bool:
        if not matches:
            return False
        best_score = matches[0].score
        return best_score >= settings.voice_assistant_soft_min_confidence

    @staticmethod
    def _extractive_answer(entry: KnowledgeBaseEntry) -> str:
        return BaseQwenAssistantService._clean_answer(entry.answer)

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
                "Спробуйте переформулювати питання або додати більше деталей."
            ),
            confidence=0,
            source="fallback",
            sources=[],
            can_create_ticket=False,
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
                "Спробуйте повторити питання трохи пізніше або уточнити формулювання."
            ),
            confidence=matches[0].score if matches else 0,
            source="llm_unavailable",
            sources=self._sources(matches),
            can_create_ticket=False,
            used_llm=False,
            model_name=None,
        )


@lru_cache
def get_knowledge_base_service() -> KnowledgeBaseService:
    return KnowledgeBaseService()


@lru_cache
def get_base_qwen_assistant_service() -> AssistantService:
    if settings.voice_assistant_inference_engine == "openai_compatible":
        return OpenAICompatibleAssistantService(
            model_name=settings.voice_assistant_model,
            base_url=settings.voice_assistant_openai_base_url,
            api_key=settings.voice_assistant_openai_api_key,
            timeout_seconds=settings.voice_assistant_openai_timeout_seconds,
            temperature=settings.voice_assistant_openai_temperature,
        )
    return BaseQwenAssistantService()


@lru_cache
def get_phone_qwen_assistant_service() -> AssistantService:
    if settings.voice_assistant_phone_inference_engine == "openai_compatible":
        return OpenAICompatibleAssistantService(
            model_name=settings.voice_assistant_phone_model,
            base_url=settings.voice_assistant_phone_openai_base_url,
            api_key=settings.voice_assistant_phone_openai_api_key,
            timeout_seconds=settings.voice_assistant_phone_openai_timeout_seconds,
            temperature=settings.voice_assistant_phone_openai_temperature,
        )
    return BaseQwenAssistantService(
        model_name=settings.voice_assistant_phone_model,
        reuse_classifier_model=settings.voice_assistant_phone_reuse_classifier_model,
        quantization=settings.voice_assistant_phone_quantization,
    )


@lru_cache
def get_voice_assistant_service() -> VoiceAssistantService:
    return VoiceAssistantService()
