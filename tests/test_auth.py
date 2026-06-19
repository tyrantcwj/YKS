import base64

from app.config import settings
from app.main import _valid_basic_auth


def _basic(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def test_basic_auth_is_disabled_without_password(monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "")

    assert _valid_basic_auth(None)


def test_basic_auth_accepts_matching_credentials(monkeypatch):
    monkeypatch.setattr(settings, "auth_username", "me")
    monkeypatch.setattr(settings, "auth_password", "secret")

    assert _valid_basic_auth(_basic("me", "secret"))


def test_basic_auth_rejects_missing_or_wrong_credentials(monkeypatch):
    monkeypatch.setattr(settings, "auth_username", "me")
    monkeypatch.setattr(settings, "auth_password", "secret")

    assert not _valid_basic_auth(None)
    assert not _valid_basic_auth(_basic("me", "wrong"))
