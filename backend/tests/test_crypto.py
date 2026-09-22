"""Encryption at rest for stored secrets."""

import base64
import os
import stat
import sys

from cryptography.fernet import Fernet

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import AppSetting
from app.services import app_settings as store
from app.services import crypto

SECRET = "numista-live-key-abcd"


def _session():
    return next(app.dependency_overrides[get_db]())


def _raw_stored(key: str):
    """The value exactly as it sits in the database."""
    db = _session()
    try:
        row = db.get(AppSetting, key)
        return None if row is None else row.value
    finally:
        db.close()


def test_secret_is_ciphertext_in_the_database(client):
    client.put("/api/settings", json={"numista_api_key": SECRET})

    stored = _raw_stored("numista_api_key")
    assert stored is not None
    assert SECRET not in stored  # the plaintext never lands in the DB
    assert crypto.is_encrypted(stored)

    # …and still round-trips for the application
    db = _session()
    try:
        assert store.get_setting(db, "numista_api_key") == SECRET
    finally:
        db.close()


def test_ciphertext_differs_per_write(client):
    client.put("/api/settings", json={"numista_api_key": SECRET})
    first = _raw_stored("numista_api_key")
    client.put("/api/settings", json={"numista_api_key": SECRET})
    second = _raw_stored("numista_api_key")
    assert first != second  # Fernet embeds a random IV; no ECB-style leakage


def test_tampered_ciphertext_is_rejected(client):
    client.put("/api/settings", json={"numista_api_key": SECRET})
    stored = _raw_stored("numista_api_key")

    db = _session()
    try:
        row = db.get(AppSetting, "numista_api_key")
        row.value = stored[:-4] + "AAAA"  # flip the tail of the token
        db.commit()
        # authenticated encryption: tampering fails closed, no crash
        assert store.get_setting(db, "numista_api_key") == ""
    finally:
        db.close()


def test_key_rotation(client, monkeypatch):
    client.put("/api/settings", json={"numista_api_key": SECRET})

    old_key = get_settings().secret_key
    new_key = Fernet.generate_key().decode()

    # New key first (encrypts), old key retained (still decrypts).
    monkeypatch.setenv("SECRET_KEY", f"{new_key},{old_key}")
    get_settings.cache_clear()
    crypto.reset_cache()

    db = _session()
    try:
        assert store.get_setting(db, "numista_api_key") == SECRET
        store.set_setting(db, "numista_api_key", SECRET)  # re-encrypt under the new key
        db.commit()
    finally:
        db.close()

    # Dropping the old key entirely still works for the re-encrypted value.
    monkeypatch.setenv("SECRET_KEY", new_key)
    get_settings.cache_clear()
    crypto.reset_cache()
    db = _session()
    try:
        assert store.get_setting(db, "numista_api_key") == SECRET
    finally:
        db.close()


def test_unreadable_secret_degrades_to_unset(client, monkeypatch):
    client.put("/api/settings", json={"numista_api_key": SECRET})

    # Key lost/replaced without retaining the old one.
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    crypto.reset_cache()

    body = client.get("/api/settings").json()  # must not 500
    numista = next(s for s in body["sources"] if s["key"] == "numista")
    assert numista["configured"] is False


def _plant(key: str, value: str) -> None:
    """Write a value straight into the table, as an edited archive could."""
    db = _session()
    try:
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        db.commit()
    finally:
        db.close()


def test_plain_text_secret_is_never_used(client):
    """No self-heal (v0.30.0): plain text reads as unset and stays as it was
    until the clear-out, never encrypted in place."""
    _plant("alert_webhook_url", "https://attacker.example/hook")
    db = _session()
    try:
        assert store.get_setting(db, "alert_webhook_url") == ""
        db.commit()
    finally:
        db.close()
    assert _raw_stored("alert_webhook_url") == "https://attacker.example/hook"
    assert client.get("/api/settings").json()["alert_webhook_hint"] is None


def test_plain_text_secrets_are_cleared_and_named(client, monkeypatch):
    from app.services import alerts, scheduled

    sent = []
    monkeypatch.setattr(alerts, "event", lambda db, key, title, message: sent.append(message))
    client.put("/api/settings", json={"numista_api_key": SECRET})  # encrypted: kept
    _plant("alert_webhook_url", "https://attacker.example/hook")
    _plant("pcgs_api_token", "plain-token-1234")

    db = _session()
    try:
        cleared = scheduled.clear_secrets(db)
    finally:
        db.close()
    assert cleared == ["alert_webhook_url", "pcgs_api_token"]
    assert _raw_stored("alert_webhook_url") == ""
    assert _raw_stored("pcgs_api_token") == ""
    assert crypto.is_encrypted(_raw_stored("numista_api_key"))
    # named, never shown
    assert sent and "alert webhook" in sent[0] and "PCGS API token" in sent[0]
    assert "attacker" not in sent[0] and "plain-token" not in sent[0]
    # and audited by name, as the system (v0.30.0)
    from app.models.auth import AuditEntry

    db = _session()
    try:
        (row,) = db.query(AuditEntry).filter_by(action="secrets_cleared").all()
        assert row.actor_kind == "system"
        assert row.detail == {"names": ["alert_webhook_url", "pcgs_api_token"]}
    finally:
        db.close()

    body = client.get("/api/settings").json()
    assert body["secrets_cleared"] == ["alert webhook", "PCGS API token"]
    # entering one again takes it off the list; the next run finds nothing
    client.put("/api/settings", json={"pcgs_api_token": "new-token-5678"})
    assert client.get("/api/settings").json()["secrets_cleared"] == ["alert webhook"]
    db = _session()
    try:
        assert scheduled.clear_secrets(db) == []
    finally:
        db.close()
    assert len(sent) == 1


def test_undecryptable_secrets_are_cleared_only_when_asked(client, monkeypatch):
    """After a restore, a secret encrypted under another key is cleared too;
    at startup and hourly it is left alone (it already reads as unset)."""
    from app.services import scheduled

    client.put("/api/settings", json={"numista_api_key": SECRET})
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    crypto.reset_cache()
    db = _session()
    try:
        assert scheduled.clear_secrets(db) == []
        assert scheduled.clear_secrets(db, undecryptable=True) == ["numista_api_key"]
    finally:
        db.close()
    assert _raw_stored("numista_api_key") == ""


def test_generated_key_file_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "state" / "secret.key"))
    get_settings.cache_clear()
    crypto.reset_cache()
    try:
        token = crypto.encrypt("value")
        assert crypto.decrypt(token) == "value"

        path = tmp_path / "state" / "secret.key"
        assert path.is_file()
        if sys.platform != "win32":
            # A key file must never be group/world readable. Windows has no
            # POSIX mode bits, so this is asserted only where it's meaningful:
            # the app runs on Linux in the container.
            assert stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0
        # a second load reuses the persisted key
        crypto.reset_cache()
        assert crypto.decrypt(token) == "value"
    finally:
        get_settings.cache_clear()
        crypto.reset_cache()


def test_invalid_key_is_reported_clearly(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", base64.urlsafe_b64encode(b"too-short").decode())
    get_settings.cache_clear()
    crypto.reset_cache()
    try:
        try:
            crypto.encrypt("x")
        except RuntimeError as exc:
            assert "Fernet key" in str(exc)
        else:
            raise AssertionError("expected a RuntimeError for an invalid SECRET_KEY")
    finally:
        get_settings.cache_clear()
        crypto.reset_cache()
