from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import Timestamped


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    contact_url: str | None = None
    is_active: bool = True


class DepartmentRead(Timestamped):
    id: UUID
    name: str
    description: str | None
    contact_url: str | None
    is_active: bool


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    default_department_id: UUID | None = None


class CategoryRead(Timestamped):
    id: UUID
    name: str
    description: str | None
    default_department_id: UUID | None
