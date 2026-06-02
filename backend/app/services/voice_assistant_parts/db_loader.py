# ruff: noqa: F403,F405
from .shared import *
from .shared import _DATABASE_KNOWLEDGE_BASE_CACHE
from .models import KnowledgeBaseEntry
from .knowledge_base import KnowledgeBaseService
async def load_published_knowledge_base(db: AsyncSession) -> KnowledgeBaseService | None:
    result = await db.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.status == KnowledgeEntryStatus.published)
        .order_by(KnowledgeEntry.title)
    )
    rows = list(result.scalars())
    if not rows:
        return None

    version_payload = [
        (
            str(row.id),
            row.content_hash,
            row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]
    version_key = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cached = _DATABASE_KNOWLEDGE_BASE_CACHE.get(version_key)
    if cached is not None:
        return cached

    service = KnowledgeBaseService.from_entries(
        [
            KnowledgeBaseEntry(
                id=row.slug or str(row.id),
                title=row.title,
                question=row.question,
                answer=row.answer,
                source_url=row.source_url,
                tags=tuple(str(tag) for tag in row.tags_json or []),
            )
            for row in rows
        ]
    )
    if len(_DATABASE_KNOWLEDGE_BASE_CACHE) >= 4:
        _DATABASE_KNOWLEDGE_BASE_CACHE.clear()
    _DATABASE_KNOWLEDGE_BASE_CACHE[version_key] = service
    return service
