from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole
from app.schemas.common import Timestamped


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    student_group: str | None = Field(default=None, max_length=80)
    role: UserRole = UserRole.student


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(Timestamped):
    id: UUID
    email: EmailStr
    full_name: str
    student_group: str | None = None
    role: UserRole
    is_active: bool


class UserProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    student_group: str | None = Field(default=None, max_length=80)


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserStatusUpdate(BaseModel):
    is_active: bool
