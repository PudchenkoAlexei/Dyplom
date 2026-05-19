from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.services.voice_assistant import normalize_text

settings = get_settings()


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

        speech_text = normalize_text(text)[: settings.voice_assistant_tts_max_chars]
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
