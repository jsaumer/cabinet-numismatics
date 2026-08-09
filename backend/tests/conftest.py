import io
import os
import tempfile

# Point PHOTO_DIR somewhere disposable before app.config is imported,
# so the lifespan hook doesn't create a photos/ dir in the repo.
os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Grade
from app.models.grades_seed import seed_rows


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient backed by a fresh in-memory SQLite DB (grades seeded) and a
    temp photo dir."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
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
