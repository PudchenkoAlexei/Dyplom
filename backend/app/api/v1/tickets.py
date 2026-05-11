from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.category import Category
from app.models.department import Department
from app.models.enums import TicketEventType, TicketStatus, UserRole
from app.models.model import ModelPrediction, ModelVersion
from app.models.ticket import Ticket, TicketAudio, TicketMessage, TicketTranscript
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.ticket import (
    DraftTicketResponse,
    OperatorTicketRead,
    TicketClassificationUpdate,
    TicketListItem,
    TicketMessageCreate,
    TicketRead,
    TicketTextUpdate,
)
from app.security.deps import (
    get_profile_ready_operator,
    get_profile_ready_requester,
    get_profile_ready_user,
)
from app.services.classifier import CatalogItem, get_classifier_service
from app.services.events import add_ticket_event
from app.services.storage import delete_audio_file, resolve_audio_path, save_ticket_audio
from app.services.stt import get_stt_service
from app.core.config import get_settings

router = APIRouter(prefix="/tickets", tags=["tickets"])
settings = get_settings()


def _ticket_options(include_author: bool = False) -> list:
    options = [
        selectinload(Ticket.author),
        selectinload(Ticket.category),
        selectinload(Ticket.department),
        selectinload(Ticket.audio),
        selectinload(Ticket.transcript),
        selectinload(Ticket.messages),
        selectinload(Ticket.events),
        selectinload(Ticket.assigned_operator),
    ]
    return options


async def _get_ticket(db: AsyncSession, ticket_id: UUID, include_author: bool = False) -> Ticket:
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(*_ticket_options(include_author))
        .execution_options(populate_existing=True)
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


def _ensure_ticket_view_access(ticket: Ticket, user: User) -> None:
    if user.role in {UserRole.operator, UserRole.admin}:
        return
    if ticket.author_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ticket access denied.")


def _ensure_ticket_operator_access(ticket: Ticket, user: User) -> None:
    if user.role == UserRole.admin:
        return
    if ticket.assigned_operator_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket must be claimed by this operator before editing.",
        )


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _find_by_name(items: list[Category] | list[Department], name: str):
    normalized = _normalize_name(name)
    for item in items:
        if _normalize_name(item.name) == normalized:
            return item
    return None


def _department_by_id(departments: list[Department]) -> dict:
    return {department.id: department for department in departments}


def _category_catalog_item(category: Category) -> CatalogItem:
    return CatalogItem(name=category.name, description=category.description)


def _make_title(text: str) -> str:
    text = " ".join(text.split())
    return text[:177] + "..." if len(text) > 180 else text


def _normalize_client_request_id(client_request_id: str | None) -> str | None:
    if client_request_id is None:
        return None
    normalized = client_request_id.strip()
    if not normalized:
        return None
    if len(normalized) > 80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Client request id is too long.",
        )
    return normalized


def _ticket_transcript_text(ticket: Ticket) -> str:
    if ticket.transcript:
        return ticket.transcript.edited_text or ticket.transcript.raw_text
    return ticket.edited_text or ""


async def _get_ticket_by_client_request_id(
    db: AsyncSession,
    author_id: UUID,
    client_request_id: str | None,
) -> Ticket | None:
    if client_request_id is None:
        return None
    return await db.scalar(
        select(Ticket)
        .where(Ticket.author_id == author_id, Ticket.client_request_id == client_request_id)
        .options(*_ticket_options())
    )


async def _existing_draft_response(
    db: AsyncSession,
    author_id: UUID,
    client_request_id: str | None,
) -> DraftTicketResponse | None:
    ticket = await _get_ticket_by_client_request_id(db, author_id, client_request_id)
    if not ticket:
        return None
    return DraftTicketResponse(ticket=ticket, transcript_text=_ticket_transcript_text(ticket))


async def _get_model_version(db: AsyncSession) -> ModelVersion:
    name = f"{settings.llm_base_model}:{settings.lora_adapter_path}"
    version = await db.scalar(select(ModelVersion).where(ModelVersion.name == name))
    if version:
        return version
    version = ModelVersion(
        name=name,
        base_model=settings.llm_base_model,
        lora_adapter_path=str(settings.lora_adapter_path),
        dataset_version=None,
        metrics_json=None,
    )
    db.add(version)
    await db.flush()
    return version


async def _delete_ticket_with_audio(db: AsyncSession, ticket: Ticket) -> None:
    audio_path = ticket.audio.file_path if ticket.audio else None
    await db.delete(ticket)
    await db.commit()
    if audio_path:
        delete_audio_file(audio_path)


@router.post("/draft-audio", response_model=DraftTicketResponse, status_code=status.HTTP_201_CREATED)
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft tickets can be edited.")

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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ticket text is empty.")

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

    categories = list((await db.execute(select(Category))).scalars())
    departments = list((await db.execute(select(Department).where(Department.is_active.is_(True)))).scalars())
    if not categories or not departments:
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={"classification_status": "skipped", "reason": "Catalog is not configured."},
        )
        await db.commit()
        return await _get_ticket(db, ticket.id)

    departments_by_id = _department_by_id(departments)
    try:
        classifier = get_classifier_service()
        classification = classifier.classify(
            role=current_user.role,
            text=ticket.edited_text,
            categories=[_category_catalog_item(item) for item in categories],
        )
    except RuntimeError as exc:
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={"classification_status": "failed", "reason": str(exc)},
        )
        await db.commit()
        return await _get_ticket(db, ticket.id)

    category = _find_by_name(categories, classification.category)
    if not category:
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={
                "classification_status": "failed",
                "reason": "Classifier returned a category outside the configured catalog.",
            },
        )
        await db.commit()
        return await _get_ticket(db, ticket.id)

    default_department = departments_by_id.get(category.default_department_id)
    if not default_department:
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={
                "classification_status": "failed",
                "reason": "The classified category has no active default department.",
            },
        )
        await db.commit()
        return await _get_ticket(db, ticket.id)
    department = default_department
    prediction_note = "Категорію і пріоритет визначено мовною моделлю; підрозділ взято з каталогу категорій."
    prediction_raw = classification.model_dump(mode="json") | {"route_to": department.name}

    model_version = await _get_model_version(db)
    db.add(
        ModelPrediction(
            ticket_id=ticket.id,
            model_version_id=model_version.id,
            category_name=classification.category,
            department_name=department.name,
            priority=classification.priority,
            confidence=classification.confidence,
            reason=prediction_note,
            raw_output=prediction_raw,
        )
    )

    ticket.status = TicketStatus.classified
    ticket.category_id = category.id
    ticket.department_id = department.id
    ticket.priority = classification.priority
    ticket.model_confidence = classification.confidence
    ticket.model_reason = None
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=None,
        event_type=TicketEventType.classified,
        new_value=prediction_raw,
    )
    await db.commit()
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Closed ticket cannot receive messages.")

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


operator_router = APIRouter(prefix="/operator/tickets", tags=["operator tickets"])


@operator_router.get("", response_model=list[OperatorTicketRead])
async def list_operator_tickets(
    status_filter: TicketStatus | None = None,
    assigned_to_me: bool | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> list[Ticket]:
    query = select(Ticket).options(*_ticket_options(include_author=True)).order_by(Ticket.created_at.desc())
    if status_filter:
        query = query.where(Ticket.status == status_filter)
    if assigned_to_me is True:
        query = query.where(Ticket.assigned_operator_id == current_user.id)
    elif assigned_to_me is False:
        query = query.where(Ticket.assigned_operator_id.is_(None))
    result = await db.execute(query)
    return list(result.scalars())


@operator_router.get("/{ticket_id}", response_model=OperatorTicketRead)
async def get_operator_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_profile_ready_operator),
) -> Ticket:
    return await _get_ticket(db, ticket_id, include_author=True)


@operator_router.delete("/{ticket_id}", response_model=MessageResponse)
async def delete_operator_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_profile_ready_operator),
) -> MessageResponse:
    ticket = await _get_ticket(db, ticket_id)
    await _delete_ticket_with_audio(db, ticket)
    return MessageResponse(message="Ticket deleted.")


@operator_router.post("/{ticket_id}/claim", response_model=OperatorTicketRead)
async def claim_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    if ticket.assigned_operator_id == current_user.id:
        return await _get_ticket(db, ticket_id, include_author=True)

    result = await db.execute(
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.assigned_operator_id.is_(None),
            Ticket.status.in_([TicketStatus.submitted, TicketStatus.classified]),
        )
        .values(
            assigned_operator_id=current_user.id,
            status=TicketStatus.in_progress,
            updated_at=datetime.now(timezone.utc),
        )
        .returning(Ticket.id)
    )
    claimed_id = result.scalar_one_or_none()
    if not claimed_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ticket has already been claimed or is not claimable.",
        )
    await add_ticket_event(
        db,
        ticket_id=ticket_id,
        actor_id=current_user.id,
        event_type=TicketEventType.claimed,
        new_value={"assigned_operator_id": str(current_user.id)},
    )
    await db.commit()
    return await _get_ticket(db, ticket_id, include_author=True)


@operator_router.patch("/{ticket_id}/classification", response_model=OperatorTicketRead)
async def update_ticket_classification(
    ticket_id: UUID,
    payload: TicketClassificationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    _ensure_ticket_operator_access(ticket, current_user)

    category = await db.get(Category, payload.category_id)
    department = await db.get(Department, payload.department_id)
    if not category or not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category or department not found.")

    old_value = {
        "category_id": str(ticket.category_id) if ticket.category_id else None,
        "department_id": str(ticket.department_id) if ticket.department_id else None,
        "priority": ticket.priority.value if ticket.priority else None,
    }
    ticket.category_id = category.id
    ticket.department_id = department.id
    ticket.priority = payload.priority
    if payload.reason:
        ticket.model_reason = payload.reason
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.classification_changed,
        old_value=old_value,
        new_value={
            "category_id": str(category.id),
            "department_id": str(department.id),
            "priority": payload.priority.value,
        },
    )
    await db.commit()
    return await _get_ticket(db, ticket.id, include_author=True)


@operator_router.post("/{ticket_id}/messages", response_model=OperatorTicketRead)
async def add_operator_message(
    ticket_id: UUID,
    payload: TicketMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    _ensure_ticket_operator_access(ticket, current_user)
    if ticket.status == TicketStatus.closed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Closed ticket cannot receive messages.")

    db.add(TicketMessage(ticket_id=ticket.id, sender_id=current_user.id, message=payload.message))
    old_status = ticket.status
    ticket.status = TicketStatus.answered
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.message_sent,
        old_value={"status": old_status.value},
        new_value={"status": TicketStatus.answered.value, "sender_id": str(current_user.id)},
    )
    await db.commit()
    return await _get_ticket(db, ticket.id, include_author=True)


@operator_router.post("/{ticket_id}/close", response_model=OperatorTicketRead)
async def close_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> Ticket:
    ticket = await _get_ticket(db, ticket_id)
    _ensure_ticket_operator_access(ticket, current_user)
    if ticket.status == TicketStatus.closed:
        return await _get_ticket(db, ticket.id, include_author=True)

    old_status = ticket.status
    ticket.status = TicketStatus.closed
    ticket.closed_at = datetime.now(timezone.utc)
    await add_ticket_event(
        db,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type=TicketEventType.closed,
        old_value={"status": old_status.value},
        new_value={"status": TicketStatus.closed.value},
    )
    await db.commit()
    return await _get_ticket(db, ticket.id, include_author=True)
