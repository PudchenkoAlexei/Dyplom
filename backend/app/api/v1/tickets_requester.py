from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.tickets_support import (
    _delete_ticket_with_audio,
    _ensure_ticket_view_access,
    _existing_draft_response,
    _get_ticket,
    _make_title,
    _normalize_client_request_id,
    _ticket_options,
)
from app.db.session import get_db
from app.models.enums import TicketEventType, TicketStatus
from app.models.ticket import Ticket, TicketAudio, TicketMessage, TicketTranscript
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.ticket import (
    DraftTicketResponse,
    TicketListItem,
    TicketMessageCreate,
    TicketRead,
    TicketTextUpdate,
)
from app.security.deps import get_profile_ready_requester, get_profile_ready_user
from app.services.events import add_ticket_event
from app.services.ticket_classification import classify_submitted_ticket
from app.services.storage import resolve_audio_path, save_ticket_audio
from app.services.stt import get_stt_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post(
    "/draft-audio", response_model=DraftTicketResponse, status_code=status.HTTP_201_CREATED
)
async def create_draft_from_audio(
    audio: UploadFile = File(...),
    client_request_id: str | None = Form(default=None, max_length=80),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> DraftTicketResponse:
    normalized_client_request_id = _normalize_client_request_id(client_request_id)
    existing = await _existing_draft_response(db, current_user.id, normalized_client_request_id)
    if existing:
        return existing

    ticket = Ticket(
        author_id=current_user.id,
        client_request_id=normalized_client_request_id,
        status=TicketStatus.draft,
    )
    db.add(ticket)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _existing_draft_response(db, current_user.id, normalized_client_request_id)
        if existing:
            return existing
        raise

    stored_audio = await save_ticket_audio(ticket.id, audio)
    transcription = await get_stt_service().transcribe(stored_audio.file_path)

    ticket.title = _make_title(transcription.text)
    ticket.edited_text = transcription.text
    ticket.audio = TicketAudio(
        file_path=str(stored_audio.file_path),
        original_filename=audio.filename,
        mime_type=stored_audio.mime_type,
        size_bytes=stored_audio.size_bytes,
        duration_seconds=transcription.duration_seconds,
    )
    ticket.transcript = TicketTranscript(
        raw_text=transcription.text,
        edited_text=transcription.text,
        stt_model=transcription.model_name,
        language=transcription.language,
    )
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.created,
        new_value={"status": TicketStatus.draft.value},
    )
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.audio_uploaded,
        new_value={"mime_type": stored_audio.mime_type, "size_bytes": stored_audio.size_bytes},
    )
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.transcribed,
        new_value={"stt_model": transcription.model_name, "language": transcription.language},
    )
    await db.commit()
    loaded = await _get_ticket(db, ticket.id)
    return DraftTicketResponse(ticket=loaded, transcript_text=transcription.text)


@router.post(
    "/draft-browser-transcript",
    response_model=DraftTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_from_browser_transcript(
    transcript_text: str = Form(..., min_length=3, max_length=12000),
    client_request_id: str | None = Form(default=None, max_length=80),
    audio: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> DraftTicketResponse:
    text = " ".join(transcript_text.split())
    normalized_client_request_id = _normalize_client_request_id(client_request_id)
    existing = await _existing_draft_response(db, current_user.id, normalized_client_request_id)
    if existing:
        return existing

    ticket = Ticket(
        author_id=current_user.id,
        client_request_id=normalized_client_request_id,
        status=TicketStatus.draft,
        title=_make_title(text),
        edited_text=text,
    )
    db.add(ticket)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _existing_draft_response(db, current_user.id, normalized_client_request_id)
        if existing:
            return existing
        raise

    if audio:
        stored_audio = await save_ticket_audio(ticket.id, audio)
        ticket.audio = TicketAudio(
            file_path=str(stored_audio.file_path),
            original_filename=audio.filename,
            mime_type=stored_audio.mime_type,
            size_bytes=stored_audio.size_bytes,
            duration_seconds=None,
        )
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            event_type=TicketEventType.audio_uploaded,
            new_value={"mime_type": stored_audio.mime_type, "size_bytes": stored_audio.size_bytes},
        )

    ticket.transcript = TicketTranscript(
        raw_text=text,
        edited_text=text,
        stt_model="browser-speech-recognition",
        language="uk-UA",
    )
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.created,
        new_value={"status": TicketStatus.draft.value},
    )
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.transcribed,
        new_value={"stt_model": "browser-speech-recognition", "language": "uk-UA"},
    )
    await db.commit()
    loaded = await _get_ticket(db, ticket.id)
    return DraftTicketResponse(ticket=loaded, transcript_text=text)


@router.get("/my", response_model=list[TicketListItem])
async def list_my_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> list[Ticket]:
    result = await db.execute(
        select(Ticket)
        .where(Ticket.author_id == current_user.id)
        .options(*_ticket_options())
        .order_by(Ticket.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_user),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    _ensure_ticket_view_access(ticket, current_user)
    return ticket


@router.get("/{ticket_id}/audio")
async def get_ticket_audio(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_user),
) -> FileResponse:
    ticket = await _get_ticket(db, ticket_id)
    _ensure_ticket_view_access(ticket, current_user)
    if not ticket.audio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket has no audio.")
    path = resolve_audio_path(ticket.audio.file_path)
    return FileResponse(path, media_type=ticket.audio.mime_type, filename=path.name)


@router.delete("/{ticket_id}", response_model=MessageResponse)
async def delete_my_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> MessageResponse:
    ticket = await _get_ticket(db, ticket_id)
    if ticket.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ticket access denied.")

    await _delete_ticket_with_audio(db, ticket)
    return MessageResponse(message="Ticket deleted.")


@router.patch("/{ticket_id}/text", response_model=TicketRead)
async def update_draft_text(
    ticket_id: UUID,
    payload: TicketTextUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    if ticket.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ticket access denied.")
    if ticket.status != TicketStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only draft tickets can be edited."
        )

    old_text = ticket.edited_text
    ticket.edited_text = payload.edited_text
    ticket.title = _make_title(payload.edited_text)
    if ticket.transcript:
        ticket.transcript.edited_text = payload.edited_text
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.edited,
        old_value={"edited_text": old_text},
        new_value={"edited_text": payload.edited_text},
    )
    await db.commit()
    return await _get_ticket(db, ticket.id)


@router.post("/{ticket_id}/submit", response_model=TicketRead)
async def submit_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    if ticket.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ticket access denied.")
    if ticket.status != TicketStatus.draft:
        return await _get_ticket(db, ticket.id)
    if not ticket.edited_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ticket text is empty."
        )

    result = await db.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id, Ticket.status == TicketStatus.draft)
        .values(status=TicketStatus.submitted, updated_at=datetime.now(timezone.utc))
        .returning(Ticket.id)
    )
    if not result.scalar_one_or_none():
        await db.rollback()
        return await _get_ticket(db, ticket_id)

    ticket.status = TicketStatus.submitted
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.submitted,
        new_value={"status": TicketStatus.submitted.value},
    )
    await db.commit()

    await classify_submitted_ticket(db, ticket, current_user)
    return await _get_ticket(db, ticket.id)


@router.post("/{ticket_id}/messages", response_model=TicketRead)
async def add_requester_message(
    ticket_id: UUID,
    payload: TicketMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_requester),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    if ticket.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ticket access denied.")
    if ticket.status == TicketStatus.closed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Closed ticket cannot receive messages."
        )

    db.add(TicketMessage(ticket_id=ticket.id, sender_id=current_user.id, message=payload.message))
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.message_sent,
        new_value={"sender_id": str(current_user.id)},
    )
    await db.commit()
    return await _get_ticket(db, ticket.id)
