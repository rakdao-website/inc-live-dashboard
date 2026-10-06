import time

from app.admin_panel import security
from app.config import settings
from tests.conftest import PASSWORD


def test_password_hash_verifies_and_is_salted():
    first = security.hash_password(PASSWORD)
    second = security.hash_password(PASSWORD)
    assert first != second
    assert security.verify_password(PASSWORD, first)
    assert not security.verify_password("wrong", first)
    assert not security.verify_password(PASSWORD, "not-a-hash")


def test_password_policy_rejects_weak_passwords():
    assert security.password_problem("short1A")
    assert security.password_problem("alllowercase123456")
    assert security.password_problem(PASSWORD) is None


def test_token_round_trip_and_tamper(monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", "k" * 40)
    token = security.sign_token("abc", int(time.time()) + 60)
    assert security.read_token(token) == "abc"
    body, signature = token.split(".")
    assert security.read_token(f"{body}.{signature[:-2]}xx") is None
    assert security.read_token(None) is None
    assert security.read_token("garbage") is None


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", "k" * 40)
    assert security.read_token(security.sign_token("abc", int(time.time()) - 1)) is None


def test_token_signed_with_another_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", "a" * 40)
    token = security.sign_token("abc", int(time.time()) + 60)
    monkeypatch.setattr(settings, "admin_session_secret", "b" * 40)
    assert security.read_token(token) is None


def test_production_refuses_to_start_without_secret(monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", "")
    monkeypatch.setattr(settings, "environment", "production")
    try:
        security.get_session_secret()
    except security.AdminSecretMissing:
        return
    raise AssertionError("expected AdminSecretMissing")
