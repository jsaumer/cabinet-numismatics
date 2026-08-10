import os

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health_ok():
    # `with` runs the lifespan hook, covering PHOTO_DIR creation too.
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] in ("ok", "unreachable")  # no postgres required for tests
    assert body["version"]  # reported for support/upgrade checks
    assert os.path.isdir(get_settings().photo_dir)
