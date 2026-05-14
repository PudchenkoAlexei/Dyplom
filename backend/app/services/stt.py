import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None
    model_name: str


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

    def _transcribe_sync(self, audio_path: Path) -> TranscriptionResult:
        segments, info = self.model.transcribe(
            str(audio_path),
            language="uk",
            vad_filter=True,
            beam_size=settings.whisper_beam_size,
            condition_on_previous_text=False,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
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
