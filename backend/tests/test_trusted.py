"""Single sign-on, stage 3 (v0.33.0, SPEC_0330 sections 7, 9, and 11): the
trusted-header mode. A gateway's signed assertion, verified against the
fake provider's keys (standing in for the gateway's JWKS), starts a
session and links an identity; the anonymous `state` never touches it;
and the proxy's start script renders nginx's identity include."""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config as app_config
from app.auth import accounts, oidc, sessions
from app.auth.audit import Actor
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.auth import AuditEntry, Identity, Session
from app.services import alerts
from tests.conftest import BASE_URL, PASSWORD, SAME_ORIGIN
from tests.fake_idp import GATEWAY_AUDIENCE, GATEWAY_ISSUER, JWKS_URL, FakeIdP

HEADER = "X-authentik-jwt"
TRUSTED = "/api/auth/trusted"
LINK = "/api/auth/identities/trusted_header"
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "proxy" / "40-cabinet-config.sh"


def _db():
    return next(app.dependency_overrides[get_db]())


def browser(**headers) -> TestClient:
    return TestClient(app, base_url=BASE_URL, headers={**SAME_ORIGIN, **headers})


@pytest.fixture()
def idp(monkeypatch):
    fake = FakeIdP()
    monkeypatch.setattr(oidc, "_client", fake.client)
    return fake


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        alerts, "event", lambda db, key, title, message: calls.append((key, message))
    )
    return calls


def _configure(monkeypatch, **values):
    wanted = {
        "TRUSTED_ASSERTION_HEADER": HEADER,
        "TRUSTED_ASSERTION_JWKS_URL": JWKS_URL,
        "TRUSTED_ASSERTION_ISSUER": GATEWAY_ISSUER,
        "TRUSTED_ASSERTION_AUDIENCE": GATEWAY_AUDIENCE,
        **values,
    }
    for name, value in wanted.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.fixture()
def gateway(client, idp, monkeypatch):
    """The mode configured (the four variables) and on (the default switch)."""
    _configure(monkeypatch)
    return idp


def linked(client, idp, sub="gateway-sub") -> int:
    r = client.post(LINK, headers={HEADER: idp.assertion(sub)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rejected() -> list[dict]:
    db = _db()
    try:
        rows = db.scalars(
            select(AuditEntry).where(AuditEntry.action == "sso_sign_in_rejected")
        ).all()
        return [row.detail for row in rows]
    finally:
        db.close()


def signed_in(idp, sub="gateway-sub") -> TestClient:
    b = browser()
    r = b.post(TRUSTED, headers={HEADER: idp.assertion(sub)})
    assert r.status_code == 200, r.text
    return b


# --- sign-in -------------------------------------------------------------------------


def test_trusted_sign_in_round_trip(client, gateway, sent):
    identity_id = linked(client, gateway)
    assert sent[-1][0] == "identity_linked"
    summary = next(
        row
        for row in client.get("/api/auth/signin-config").json()["identities"]
        if row["id"] == identity_id
    )
    assert summary["kind"] == "trusted_header" and summary["provider_id"] is None
    assert summary["issuer"] == GATEWAY_ISSUER and summary["subject"] == "gateway-sub"
    assert summary["display"] == "owner@example.com"

    b = browser()
    r = b.post(TRUSTED, headers={HEADER: gateway.assertion()})
    assert r.status_code == 200 and r.json() == {"username": "owner"}
    session_name, device_name = sessions.cookie_names()
    set_cookie = r.headers.get_list("set-cookie")
    assert any(c.startswith(f"{session_name}=") for c in set_cookie)
    assert any(c.startswith(f"{sessions.browser_cookie_name()}=") for c in set_cookie)
    assert not any(c.startswith(f"{device_name}=") for c in set_cookie)

    me = b.get("/api/auth/me").json()
    assert me["auth_method"] == "trusted_header"
    assert me["confirm_methods"] == ["password"]
    db = _db()
    try:
        row = db.scalar(select(Session).where(Session.auth_method == "trusted_header"))
        assert row.identity_id == identity_id
        assert db.get(Identity, identity_id).last_used_at is not None
    finally:
        db.close()


def test_trusted_sign_in_rotates_the_browsers_session(client, gateway):
    linked(client, gateway)
    b = signed_in(gateway)
    first = b.cookies.get(sessions.cookie_names()[0])
    r = b.post(TRUSTED, headers={HEADER: gateway.assertion()})
    assert r.status_code == 200
    db = _db()
    try:
        assert sessions.find(db, first) is None
    finally:
        db.close()


def test_trusted_unlinked_is_refused_and_audited(client, gateway):
    token = gateway.assertion("nobody-linked")
    r = browser().post(TRUSTED, headers={HEADER: token})
    assert r.status_code == 403 and r.json()["code"] == "unlinked"
    found = rejected()
    assert found == [
        {
            "reason": "unlinked",
            "check": "unlinked",
            "intent": "login",
            "kind": "trusted_header",
            "subject": "nobody-linked",
        }
    ]
    assert token not in json.dumps(found)


def test_trusted_duplicate_header_fails_closed(client, gateway):
    linked(client, gateway)
    token = gateway.assertion()
    # nginx joins a repeated header with ", ".
    r = browser().post(TRUSTED, headers={HEADER: f"{token}, {token}"})
    assert r.status_code == 403 and r.json()["code"] == "assertion"
    # Two header lines straight to the backend.
    r = browser().post(TRUSTED, headers=[(HEADER, token), (HEADER, token)])
    assert r.status_code == 403 and r.json()["code"] == "assertion"
    checks = [row["check"] for row in rejected()]
    assert checks == ["whitespace", "duplicate"]
    assert token not in json.dumps(rejected())


def test_trusted_hs256_and_none_refused(client, gateway):
    linked(client, gateway)
    for token in (
        gateway.assertion(alg="HS256"),
        gateway.assertion(alg="none"),
    ):
        r = browser().post(TRUSTED, headers={HEADER: token})
        assert r.status_code == 403 and r.json()["code"] == "assertion"


def test_trusted_oct_key_refused(client, gateway):
    """An HMAC key published in the JWKS under a known kid is never used."""
    gateway.extra_keys.append({"kty": "oct", "kid": "oct-1", "k": "c2VjcmV0", "use": "sig"})
    linked(client, gateway)
    token = gateway.assertion(kid="oct-1")  # an RS256 header naming the HMAC key
    r = browser().post(TRUSTED, headers={HEADER: token})
    assert r.status_code == 403
    assert rejected()[-1]["check"] == "oct"
    token = gateway.assertion(alg="HS256", kid="oct-1")
    assert browser().post(TRUSTED, headers={HEADER: token}).status_code == 403
    assert rejected()[-1]["check"] == "alg"


def test_trusted_expired_refused(client, gateway):
    linked(client, gateway)
    token = gateway.assertion(exp=int(time.time()) - 3600)
    r = browser().post(TRUSTED, headers={HEADER: token})
    assert r.status_code == 403
    assert rejected()[-1]["check"] == "ExpiredSignatureError"
    # Inside the leeway still passes.
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion(exp=int(time.time()) - 30)})
    assert r.status_code == 200


def test_trusted_needs_exp_iss_and_sub_but_not_iat(client, gateway):
    linked(client, gateway)
    for missing in ("exp", "iss", "sub"):
        token = gateway.assertion(**{missing: None})
        assert browser().post(TRUSTED, headers={HEADER: token}).status_code == 403, missing
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion(iat=None)})
    assert r.status_code == 200


def test_trusted_wrong_issuer_or_unknown_key_refused(client, gateway):
    linked(client, gateway)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (
        gateway.assertion(iss="https://elsewhere.test/"),
        gateway.assertion(key=other),  # right kid, wrong key
        gateway.assertion(key=other, kid="unknown"),
    ):
        r = browser().post(TRUSTED, headers={HEADER: token})
        assert r.status_code == 403


def test_assertion_for_another_audience_refused(client, gateway):
    linked(client, gateway)
    for aud in ("another-app", [GATEWAY_AUDIENCE, "another-app"], []):
        r = browser().post(TRUSTED, headers={HEADER: gateway.assertion(aud=aud)})
        assert r.status_code == 403, aud
    assert all(row["reason"] == "assertion" for row in rejected())
    assert browser().post(TRUSTED, headers={HEADER: gateway.assertion()}).status_code == 200


def test_meta_jwks_header_ignored(client, gateway, monkeypatch):
    """A header naming other keys changes nothing: the keys come only from
    TRUSTED_ASSERTION_JWKS_URL (CR-05)."""
    linked(client, gateway)
    evil = FakeIdP()
    asked = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "evil.test":
            asked.append(str(request.url))
            return httpx.Response(200, json=evil.jwks())
        return gateway.handle(request)

    monkeypatch.setattr(
        oidc,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False),
    )
    meta = {"X-authentik-meta-jwks": "https://evil.test/jwks"}
    forged = evil.assertion()  # the right iss, aud, and sub, signed by other keys
    r = browser().post(TRUSTED, headers={HEADER: forged, **meta})
    assert r.status_code == 403
    assert asked == []
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion(), **meta})
    assert r.status_code == 200
    assert asked == []


def test_trusted_jwks_unreachable_is_502(client, gateway):
    linked(client, gateway)
    oidc.reset_memory()
    gateway.redirect.add("jwks")
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion()})
    assert r.status_code == 502 and r.json()["code"] == "provider"
    assert "password" in r.json()["detail"]
    assert rejected()[-1]["check"].startswith("jwks_")


def test_trusted_failures_are_throttled(client, gateway):
    for _ in range(20):
        assert browser().post(TRUSTED, headers={HEADER: "a.b.c"}).status_code == 403
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion()})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert len(rejected()) == 20


def test_trusted_post_is_small_body_and_same_site(client, gateway):
    anon = browser()
    big = "x" * (9 * 1024)
    r = anon.post(TRUSTED, content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    for site in ("cross-site", "same-site"):
        r = anon.post(TRUSTED, headers={HEADER: gateway.assertion(), "Sec-Fetch-Site": site})
        assert r.status_code == 403, site
    # An empty JSON object is fine.
    linked(client, gateway)
    r = anon.post(TRUSTED, json={}, headers={HEADER: gateway.assertion()})
    assert r.status_code == 200


def test_trusted_routes_404_when_unconfigured(client, idp):
    anon = browser()
    r = anon.post(TRUSTED, headers={HEADER: idp.assertion()})
    assert r.status_code == 404 and r.json() == {"detail": "Not found"}
    r = client.post(LINK, headers={HEADER: idp.assertion()})
    assert r.status_code == 404
    assert anon.get("/api/auth/state").json()["methods"]["trusted_header"] is None
    header = client.get("/api/auth/signin-config").json()["trusted_header"]
    assert header == {
        "configured": False,
        "enabled": True,
        "header_name": None,
        "issuer": None,
        "link_ready": False,
    }
    assert rejected() == []


# --- state and the switch ------------------------------------------------------------------


def test_state_never_touches_jwks(client, gateway, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("state fetched the gateway's keys")

    monkeypatch.setattr(oidc, "_jwks", boom)
    monkeypatch.setattr(oidc, "_client", boom)
    anon = browser()
    for headers in ({}, {HEADER: gateway.assertion()}, {HEADER: "not a jwt"}):
        r = anon.get("/api/auth/state", headers=headers)
        assert r.status_code == 200
        assert r.json()["methods"]["trusted_header"] == {"available": True}


def test_signin_config_reports_the_deployment(client, gateway):
    header = client.get("/api/auth/signin-config").json()["trusted_header"]
    assert header == {
        "configured": True,
        "enabled": True,
        "header_name": HEADER,
        "issuer": GATEWAY_ISSUER,
        "link_ready": False,
    }
    # Present is enough; nothing is verified here.
    r = client.get("/api/auth/signin-config", headers={HEADER: "not a jwt"})
    assert r.json()["trusted_header"]["link_ready"] is True


def test_disable_sso_switches_header_mode_off(client, gateway):
    linked(client, gateway)
    b = signed_in(gateway)
    assert b.get("/api/auth/me").status_code == 200
    db = _db()
    try:
        done = accounts.disable_sso(db, Actor.system())
    finally:
        db.close()
    assert done["trusted_header_switched_off"] is True and done["sessions_ended"] == 1
    assert b.get("/api/auth/me").status_code == 401
    anon = browser()
    assert anon.post(TRUSTED, headers={HEADER: gateway.assertion()}).status_code == 404
    assert client.post(LINK, headers={HEADER: gateway.assertion()}).status_code == 404
    assert anon.get("/api/auth/state").json()["methods"]["trusted_header"] is None
    r = browser().post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert r.status_code == 200

    r = client.put("/api/auth/signin-config", json={"trusted_header_enabled": True})
    assert r.status_code == 200 and r.json()["trusted_header"]["enabled"] is True
    assert anon.post(TRUSTED, headers={HEADER: gateway.assertion()}).status_code == 200


def test_switching_back_on_needs_a_fresh_session(client, stale_client, gateway):
    r = stale_client.put("/api/auth/signin-config", json={"trusted_header_enabled": True})
    assert r.status_code == 403 and r.json().get("reauth_required") is True


# --- linking ----------------------------------------------------------------------------------


def test_trusted_link_refuses_email_subject(client, gateway):
    for sub in ("owner@example.com", "owner"):  # the email, then preferred_username
        r = client.post(LINK, headers={HEADER: gateway.assertion(sub)})
        assert r.status_code == 403 and r.json()["code"] == "subject", sub
    assert [row["intent"] for row in rejected()] == ["link", "link"]
    db = _db()
    try:
        assert db.scalar(select(Identity)) is None
    finally:
        db.close()


def test_trusted_link_needs_fresh_session(client, stale_client, gateway):
    r = stale_client.post(LINK, headers={HEADER: gateway.assertion()})
    assert r.status_code == 403 and r.json().get("reauth_required") is True
    assert browser().post(LINK, headers={HEADER: gateway.assertion()}).status_code == 401


def test_trusted_link_refuses_a_bad_assertion_and_a_second_identity(client, gateway):
    r = client.post(LINK, headers={HEADER: gateway.assertion(aud="another-app")})
    assert r.status_code == 403 and r.json()["code"] == "assertion"
    assert rejected()[-1]["intent"] == "link"
    assert client.post(LINK).status_code == 403  # no header at all
    linked(client, gateway)
    r = client.post(LINK, headers={HEADER: gateway.assertion("another-sub")})
    assert r.status_code == 409 and r.json()["code"] == "already_linked"
    r = client.post(LINK, headers={HEADER: gateway.assertion()})
    assert r.status_code == 409


def test_unlink_header_identity_ends_its_sessions(client, gateway):
    identity_id = linked(client, gateway)
    b = signed_in(gateway)
    assert b.get("/api/auth/me").status_code == 200
    assert client.delete(f"/api/auth/identities/{identity_id}").status_code == 204
    assert b.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200  # the password session stays
    r = browser().post(TRUSTED, headers={HEADER: gateway.assertion()})
    assert r.status_code == 403 and r.json()["code"] == "unlinked"


# --- the proxy's start script ------------------------------------------------------------------


def _forbidden_in_script() -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    found = re.search(r'^forbidden="([^"]*)"', text, re.MULTILINE)
    assert found, "the script's forbidden list moved"
    return found.group(1).split()


def test_script_and_backend_forbid_the_same_headers():
    script = sorted(entry.rstrip("*") for entry in _forbidden_in_script())
    assert script == sorted(app_config.TRUSTED_HEADER_FORBIDDEN)


def _render(tmp_path: Path, header: str | None) -> subprocess.CompletedProcess:
    sh = shutil.which("sh")
    out = tmp_path / (header or "none").lower()
    env = {
        **os.environ,
        "CABINET_NGINX_DIR": str(out).replace("\\", "/"),
        "PUBLIC_ORIGINS": "http://localhost",
        "ALLOWED_HOSTS": "",
    }
    env.pop("TRUSTED_ASSERTION_HEADER", None)
    if header is not None:
        env["TRUSTED_ASSERTION_HEADER"] = header
    return subprocess.run(
        [sh, str(SCRIPT).replace("\\", "/")], env=env, capture_output=True, text=True, check=False
    )


def _lines(tmp_path: Path, header: str | None) -> list[str]:
    path = tmp_path / (header or "none").lower() / "cabinet-identity.conf"
    text = path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith("proxy_set_header")]


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh on PATH")
def test_identity_include_rendering(tmp_path):
    done = _render(tmp_path, None)
    assert done.returncode == 0, done.stderr
    lines = _lines(tmp_path, None)
    assert len(lines) > 20
    assert all(line.endswith(' "";') for line in lines)
    assert not any("$http_" in line for line in lines)
    names = {line.split()[1].lower() for line in lines}
    for name in ("x-authentik-jwt", "x-goog-iap-jwt-assertion", "remote-user"):
        assert name in names
    assert (tmp_path / "none" / "hosts.conf").read_text().strip() == "server_name localhost;"

    for given in ("X-authentik-jwt", "x-authentik-JWT"):
        done = _render(tmp_path, given)
        assert done.returncode == 0, done.stderr
        lines = _lines(tmp_path, given)
        passed = [line for line in lines if "$http_" in line]
        assert passed == ["proxy_set_header X-authentik-jwt $http_x_authentik_jwt;"]
        assert len(lines) == len(_lines(tmp_path, None))
        assert 'proxy_set_header X-Goog-IAP-JWT-Assertion "";' in lines

    done = _render(tmp_path, "X-Gateway-Assertion")  # not in the list: added and said so
    assert done.returncode == 0, done.stderr
    passed = [line for line in _lines(tmp_path, "X-Gateway-Assertion") if "$http_" in line]
    assert passed == ["proxy_set_header X-Gateway-Assertion $http_x_gateway_assertion;"]
    assert "X-Gateway-Assertion" in done.stdout

    for bad in ("Host", "cookie", "Sec-Fetch-Site", "X-Forwarded-For", "x-real-ip", "a", "X_JWT"):
        done = _render(tmp_path, bad)
        assert done.returncode != 0, bad
        assert "TRUSTED_ASSERTION_HEADER" in done.stderr
        assert not (tmp_path / bad.lower() / "cabinet-identity.conf").exists()


def test_the_script_is_posix_sh():
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no POSIX sh on PATH")
    done = subprocess.run([sh, "-n", str(SCRIPT).replace("\\", "/")], capture_output=True)
    assert done.returncode == 0, done.stderr
