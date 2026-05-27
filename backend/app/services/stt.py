import asyncio
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
import unicodedata

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parents[1] / "data" / "kpi_faq_knowledge_base.json"
WORD_RE = re.compile(r"[0-9a-zа-щьюяґєії'’`-]{1,}", re.IGNORECASE)
CYRILLIC_RE = re.compile(r"[а-щьюяґєії]", re.IGNORECASE)
STT_LEXICON_STOP_WORDS = {
    "або",
    "але",
    "буде",
    "бути",
    "вам",
    "ваш",
    "від",
    "вже",
    "для",
    "де",
    "до",
    "за",
    "із",
    "його",
    "коли",
    "кпі",
    "мене",
    "може",
    "можна",
    "моє",
    "на",
    "не",
    "після",
    "по",
    "про",
    "та",
    "так",
    "таке",
    "треба",
    "у",
    "чи",
    "що",
    "як",
    "яка",
    "який",
    "які",
    "якщо",
}
INITIAL_PROMPT_TERMS_MAX = 12
INITIAL_PROMPT_CHARS_MAX = 180
HOTWORDS_TERMS_MAX = 30
HOTWORDS_CHARS_MAX = 340


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None
    model_name: str


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def normalize_for_stt_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.casefold().replace("’", "'").replace("`", "'").replace("-", " ")
    return normalize_text(normalized)


def stt_words(value: str) -> tuple[str, ...]:
    return tuple(WORD_RE.findall(normalize_for_stt_matching(value)))


def is_domain_word(value: str) -> bool:
    normalized = normalize_for_stt_matching(value)
    return (
        len(normalized) >= 5
        and normalized not in STT_LEXICON_STOP_WORDS
        and bool(CYRILLIC_RE.search(normalized))
    )


def add_domain_term(term: str, weight: int, counter: Counter[str]) -> None:
    term_words = stt_words(term)
    if len(term_words) > 4:
        return
    normalized = " ".join(term_words).strip(" '")
    if not normalized:
        return
    if " " not in normalized and normalized in STT_LEXICON_STOP_WORDS:
        return
    if 4 <= len(normalized) <= 48 and CYRILLIC_RE.search(normalized):
        counter[normalized] = max(counter[normalized], weight)


def add_domain_words(text: str, weight: int, counter: Counter[str]) -> None:
    for word in stt_words(text):
        if is_domain_word(word):
            counter[word] = max(counter[word], weight)


@lru_cache
def build_stt_domain_terms(path: Path = KNOWLEDGE_BASE_PATH) -> tuple[str, ...]:
    counter: Counter[str] = Counter()

    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not load STT domain terms from knowledge base.")
        entries = []

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        title = str(raw_entry.get("title") or "")
        question = str(raw_entry.get("question") or "")
        tags = [str(tag) for tag in raw_entry.get("tags", []) if isinstance(tag, str)]

        add_domain_term(title, 12, counter)
        add_domain_words(title, 8, counter)
        add_domain_words(question, 3, counter)
        for tag in tags:
            add_domain_term(tag, 7, counter)
            add_domain_words(tag, 5, counter)

    terms = sorted(
        counter.items(),
        key=lambda item: (-item[1], len(item[0].split()), -len(item[0]), item[0]),
    )
    return tuple(term for term, _score in terms)


def build_stt_prompt_terms() -> tuple[str, ...]:
    if not settings.whisper_domain_hints_enabled or settings.whisper_domain_terms_max <= 0:
        return ()
    return build_stt_domain_terms()[: settings.whisper_domain_terms_max]


def fit_terms_to_budget(terms: tuple[str, ...], *, max_terms: int, max_chars: int) -> tuple[str, ...]:
    selected: list[str] = []
    used_chars = 0
    for term in terms:
        separator_chars = 2 if selected else 0
        next_chars = used_chars + separator_chars + len(term)
        if selected and next_chars > max_chars:
            break
        selected.append(term)
        used_chars = next_chars
        if len(selected) >= max_terms:
            break
    return tuple(selected)


def build_initial_prompt(terms: tuple[str, ...]) -> str | None:
    if not terms:
        return None
    prompt_terms = fit_terms_to_budget(
        terms,
        max_terms=INITIAL_PROMPT_TERMS_MAX,
        max_chars=INITIAL_PROMPT_CHARS_MAX,
    )
    compact_terms = ", ".join(prompt_terms)
    return (
        "Українська телефонна розмова з довідковою службою КПІ імені Ігоря "
        f"Сікорського. Типові слова і теми: {compact_terms}."
    )


def build_hotwords(terms: tuple[str, ...]) -> str | None:
    if not terms:
        return None
    hotword_terms = fit_terms_to_budget(
        terms,
        max_terms=HOTWORDS_TERMS_MAX,
        max_chars=HOTWORDS_CHARS_MAX,
    )
    return ", ".join(hotword_terms)


def levenshtein_distance(left: str, right: str, *, limit: int | None = None) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if limit is not None and abs(len(left) - len(right)) > limit:
        return limit + 1

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            substitution_cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + substitution_cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if limit is not None and row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def has_close_shape(left: str, right: str) -> bool:
    if len(left) < 5 or len(right) < 5:
        return False
    if left[:1] != right[:1]:
        return False
    if len(left) >= 6 and len(right) >= 6 and left[:2] != right[:2]:
        return False
    length_ratio = min(len(left), len(right)) / max(len(left), len(right))
    return length_ratio >= 0.72


def best_domain_match(
    value: str,
    vocabulary: tuple[str, ...],
    *,
    min_score: float,
    max_distance: int,
) -> str | None:
    normalized_value = normalize_for_stt_matching(value)
    if len(normalized_value) < 5 or normalized_value in vocabulary:
        return None

    best_term: str | None = None
    best_score = 0.0
    second_score = 0.0
    for term in vocabulary:
        if (
            abs(len(normalized_value) - len(term)) <= 2
            and (normalized_value.startswith(term) or term.startswith(normalized_value))
        ):
            continue
        if not has_close_shape(normalized_value, term):
            continue
        distance = levenshtein_distance(normalized_value, term, limit=max_distance)
        if distance > max_distance:
            continue
        score = 1.0 - distance / max(len(normalized_value), len(term))
        if score > best_score:
            second_score = best_score
            best_score = score
            best_term = term
        elif score > second_score:
            second_score = score

    if best_term and best_score >= min_score and best_score - second_score >= 0.04:
        return best_term
    return None


def correct_domain_transcription_text(text: str, vocabulary: tuple[str, ...] | None = None) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return normalized

    terms = vocabulary or build_stt_domain_terms()
    word_vocabulary = tuple(term for term in terms if " " not in term and is_domain_word(term))
    words = list(stt_words(normalized))
    if not words:
        return normalized

    corrected_words: list[str] = []
    index = 0
    while index < len(words):
        replacement: str | None = None
        consumed = 1

        for window_size in (3, 2):
            if index + window_size > len(words):
                continue
            window_words = words[index : index + window_size]
            if all(len(word) > 3 for word in window_words):
                continue
            joined = "".join(window_words)
            replacement = best_domain_match(
                joined,
                word_vocabulary,
                min_score=0.84,
                max_distance=2,
            )
            if replacement:
                consumed = window_size
                break

        if not replacement:
            word = words[index]
            min_score = 0.66 if len(word) >= 6 else 0.78
            replacement = best_domain_match(
                word,
                word_vocabulary,
                min_score=min_score,
                max_distance=2,
            )

        corrected_words.append(replacement or words[index])
        index += consumed

    return normalize_text(" ".join(corrected_words))


class SpeechToTextService:
    def __init__(self) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Install backend dependencies before transcription."
            ) from exc

        self.model_name = settings.whisper_model_size
        self.model = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        self.prompt_terms = build_stt_prompt_terms()
        self.initial_prompt = build_initial_prompt(self.prompt_terms)
        self.hotwords = build_hotwords(self.prompt_terms)

    def _transcribe_sync(self, audio_path: Path) -> TranscriptionResult:
        segments, info = self.model.transcribe(
            str(audio_path),
            language="uk",
            vad_filter=True,
            beam_size=settings.whisper_beam_size,
            temperature=settings.whisper_temperature,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt,
            hotwords=self.hotwords,
        )
        segment_list = list(segments)
        raw_text = " ".join(segment.text.strip() for segment in segment_list).strip()
        text = normalize_text(raw_text)
        if settings.whisper_transcription_corrections_enabled:
            text = correct_domain_transcription_text(text)
            if text != normalize_text(raw_text):
                logger.info("STT corrected transcription: %r -> %r", raw_text, text)
        duration = segment_list[-1].end if segment_list else None
        return TranscriptionResult(
            text=text,
            language=info.language,
            duration_seconds=duration,
            model_name=f"faster-whisper/{self.model_name}",
        )

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path)


@lru_cache
def get_stt_service() -> SpeechToTextService:
    return SpeechToTextService()
