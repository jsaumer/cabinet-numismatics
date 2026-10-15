"""The colour theme (v0.35.0): read by anyone signed in, set by the admin
without the password again, and only ever one of the known themes."""

from app.routers.appearance import THEMES
from app.services import app_settings as store


def test_default_is_bronze_and_lists_the_themes(client):
    body = client.get("/api/appearance").json()
    assert body == {"theme": "bronze", "themes": ["bronze", "silver", "album", "ledger"]}


def test_admin_sets_a_theme_and_it_is_kept(client):
    assert client.put("/api/appearance", json={"theme": "album"}).json()["theme"] == "album"
    assert client.get("/api/appearance").json()["theme"] == "album"


def test_unknown_theme_is_refused(client):
    assert client.put("/api/appearance", json={"theme": "contrast"}).status_code == 422
    assert client.put("/api/appearance", json={}).status_code == 422
    assert client.get("/api/appearance").json()["theme"] == "bronze"


def test_no_fresh_password_needed(stale_client):
    """A display choice, like the dashboard layout: an admin outside the
    recent-password window can still change it."""
    assert stale_client.put("/api/appearance", json={"theme": "ledger"}).status_code == 200


def test_a_read_token_reads_but_cannot_set(token_client):
    reader = token_client("read")
    assert reader.get("/api/appearance").status_code == 200
    assert reader.put("/api/appearance", json={"theme": "silver"}).status_code == 403


def test_a_stored_theme_this_build_lacks_reads_as_the_default(client):
    """An archive from a later release could carry a theme this one doesn't have."""
    from app.db import get_db
    from app.main import app

    db = next(app.dependency_overrides.get(get_db, get_db)())
    store.set_setting(db, "ui_theme", "midnight")
    db.commit()
    assert client.get("/api/appearance").json()["theme"] == "bronze"
    assert "midnight" not in THEMES


def test_settings_put_cannot_set_it(client):
    """Only its own endpoint writes it; PUT /api/settings ignores or refuses it."""
    client.put("/api/settings", json={"ui_theme": "album"})
    assert client.get("/api/appearance").json()["theme"] == "bronze"
