from uuid import uuid4

from app.models.enums import UserRole
from app.security.passwords import hash_password, verify_password
from app.security.tokens import create_access_token, decode_access_token


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

