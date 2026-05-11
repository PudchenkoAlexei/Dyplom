import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.student_groups import get_student_groups, is_known_student_group
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserProfileUpdate, UserRead, UserRoleUpdate, UserStatusUpdate
from app.security.deps import get_current_user, require_roles

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/student-groups", response_model=list[str])
async def list_student_groups() -> list[str]:
    return list(await asyncio.to_thread(get_student_groups))


@router.patch("/me/profile", response_model=UserRead)
async def update_my_profile(
    payload: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    full_name = " ".join(payload.full_name.split())
    if len(full_name.split()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ПІБ має містити прізвище, ім'я та по батькові.",
        )
    current_user.full_name = full_name
    if current_user.role == UserRole.student:
        student_group = (payload.student_group or "").strip()
        if not student_group:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для студентського профілю потрібно вибрати групу.",
            )
        if not await asyncio.to_thread(is_known_student_group, student_group):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Такої групи немає у списку груп КПІ.",
            )
        current_user.student_group = student_group
    else:
        current_user.student_group = None

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("", response_model=list[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars())


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.role = payload.role
    if payload.role != UserRole.student:
        user.student_group = None
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserRead)
async def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.is_active = payload.is_active
    await db.commit()
    await db.refresh(user)
    return user
