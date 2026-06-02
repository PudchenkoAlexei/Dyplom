# ruff: noqa: F401,F821
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

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parents[2] / "data" / "kpi_faq_knowledge_base.json"
_DATABASE_KNOWLEDGE_BASE_CACHE: dict[str, Any] = {}
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
