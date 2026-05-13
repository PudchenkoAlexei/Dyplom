from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.security.tokens import decode_access_token


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = access_token or _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token."
        ) from None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user.")
    return user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient rights."
            )
        return current_user

    return dependency


async def get_current_requester(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {UserRole.student, UserRole.teacher}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Requester role required."
        )
    return current_user


async def get_current_operator(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {UserRole.operator, UserRole.admin}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator role required.")
    return current_user


def get_profile_issues(user: User) -> list[str]:
    issues: list[str] = []
    full_name_parts = [part for part in user.full_name.split() if part]
    if len(full_name_parts) < 3:
        issues.append("вкажіть прізвище, ім'я та по батькові")
    if user.role == UserRole.student and not (user.student_group or "").strip():
        issues.append("виберіть академічну групу")
    return issues


def ensure_profile_complete(user: User) -> None:
    issues = get_profile_issues(user)
    if issues:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Заповніть профіль перед роботою із заявками: " + "; ".join(issues) + ".",
        )


async def get_profile_ready_user(current_user: User = Depends(get_current_user)) -> User:
    ensure_profile_complete(current_user)
    return current_user


async def get_profile_ready_requester(current_user: User = Depends(get_current_requester)) -> User:
    ensure_profile_complete(current_user)
    return current_user


async def get_profile_ready_operator(current_user: User = Depends(get_current_operator)) -> User:
    ensure_profile_complete(current_user)
    return current_user
