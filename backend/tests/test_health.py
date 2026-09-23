import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import scheduled, schema

LATEST = sorted(
    p.name.split("_")[0] for p in (Path(__file__).parents[1] / "alembic" / "versions").glob("0*.py")
)[-1]


def test_health_ok():
    # `with` runs the lifespan hook, covering PHOTO_DIR creation too.
    with TestClient(app) as anonymous:
        resp = anonymous.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}  # nothing more for an anonymous caller
    assert os.path.isdir(get_settings().photo_dir)


def test_health_full_body_for_the_signed_in(client, token_client):
    for caller in (client, token_client("metrics")):
        body = caller.get("/api/health").json()
        assert set(body) >= {"status", "db", "version", "schema", "auth_schema"}
    resp = client.get("/api/health")
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] in ("ok", "unreachable")  # no postgres required for tests
    assert body["version"]  # reported for support/upgrade checks
    assert body["schema"]["expected"] == LATEST  # the newest migration this build ships


def test_schema_states():
    known = frozenset({"0009", "0010"})
    assert schema.describe("0010", "0010", known, reachable=True)["status"] == "ok"
    assert schema.describe("0009", "0010", known, reachable=True)["status"] == "pending"
    assert schema.describe(None, "0010", known, reachable=True)["status"] == "pending"  # empty
    assert schema.describe("0011", "0010", known, reachable=True)["status"] == "ahead"
    assert schema.describe(None, "0010", known, reachable=False)["status"] == "unknown"


def _start_with(monkeypatch, auto_migrate: str) -> list:
    calls: list = []
    monkeypatch.setattr(schema, "upgrade_to_head", lambda engine: calls.append("migrate"))
    # Stored secrets are checked right after migrating (no database here).
    monkeypatch.setattr(scheduled, "clear_secrets", lambda db: calls.append("secrets"))
    import app.main as main

    monkeypatch.setattr(main, "_check_key_against_record", lambda db: calls.append("key"))
    monkeypatch.setattr(main.auth_setup, "prepare", lambda db: calls.append("setup"))
    monkeypatch.setenv("AUTO_MIGRATE", auto_migrate)
    get_settings.cache_clear()
    try:
        with TestClient(app):
            pass
    finally:
        get_settings.cache_clear()
    return calls


def test_startup_migrates_by_default(monkeypatch):
    assert _start_with(monkeypatch, "true") == ["migrate", "secrets", "key", "setup"]


def test_startup_skips_migrations_when_disabled(monkeypatch):
    assert _start_with(monkeypatch, "false") == []
