from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import KnowledgeEntryStatus, UserRole
from app.models.knowledge import KnowledgeEntry
from app.models.user import User
from app.schemas.knowledge import KnowledgeEntryCreate, KnowledgeEntryPage, KnowledgeEntryRead
from app.schemas.knowledge import KnowledgeEntryUpdate
from app.security.deps import require_roles
from app.services.knowledge_base_admin import (
    entry_to_read,
    make_unique_slug,
    normalize_tags,
    set_entry_content_hash,
    utc_now,
)

router = APIRouter(prefix="/admin/knowledge", tags=["admin knowledge"])


async def get_knowledge_entry(db: AsyncSession, entry_id: UUID) -> KnowledgeEntry:
    entry = await db.get(KnowledgeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge entry not found.")
    return entry


@router.get("", response_model=KnowledgeEntryPage)
async def list_knowledge_entries(
    status_filter: KnowledgeEntryStatus | None = None,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryPage:
    query = select(KnowledgeEntry)
    count_query = select(func.count(KnowledgeEntry.id))

    if status_filter:
        query = query.where(KnowledgeEntry.status == status_filter)
        count_query = count_query.where(KnowledgeEntry.status == status_filter)

    normalized_search = " ".join((search or "").split())
    if normalized_search:
        pattern = f"%{normalized_search}%"
        search_clause = or_(
            KnowledgeEntry.slug.ilike(pattern),
            KnowledgeEntry.title.ilike(pattern),
            KnowledgeEntry.question.ilike(pattern),
            KnowledgeEntry.answer.ilike(pattern),
            KnowledgeEntry.source_url.ilike(pattern),
        )
        query = query.where(search_clause)
        count_query = count_query.where(search_clause)

    total = await db.scalar(count_query)
    result = await db.execute(
        query.order_by(KnowledgeEntry.updated_at.desc()).limit(limit).offset(offset)
    )
    entries = result.scalars().all()
    return KnowledgeEntryPage(
        items=[entry_to_read(entry) for entry in entries],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=KnowledgeEntryRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_entry(
    payload: KnowledgeEntryCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryRead:
    entry = KnowledgeEntry(
        slug=await make_unique_slug(db, payload.slug or payload.title),
        title=" ".join(payload.title.split()),
        question=" ".join(payload.question.split()),
        answer=" ".join(payload.answer.split()),
        source_url=payload.source_url.strip(),
        tags_json=normalize_tags(payload.tags),
        status=payload.status,
        content_hash="",
        published_at=utc_now() if payload.status == KnowledgeEntryStatus.published else None,
    )
    set_entry_content_hash(entry)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry_to_read(entry)


@router.get("/{entry_id}", response_model=KnowledgeEntryRead)
async def read_knowledge_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryRead:
    return entry_to_read(await get_knowledge_entry(db, entry_id))


@router.patch("/{entry_id}", response_model=KnowledgeEntryRead)
async def update_knowledge_entry(
    entry_id: UUID,
    payload: KnowledgeEntryUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryRead:
    entry = await get_knowledge_entry(db, entry_id)
    changes = payload.model_dump(exclude_unset=True)

    content_changed = False
    if "title" in changes and changes["title"] is not None:
        entry.title = " ".join(changes["title"].split())
        content_changed = True
    if "question" in changes and changes["question"] is not None:
        entry.question = " ".join(changes["question"].split())
        content_changed = True
    if "answer" in changes and changes["answer"] is not None:
        entry.answer = " ".join(changes["answer"].split())
        content_changed = True
    if "source_url" in changes and changes["source_url"] is not None:
        entry.source_url = changes["source_url"].strip()
        content_changed = True
    if "tags" in changes and changes["tags"] is not None:
        entry.tags_json = normalize_tags(changes["tags"])
        content_changed = True
    if "status" in changes and changes["status"] is not None:
        entry.status = changes["status"]
        if entry.status == KnowledgeEntryStatus.published and entry.published_at is None:
            entry.published_at = utc_now()

    if content_changed:
        set_entry_content_hash(entry)

    await db.commit()
    await db.refresh(entry)
    return entry_to_read(entry)


@router.post("/{entry_id}/publish", response_model=KnowledgeEntryRead)
async def publish_knowledge_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryRead:
    entry = await get_knowledge_entry(db, entry_id)
    entry.status = KnowledgeEntryStatus.published
    entry.published_at = entry.published_at or utc_now()
    await db.commit()
    await db.refresh(entry)
    return entry_to_read(entry)


@router.post("/{entry_id}/archive", response_model=KnowledgeEntryRead)
async def archive_knowledge_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeEntryRead:
    entry = await get_knowledge_entry(db, entry_id)
    entry.status = KnowledgeEntryStatus.archived
    await db.commit()
    await db.refresh(entry)
    return entry_to_read(entry)
