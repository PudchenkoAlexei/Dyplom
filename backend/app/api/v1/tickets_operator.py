from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.tickets_support import (
    _delete_ticket_with_audio,
    _ensure_ticket_operator_access,
    _get_ticket,
    _ticket_options,
)
from app.db.session import get_db
from app.models.category import Category
from app.models.department import Department
from app.models.enums import TicketEventType, TicketStatus
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.ticket import (
    OperatorTicketPage,
    OperatorTicketRead,
    TicketClassificationUpdate,
    TicketMessageCreate,
)
from app.security.deps import get_profile_ready_operator
from app.services.events import add_ticket_event


operator_router = APIRouter(prefix="/operator/tickets", tags=["operator tickets"])


@operator_router.get("", response_model=OperatorTicketPage)
async def list_operator_tickets(
    status_filter: TicketStatus | None = None,
    assigned_to_me: bool | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_profile_ready_operator),
) -> OperatorTicketPage:
    query = (
        select(Ticket)
        .options(*_ticket_options(include_author=True))
        .order_by(Ticket.created_at.desc())
    )
    count_query = select(func.count(Ticket.id))
    if status_filter:
        query = query.where(Ticket.status == status_filter)
        count_query = count_query.where(Ticket.status == status_filter)
    if assigned_to_me is True:
        query = query.where(Ticket.assigned_operator_id == current_user.id)
        count_query = count_query.where(Ticket.assigned_operator_id == current_user.id)
    elif assigned_to_me is False:
        query = query.where(Ticket.assigned_operator_id.is_(None))
        count_query = count_query.where(Ticket.assigned_operator_id.is_(None))
    total = await db.scalar(count_query)
    result = await db.execute(query.limit(limit).offset(offset))
    return OperatorTicketPage(
        items=list(result.scalars()),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category or department not found."
        )

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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Closed ticket cannot receive messages."
        )

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
