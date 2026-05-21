import base64
import logging
import secrets
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.phone import PhoneAssistantCall
from app.schemas.phone_assistant import PhoneAssistantResponse
from app.schemas.voice_assistant import VoiceAssistantResponse
from app.services.storage import save_ticket_audio
from app.services.stt import get_stt_service
from app.services.tts import get_tts_service
from app.services.voice_assistant import get_voice_assistant_service, normalize_text

router = APIRouter(prefix="/phone-assistant", tags=["phone assistant"])
settings = get_settings()
logger = logging.getLogger("uvicorn.error")


def require_pbx_token(x_pbx_token: str | None = Header(default=None)) -> None:
    if not x_pbx_token or not secrets.compare_digest(x_pbx_token, settings.pbx_internal_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid PBX token.")


def _unrecognized_question_response(question: str) -> VoiceAssistantResponse:
    return VoiceAssistantResponse(
        question_text=question,
        answer_text=(
            "Не вдалося розпізнати питання з телефонного дзвінка. "
            "Будь ласка, зателефонуйте ще раз і сформулюйте питання після сигналу."
        ),
        confidence=0,
        source="unrecognized_audio",
        sources=[],
        can_create_ticket=False,
        used_llm=False,
        model_name=None,
    )


@router.post("/ask", response_model=PhoneAssistantResponse)
async def ask_phone_assistant(
    call_id: str = Form(..., min_length=1, max_length=160),
    caller_number: str | None = Form(default=None, max_length=80),
    audio: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_pbx_token),
) -> PhoneAssistantResponse:
    started_at = perf_counter()
    stored_audio = await save_ticket_audio(uuid4(), audio)
    audio_saved_at = perf_counter()
    transcription = await get_stt_service().transcribe(stored_audio.file_path)
    question = normalize_text(transcription.text)
    transcribed_at = perf_counter()

    if len(question) >= 3:
        assistant_response = await get_voice_assistant_service().answer(question)
    else:
        assistant_response = _unrecognized_question_response(question)
    answered_at = perf_counter()

    tts_result = await get_tts_service().synthesize(assistant_response.answer_text)
    synthesized_at = perf_counter()
    source_rows = [source.model_dump(mode="json") for source in assistant_response.sources]

    db.add(
        PhoneAssistantCall(
            call_id=call_id,
            caller_number=normalize_text(caller_number or "") or None,
            question_audio_path=str(stored_audio.file_path),
            question_audio_mime_type=stored_audio.mime_type,
            question_audio_size_bytes=stored_audio.size_bytes,
            question_text=assistant_response.question_text,
            answer_text=assistant_response.answer_text,
            confidence=assistant_response.confidence,
            source=assistant_response.source,
            sources_json=source_rows,
            used_llm=assistant_response.used_llm,
            model_name=assistant_response.model_name,
        )
    )
    await db.commit()
    committed_at = perf_counter()

    logger.info(
        "phone assistant call %s timing: save=%.2fs stt=%.2fs answer=%.2fs tts=%.2fs db=%.2fs total=%.2fs",
        call_id,
        audio_saved_at - started_at,
        transcribed_at - audio_saved_at,
        answered_at - transcribed_at,
        synthesized_at - answered_at,
        committed_at - synthesized_at,
        committed_at - started_at,
    )

    return PhoneAssistantResponse(
        call_id=call_id,
        caller_number=normalize_text(caller_number or "") or None,
        question_text=assistant_response.question_text,
        answer_text=assistant_response.answer_text,
        confidence=assistant_response.confidence,
        source=assistant_response.source,
        sources=assistant_response.sources,
        used_llm=assistant_response.used_llm,
        model_name=assistant_response.model_name,
        answer_audio_mime_type=tts_result.mime_type,
        answer_audio_base64=base64.b64encode(tts_result.audio).decode("ascii"),
    )
