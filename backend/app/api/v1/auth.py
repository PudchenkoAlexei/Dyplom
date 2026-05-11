import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.student_groups import is_known_student_group
from app.db.session import get_db
from app.models.auth import RefreshToken
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.user import UserCreate, UserLogin, UserRead
from app.security.deps import get_current_user
from app.security.passwords import hash_password, verify_password
from app.security.tokens import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        "access_token",
        access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", domain=settings.cookie_domain)
    response.delete_cookie("refresh_token", domain=settings.cookie_domain)


async def _issue_session(db: AsyncSession, response: Response, user: User) -> None:
    access_token = create_access_token(user.id, user.role)
    refresh_token, refresh_hash, expires_at = create_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=refresh_hash, expires_at=expires_at))
    await db.commit()
    _set_auth_cookies(response, access_token, refresh_token)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    if payload.role not in {UserRole.student, UserRole.teacher}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only student and teacher accounts can self-register.",
        )
    full_name = " ".join(payload.full_name.split())
    if len(full_name.split()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ПІБ має містити прізвище, ім'я та по батькові.",
        )
    student_group = (payload.student_group or "").strip() or None
    if payload.role == UserRole.student:
        if not student_group:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для студентського акаунта потрібно вибрати групу.",
            )
        if not await asyncio.to_thread(is_known_student_group, student_group):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Такої групи немає у списку груп КПІ.",
            )
    else:
        student_group = None

    existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=full_name,
        student_group=student_group,
        role=payload.role,
    )
    db.add(user)
    await db.flush()
    await _issue_session(db, response, user)
    await db.refresh(user)
    return user


@router.post("/login", response_model=UserRead)
async def login(payload: UserLogin, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive.")

    await _issue_session(db, response, user)
    return user


@router.post("/refresh", response_model=UserRead)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token.")

    refresh_hash = hash_refresh_token(refresh_token)
    token_row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == refresh_hash))
    now = datetime.now(timezone.utc)
    if not token_row or token_row.revoked_at or token_row.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    user = await db.get(User, token_row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user.")

    token_row.revoked_at = now
    await _issue_session(db, response, user)
    return user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if refresh_token:
        refresh_hash = hash_refresh_token(refresh_token)
        token_row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == refresh_hash))
        if token_row and not token_row.revoked_at:
            token_row.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    _clear_auth_cookies(response)
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
