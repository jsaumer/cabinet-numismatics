import os
import tempfile

# Point PHOTO_DIR somewhere disposable before app.config is imported,
# so the lifespan hook doesn't create a photos/ dir in the repo.
os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient backed by a fresh in-memory SQLite DB and a temp photo dir."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
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
