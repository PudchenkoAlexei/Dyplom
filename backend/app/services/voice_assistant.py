from __future__ import annotations

import asyncio
import json
import logging
import re
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
}


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


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def tokenize(value: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(value)
        if token.casefold() not in STOP_WORDS
    }


def tokens_overlap(query_tokens: set[str], document_tokens: set[str]) -> int:
    overlap = 0
    for query_token in query_tokens:
        if query_token in document_tokens:
            overlap += 1
            continue
        if len(query_token) < 6:
            continue
        query_prefix = query_token[:5]
        if any(len(document_token) >= 6 and document_token.startswith(query_prefix) for document_token in document_tokens):
            overlap += 1
    return overlap


class KnowledgeBaseService:
    def __init__(self, path: Path = KNOWLEDGE_BASE_PATH) -> None:
        raw_entries = json.loads(path.read_text(encoding="utf-8"))
        self.entries = [KnowledgeBaseEntry.from_dict(item) for item in raw_entries]
        self._title_tokens = {entry.id: tokenize(entry.title) for entry in self.entries}
        self._question_tokens = {entry.id: tokenize(entry.question) for entry in self.entries}
        self._tag_tokens = {entry.id: tokenize(" ".join(entry.tags)) for entry in self.entries}
        self._answer_tokens = {entry.id: tokenize(entry.answer) for entry in self.entries}

    def search(self, question: str, *, limit: int | None = None) -> list[KnowledgeMatch]:
        query_tokens = tokenize(question)
        if not query_tokens:
            return []

        matches = []
        for entry in self.entries:
            title_overlap = tokens_overlap(query_tokens, self._title_tokens[entry.id])
            question_overlap = tokens_overlap(query_tokens, self._question_tokens[entry.id])
            tag_overlap = tokens_overlap(query_tokens, self._tag_tokens[entry.id])
            answer_overlap = tokens_overlap(query_tokens, self._answer_tokens[entry.id])
            weighted_overlap = title_overlap * 5 + question_overlap * 4 + tag_overlap * 2 + answer_overlap * 0.5
            score = min(weighted_overlap / max(len(query_tokens) * 7, 1), 1.0)
            if score > 0:
                matches.append(KnowledgeMatch(entry=entry, score=round(score, 4)))

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[: limit or settings.voice_assistant_max_context_items]


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
                    "Використовуй тільки надані джерела. "
                    "Якщо в джерелах недостатньо інформації, скажи, що краще створити заявку."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    f"Доступні джерела:\n{context}\n\n"
                    "Сформуй одну коротку відповідь для озвучення голосом. "
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
        best_score = matches[0].score if matches else 0.0
        if best_score < settings.voice_assistant_min_confidence:
            return self._fallback_response(question)

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
