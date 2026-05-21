from dataclasses import dataclass
from functools import lru_cache
import re

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.services.voice_assistant import normalize_text

settings = get_settings()

KPI_SPOKEN = "\u043a\u0430 \u043f\u0435 \u0456"
TTS_REPLACEMENTS = (
    (re.compile(r"\b(?:\u041a\u041f\u0406|KPI)\b", re.IGNORECASE), KPI_SPOKEN),
    (re.compile(r"\b\u041d\u0422\u0423\u0423\b", re.IGNORECASE), "\u0435\u043d \u0442\u0435 \u0443 \u0443"),
    (
        re.compile(r"\b\u0428\u0406-\u043c\u043e\u0434\u0435\u043b\w*\b", re.IGNORECASE),
        "\u043c\u043e\u0434\u0435\u043b\u044c \u0448\u0442\u0443\u0447\u043d\u043e\u0433\u043e \u0456\u043d\u0442\u0435\u043b\u0435\u043a\u0442\u0443",
    ),
    (
        re.compile(r"\b\u0428\u0406\b", re.IGNORECASE),
        "\u0448\u0442\u0443\u0447\u043d\u0438\u0439 \u0456\u043d\u0442\u0435\u043b\u0435\u043a\u0442",
    ),
    (re.compile(r"\bFAQ\b", re.IGNORECASE), "\u043f\u043e\u0448\u0438\u0440\u0435\u043d\u0438\u0445 \u043f\u0438\u0442\u0430\u043d\u044c"),
    (re.compile(r"\bURL\b", re.IGNORECASE), "\u043f\u043e\u0441\u0438\u043b\u0430\u043d\u043d\u044f"),
    (re.compile(r"\b\u0456\u043c\.", re.IGNORECASE), "\u0456\u043c\u0435\u043d\u0456"),
    (re.compile(r"\b\u043f\u0440\.", re.IGNORECASE), "\u043f\u0440\u043e\u0441\u043f\u0435\u043a\u0442"),
    (re.compile(r"\bemail\b|\be-mail\b", re.IGNORECASE), "\u0435\u043b\u0435\u043a\u0442\u0440\u043e\u043d\u043d\u0430 \u043f\u043e\u0448\u0442\u0430"),
    (re.compile(r"\b\u0442\u0435\u043b\./\u0444\u0430\u043a\u0441\b", re.IGNORECASE), "\u0442\u0435\u043b\u0435\u0444\u043e\u043d \u0456 \u0444\u0430\u043a\u0441"),
)


def prepare_text_for_speech(text: str) -> str:
    speech_text = normalize_text(text)
    for pattern, replacement in TTS_REPLACEMENTS:
        speech_text = pattern.sub(replacement, speech_text)
    speech_text = speech_text.replace(f"{KPI_SPOKEN}-", f"{KPI_SPOKEN} ")
    speech_text = re.sub(
        rf"{KPI_SPOKEN} (?=\u0456\u043c\u0435\u043d\u0456\b)",
        f"{KPI_SPOKEN}, ",
        speech_text,
        flags=re.IGNORECASE,
    )
    return normalize_text(speech_text)


@dataclass(frozen=True)
class TextToSpeechResult:
    audio: bytes
    mime_type: str
    voice: str


class TextToSpeechService:
    async def synthesize(self, text: str) -> TextToSpeechResult:
        if not settings.voice_assistant_tts_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text-to-speech is disabled.",
            )

        try:
            import edge_tts
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text-to-speech dependency is not installed.",
            ) from exc

        speech_text = prepare_text_for_speech(text)[: settings.voice_assistant_tts_max_chars]
        communicate = edge_tts.Communicate(
            speech_text,
            settings.voice_assistant_tts_voice,
            rate=settings.voice_assistant_tts_rate,
        )
        chunks: list[bytes] = []
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text-to-speech service is unavailable.",
            ) from exc

        audio = b"".join(chunks)
        if not audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text-to-speech service returned empty audio.",
            )

        return TextToSpeechResult(
            audio=audio,
            mime_type="audio/mpeg",
            voice=settings.voice_assistant_tts_voice,
        )


@lru_cache
def get_tts_service() -> TextToSpeechService:
    return TextToSpeechService()
