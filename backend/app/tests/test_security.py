from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core.config import Settings
from app.main import create_app
from app.models.enums import UserRole
from app.security.passwords import hash_password, verify_password
from app.security.tokens import create_access_token, decode_access_token
from app.services import storage


def test_password_hash_roundtrip() -> None:
    password = "strong-password-123"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip() -> None:
    user_id = uuid4()
    token = create_access_token(user_id, UserRole.student)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["role"] == UserRole.student.value
    assert payload["type"] == "access"


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        Settings(
            environment="production",
            jwt_secret_key="x" * 48,
            cookie_secure=False,
            cors_origins=["https://example.com"],
            allowed_hosts=["example.com"],
        )


def test_security_headers_are_added() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_empty_audio_upload_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage.settings, "audio_storage_dir", tmp_path)
    upload = UploadFile(
        file=BytesIO(b""),
        filename="empty.webm",
        headers=Headers({"content-type": "audio/webm"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        await storage.save_ticket_audio(uuid4(), upload)

    assert exc_info.value.status_code == 422
