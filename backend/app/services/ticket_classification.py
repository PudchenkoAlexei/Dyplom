import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.tickets_support import (
    _category_catalog_item,
    _department_by_id,
    _find_by_name,
    _get_model_version,
)
from app.models.category import Category
from app.models.department import Department
from app.models.enums import TicketEventType, TicketStatus
from app.models.model import ModelPrediction
from app.models.ticket import Ticket
from app.models.user import User
from app.services.classifier import get_classifier_service
from app.services.events import add_ticket_event

logger = logging.getLogger(__name__)


async def classify_submitted_ticket(db: AsyncSession, ticket: Ticket, current_user: User) -> None:
    categories = list((await db.execute(select(Category))).scalars())
    departments = list(
        (await db.execute(select(Department).where(Department.is_active.is_(True)))).scalars()
    )
    if not categories or not departments:
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={"classification_status": "skipped", "reason": "Catalog is not configured."},
        )
        await db.commit()
        return

    departments_by_id = _department_by_id(departments)
    try:
        classifier = get_classifier_service()
        classification = classifier.classify(
            role=current_user.role,
            text=ticket.edited_text,
            categories=[_category_catalog_item(item) for item in categories],
        )
    except RuntimeError:
        logger.exception("Ticket classification failed for ticket %s.", ticket.id)
        await add_ticket_event(
            db,
            ticket_id=ticket.id,
            actor_id=None,
            event_type=TicketEventType.status_changed,
            new_value={
                "classification_status": "failed",
                "reason": "Classifier service failed. Ticket remains in submitted state.",
            },
        )
        await db.commit()
        return

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
        return

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
        return
    department = default_department
    if classification.fallback_reason:
        logger.warning(
            "Ticket %s classified through fallback route: %s",
            ticket.id,
            classification.fallback_reason,
        )
        prediction_note = (
            "Застосовано fallback-маршрутизацію: модель не повернула придатний результат, "
            "тому заявку передано в первинну маршрутизацію."
        )
    else:
        prediction_note = (
            "Категорію і пріоритет визначено мовною моделлю; підрозділ взято з каталогу категорій. "
            "Поле confidence є службовим routing score, а не ймовірністю, згенерованою моделлю."
        )
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
    return
