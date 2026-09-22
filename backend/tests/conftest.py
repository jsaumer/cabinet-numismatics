import base64
import io
import os
import tempfile

# Point PHOTO_DIR somewhere disposable before app.config is imported,
# so the lifespan hook doesn't create a photos/ dir in the repo.
os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))
# Tests build their schema with create_all on SQLite; never migrate at startup.
os.environ.setdefault("AUTO_MIGRATE", "false")
# Deterministic encryption key so tests never generate or read a key file.
os.environ.setdefault(
    "SECRET_KEY", base64.urlsafe_b64encode(b"cabinet-test-key-32-bytes-long!!").decode()
)

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Grade
from app.models.grades_seed import seed_rows
from app.services import crypto


@pytest.fixture(autouse=True)
def _no_network_rates(monkeypatch):
    """Exchange-rate fetches never hit the network in tests; individual tests
    monkeypatch a working rate when they need conversion."""
    from app.services import currency

    def unavailable(base, quote):
        raise currency.RateUnavailable("offline in tests")

    monkeypatch.setattr(currency, "fetch_rate", unavailable)


@pytest.fixture(autouse=True)
def _fresh_monitoring_state():
    """Alert outcomes and the metrics cache live in memory, per process."""
    from app.services import alerts, metrics, restore

    alerts.reset_memory()
    metrics.reset_cache()
    restore.reset_memory()
    yield


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient backed by a fresh in-memory SQLite DB (grades seeded) and a
    temp photo dir."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        # Make SQLite honor ON DELETE CASCADE / SET NULL like postgres does.
        dbapi_conn.execute("pragma foreign_keys=on")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(Grade), seed_rows())
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path.with_name(tmp_path.name + "-documents")))
    monkeypatch.setenv("REQUIRE_DOCUMENT_MOUNT", "false")
    # Beside the photo dir, never inside it (the backup service refuses that).
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path.with_name(tmp_path.name + "-backups")))
    # The restore outcome file is written beside the key file.
    monkeypatch.setenv(
        "SECRET_KEY_FILE", str(tmp_path.with_name(tmp_path.name + "-state") / "secret.key")
    )
    get_settings.cache_clear()
    crypto.reset_cache()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        crypto.reset_cache()
        engine.dispose()


def image_bytes(fmt: str = "PNG", size=(60, 40), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


COIN = {
    "type": "coin",
    "country": "United States",
    "denomination": "25 cents",
    "year": 1932,
    "mint_mark": "D",
    "series": "Washington Quarter",
    "quantity": 1,
    "acquisition_price": 120.0,
    "currency": "USD",
}


@pytest.fixture()
def coin(client):
    """A created item, for tests that need one to exist."""
    resp = client.post("/api/items", json=COIN)
    assert resp.status_code == 201
    return resp.json()


def import_cabinet_csv(client, text, name: str = "items.csv") -> dict:
    """Import a CSV in Cabinet's export format through `/api/imports` (upload,
    preview, run), read as the `cabinet` format whatever its columns, so a
    hand-written CSV with only a few export columns reads as one. Returns the
    run result: `created`, `skipped`, `errors` (`{row, error}`, `row` counting
    data rows from 1), `photos_added`, `photos_failed`. Rows whose exported id
    is already here, trash included, are skipped."""
    body = text.encode() if isinstance(text, str) else text
    upload = client.post("/api/imports", files={"file": (name, body, "text/csv")})
    assert upload.status_code == 201, upload.text
    upload_id = upload.json()["upload_id"]
    options = {"format": "cabinet"}
    preview = client.post(f"/api/imports/{upload_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    run = client.post(f"/api/imports/{upload_id}/run", json=options)
    assert run.status_code == 200, run.text
    return run.json()
