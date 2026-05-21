import pytest
from fastapi import HTTPException

from app.api.v1.phone_assistant import require_pbx_token, settings


def test_phone_assistant_rejects_invalid_pbx_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pbx_internal_token", "expected-token-value")

    with pytest.raises(HTTPException) as exc_info:
        require_pbx_token("wrong-token")

    assert exc_info.value.status_code == 403


def test_phone_assistant_accepts_valid_pbx_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pbx_internal_token", "expected-token-value")

    require_pbx_token("expected-token-value")
