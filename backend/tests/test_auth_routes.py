"""The sign-in routes and setup (SPEC_0300 sections 5 and 6), through the
HTTP API: cookies, status codes, the claim, and what each route records."""

import pytest
from sqlalchemy import select

from app.auth import accounts, passwords, sessions, setup, throttle
from app.config import ConfigError, check_startup, get_settings
from app.db import get_db
from app.main import app
from app.models.auth import AuditEntry

PASSWORD = "correct horse battery"
SESSION, DEVICE = "__Host-cabinet_session", "__Host-cabinet_device"


def db_session():
    return next(app.dependency_overrides[get_db]())


def actions() -> list[str]:
    db = db_session()
    try:
        return list(db.scalars(select(AuditEntry.action).order_by(AuditEntry.id)).all())
    finally:
        db.close()


def set_cookies(resp) -> dict[str, str]:
    return {h.split("=", 1)[0]: h for h in resp.headers.get_list("set-cookie")}


# --- setup ------------------------------------------------------------------------


def test_setup_claims_once(unclaimed_client):
    c = unclaimed_client
    assert c.get("/api/auth/state").json() == {"setup_required": True}
    code = setup._code
    assert code and len(code) == 32  # 160 bits of base32
    body = {"code": setup.grouped(code).lower(), "username": "Owner", "password": PASSWORD}
    resp = c.post("/api/auth/setup", json=body)
    assert resp.status_code == 201 and resp.json() == {"username": "owner"}
    cookies = set_cookies(resp)
    assert SESSION in cookies and DEVICE in cookies
    assert c.get("/api/auth/state").json() == {"setup_required": False}
    assert c.get("/api/items").status_code == 200  # signed in by the setup
    again = c.post("/api/auth/setup", json={**body, "username": "second"})
    assert again.status_code == 409 and again.json()["detail"] == "Cabinet is already set up."
    assert setup.marker_exists()
    assert "setup" in actions()


def test_setup_checks_the_code_before_anything(unclaimed_client):
    c = unclaimed_client
    c.get("/api/auth/state")
    resp = c.post(
        "/api/auth/setup", json={"code": "WRONG" * 7, "username": "x", "password": "short"}
    )
    assert resp.status_code == 403
    right = setup._code
    short = c.post("/api/auth/setup", json={"code": right, "username": "x", "password": "short"})
    assert short.status_code == 422 and "12 to 256" in short.json()["detail"]


def test_wrong_codes_are_throttled_but_a_right_code_always_passes(unclaimed_client):
    c = unclaimed_client
    c.get("/api/auth/state")
    wrong = {"code": "A" * 32, "username": "owner", "password": PASSWORD}
    for _ in range(5):
        assert c.post("/api/auth/setup", json=wrong).status_code == 403
    throttled = c.post("/api/auth/setup", json=wrong)
    assert throttled.status_code == 429 and int(throttled.headers["retry-after"]) > 0
    right = {**wrong, "code": setup._code}
    assert c.post("/api/auth/setup", json=right).status_code == 201


def test_a_supplied_code_and_the_marker(unclaimed_client, monkeypatch):
    supplied = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
    monkeypatch.setenv("SETUP_CODE", supplied)
    get_settings.cache_clear()
    setup.reset_memory()
    db = db_session()
    try:
        setup.prepare(db)
        assert setup.check(supplied) and setup.check(supplied[:16] + "-" + supplied[16:])
        assert not setup.check(supplied.upper())  # supplied codes compare as written
        # Once the marker exists, the environment's code is inert for good.
        setup.marker_path().parent.mkdir(parents=True, exist_ok=True)
        setup.marker_path().write_text("claimed\n")
        setup.prepare(db)
        assert not setup.check(supplied)
        assert setup._generated
    finally:
        db.close()


def test_the_marker_is_written_for_a_claimed_database(client):
    setup.marker_path().unlink(missing_ok=True)
    db = db_session()
    try:
        setup.prepare(db)
    finally:
        db.close()
    assert setup.marker_exists() and setup._code is None


def test_a_weak_code_is_ignored_once_claimed(client, monkeypatch):
    monkeypatch.setenv("SETUP_CODE", "short")
    get_settings.cache_clear()
    setup.marker_path().unlink(missing_ok=True)
    with pytest.raises(ConfigError):
        check_startup(get_settings())
    setup.marker_path().write_text("claimed\n")
    check_startup(get_settings())


# --- sign-in ----------------------------------------------------------------------


def test_login_sets_both_cookies(client, anon_client):
    resp = anon_client.post("/api/auth/login", json={"username": "OWNER", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["username"] == "owner"
    assert resp.json()["failed_since_previous"] == 0
    cookies = set_cookies(resp)
    session, device = cookies[SESSION].lower(), cookies[DEVICE].lower()
    for attr in ("secure", "httponly", "path=/"):
        assert attr in session and attr in device
    assert "samesite=lax" in session and "max-age" not in session and "domain" not in session
    assert "samesite=strict" in device and "max-age=604800" in device
    assert anon_client.get("/api/items").status_code == 200


def test_login_failures(client, anon_client, monkeypatch):
    wrong = {"username": "owner", "password": "wrong password!"}
    resp = anon_client.post("/api/auth/login", json=wrong)
    assert resp.status_code == 401 and resp.json()["detail"] == "Wrong username or password."
    for _ in range(4):
        anon_client.post("/api/auth/login", json=wrong)
    throttled = anon_client.post("/api/auth/login", json=wrong)
    assert throttled.status_code == 429 and throttled.headers["retry-after"]

    def busy(*args, **kwargs):
        raise passwords.Busy()

    throttle.clear()
    monkeypatch.setattr(accounts, "sign_in", busy)
    resp = anon_client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert resp.status_code == 503 and resp.headers["retry-after"] == "5"
    assert anon_client.post("/api/auth/login", content="not json").status_code == 415
    bad = anon_client.post(
        "/api/auth/login", content="not json", headers={"Content-Type": "application/json"}
    )
    assert bad.status_code == 422


def test_login_reports_failures_since_the_last_visit(client, anon_client):
    for _ in range(3):
        anon_client.post("/api/auth/login", json={"username": "owner", "password": "nope nope!!"})
    throttle.clear()
    resp = anon_client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert resp.json()["failed_since_previous"] == 3
    assert resp.json()["previous_sign_in_at"]


def test_login_ends_the_session_the_browser_held(client):
    old = client.admin.session_secret
    resp = client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert resp.status_code == 200
    db = db_session()
    try:
        assert sessions.find(db, old) is None
    finally:
        db.close()


def test_logout(client):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 204 and resp.headers["clear-site-data"] == '"cache"'
    assert SESSION in set_cookies(resp)
    client.cookies.clear()
    client.cookies.set(SESSION, client.admin.session_secret)
    assert client.get("/api/items").status_code == 401


def test_me(client, token_client):
    body = client.get("/api/auth/me").json()
    assert body["username"] == "owner" and body["via"] == "session" and body["scope"] is None
    assert body["confirmed_until"]
    body = token_client("read").get("/api/auth/me").json()
    assert body["via"] == "token" and body["scope"] == "read" and body["confirmed_until"] is None


# --- the recent-password window -------------------------------------------------------


def test_confirm_opens_the_window(stale_client):
    assert stale_client.get("/api/auth/me").json()["confirmed_until"] is None
    assert stale_client.post("/api/auth/tokens", json={"name": "x", "scope": "read"}).json()[
        "reauth_required"
    ]
    wrong = stale_client.post("/api/auth/confirm", json={"password": "not it at all"})
    assert wrong.status_code == 403  # the session is fine; the password isn't
    assert stale_client.post("/api/auth/confirm", json={"password": PASSWORD}).status_code == 204
    assert stale_client.get("/api/auth/me").json()["confirmed_until"]
    made = stale_client.post("/api/auth/tokens", json={"name": "x", "scope": "read"})
    assert made.status_code == 201


def test_confirm_is_never_for_a_token(client, token_client):
    resp = token_client("write").post("/api/auth/confirm", json={"password": PASSWORD})
    assert resp.status_code == 403


# --- the account ----------------------------------------------------------------------


def test_password_change(stale_client, client, token_client):
    reader = token_client("read")
    wrong = stale_client.post(
        "/api/auth/password",
        json={"current_password": "not the password", "new_password": "a brand new password"},
    )
    assert wrong.status_code == 403
    resp = stale_client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a brand new password"},
    )
    assert resp.status_code == 200
    assert [t["scope"] for t in resp.json()["revoked_tokens"]] == ["read"]
    assert SESSION in set_cookies(resp)
    assert stale_client.get("/api/items").status_code == 200  # the new cookie
    assert client.get("/api/items").status_code == 401  # every other session ended
    assert reader.get("/api/items").status_code == 401


def test_username_change(client, anon_client):
    assert (
        client.post(
            "/api/auth/username", json={"current_password": "nope nope nope", "username": "jay"}
        ).status_code
        == 403
    )
    ok = client.post("/api/auth/username", json={"current_password": PASSWORD, "username": "Jay"})
    assert ok.status_code == 204
    resp = anon_client.post("/api/auth/login", json={"username": "jay", "password": PASSWORD})
    assert resp.status_code == 200


def test_sessions(client, stale_client):
    listed = client.get("/api/auth/sessions").json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    other = next(s for s in listed if not s["current"])
    # ending another session asks for the password; this one's was confirmed
    assert stale_client.delete(f"/api/auth/sessions/{listed[0]['id']}").status_code in (204, 403)
    assert client.delete(f"/api/auth/sessions/{other['id']}").status_code in (204, 404)
    assert client.delete("/api/auth/sessions/999999").status_code == 404


def test_ending_another_session_needs_the_window(client, stale_client):
    mine = next(s for s in client.get("/api/auth/sessions").json() if s["current"])
    resp = stale_client.delete(f"/api/auth/sessions/{mine['id']}")
    assert resp.json()["reauth_required"] is True
    own = next(s for s in stale_client.get("/api/auth/sessions").json() if s["current"])
    signed_out = stale_client.delete(f"/api/auth/sessions/{own['id']}")
    assert signed_out.status_code == 204  # ending one's own never asks
    assert signed_out.headers["clear-site-data"] == '"cache"'


def test_sign_out_everywhere(client, stale_client):
    assert stale_client.delete("/api/auth/sessions").json()["reauth_required"] is True
    resp = client.delete("/api/auth/sessions")
    assert resp.status_code == 204
    assert client.get("/api/items").status_code == 401
    assert stale_client.get("/api/items").status_code == 401


def test_tokens(client):
    made = client.post("/api/auth/tokens", json={"name": "ci", "scope": "write", "days": 7})
    assert made.status_code == 201
    token = made.json()["token"]
    assert token.startswith("cabinet_") and made.json()["expires_at"]
    listed = client.get("/api/auth/tokens").json()
    assert [t["name"] for t in listed] == ["ci"] and "token" not in listed[0]
    assert token not in client.get("/api/auth/tokens").text
    forever = client.post("/api/auth/tokens", json={"name": "rw", "scope": "read", "days": None})
    assert forever.status_code == 422
    metrics = client.post(
        "/api/auth/tokens", json={"name": "homepage", "scope": "metrics", "days": None}
    )
    assert metrics.status_code == 201 and metrics.json()["expires_at"] is None
    assert client.delete(f"/api/auth/tokens/{listed[0]['id']}").status_code == 204
    assert client.get("/api/items", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.delete(f"/api/auth/tokens/{listed[0]['id']}").status_code == 404
    assert "token_created" in actions() and "token_revoked" in actions()


def test_audit(client):
    for _ in range(3):
        client.post("/api/auth/confirm", json={"password": PASSWORD})
    rows = client.get("/api/auth/audit?limit=2").json()
    assert len(rows) == 2 and rows[0]["id"] > rows[1]["id"]
    older = client.get(f"/api/auth/audit?before={rows[-1]['id']}&limit=500").json()
    assert all(r["id"] < rows[-1]["id"] for r in older)
    assert {"action", "actor_kind", "actor_label", "at"} <= set(rows[0])


# --- the photo check --------------------------------------------------------------------


def test_photo_check(client, anon_client, token_client):
    assert client.get("/api/auth/photo").status_code == 204
    assert client.get("/api/auth/photo", headers={"Sec-Fetch-Site": "none"}).status_code == 204
    cross = client.get("/api/auth/photo", headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert token_client("read").get("/api/auth/photo").status_code == 204
    assert token_client("write").get("/api/auth/photo").status_code == 204
    assert token_client("metrics").get("/api/auth/photo").status_code == 403
    assert anon_client.get("/api/auth/photo").status_code == 401


# --- what the routes record ---------------------------------------------------------------


def test_exports_and_downloads_are_audited(client, monkeypatch):
    sent = []
    from app.services import alerts

    monkeypatch.setattr(alerts, "event", lambda db, key, title, message: sent.append(key))
    assert client.get("/api/items/export.csv").status_code == 200
    assert client.get("/api/items/export.xlsx").status_code == 200
    assert actions().count("export_downloaded") == 2
    assert sent.count("export_downloaded") == 2
    resp = client.get("/api/items/export.csv")
    assert resp.headers["cache-control"] == "private, no-store"


def test_exports_need_a_recent_password(stale_client, token_client):
    assert stale_client.get("/api/items/export.csv").json()["reauth_required"] is True
    assert token_client("read").get("/api/items/export.csv").status_code == 403


def test_two_claims_at_once_give_one_admin(unclaimed_client, monkeypatch):
    """Both pass the `claimed` check (set up here by hand; CI races two real
    requests on Postgres): the claim row lets only one commit."""
    c = unclaimed_client
    c.get("/api/auth/state")
    code = setup._code
    first = c.post("/api/auth/setup", json={"code": code, "username": "a", "password": PASSWORD})
    assert first.status_code == 201
    monkeypatch.setattr(accounts, "claimed", lambda db: False)
    setup._code, setup._generated = code, True  # as if the second read it first
    second = c.post("/api/auth/setup", json={"code": code, "username": "b", "password": PASSWORD})
    assert second.status_code == 409


class Records:
    def __init__(self):
        import logging

        self.handler = logging.Handler()
        self.lines = []
        self.handler.emit = lambda record: self.lines.append(record.getMessage())
        self.logger = logging.getLogger("app.auth.setup")

    def __enter__(self):
        self.logger.addHandler(self.handler)
        return self.lines

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)


def test_the_generated_code_is_logged_once(unclaimed_client):
    import threading

    setup.reset_memory()
    with Records() as lines:
        threads = [
            threading.Thread(target=lambda: setup.ensure_prepared(db_session())) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        unclaimed_client.get("/api/auth/state")
    with_code = [line for line in lines if "setup code:" in line]
    assert len(with_code) == 1 and setup.grouped(setup._code) in with_code[0]


def test_a_supplied_code_is_never_logged(unclaimed_client, monkeypatch):
    supplied = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
    monkeypatch.setenv("SETUP_CODE", supplied)
    get_settings.cache_clear()
    setup.reset_memory()
    with Records() as lines:
        db = db_session()
        try:
            setup.prepare(db)
        finally:
            db.close()
        body = {"code": supplied, "username": "owner", "password": PASSWORD}
        assert unclaimed_client.post("/api/auth/setup", json=body).status_code == 201
    assert lines and not any(supplied in line for line in lines)


def test_a_marker_that_cannot_be_written_still_finishes_setup(unclaimed_client, monkeypatch):
    unclaimed_client.get("/api/auth/state")

    def unwritable():
        raise OSError("read-only file system")

    monkeypatch.setattr(setup, "_write_marker", unwritable)
    body = {"code": setup._code, "username": "owner", "password": PASSWORD}
    resp = unclaimed_client.post("/api/auth/setup", json=body)
    assert resp.status_code == 201 and SESSION in set_cookies(resp)


def test_photo_check_during_a_restore_is_503(client):
    """nginx turns anything but 401 or 403 from the check into its own 503
    with a retry, so a restore never shows photos to anyone."""
    from app.services import maintenance

    maintenance.enter()
    try:
        assert client.get("/api/auth/photo").status_code == 503
    finally:
        maintenance.leave()


def test_anonymous_health_touches_nothing(anon_client, monkeypatch):
    """Anyone can call it, so it costs nothing: no database, no schema read."""
    from app.routers import health

    def boom(*args, **kwargs):
        raise AssertionError("anonymous health did work")

    monkeypatch.setattr(health, "_health", boom)
    assert anon_client.get("/api/health").json() == {"status": "ok"}
