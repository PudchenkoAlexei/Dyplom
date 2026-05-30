from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import KnowledgeEntryStatus
from app.schemas.common import Timestamped


class KnowledgeEntryBase(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    question: str = Field(min_length=3, max_length=12000)
    answer: str = Field(min_length=3, max_length=20000)
    source_url: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=40)


class KnowledgeEntryCreate(KnowledgeEntryBase):
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    status: KnowledgeEntryStatus = KnowledgeEntryStatus.draft


class KnowledgeEntryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    question: str | None = Field(default=None, min_length=3, max_length=12000)
    answer: str | None = Field(default=None, min_length=3, max_length=20000)
    source_url: str | None = Field(default=None, min_length=1, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=40)
    status: KnowledgeEntryStatus | None = None


class KnowledgeEntryRead(Timestamped):
    id: UUID
    slug: str
    title: str
    question: str
    answer: str
    source_url: str
    tags: list[str]
    status: KnowledgeEntryStatus
    content_hash: str
    published_at: datetime | None


class KnowledgeEntryPage(BaseModel):
    items: list[KnowledgeEntryRead]
    total: int
    limit: int
    offset: int
