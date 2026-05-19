from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.models.user import User
from app.schemas.voice_assistant import VoiceAssistantResponse, VoiceAssistantSpeechRequest
from app.security.deps import get_profile_ready_requester
from app.services.storage import delete_audio_file, save_ticket_audio
from app.services.stt import get_stt_service
from app.services.tts import get_tts_service
from app.services.voice_assistant import get_voice_assistant_service, normalize_text

router = APIRouter(prefix="/voice-assistant", tags=["voice assistant"])


@router.post("/ask", response_model=VoiceAssistantResponse)
async def ask_voice_assistant(
    question_text: str | None = Form(default=None, min_length=3, max_length=12000),
    audio: UploadFile | None = File(default=None),
    _: User = Depends(get_profile_ready_requester),
) -> VoiceAssistantResponse:
    question = normalize_text(question_text or "")
    if not question and not audio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide question text or audio.",
        )

    if not question and audio:
        stored_audio = await save_ticket_audio(uuid4(), audio)
        try:
            transcription = await get_stt_service().transcribe(stored_audio.file_path)
            question = normalize_text(transcription.text)
        finally:
            delete_audio_file(str(stored_audio.file_path))

    if len(question) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question text is too short.",
        )

    return await get_voice_assistant_service().answer(question)


@router.post("/speech")
async def synthesize_voice_assistant_speech(
    payload: VoiceAssistantSpeechRequest,
    _: User = Depends(get_profile_ready_requester),
) -> Response:
    result = await get_tts_service().synthesize(payload.text)
    return Response(
        content=result.audio,
        media_type=result.mime_type,
        headers={"X-TTS-Voice": result.voice},
    )
