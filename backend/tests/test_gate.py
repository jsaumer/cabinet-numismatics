"""The gate (SPEC_0300 sections 3 and 4): deny by default, both layers, CSRF.

Every matrix is driven by the OpenAPI document, never `app.routes`, so a
route that exists is a route that is tested. To call every operation without
running any handler, `dry_run` swaps layer 2's check for one that answers 418
wherever the real check would have let the call through.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.routing import Route

from app.auth import gate, permissions, sessions
from app.auth.permissions import declared
from app.main import app
from app.services import maintenance

ALLOWED = 418
ANONYMOUS = {
    ("GET", "/api/health"),
    ("GET", "/api/auth/state"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/login"),
}
SPEC = Path(__file__).resolve().parents[2] / "docs" / "specs" / "SPEC_0300.md"


def operations() -> list[tuple[str, str]]:
    found = []
    for path, item in app.openapi()["paths"].items():
        for method in item:
            found.append((method.upper(), path))
    return sorted(found)


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def call(c, method: str, path: str, **kwargs):
    return c.request(method, concrete(path), **kwargs)


def endpoint_for(method: str, path: str):
    """The function FastAPI registered for this OpenAPI operation. Included
    routers carry each route's full path in their effective contexts (test
    code only reads them; the app never does)."""
    for included in app.router.routes:
        contexts = getattr(included, "effective_route_contexts", None)
        for context in contexts() if contexts else ():
            if context.path_format == path and method in (context.methods or ()):
                return context.endpoint
    raise AssertionError(f"no route for {method} {path}")


@pytest.fixture()
def dry_run(monkeypatch):
    real = permissions.check

    def check(who, cls, *, metrics_ok=False, fresh=False):
        real(who, cls, metrics_ok=metrics_ok, fresh=fresh)
        raise HTTPException(ALLOWED, "allowed")

    monkeypatch.setattr(permissions, "check", check)


# --- the permission table ---------------------------------------------------------------


def spec_table() -> dict[tuple[str, str], permissions.Declared]:
    """Every route's class from the spec's appendix."""
    text = SPEC.read_text(encoding="utf-8").split("# Appendix: route permissions", 1)[1]
    table = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        method, path, cls = cells[0], cells[1].strip("`").split("?")[0], cells[2]
        if cls.startswith("write (admin"):  # the handler asks for more when purging
            cls = "write"
        base = re.match(r"(public|read|write|admin)", cls).group(1)
        fresh = "fresh" in cls and "unless" not in cls
        table[(method, path)] = permissions.Declared(base, "metrics_ok" in cls, fresh)
    return table


# The current password in their bodies is the confirmation (see
# routers/auth.py), and ending one's own session never asks.
BODY_CONFIRMED = {("POST", "/api/auth/password"), ("POST", "/api/auth/username")}


def test_every_operation_declares_what_the_spec_says():
    table = spec_table()
    ops = operations()
    assert len(ops) == 117 == len(table)
    for method, path in ops:
        found = declared(endpoint_for(method, path))
        assert found is not None, f"{method} {path} declares no @permission"
        want = table[(method, path)]
        if (method, path) in BODY_CONFIRMED:
            want = permissions.Declared(want.cls, want.metrics_ok, False)
        assert found == want, (method, path)


def test_class_counts():
    counts = {}
    for method, path in operations():
        cls = declared(endpoint_for(method, path)).cls
        counts[cls] = counts.get(cls, 0) + 1
    # 99 existing (public 1, read 33, write 42, admin 23: photo delete and
    # replace and document delete moved to admin in stage 12) and 18 new.
    assert counts == {"public": 4, "read": 35, "write": 42, "admin": 36}


def test_completeness_every_operation_reaches_layer_two(client, dry_run):
    for method, path in operations():
        resp = call(client, method, path)
        assert resp.status_code == ALLOWED, (method, path, resp.status_code, resp.text[:200])


def test_an_undeclared_route_is_refused_by_name(monkeypatch, client):
    endpoint = endpoint_for("GET", "/api/items")
    monkeypatch.delattr(endpoint, permissions.ATTRIBUTE)
    with pytest.raises(RuntimeError, match="declares no @permission"):
        client.get("/api/items")
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    assert client.get("/api/items").status_code == 403


# --- anonymous ---------------------------------------------------------------------


def anonymous_requests():
    for method, path in operations():
        for m in {method, "HEAD", "OPTIONS"}:
            yield m, path
            yield m, path + "/"
    for extra in ("/api/openapi.json", "/api/docs", "/api/redoc", "/docs/oauth2-redirect"):
        yield "GET", extra
    yield "GET", "/api/no-such-thing"
    yield "GET", "/"


def test_anonymous_matrix(anon_client, dry_run):
    for method, path in anonymous_requests():
        resp = call(anon_client, method, path)
        if (method, path) in ANONYMOUS:
            assert resp.status_code != 401, (method, path)
        else:
            assert resp.status_code == 401, (method, path, resp.status_code)
            assert resp.headers["cache-control"] == "no-store"


def test_anonymous_health_is_only_the_status(anon_client):
    assert anon_client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "path",
    # Dot segments are normalised by the HTTP client before sending (and by
    # nginx in front); the real-nginx cases are stage 8's.
    ["/api//health", "/api/health;x=1", "/API/health", "/api/health/"],
)
def test_odd_paths_never_reach_an_anonymous_handler(anon_client, path):
    assert anon_client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/%68ealth",
        "/api/auth/%73tate",
        "/api/%6fpenapi.json",
        "/api/items%2f1",
        "/api/%2e%2e/api/health",
        "/api/pcgs/cert/%31234",
    ],
)
def test_encoded_paths_are_400_for_everyone(anon_client, client, token_client, path):
    for c in (anon_client, client, token_client("write")):
        assert c.get(path).status_code == 400, (path, c)


def test_unknown_paths_are_404_signed_in(client):
    for path in ("/api/docs", "/api/redoc", "/api/no-such-thing"):
        assert client.get(path).status_code == 404


def test_only_plain_route_is_the_schema():
    plain = [r.path for r in app.routes if type(r) is Route]
    assert plain == ["/api/openapi.json"]


def test_schema_is_for_a_session_only(client, token_client, anon_client):
    assert client.get("/api/openapi.json").status_code == 200
    for scope in ("read", "write", "metrics"):
        assert token_client(scope).get("/api/openapi.json").status_code == 403
    assert anon_client.get("/api/openapi.json").status_code == 401


# --- tokens -----------------------------------------------------------------------


def expected_for_token(scope: str, found: permissions.Declared) -> int:
    if found.cls == "public":
        return ALLOWED
    ok = (
        (found.cls == "read" and scope in ("read", "write"))
        or (found.cls == "write" and scope == "write")
        or (found.metrics_ok and scope == "metrics")
    )
    return ALLOWED if ok and not found.fresh else 403


@pytest.mark.parametrize("scope", ["read", "write", "metrics"])
def test_scope_matrix(client, token_client, dry_run, scope):
    c = token_client(scope)
    for method, path in operations():
        want = expected_for_token(scope, declared(endpoint_for(method, path)))
        resp = call(c, method, path)
        assert resp.status_code == want, (scope, method, path, resp.status_code)


def test_metrics_token_sees_only_totals(client, token_client):
    c = token_client("metrics")
    body = c.get("/api/stats/collection").json()
    assert len(body) == 9 and set(body) == set(client.get("/api/stats/collection").json())
    assert c.get("/api/items").status_code == 403
    assert token_client("read").get("/api/metrics").status_code == 403
    assert c.get("/api/metrics").status_code == 404  # until metrics_enabled


def test_invalid_token_never_falls_back_to_the_cookie(client):
    session_name, _ = sessions.cookie_names()
    bad = "Bearer cabinet_" + "a" * 10 + "_" + "b" * 43
    assert client.get("/api/items", headers={"Authorization": bad}).status_code == 401
    # someone else's scheme is ignored, and the cookie is used
    other = {"Authorization": "Bearer eyJhbGciOi.from-authentik"}
    assert client.get("/api/items", headers=other).status_code == 200
    assert client.get("/api/items", headers={"Authorization": "Basic dTpw"}).status_code == 200


def test_tokens_are_never_read_from_a_query_or_a_cookie(anon_client, token_client):
    plaintext = token_client("read").token
    assert anon_client.get(f"/api/items?token={plaintext}").status_code == 401
    anon_client.cookies.set("token", plaintext)
    assert anon_client.get("/api/items").status_code == 401


# --- fresh ------------------------------------------------------------------------


def fresh_operations():
    return [op for op in operations() if declared(endpoint_for(*op)).fresh]


def test_fresh_matrix(client, stale_client, token_client, dry_run):
    ops = fresh_operations()
    # The spec's 15, less the two confirmed by their body, plus the three
    # photo and document deletions (section 16).
    assert len(ops) == 16
    for method, path in ops:
        stale = call(stale_client, method, path)
        assert stale.status_code == 403, (method, path)
        assert stale.json() == {
            "detail": "Confirm your password to continue.",
            "reauth_required": True,
        }
        assert call(client, method, path).status_code == ALLOWED, (method, path)
        for scope in ("read", "write", "metrics"):
            assert call(token_client(scope), method, path).status_code == 403


def test_deleting_for_good_asks_for_the_password(client, stale_client, coin):
    item = coin["id"]
    assert stale_client.delete(f"/api/items/{item}").status_code == 204  # to the trash
    assert stale_client.delete(f"/api/items/{item}").status_code == 403  # already trashed
    resp = stale_client.delete(f"/api/items/{item}?permanent=true")
    assert resp.json()["reauth_required"] is True
    assert client.delete(f"/api/items/{item}").status_code == 204


def test_a_write_token_can_trash_but_not_purge(client, token_client, coin):
    writer = token_client("write")
    assert writer.delete(f"/api/items/{coin['id']}").status_code == 204
    assert writer.delete(f"/api/items/{coin['id']}").status_code == 403


# --- CSRF -------------------------------------------------------------------------


def session_with(client, **headers):
    from fastapi.testclient import TestClient

    c = TestClient(app, base_url="https://testserver", headers=headers)
    c.cookies.set(sessions.cookie_names()[0], client.admin.session_secret)
    return c


def test_csrf_table(client, token_client, dry_run):
    cross = session_with(client, **{"Sec-Fetch-Site": "cross-site"})
    same_site = session_with(client, **{"Sec-Fetch-Site": "same-site"})
    none = session_with(client, **{"Sec-Fetch-Site": "none"})
    bare = session_with(client)
    reader = token_client("read")
    direct = {("GET", "/api/documents/{document_id}/file")}
    for method, path in operations():
        if (method, path) in ANONYMOUS:
            continue
        photo = (method, path) == ("GET", "/api/auth/photo")
        assert call(client, method, path).status_code == ALLOWED, (method, path)
        assert call(cross, method, path).status_code == 403, (method, path)
        assert call(same_site, method, path).status_code == (ALLOWED if photo else 403)
        assert call(bare, method, path).status_code == (ALLOWED if photo else 403)
        want_none = ALLOWED if photo or (method, path) in direct else 403
        assert call(none, method, path).status_code == want_none, (method, path)
        if method == "GET" and declared(endpoint_for(method, path)).cls == "read":
            assert call(reader, method, path).status_code == ALLOWED  # no CSRF for Bearer
    assert none.get("/api/openapi.json").status_code == 200
    for c in (cross, same_site, none, bare):
        c.close()


def test_csrf_origin_rule(client, monkeypatch, dry_run):
    bare = session_with(client)
    good = bare.post("/api/items", headers={"Origin": "https://testserver:443"})
    assert good.status_code == ALLOWED  # the default port is dropped
    assert bare.post("/api/items", headers={"Referer": "https://testserver/x"}).status_code == (
        ALLOWED
    )
    for origin in ("http://localhost", "https://evil.example", "null", "https://testserver.evil"):
        assert bare.post("/api/items", headers={"Origin": origin}).status_code == 403, origin
    bare.close()


def test_origin_only_in_allowed_hosts_is_refused(client, monkeypatch, dry_run):
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
    from app.config import get_settings

    get_settings.cache_clear()
    bare = session_with(client)
    assert bare.post("/api/items", headers={"Origin": "http://localhost"}).status_code == 403
    bare.close()


def test_csrf_helper_on_its_own():
    same = {b"sec-fetch-site": b"same-origin"}
    assert gate.csrf_allows(b"POST", b"/api/items", same)
    assert not gate.csrf_allows(b"GET", b"/api/items", {b"sec-fetch-site": b"cross-site"})
    assert gate.csrf_allows(b"GET", b"/api/auth/photo", {b"sec-fetch-site": b"none"})
    assert not gate.csrf_allows(b"GET", b"/api/auth/photo", {b"sec-fetch-site": b"cross-site"})


# --- headers, bodies, ordering -----------------------------------------------------------


def test_api_answers_default_to_no_store(client):
    assert client.get("/api/items").headers["cache-control"] == "private, no-store"
    assert "no-store" in client.get("/api/auth/me").headers["cache-control"]
    assert client.get("/api/auth/state").headers["cache-control"] == "no-store"


def test_small_bodies_on_the_anonymous_writes(anon_client):
    big = "x" * (9 * 1024)
    for path in ("/api/auth/login", "/api/auth/setup"):
        resp = anon_client.post(path, content=big, headers={"Content-Type": "application/json"})
        assert resp.status_code == 413, path


def test_middleware_order():
    names = [m.cls.__name__ for m in app.user_middleware]
    assert names == ["MaintenanceMiddleware", "AuthGate"]  # the first runs first


def test_maintenance_answers_before_the_gate(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the gate looked someone up during maintenance")

    monkeypatch.setattr(gate, "_lookup", boom)
    monkeypatch.setattr(sessions, "find", boom)
    maintenance.enter()
    try:
        assert client.get("/api/items").status_code == 503
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/restore/status").status_code == 401  # no grant
    finally:
        maintenance.leave()


def test_restore_status_answers_only_the_granted_session(client, stale_client, monkeypatch):
    from app.auth import common
    from app.services import restore

    def boom(*args, **kwargs):
        raise AssertionError("database touched")

    who = permissions.Principal(1, "owner", "session", session_id=1, confirmed=True)
    restore.issue_grant(common.digest(client.admin.session_secret), "r1", who)
    monkeypatch.setattr(gate, "_lookup", boom)
    maintenance.enter()
    try:
        assert client.get("/api/restore/status").status_code == 200
        assert stale_client.get("/api/restore/status").status_code == 401
    finally:
        maintenance.leave()
        restore.drop_grant()


def test_restore_grant_expires(monkeypatch):
    from app.services import restore

    clock = [1000.0]
    monkeypatch.setattr(restore.time, "monotonic", lambda: clock[0])
    restore.issue_grant(b"h" * 32, "r1", "who")
    assert restore.granted(b"h" * 32) == "who"
    assert restore.granted(b"x" * 32) is None
    restore._end_grant("r1")
    clock[0] += 599
    assert restore.granted(b"h" * 32) == "who"
    clock[0] += 2
    assert restore.granted(b"h" * 32) is None
    restore.issue_grant(b"h" * 32, "r2", "who")
    clock[0] += 2 * 3600 + 1
    assert restore.granted(b"h" * 32) is None
    restore.drop_grant()


# --- source lint ------------------------------------------------------------------------


def test_source_lint():
    root = Path(__file__).resolve().parents[1] / "app"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "include_in_schema=False" not in text, path
        assert "app.mount(" not in text, path
        if path.parent.name != "routers":
            assert "add_api_route" not in text, path
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "docs_url=None" in main and "redoc_url=None" in main
    assert app.docs_url is None and app.redoc_url is None


def test_a_refused_cross_site_request_never_keeps_a_session_alive(client):
    from datetime import timedelta

    from app.auth import common
    from app.db import get_db
    from app.models.auth import Session

    db = next(app.dependency_overrides[get_db]())
    try:
        row = (
            db.query(Session)
            .filter_by(secret_hash=common.digest(client.admin.session_secret))
            .one()
        )
        before = common.aware(row.last_seen_at) - timedelta(minutes=5)
        row.last_seen_at = before
        db.commit()
        cross = client.get("/api/items", headers={"Sec-Fetch-Site": "cross-site"})
        assert cross.status_code == 403
        db.expire_all()
        assert common.aware(db.get(Session, row.id).last_seen_at) == before
        assert client.get("/api/items").status_code == 200
        db.expire_all()
        assert common.aware(db.get(Session, row.id).last_seen_at) > before
    finally:
        db.close()


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_sign_in_and_setup_refuse_other_sites(unclaimed_client, site):
    body = {"username": "owner", "password": "correct horse battery", "code": "x" * 32}
    for path in ("/api/auth/login", "/api/auth/setup"):
        resp = unclaimed_client.post(path, json=body, headers={"Sec-Fetch-Site": site})
        assert resp.status_code == 403, path


def test_sign_in_and_setup_take_only_json(unclaimed_client):
    for path in ("/api/auth/login", "/api/auth/setup"):
        resp = unclaimed_client.post(
            path,
            content=b'{"username": "owner", "password": "x"}',
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 415, path


def test_a_chunked_body_over_8_kib_is_refused(unclaimed_client):
    def chunks():
        for _ in range(10):
            yield b"x" * 1024

    resp = unclaimed_client.post(
        "/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413


def test_auth_validation_errors_never_echo_the_fields(client):
    resp = client.post("/api/auth/password", json={"current_password": "my secret words"})
    assert resp.status_code == 422
    assert "my secret words" not in resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", "new_password"]


# --- a low-scope token never gets a body read (stage 12) --------------------------------


@pytest.mark.parametrize("scope", ["read", "metrics"])
def test_a_read_or_metrics_token_is_refused_before_any_body_is_read(
    client, token_client, monkeypatch, scope
):
    """Every unsafe-method route is write or admin, so the gate refuses these
    tokens before FastAPI parses a body: a metrics token in a Prometheus
    config can't make the backend spool a 1 GB import."""
    from starlette.requests import Request

    def boom(self, *args, **kwargs):
        raise AssertionError("the body was read")

    monkeypatch.setattr(Request, "form", boom)
    c = token_client(scope)
    big = b"x" * (3 * 1024 * 1024)
    resp = c.post("/api/imports", files={"file": ("big.csv", big, "text/csv")})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This API token's scope doesn't allow that."
    assert c.delete("/api/items/1").status_code == 403
    assert c.get("/api/items").status_code == (200 if scope == "read" else 403)


def test_a_write_token_still_writes(client, token_client):
    writer = token_client("write")
    resp = writer.post(
        "/api/items", json={"type": "coin", "country": "Gate", "denomination": "1", "year": 2000}
    )
    assert resp.status_code == 201
