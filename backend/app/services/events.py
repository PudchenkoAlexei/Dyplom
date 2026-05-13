from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TicketEventType
from app.models.ticket import TicketEvent


async def add_ticket_event(
    db: AsyncSession,
    *,
    ticket_id: UUID,
    actor_id: UUID | None,
    event_type: TicketEventType,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
) -> TicketEvent:
    event = TicketEvent(
        ticket_id=ticket_id,
        actor_id=actor_id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(event)
    return event
