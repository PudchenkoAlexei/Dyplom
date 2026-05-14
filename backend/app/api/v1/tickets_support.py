import hashlib
import json
from pathlib import Path
from typing import overload
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import PROJECT_ROOT, get_settings
from app.models.category import Category
from app.models.department import Department
from app.models.enums import UserRole
from app.models.model import ModelVersion
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.schemas.ticket import DraftTicketResponse, TicketRead
from app.services.classifier_prompt import CatalogItem
from app.services.storage import delete_audio_file

settings = get_settings()
MODEL_DATASET_PATH = PROJECT_ROOT / "ml/data/curated/tickets_curated.jsonl"
TEST_METRICS_PATH = PROJECT_ROOT / "ml/outputs/evaluation_metrics.json"
GENERATED_METRICS_PATH = PROJECT_ROOT / "ml/outputs/generated_100_eval_metrics.json"


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


def _file_sha256_prefix(path: Path, length: int = 12) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def _current_dataset_version() -> str | None:
    digest = _file_sha256_prefix(MODEL_DATASET_PATH)
    return f"tickets_curated:{digest}" if digest else None


def _compact_metrics(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    keys = [
        "split",
        "count",
        "parsed",
        "parse_failures",
        "category_accuracy",
        "priority_accuracy",
        "difficulty",
        "unknown_categories",
    ]
    return {key: data[key] for key in keys if key in data}


def _current_metrics_snapshot() -> dict | None:
    metrics = {
        "test": _compact_metrics(TEST_METRICS_PATH),
        "generated_100": _compact_metrics(GENERATED_METRICS_PATH),
    }
    compacted = {key: value for key, value in metrics.items() if value is not None}
    return compacted or None


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


async def _get_ticket_message(db: AsyncSession, ticket_id: UUID, message_id: UUID) -> TicketMessage:
    message = await db.scalar(
        select(TicketMessage).where(
            TicketMessage.id == message_id,
            TicketMessage.ticket_id == ticket_id,
        )
    )
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    return message


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


@overload
def _find_by_name(items: list[Category], name: str) -> Category | None: ...


@overload
def _find_by_name(items: list[Department], name: str) -> Department | None: ...


def _find_by_name(
    items: list[Category] | list[Department],
    name: str,
) -> Category | Department | None:
    normalized = _normalize_name(name)
    for item in items:
        if _normalize_name(item.name) == normalized:
            return item
    return None


def _department_by_id(departments: list[Department]) -> dict[UUID, Department]:
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
    return DraftTicketResponse(
        ticket=TicketRead.model_validate(ticket),
        transcript_text=_ticket_transcript_text(ticket),
    )


async def _get_model_version(db: AsyncSession) -> ModelVersion:
    name = f"{settings.llm_base_model}:{settings.lora_adapter_path}"
    dataset_version = _current_dataset_version()
    metrics_json = _current_metrics_snapshot()
    version = await db.scalar(select(ModelVersion).where(ModelVersion.name == name))
    if version:
        changed = False
        if dataset_version and version.dataset_version != dataset_version:
            version.dataset_version = dataset_version
            changed = True
        if metrics_json and version.metrics_json != metrics_json:
            version.metrics_json = metrics_json
            changed = True
        if changed:
            await db.flush()
        return version
    version = ModelVersion(
        name=name,
        base_model=settings.llm_base_model,
        lora_adapter_path=str(settings.lora_adapter_path),
        dataset_version=dataset_version,
        metrics_json=metrics_json,
    )
    db.add(version)
    await db.flush()
    return version


async def _delete_ticket_with_audio(db: AsyncSession, ticket: Ticket) -> None:
    audio_path = ticket.audio.file_path if ticket.audio else None
    message_audio_paths = [
        message.audio_file_path for message in ticket.messages if message.audio_file_path
    ]
    await db.delete(ticket)
    await db.commit()
    if audio_path:
        delete_audio_file(audio_path)
    for message_audio_path in message_audio_paths:
        delete_audio_file(message_audio_path)
