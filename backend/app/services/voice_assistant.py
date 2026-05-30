from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import KnowledgeEntryStatus
from app.models.knowledge import KnowledgeEntry
from app.schemas.voice_assistant import VoiceAssistantResponse, VoiceAssistantSource
from app.services.classifier import get_classifier_service, install_sklearn_stub
from app.services.classifier_prompt import apply_classifier_chat_template

settings = get_settings()
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parents[1] / "data" / "kpi_faq_knowledge_base.json"
_DATABASE_KNOWLEDGE_BASE_CACHE: dict[str, "KnowledgeBaseService"] = {}
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
    "потрібен",
    "потрібна",
    "потрібне",
    "потрібний",
    "потрібних",
    "потрібно",
    "потрібні",
    "та",
    "так",
    "таке",
    "треба",
    "у",
    "чи",
    "що",
    "щоб",
    "як",
    "яке",
    "який",
    "яка",
    "яким",
    "яких",
    "які",
    "яку",
    "якщо",
    "куди",
    "питання",
    "отримати",
    "подати",
    "взяти",
    "оформити",
    "робити",
}
LOW_VALUE_SEARCH_STEMS = {
    "документ",
    "питанн",
}
SEARCH_SYNONYM_STEMS = {
    "дізнатис": ("знайти", "інформаці"),
    "дізнатися": ("знайти", "інформаці"),
    "дізнатись": ("знайти", "інформаці"),
    "знайти": ("дізнатис", "дізнатися", "дізнатись", "інформаці"),
    "інформаці": ("дізнатис", "дізнатися", "дізнатись", "знайти"),
}
INFO_SEEKING_QUERY_STEMS = {"дізнатис", "дізнатися", "дізнатись", "знайти", "шукаю", "інформаці"}
INFO_SOURCE_STEMS = {"знайт", "знайти", "інформаці", "шукаю", "консульту", "звертатис"}
CONTEXTUAL_CAVEAT_RE = re.compile(
    r"\b("
    r"не\s+існує|"
    r"немає|"
    r"не\s+передбачено|"
    r"залежно\s+від|"
    r"у\s+разі|"
    r"якщо|"
    r"але|"
    r"водночас|"
    r"є\s+[А-ЩЬЮЯҐЄІЇа-щьюяґєії'’\s-]{2,80}"
    r")\b",
    re.IGNORECASE,
)

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
    (re.compile(r"\bпідтвердюють\b", re.IGNORECASE), "підтверджують"),
    (re.compile(r"\bпідтвердює\b", re.IGNORECASE), "підтверджує"),
    (re.compile(r"\bзалесяти\b", re.IGNORECASE), "подати"),
    (re.compile(r"\bзготувати\b", re.IGNORECASE), "підготувати"),
    (re.compile(r"\bхочеш\b", re.IGNORECASE), "хочете"),
    (re.compile(r"\bтвоїх\b", re.IGNORECASE), "ваших"),
    (re.compile(r"\bтвої\b", re.IGNORECASE), "ваші"),
    (re.compile(r"\bтвою\b", re.IGNORECASE), "вашу"),
    (re.compile(r"\bтвоє\b", re.IGNORECASE), "ваше"),
    (re.compile(r"\bтебе\b", re.IGNORECASE), "вас"),
    (re.compile(r"\bти\b", re.IGNORECASE), "ви"),
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
ANSWER_TRAILING_DROP_PATTERNS = (
    re.compile(r"\s*Якщо потрібно,\s*(?:я\s+)?можу[^.?!]*[.?!]?\s*$", re.IGNORECASE),
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


@dataclass(frozen=True)
class DirectFactIntent:
    name: str
    query_pattern: re.Pattern[str]
    fact_keywords: tuple[str, ...]


class GenerativeModel(Protocol):
    def eval(self) -> Any: ...

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class EntrySearchIndex:
    entry: KnowledgeBaseEntry
    tokens: dict[str, tuple[str, ...]]
    stems: dict[str, set[str]]
    ngrams: dict[str, set[str]]
    primary_aliases: set[str]


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


DIRECT_FACT_INTENTS = (
    DirectFactIntent(
        name="адресу або місце розташування",
        query_pattern=re.compile(
            r"\b(адрес\w*|де\s+(?:знаход\w*|розташован\w*)|локац\w*|місцезнаходжен\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=(
            "адрес",
            "знаход",
            "розташ",
            "локац",
            "місцезнаходжен",
            "корпус",
            "кабінет",
            "кімн",
            "аудитор",
            "поверх",
            "проспект",
            "вул",
            "вулиц",
        ),
    ),
    DirectFactIntent(
        name="телефон або номер для зв'язку",
        query_pattern=re.compile(
            r"\b(телефон\w*|номер\w*|подзвон\w*|зателефон\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("телефон", "тел.", "номер", "дзвон", "зв'яз", "контакт"),
    ),
    DirectFactIntent(
        name="електронну пошту",
        query_pattern=re.compile(
            r"\b(email|e-mail|емейл\w*|пошт\w*|електронн\w+\s+адрес\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("email", "e-mail", "пошта", "електронн", "@"),
    ),
    DirectFactIntent(
        name="час, дату, графік або дедлайн",
        query_pattern=re.compile(
            r"\b(о\s+котрій|час\w*|графік\w*|розклад\w*|дата\w*|дедлайн\w*|термін\w*|початок\w*|"
            r"до\s+якого\s+(?:числа|терміну)|коли\s+(?:почина\w*|закінчу\w*|відбуд\w*|буде))\b",
            re.IGNORECASE,
        ),
        fact_keywords=("час", "графік", "розклад", "дата", "дедлайн", "термін", "початок", "до "),
    ),
    DirectFactIntent(
        name="вартість, оплату або суму",
        query_pattern=re.compile(
            r"\b(варт\w*|скільки\s+кошту\w*|оплат\w*|ціна\w*|сума\w*|рахунок\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("варт", "кошту", "оплат", "ціна", "сума", "рахунок", "квитанц"),
    ),
    DirectFactIntent(
        name="пакет документів або перелік вимог",
        query_pattern=re.compile(
            r"\b(документ\w*|пакет\w*|перелік\w*|що\s+потрібн\w*|які\s+потрібн\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=(
            "документ",
            "пакет",
            "перелік",
            "заява",
            "копія",
            "оригінал",
            "квитанц",
            "згода",
            "довідка",
            "паспорт",
            "потріб",
            "надати",
            "подати",
        ),
    ),
)

FACT_FIELD_BOUNDARY_RE = re.compile(
    r"\s+(?=("
    r"адрес[а-яіїєґ'’\s-]{0,80}:|"
    r"телефон[а-яіїєґ'’\s-]{0,60}:|"
    r"тел\.\s*:?|"
    r"email\s*:|"
    r"e-mail\s*:|"
    r"електронн[а-яіїєґ'’\s-]{0,60}пошт[а-яіїєґ'’\s-]{0,20}:|"
    r"пошт[а-яіїєґ'’\s-]{0,40}:|"
    r"графік[а-яіїєґ'’\s-]{0,60}:|"
    r"режим\s+роботи\s*:|"
    r"розклад[а-яіїєґ'’\s-]{0,60}:|"
    r"дата[а-яіїєґ'’\s-]{0,40}:|"
    r"дедлайн[а-яіїєґ'’\s-]{0,40}:|"
    r"кінцевий\s+термін[а-яіїєґ'’\s-]{0,40}:|"
    r"термін[а-яіїєґ'’\s-]{0,40}:|"
    r"вартість[а-яіїєґ'’\s-]{0,40}:|"
    r"ціна[а-яіїєґ'’\s-]{0,40}:|"
    r"сума[а-яіїєґ'’\s-]{0,40}:|"
    r"початок\s+[а-яіїєґ'’]+"
    r"))",
    re.IGNORECASE,
)
PHONE_FIELD_LABEL_RE = re.compile(
    r"\b(?:тел\.?|телефони?|номер(?:и)?(?:\s+телефон(?:у|а|ів))?|"
    r"контактн[а-яіїєґ'’\s-]{0,40}телефон[а-яіїєґ'’]*)\s*:?\s*",
    re.IGNORECASE,
)
PHONE_NUMBER_RE = re.compile(
    r"(?:"
    r"\+?380[\s)]*\d{2}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}|"
    r"\(?\d{2,5}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}|"
    r"\d{3}[-\s]\d{2}[-\s]\d{2}"
    r")",
    re.IGNORECASE,
)
EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTACT_TAIL_RE = re.compile(
    r"\s*,?\s+\b(?:тел\.?|телефони?|телефон[а-яіїєґ'’]*|номер[а-яіїєґ'’]*|"
    r"email|e-mail|пошт[а-яіїєґ'’]*|сайт[а-яіїєґ'’]*)\b.*$",
    re.IGNORECASE,
)
PHONE_CONTEXT_PREFIX_RE = re.compile(
    r"\b(?:не\s+існує|немає|не\s+зазначено|не\s+вказано|не\s+передбачено|є\s+довідков)",
    re.IGNORECASE,
)
SENTENCE_ABBREVIATION_DOT = "\uE000"
SENTENCE_ABBREVIATION_RE = re.compile(
    r"\b(?:"
    r"\u0430\u0443\u0434|"
    r"\u0431\u0443\u0434|"
    r"\u0432\u0443\u043b|"
    r"\u0456\u043c|"
    r"\u043a\u0430\u0431|"
    r"\u043a\u0456\u043c|"
    r"\u043a\u043e\u0440\u043f|"
    r"\u043c|"
    r"\u043f\u0440|"
    r"\u0440|"
    r"\u0441\u0442|"
    r"\u0442\u0435\u043b"
    r")\.",
    re.IGNORECASE,
)


def _protect_sentence_abbreviations(text: str) -> str:
    return SENTENCE_ABBREVIATION_RE.sub(
        lambda match: match.group(0)[:-1] + SENTENCE_ABBREVIATION_DOT,
        text,
    )


def _restore_sentence_abbreviations(text: str) -> str:
    return text.replace(SENTENCE_ABBREVIATION_DOT, ".")


def detect_direct_fact_intent(question: str) -> DirectFactIntent | None:
    normalized_question = normalize_for_search(question)
    for intent in DIRECT_FACT_INTENTS:
        if intent.query_pattern.search(normalized_question):
            return intent
    return None


def split_fact_chunks(text: str) -> list[str]:
    with_field_boundaries = FACT_FIELD_BOUNDARY_RE.sub("\n", text)
    protected_text = _protect_sentence_abbreviations(with_field_boundaries)
    with_sentence_boundaries = re.sub(r"(?<=[.!?…])\s+", "\n", protected_text)
    with_sentence_boundaries = _restore_sentence_abbreviations(with_sentence_boundaries)
    chunks = [
        normalize_text(chunk.strip(" \t\r\n;"))
        for chunk in with_sentence_boundaries.splitlines()
    ]
    return [chunk for chunk in chunks if chunk]


def has_fact_keyword(normalized_chunk: str, keyword: str) -> bool:
    normalized_keyword = normalize_for_search(keyword).strip()
    if not normalized_keyword:
        return False
    if len(normalized_keyword) <= 3 and normalized_keyword.isalpha():
        return bool(
            re.search(
                rf"(?<![0-9a-zа-щьюяґєії']){re.escape(normalized_keyword)}(?![0-9a-zа-щьюяґєії'])",
                normalized_chunk,
                re.IGNORECASE,
            )
        )
    return normalized_keyword in normalized_chunk


def is_informative_direct_fact_chunk(chunk: str, intent: DirectFactIntent) -> bool:
    normalized_chunk = normalize_for_search(chunk)
    if not any(has_fact_keyword(normalized_chunk, keyword) for keyword in intent.fact_keywords):
        return False
    if re.search(r"\b(?:за\s+адресою|за\s+посиланням|на\s+сайті)\s*\.?$", normalized_chunk):
        return False
    if re.search(r"\bпідписатися\s+на\s*,", normalized_chunk):
        return False
    return True


def select_direct_fact_chunks(text: str, intent: DirectFactIntent) -> list[str]:
    return [
        chunk
        for chunk in split_fact_chunks(text)
        if is_informative_direct_fact_chunk(chunk, intent)
    ]


def select_direct_fact_chunks_with_context(text: str, intent: DirectFactIntent) -> list[str]:
    chunks = split_fact_chunks(text)
    selected_indexes = [
        index
        for index, chunk in enumerate(chunks)
        if is_informative_direct_fact_chunk(chunk, intent)
    ]
    selected_index_set = set(selected_indexes)
    result: list[str] = []

    for index in selected_indexes:
        context_chunks: list[str] = []
        previous_index = index - 1
        while previous_index >= 0 and previous_index not in selected_index_set and len(context_chunks) < 3:
            previous_chunk = chunks[previous_index]
            if len(previous_chunk) > 220 or not CONTEXTUAL_CAVEAT_RE.search(previous_chunk):
                break
            context_chunks.append(previous_chunk)
            previous_index -= 1
        result.extend(reversed(context_chunks))
        result.append(chunks[index])

    deduped: list[str] = []
    seen: set[str] = set()
    for chunk in result:
        key = normalize_for_search(chunk)
        if key in seen:
            continue
        deduped.append(chunk)
        seen.add(key)
    return deduped


def is_phone_intent(intent: DirectFactIntent) -> bool:
    return "телефон" in intent.name or "номер" in intent.name


def is_address_intent(intent: DirectFactIntent) -> bool:
    return "адрес" in intent.name or "місце" in intent.name


def is_email_intent(intent: DirectFactIntent) -> bool:
    return "пошту" in intent.name


def is_strict_contact_intent(intent: DirectFactIntent) -> bool:
    return is_phone_intent(intent) or is_email_intent(intent)


def uses_direct_fact_field_reranking(intent: DirectFactIntent) -> bool:
    return (
        is_phone_intent(intent)
        or is_address_intent(intent)
        or is_email_intent(intent)
        or "час" in intent.name
    )


def normalize_phone_value(value: str) -> str:
    return normalize_text(value.strip(" ,;:.()"))


def is_valid_phone_value(value: str) -> bool:
    cleaned = normalize_phone_value(value)
    digits = re.sub(r"\D+", "", cleaned)
    if len(digits) < 7:
        return False
    groups = re.findall(r"\d+", cleaned)
    if len(digits) == 7 and groups and len(groups[0]) != 3:
        return False
    if len(digits) <= 8 and groups and all(len(group) <= 2 for group in groups):
        return False
    if len(digits) <= 8 and any(group == "00" for group in groups):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}[.-]\d{1,2}[.-]\d{1,2}", cleaned):
        return False
    if re.fullmatch(r"\d{1,2}[.-]\d{1,2}[.-]\d{2,4}", cleaned):
        return False
    if re.fullmatch(r"\d{1,2}[\s.:]\d{2}\s*[-–—]\s*\d{1,2}[\s.:]\d{2}", cleaned):
        return False
    return True


def extract_phone_numbers_from_chunk(chunk: str) -> list[str]:
    label_match = PHONE_FIELD_LABEL_RE.search(chunk)
    search_area = chunk[label_match.end() :] if label_match else chunk
    numbers: list[str] = []
    seen: set[str] = set()
    for match in PHONE_NUMBER_RE.finditer(search_area):
        number = normalize_phone_value(match.group(0))
        key = re.sub(r"\D+", "", number)
        if not is_valid_phone_value(number) or key in seen:
            continue
        numbers.append(number)
        seen.add(key)
    return numbers


def format_phone_fact_chunks(chunks: list[str]) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    first_phone_chunk_index: int | None = None
    for index, chunk in enumerate(chunks):
        chunk_numbers = extract_phone_numbers_from_chunk(chunk)
        if chunk_numbers and first_phone_chunk_index is None:
            first_phone_chunk_index = index
        for number in chunk_numbers:
            key = re.sub(r"\D+", "", number)
            if key in seen:
                continue
            numbers.append(number)
            seen.add(key)

    if not numbers:
        return [chunk for chunk in chunks if not PHONE_FIELD_LABEL_RE.search(chunk)]

    label = "Телефон" if len(numbers) == 1 else "Телефони"
    prefix = [
        chunk
        for chunk in chunks[: first_phone_chunk_index or 0]
        if PHONE_CONTEXT_PREFIX_RE.search(chunk)
    ]
    return [*prefix, f"{label}: {', '.join(numbers)}."]


def extract_email_addresses_from_chunk(chunk: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_ADDRESS_RE.finditer(chunk):
        email = match.group(0).strip(" ,;:.")
        key = email.casefold()
        if key in seen:
            continue
        emails.append(email)
        seen.add(key)
    return emails


def format_email_fact_chunks(chunks: list[str]) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_emails = extract_email_addresses_from_chunk(chunk)
        for email in chunk_emails:
            key = email.casefold()
            if key in seen:
                continue
            emails.append(email)
            seen.add(key)

    if not emails:
        return chunks

    label = "Електронна пошта" if len(emails) == 1 else "Електронні пошти"
    return [f"{label}: {', '.join(emails)}."]


def trim_address_chunk(chunk: str) -> str:
    trimmed = CONTACT_TAIL_RE.sub("", chunk)
    trimmed = re.sub(r"\s+[,.;:]", lambda match: match.group(0).strip(), trimmed)
    return normalize_text(trimmed.strip(" ,;"))


def focus_direct_fact_chunks(text: str, intent: DirectFactIntent) -> list[str]:
    chunks = select_direct_fact_chunks_with_context(text, intent)
    if not chunks:
        return []

    if is_phone_intent(intent):
        return format_phone_fact_chunks(chunks)

    if is_address_intent(intent):
        focused = [trim_address_chunk(chunk) for chunk in chunks]
        return [chunk for chunk in focused if chunk]

    if is_email_intent(intent):
        return format_email_fact_chunks(chunks)

    return chunks


def is_direct_fact_query_term(token: str, stem: str, intent: DirectFactIntent) -> bool:
    for keyword in intent.fact_keywords:
        normalized_keyword = normalize_for_search(keyword).strip()
        if len(normalized_keyword) < 3:
            continue
        keyword_token = normalized_keyword.split()[0]
        keyword_stem = stem_token(keyword_token)
        if (
            keyword_token in token
            or keyword_token in stem
            or keyword_stem in stem
            or stem in keyword_stem
        ):
            return True
    return False


def direct_fact_object_terms(
    query_tokens: tuple[str, ...],
    query_stems: tuple[str, ...],
    intent: DirectFactIntent | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if intent is None:
        return (), ()

    object_pairs = [
        (token, stem)
        for token, stem in zip(query_tokens, query_stems)
        if len(stem) >= 4 and not is_direct_fact_query_term(token, stem, intent)
    ]
    return (
        tuple(token for token, _ in object_pairs),
        tuple(stem for _, stem in object_pairs),
    )


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


def search_stem_matches(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if right in SEARCH_SYNONYM_STEMS.get(left, ()) or left in SEARCH_SYNONYM_STEMS.get(right, ()):
        return 0.82
    if len(left) >= 5 and len(right) >= 5:
        shorter, longer = sorted((left, right), key=len)
        ratio = len(shorter) / len(longer)
        if shorter in longer and ratio >= 0.64:
            return 0.82
        common_prefix = 0
        for left_char, right_char in zip(left, right):
            if left_char != right_char:
                break
            common_prefix += 1
        if common_prefix >= 5 and common_prefix / min(len(left), len(right)) >= 0.78:
            return 0.72
    return 0.0


def token_match_quality(query_token: str, query_stem: str, field_tokens: set[str], field_stems: set[str]) -> float:
    if query_token in field_tokens or query_stem in field_stems:
        return 1.0
    for field_stem in field_stems:
        quality = search_stem_matches(query_stem, field_stem)
        if quality:
            return quality
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


def compound_form_matches(left: str, right: str) -> bool:
    if len(left) < 8 or len(right) < 8:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if longer.startswith(shorter) and len(shorter) / len(longer) >= 0.82:
        return True
    return shorter in longer and len(shorter) / len(longer) >= 0.88


def compound_phrase_score(query_stems: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    if len(query_stems) < 2:
        return 0.0

    document_forms = set(document_tokens) | {stem_token(token) for token in document_tokens}
    matched_query_indexes: set[int] = set()

    for window_size in (3, 2):
        if len(query_stems) < window_size:
            continue
        for start in range(len(query_stems) - window_size + 1):
            indexes = set(range(start, start + window_size))
            if indexes & matched_query_indexes:
                continue
            compound = "".join(query_stems[start : start + window_size])
            if any(compound_form_matches(compound, document_form) for document_form in document_forms):
                matched_query_indexes.update(indexes)

    return len(matched_query_indexes) / len(query_stems)


def build_compound_aliases(
    tokens: tuple[str, ...],
    *,
    min_window_size: int = 1,
    max_window_size: int = 4,
) -> set[str]:
    aliases: set[str] = set()
    if not tokens:
        return aliases

    stems = tuple(stem_token(token) for token in tokens)
    for window_size in range(min_window_size, min(max_window_size, len(tokens)) + 1):
        for start in range(len(tokens) - window_size + 1):
            raw_alias = "".join(tokens[start : start + window_size])
            stem_alias = "".join(stems[start : start + window_size])
            for alias in (raw_alias, stem_alias):
                if len(alias) >= 8:
                    aliases.add(alias)
    return aliases


def alias_form_match_score(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if len(left) < 8 or len(right) < 8:
        return 0.0

    shorter, longer = sorted((left, right), key=len)
    ratio = len(shorter) / len(longer)
    if ratio < 0.82:
        return 0.0
    if longer.startswith(shorter):
        return 0.92
    if shorter in longer and ratio >= 0.9:
        return 0.86
    return 0.0


def alias_match_score(query_aliases: set[str], document_aliases: set[str]) -> float:
    if not query_aliases or not document_aliases:
        return 0.0

    best_score = 0.0
    for query_alias in query_aliases:
        for document_alias in document_aliases:
            best_score = max(
                best_score,
                alias_form_match_score(query_alias, document_alias),
            )
            if best_score >= 1.0:
                return 1.0
    return best_score


def dedupe_repeated_sentences(text: str) -> str:
    protected_text = _protect_sentence_abbreviations(text)
    parts = re.split(r"(?<=[.!?…])\s+", protected_text)
    deduped: list[str] = []
    seen: set[str] = set()

    for part in parts:
        sentence = _restore_sentence_abbreviations(part.strip())
        if not sentence:
            continue
        key = normalize_for_search(sentence)
        if key in seen:
            continue
        deduped.append(sentence)
        seen.add(key)

    return normalize_text(" ".join(deduped))


class KnowledgeBaseService:
    def __init__(self, path: Path = KNOWLEDGE_BASE_PATH) -> None:
        raw_entries = json.loads(path.read_text(encoding="utf-8"))
        self.entries = [KnowledgeBaseEntry.from_dict(item) for item in raw_entries]
        self._index = [self._build_index(entry) for entry in self.entries]
        self._index_by_entry_id = {item.entry.id: item for item in self._index}
        self._idf = self._build_idf(self._index)

    @classmethod
    def from_entries(cls, entries: list[KnowledgeBaseEntry]) -> "KnowledgeBaseService":
        service = cls.__new__(cls)
        service.entries = entries
        service._index = [service._build_index(entry) for entry in entries]
        service._index_by_entry_id = {item.entry.id: item for item in service._index}
        service._idf = service._build_idf(service._index)
        return service

    @staticmethod
    def _build_index(entry: KnowledgeBaseEntry) -> EntrySearchIndex:
        fields = field_tokens(entry)
        tokens = {field: tokenize(value) for field, value in fields.items()}
        primary_aliases: set[str] = set()
        for field in ("title", "question", "tags"):
            primary_aliases.update(build_compound_aliases(tokens[field]))
        return EntrySearchIndex(
            entry=entry,
            tokens=tokens,
            stems={field: {stem_token(token) for token in values} for field, values in tokens.items()},
            ngrams={field: char_ngrams(value) for field, value in fields.items()},
            primary_aliases=primary_aliases,
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
        query_aliases = build_compound_aliases(query_tokens, min_window_size=2)
        direct_fact_intent = detect_direct_fact_intent(question)
        object_tokens, object_stems = direct_fact_object_terms(
            query_tokens,
            query_stems,
            direct_fact_intent,
        )
        for item in self._index:
            score = self._score_entry(
                query_tokens,
                query_stems,
                query_ngrams,
                query_aliases,
                item,
                direct_fact_intent=direct_fact_intent,
                object_tokens=object_tokens,
                object_stems=object_stems,
            )
            if score > 0:
                matches.append(KnowledgeMatch(entry=item.entry, score=round(score, 4)))

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[: limit or settings.voice_assistant_max_context_items]

    def score_entry_for_question(self, question: str, entry: KnowledgeBaseEntry) -> float:
        query_tokens = tokenize(question)
        if not query_tokens:
            return 0.0
        item = self._index_by_entry_id.get(entry.id)
        if item is None:
            return 0.0
        query_stems = tuple(stem_token(token) for token in query_tokens)
        query_ngrams = char_ngrams(question)
        query_aliases = build_compound_aliases(query_tokens, min_window_size=2)
        direct_fact_intent = detect_direct_fact_intent(question)
        object_tokens, object_stems = direct_fact_object_terms(
            query_tokens,
            query_stems,
            direct_fact_intent,
        )
        return round(
            self._score_entry(
                query_tokens,
                query_stems,
                query_ngrams,
                query_aliases,
                item,
                direct_fact_intent=direct_fact_intent,
                object_tokens=object_tokens,
                object_stems=object_stems,
            ),
            4,
        )

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

    def _significant_coverage(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        document_tokens: set[str],
        document_stems: set[str],
    ) -> tuple[float, int]:
        significant_pairs = [
            (token, stem)
            for token, stem in zip(query_tokens, query_stems)
            if len(stem) >= 5 and stem not in LOW_VALUE_SEARCH_STEMS
        ]
        if not significant_pairs:
            return 1.0, 0

        filtered_tokens = tuple(token for token, _ in significant_pairs)
        filtered_stems = tuple(stem for _, stem in significant_pairs)
        return (
            self._coverage(filtered_tokens, filtered_stems, document_tokens, document_stems),
            len(significant_pairs),
        )

    def _score_entry(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        query_ngrams: set[str],
        query_aliases: set[str],
        item: EntrySearchIndex,
        *,
        direct_fact_intent: DirectFactIntent | None = None,
        object_tokens: tuple[str, ...] = (),
        object_stems: tuple[str, ...] = (),
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
        significant_coverage, significant_count = self._significant_coverage(
            query_tokens,
            query_stems,
            full_tokens,
            full_stems,
        )

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
        primary_compound_score = max(
            compound_phrase_score(query_stems, item.tokens["title"]),
            compound_phrase_score(query_stems, item.tokens["question"]),
            compound_phrase_score(query_stems, item.tokens["tags"]),
        )
        answer_compound_score = compound_phrase_score(query_stems, item.tokens["answer"])
        primary_alias_score = alias_match_score(query_aliases, item.primary_aliases)
        info_source_score = (
            1.0
            if set(query_stems) & INFO_SEEKING_QUERY_STEMS and primary_stems & INFO_SOURCE_STEMS
            else 0.0
        )

        field_score = max(
            title_coverage,
            question_coverage * 0.95,
            tag_coverage * 0.9,
            primary_coverage * 0.86,
            primary_compound_score * 0.92,
            primary_alias_score * 0.95,
        )
        score = (
            field_score * 0.55
            + full_coverage * 0.2
            + primary_ngram_score * 0.08
            + answer_ngram_score * 0.04
            + primary_phrase_score * 0.08
            + answer_phrase_score * 0.3
            + primary_compound_score * 0.28
            + answer_compound_score * 0.08
            + primary_alias_score * 0.32
            + info_source_score * 0.14
        )

        if (
            primary_coverage < 0.34
            and primary_compound_score == 0
            and primary_alias_score == 0
            and answer_coverage > 0
            and answer_phrase_score == 0
        ):
            score *= 0.68
        if (
            len(query_tokens) <= 2
            and primary_coverage < 0.75
            and primary_compound_score == 0
            and primary_alias_score == 0
            and answer_phrase_score == 0
        ):
            score *= 0.82
        if significant_count >= 2:
            if significant_coverage < 0.34:
                score *= 0.38
            elif significant_coverage < 0.5:
                score *= 0.62
        elif significant_count == 1 and significant_coverage == 0:
            score *= 0.55

        if direct_fact_intent is not None and uses_direct_fact_field_reranking(direct_fact_intent):
            requested_fact_chunks = focus_direct_fact_chunks(item.entry.answer, direct_fact_intent)
            has_requested_fact = bool(requested_fact_chunks)

            object_match = 1.0
            object_phrase_score = 0.0
            object_alias_score = 0.0
            if object_tokens:
                object_coverage = self._coverage(
                    object_tokens,
                    object_stems,
                    primary_tokens,
                    primary_stems,
                )
                object_phrase_score = max(
                    phrase_match_score(object_stems, item.tokens["title"]),
                    phrase_match_score(object_stems, item.tokens["question"]),
                    phrase_match_score(object_stems, item.tokens["tags"]),
                )
                object_compound_score = max(
                    compound_phrase_score(object_stems, item.tokens["title"]),
                    compound_phrase_score(object_stems, item.tokens["question"]),
                    compound_phrase_score(object_stems, item.tokens["tags"]),
                )
                object_alias_score = alias_match_score(
                    build_compound_aliases(object_tokens, min_window_size=2),
                    item.primary_aliases,
                )
                object_match = max(
                    object_coverage,
                    object_phrase_score,
                    object_compound_score,
                    object_alias_score,
                )

            if object_tokens:
                score += object_match * 0.28
                if object_phrase_score >= 0.99 or object_alias_score >= 0.99:
                    score += 0.18

            if object_tokens and object_match < 0.42:
                score *= 0.42 if has_requested_fact else 0.16
            elif has_requested_fact:
                score += 0.12 + object_match * 0.16
            elif object_tokens and object_match >= 0.74:
                score += 0.08
            else:
                score *= 0.55

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
        try:
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
        except Exception as exc:
            raise RuntimeError("Could not load assistant generation model.") from exc
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
    def _focus_facts_for_phone(text: str, intent: DirectFactIntent | None) -> str:
        clean_text = BaseQwenAssistantService._clean_answer(text, trim_incomplete=False)
        if intent is None:
            return clean_text

        relevant_chunks = focus_direct_fact_chunks(clean_text, intent)
        if not relevant_chunks:
            return clean_text
        return normalize_text(" ".join(relevant_chunks[:5]))

    @staticmethod
    def _build_phone_answer_messages(
        question: str,
        matches: list[KnowledgeMatch],
    ) -> list[dict[str, str]]:
        direct_fact_intent = detect_direct_fact_intent(question)
        context = "\n\n".join(
            f"Тема {index}: {match.entry.title}\n"
            f"Факти {index}: {BaseQwenAssistantService._focus_facts_for_phone(match.entry.answer, direct_fact_intent)}"
            for index, match in enumerate(matches, start=1)
        )
        direct_fact_instruction = ""
        if direct_fact_intent is not None:
            direct_fact_instruction = (
                f"Користувач просить конкретний факт: {direct_fact_intent.name}. "
                "Відповідай тільки цим фактом і найближчими необхідними уточненнями. "
                "Не додавай сусідні речення про оголошення, підписку, інші контакти, інші дії "
                "або загальний опис теми, якщо вони не відповідають на запитаний факт.\n\n"
            )
        definition_instruction = ""
        if re.search(r"\b(що таке|що означає|поясни|визначення)\b", normalize_for_search(question)):
            primary_topic = matches[0].entry.title if matches else "поняття"
            definition_instruction = (
                "Користувач просить пояснити поняття. Спочатку дай коротке визначення простими словами. "
                f"Орієнтуйся на тему джерела: '{primary_topic}', а не на можливу помилку розпізнавання "
                "в самому питанні. Якщо назва теми стисла або злита, розгорни її природною українською. "
                "Потім додай головні обмеження або умови з фактів.\n\n"
            )
        core_rules = (
            "Відповідай як живий телефонний консультант: спочатку пряма відповідь, потім потрібні деталі. "
            "Не цитуй джерело механічно; перефразовуй простими словами, але не додавай фактів, яких немає "
            "у наданих даних. Якщо користувач питає про документи, назви весь пакет документів з фактів. "
            "Якщо у фактах різні групи людей, не змішуй їхні умови. Не повторюй питання, не згадуй FAQ, "
            "джерела, URL, Markdown, заявку чи оператора. Не повторюй однакові речення та не замінюй "
            "офіційні назви вигаданими підрозділами. Звертайся нейтрально або на 'ви', ніколи не переходь "
            "на 'ти' і не додавай фрази на кшталт 'можу пояснити'. Говори грамотною природною українською "
            "для телефону."
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти телефонний консультант КПІ. Відповідай українською і тільки за наданими фактами. "
                    f"{core_rules}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання: {question}\n\n"
                    f"{context}\n\n"
                    f"{direct_fact_instruction}"
                    f"{definition_instruction}"
                    "Сформуй одну зв'язну відповідь для телефонного дзвінка. "
                    "Без Markdown, маркованих списків і службових пояснень."
                ),
            },
        ]

    @staticmethod
    def _clean_answer(raw: str, *, trim_incomplete: bool = True) -> str:
        answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].strip()
        answer = answer.strip("` \n\r\t")
        answer = re.sub(r"\*\*(.*?)\*\*", r"\1", answer)
        answer = re.sub(r"\s*(?:[-–—]\s*)?https?://\S+", "", answer)
        answer = re.sub(r"\s+(?=[,.;:!?])", "", answer)
        answer = re.sub(r"\s*[-–—]\s*$", "", answer)
        for pattern in ANSWER_INTRO_DROP_PATTERNS:
            answer = pattern.sub("", answer, count=1)
        for pattern, replacement in ANSWER_TEXT_REPLACEMENTS:
            answer = pattern.sub(replacement, answer)
        for pattern in ANSWER_TRAILING_DROP_PATTERNS:
            answer = pattern.sub("", answer)
        if trim_incomplete and answer and answer[-1] not in ".!?…":
            complete_answer = re.sub(r"\s+[^.!?…]*$", "", answer)
            if len(complete_answer) >= 40:
                answer = complete_answer
        return dedupe_repeated_sentences(answer)


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


async def load_published_knowledge_base(db: AsyncSession) -> KnowledgeBaseService | None:
    result = await db.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.status == KnowledgeEntryStatus.published)
        .order_by(KnowledgeEntry.title)
    )
    rows = list(result.scalars())
    if not rows:
        return None

    version_payload = [
        (
            str(row.id),
            row.content_hash,
            row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]
    version_key = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cached = _DATABASE_KNOWLEDGE_BASE_CACHE.get(version_key)
    if cached is not None:
        return cached

    service = KnowledgeBaseService.from_entries(
        [
            KnowledgeBaseEntry(
                id=row.slug or str(row.id),
                title=row.title,
                question=row.question,
                answer=row.answer,
                source_url=row.source_url,
                tags=tuple(str(tag) for tag in row.tags_json or []),
            )
            for row in rows
        ]
    )
    if len(_DATABASE_KNOWLEDGE_BASE_CACHE) >= 4:
        _DATABASE_KNOWLEDGE_BASE_CACHE.clear()
    _DATABASE_KNOWLEDGE_BASE_CACHE[version_key] = service
    return service


class VoiceAssistantService:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBaseService()

    @staticmethod
    def _direct_phone_fact_answer(question: str, entry: KnowledgeBaseEntry) -> str:
        intent = detect_direct_fact_intent(question)
        if intent is None:
            return ""

        clean_text = BaseQwenAssistantService._clean_answer(entry.answer, trim_incomplete=False)
        relevant_chunks = focus_direct_fact_chunks(clean_text, intent)
        if not relevant_chunks:
            return ""

        answer = normalize_text(" ".join(relevant_chunks))
        if len(answer) > 420:
            return ""
        if answer and answer[-1] not in ".!?…":
            answer = f"{answer}."
        return answer

    @staticmethod
    def _missing_direct_contact_answer(intent: DirectFactIntent) -> str:
        if is_phone_intent(intent):
            return "У наданій офіційній інформації телефон не вказано."
        if is_email_intent(intent):
            return "У наданій офіційній інформації електронну пошту не вказано."
        return ""

    async def answer(
        self,
        question_text: str,
        *,
        for_phone: bool = False,
        db: AsyncSession | None = None,
    ) -> VoiceAssistantResponse:
        question = normalize_text(question_text)
        knowledge_base: KnowledgeBaseService | None = None
        if db is not None:
            try:
                knowledge_base = await load_published_knowledge_base(db)
            except Exception:
                logger.exception("Failed to load published knowledge base from database.")
        return await asyncio.to_thread(
            self._answer_sync,
            question,
            for_phone=for_phone,
            knowledge_base=knowledge_base,
        )

    def _answer_sync(
        self,
        question: str,
        *,
        for_phone: bool = False,
        knowledge_base: KnowledgeBaseService | None = None,
    ) -> VoiceAssistantResponse:
        active_knowledge_base = knowledge_base or self.knowledge_base
        direct_matches = active_knowledge_base.search(question)
        matches = direct_matches
        guided_retrieval_used = False
        llm_unavailable = False
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
                    active_knowledge_base,
                )
                if self._should_accept_guided_matches(
                    question,
                    direct_matches,
                    guided_matches,
                    active_knowledge_base,
                ):
                    matches = guided_matches
                    guided_retrieval_used = True
            except Exception:
                logger.exception("Voice assistant guided retrieval failed.")
                llm_unavailable = True

        reliable_match = self._has_reliable_match(matches)
        soft_match = self._has_soft_match(matches)
        direct_fact_soft_match = (
            for_phone
            and soft_match
            and bool(matches)
            and self._has_requested_direct_fact(question, matches[0].entry)
        )
        if not guided_retrieval_used and self._has_ambiguous_soft_match(direct_matches, question=question):
            return self._fallback_response(question)
        if not reliable_match and not ((llm_enabled and soft_match) or direct_fact_soft_match):
            return self._fallback_response(question)

        best_score = matches[0].score if matches else 0
        context_matches = self._filter_context_matches(
            matches,
            reliable_match=reliable_match,
        )
        if for_phone:
            context_matches = context_matches[: settings.voice_assistant_phone_max_context_items]
            if context_matches:
                direct_fact_intent = detect_direct_fact_intent(question)
                for context_match in context_matches:
                    direct_fact_answer = self._direct_phone_fact_answer(question, context_match.entry)
                    if direct_fact_answer:
                        source = "llm_guided" if guided_retrieval_used else "knowledge_base"
                        return VoiceAssistantResponse(
                            question_text=question,
                            answer_text=direct_fact_answer,
                            confidence=context_match.score,
                            source=source,
                            sources=self._sources([context_match]),
                            can_create_ticket=False,
                            used_llm=guided_retrieval_used,
                            model_name=llm.model_name if guided_retrieval_used and llm is not None else None,
                        )
                if direct_fact_intent is not None and is_strict_contact_intent(direct_fact_intent):
                    missing_answer = self._missing_direct_contact_answer(direct_fact_intent)
                    if missing_answer:
                        source = "llm_guided" if guided_retrieval_used else "knowledge_base"
                        return VoiceAssistantResponse(
                            question_text=question,
                            answer_text=missing_answer,
                            confidence=best_score,
                            source=source,
                            sources=self._sources(context_matches),
                            can_create_ticket=False,
                            used_llm=guided_retrieval_used,
                            model_name=llm.model_name if guided_retrieval_used and llm is not None else None,
                        )
        used_llm = False
        model_name: str | None = None
        answer_text = ""

        if llm_enabled and not llm_unavailable:
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
            except Exception:
                logger.exception("Voice assistant LLM generation failed.")
                if context_matches:
                    answer_text = self._extractive_answer(context_matches[0].entry)
                elif llm_enabled:
                    return self._llm_unavailable_response(question, context_matches)

        if not answer_text:
            if context_matches:
                answer_text = self._extractive_answer(context_matches[0].entry)
            elif llm_enabled:
                return self._llm_unavailable_response(question, context_matches)

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
        knowledge_base: KnowledgeBaseService,
    ) -> list[KnowledgeMatch]:
        groups = [
            knowledge_base.search(query, limit=settings.voice_assistant_search_candidates)
            for query in (*queries, question)
        ]
        return self._merge_matches(groups, limit=settings.voice_assistant_max_context_items)

    def _should_accept_guided_matches(
        self,
        question: str,
        direct_matches: list[KnowledgeMatch],
        guided_matches: list[KnowledgeMatch],
        knowledge_base: KnowledgeBaseService,
    ) -> bool:
        if not guided_matches:
            return False
        if not direct_matches:
            return True

        direct_top = direct_matches[0]
        guided_top = guided_matches[0]
        direct_score = direct_top.score
        guided_score = guided_top.score

        if guided_top.entry.id == direct_top.entry.id:
            return guided_score >= direct_score

        guided_original_score = knowledge_base.score_entry_for_question(
            question,
            guided_top.entry,
        )

        if direct_score >= settings.voice_assistant_min_confidence:
            return guided_original_score >= direct_score + 0.08

        if direct_score < settings.voice_assistant_soft_min_confidence:
            return guided_score >= settings.voice_assistant_soft_min_confidence

        if (
            direct_score < settings.voice_assistant_min_confidence
            and guided_score >= settings.voice_assistant_soft_min_confidence
            and guided_score >= direct_score + 0.2
        ):
            return True

        return guided_original_score >= direct_score + 0.05

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
    def _has_requested_direct_fact(question: str, entry: KnowledgeBaseEntry) -> bool:
        intent = detect_direct_fact_intent(question)
        if intent is None:
            return False

        clean_text = BaseQwenAssistantService._clean_answer(entry.answer, trim_incomplete=False)
        return bool(select_direct_fact_chunks(clean_text, intent))

    @classmethod
    def _has_ambiguous_soft_match(
        cls,
        matches: list[KnowledgeMatch],
        *,
        question: str = "",
    ) -> bool:
        if len(matches) < 2:
            return False
        best_score = matches[0].score
        second_score = matches[1].score
        if best_score >= settings.voice_assistant_min_confidence:
            return False
        if question and cls._has_requested_direct_fact(question, matches[0].entry):
            second_has_requested_fact = cls._has_requested_direct_fact(question, matches[1].entry)
            if not second_has_requested_fact or best_score >= second_score + 0.015:
                return False
        return second_score >= settings.voice_assistant_soft_min_confidence and (
            best_score - second_score <= 0.06
            or second_score >= best_score * 0.88
        )

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
