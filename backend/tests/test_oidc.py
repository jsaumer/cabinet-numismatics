"""Single sign-on, stage 2 (v0.33.0, SPEC_0330 sections 5, 5a, 9, and 11):
the provider flows against an in-process fake provider, the flow cookie,
the gate's no-lookup callback, the throttle map, the log redaction, the
browser cookie, and the configuration routes."""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import accounts, common, devices, gate, oidc, sessions, throttle
from app.auth import config as sso_config
from app.auth.audit import Actor
from app.config import get_settings
from app.db import get_db
from app.main import _RedactSecrets, app
from app.models.auth import AuditEntry, Identity, KnownDevice, Session
from app.services import alerts, crypto, metrics
from tests.conftest import BASE_URL, PASSWORD, SAME_ORIGIN
from tests.fake_idp import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIdP

NAV = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
GITHUB = "https://github.com"


def _db():
    return next(app.dependency_overrides[get_db]())


def browser(**headers) -> TestClient:
    """A fresh browser: its own cookie jar, nobody signed in."""
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


def add_provider(preset="custom", *, enabled=True, **values) -> int:
    db = _db()
    try:
        fields = {
            "display_name": values.pop("display_name", "Fake IdP"),
            "client_id": values.pop("client_id", CLIENT_ID),
            "secret": values.pop("secret", CLIENT_SECRET),
        }
        if preset == "custom":
            fields["issuer"] = values.pop("issuer", ISSUER)
        row = sso_config.add_provider(db, preset=preset, **fields, **values)
        if enabled:
            sso_config.enable_provider(db, row, Actor.system())
        db.commit()
        return row.id
    finally:
        db.close()


@pytest.fixture()
def provider(client, idp) -> int:
    return add_provider()


@pytest.fixture()
def github(client, idp) -> int:
    return add_provider("github", display_name="GitHub")


def link(provider_id: int, subject: str = "owner-sub", issuer: str = ISSUER) -> int:
    db = _db()
    try:
        row = Identity(
            user_id=accounts.admin(db).id,
            kind="provider",
            provider_id=provider_id,
            issuer=issuer,
            subject=subject,
            linked_at=common.now(),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def start(c, provider_id, intent="login", next="/collection", **headers):
    params = {"provider": provider_id, "intent": intent, "next": next}
    return c.get("/api/auth/oidc/start", params=params, headers=headers, follow_redirects=False)


def callback(c, query, headers=None):
    return c.get(
        "/api/auth/oidc/callback", params=query, headers=headers or NAV, follow_redirects=False
    )


def round_trip(c, provider_id, idp, *, intent="login", next="/collection", sub="owner-sub", **kw):
    r = start(c, provider_id, intent, next)
    assert r.status_code == 302, r.text
    return callback(c, idp.authorize(r.headers["location"], sub=sub, **kw), kw.get("headers"))


def signed_in(provider_id, idp, sub="owner-sub", **headers) -> TestClient:
    b = browser(**headers)
    r = round_trip(b, provider_id, idp, sub=sub)
    assert r.status_code == 303 and r.headers["location"] == "/collection", r.headers
    return b


def landed(r) -> tuple[str, dict]:
    assert r.status_code == 303, (r.status_code, r.text)
    parts = urlsplit(r.headers["location"])
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


def rejected(action="sso_sign_in_rejected") -> list[dict]:
    db = _db()
    try:
        rows = db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all()
        return [row.detail for row in rows]
    finally:
        db.close()


def session_row(c) -> Session:
    secret = c.cookies.get(sessions.cookie_names()[0])
    db = _db()
    row = db.scalar(select(Session).where(Session.secret_hash == common.digest(secret)))
    db.close()
    return row


# --- the round trips --------------------------------------------------------------------


def test_sign_in_round_trip(provider, idp, sent):
    link(provider)
    b = browser()
    r = round_trip(b, provider, idp)
    assert landed(r) == ("/collection", {})
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("__Host-cabinet_session=") for c in cookies)
    assert any(c.startswith("__Host-cabinet_browser=") for c in cookies)
    assert not any("cabinet_device" in c for c in cookies)
    assert any(c.startswith("__Host-cabinet_oidc=") and "Max-Age=0" in c for c in cookies)
    me = b.get("/api/auth/me").json()
    assert me["auth_method"] == "oidc" and me["via"] == "session"
    assert me["confirm_methods"] == ["password", "provider"]
    signed = rejected("sign_in")[-1]
    assert signed == {"method": "oidc", "new_browser": True}
    assert [key for key, _ in sent] == ["sign_in_new_device"]
    assert "through Fake IdP" in sent[0][1]
    # The token request carried PKCE and the secret in Basic.
    posts = [q for q in idp.requests if q.method == "POST"]
    assert len(posts) == 1 and posts[0].headers["authorization"].startswith("Basic ")
    assert b"code_verifier=" in posts[0].content and b"client_secret" not in posts[0].content


def test_start_sends_the_protocol_parameters(provider, idp):
    r = start(browser(), provider)
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/authorize"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert set(q) == {
        "response_type",
        "client_id",
        "redirect_uri",
        "state",
        "code_challenge",
        "code_challenge_method",
        "scope",
        "nonce",
    }
    assert q["redirect_uri"] == "https://testserver/api/auth/oidc/callback"
    assert q["scope"].split()[0] == "openid" and q["code_challenge_method"] == "S256"
    assert r.headers["cache-control"] == "no-store"


def test_flow_cookie_attributes(provider, idp, monkeypatch):
    r = start(browser(), provider)
    cookie = next(c for c in r.headers.get_list("set-cookie") if "cabinet_oidc" in c)
    parts = [p.strip().lower() for p in cookie.split(";")]
    assert cookie.startswith("__Host-cabinet_oidc=")
    assert {"path=/", "secure", "httponly", "samesite=lax", "max-age=600"} <= set(parts)
    assert not any(p.startswith("domain=") for p in parts)

    monkeypatch.setenv("AUTH_INSECURE_HTTP", "true")
    get_settings.cache_clear()
    r = start(browser(), provider)
    cookie = next(c for c in r.headers.get_list("set-cookie") if "cabinet_oidc" in c)
    parts = [p.strip().lower() for p in cookie.split(";")]
    assert cookie.startswith("cabinet_oidc=") and "secure" not in parts
    assert {"path=/", "httponly", "samesite=lax", "max-age=600"} <= set(parts)


def test_unknown_or_disabled_provider_is_404(client, idp):
    off = add_provider(enabled=False)
    assert start(browser(), off).status_code == 404
    assert start(browser(), 999).status_code == 404


def test_unlinked_identity_is_refused_and_audited(provider, idp, sent):
    r = round_trip(browser(), provider, idp, sub="stranger")
    assert landed(r) == ("/login", {"error": "unlinked"})
    detail = rejected()[-1]
    assert detail["reason"] == "unlinked" and detail["subject"] == "stranger"
    assert detail["provider_id"] == provider
    assert "set-cookie" not in r.headers or "cabinet_session" not in r.headers["set-cookie"]


def test_callback_passes_gate_without_lookup(client, provider, idp, monkeypatch):
    """CR-01: a live session cookie with Sec-Fetch-Site cross-site reaches
    the handler with no lookup, and `last_seen_at` doesn't move."""
    r = start(client, provider, "link")
    assert r.status_code == 302
    db = _db()
    row = db.get(Session, session_row(client).id)
    before = common.aware(row.last_seen_at) - timedelta(minutes=5)
    row.last_seen_at = before
    db.commit()
    db.close()

    def boom(*args, **kwargs):
        raise AssertionError("the gate looked a credential up for the callback")

    monkeypatch.setattr(gate, "_lookup", boom)
    got = callback(client, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/settings/signin", {"linked": str(provider)})
    assert common.aware(session_row(client).last_seen_at) == before


def test_link_round_trip(client, provider, idp, sent):
    r = round_trip(client, provider, idp, intent="link")
    assert landed(r) == ("/settings/signin", {"linked": str(provider)})
    db = _db()
    row = db.scalar(select(Identity))
    assert (row.issuer, row.subject, row.display) == (ISSUER, "owner-sub", "owner@example.com")
    db.close()
    assert "identity_linked" in [key for key, _ in sent]
    assert rejected("identity_linked")[-1]["subject"] == "owner-sub"
    # A second link of the same identity is refused, in Settings.
    r = round_trip(client, provider, idp, intent="link")
    assert landed(r) == ("/settings/signin", {"error": "already_linked"})


def test_link_needs_a_fresh_session(stale_client, provider, idp, anon_client):
    r = start(stale_client, provider, "link")
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    assert start(anon_client, provider, "link").status_code == 401


def test_link_binds_to_starting_session(client, stale_client, provider, idp):
    r = start(client, provider, "link")
    flow = client.cookies.get(sessions.flow_cookie_name())
    stale_client.cookies.set(sessions.flow_cookie_name(), flow, domain="testserver.local")
    got = callback(stale_client, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/settings/signin", {"error": "session"})
    db = _db()
    assert db.scalar(select(func.count()).select_from(Identity)) == 0
    db.close()


def test_link_refuses_email_like_sub(client, provider, idp):
    r = round_trip(client, provider, idp, intent="link", sub="owner@example.com")
    assert landed(r) == ("/settings/signin", {"error": "subject"})
    idp.claims = {"email": None}
    r = round_trip(client, provider, idp, intent="link", sub="owner")  # = preferred_username
    assert landed(r) == ("/settings/signin", {"error": "subject"})
    db = _db()
    assert db.scalar(select(func.count()).select_from(Identity)) == 0
    db.close()


def test_link_errors_land_in_settings(client, provider, idp):
    idp.redirect = {"token"}
    r = round_trip(client, provider, idp, intent="link")
    assert landed(r) == ("/settings/signin", {"error": "provider"})


# --- confirm ------------------------------------------------------------------------------


def test_confirm_round_trip(provider, idp):
    link(provider)
    b = signed_in(provider, idp)
    assert b.get("/api/auth/me").json()["confirmed_until"] is None
    r = start(b, provider, "confirm", "/settings/backups")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["prompt"] == ["login"] and q["max_age"] == ["0"]
    got = callback(b, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/settings/backups", {})
    assert b.get("/api/auth/me").json()["confirmed_until"] is not None
    assert rejected("reauth")[-1] == {"method": "oidc"}


def test_confirm_start_needs_live_not_fresh(provider, idp, stale_client, anon_client):
    link(provider)
    b = signed_in(provider, idp)
    assert start(b, provider, "confirm").status_code == 302  # not fresh, and fine
    refused = start(stale_client, provider, "confirm")  # a password session
    assert refused.status_code == 403 and refused.json()["code"] == "confirm_identity"
    assert start(anon_client, provider, "confirm").status_code == 401


def test_confirm_requires_session_identity(provider, idp):
    """CR-02: the token's identity must be the one the session signed in
    through: not another sub, not an unlinked one, not another provider's."""
    link(provider)
    other = add_provider(display_name="Other", client_id="other-client")
    other_identity = link(other, subject="owner-at-other")
    b = signed_in(provider, idp)

    for sub in ("stranger", "owner-at-other"):
        r = start(b, provider, "confirm", "/settings")
        got = callback(b, idp.authorize(r.headers["location"], sub=sub))
        assert landed(got) == ("/settings", {"confirm_error": "confirm_identity"})
        assert b.get("/api/auth/me").json()["confirmed_until"] is None

    # A flow started for this provider, while the session came through the
    # other one.
    r = start(b, provider, "confirm", "/settings")
    db = _db()
    row = db.get(Session, session_row(b).id)
    row.identity_id = other_identity
    db.commit()
    db.close()
    got = callback(b, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/settings", {"confirm_error": "confirm_identity"})
    assert b.get("/api/auth/me").json()["confirmed_until"] is None
    assert [d["reason"] for d in rejected()].count("confirm_identity") == 3


def test_confirm_needs_a_recent_auth_time(provider, idp):
    link(provider)
    b = signed_in(provider, idp)
    for auth_time in (int(time.time()) - 600,):
        r = start(b, provider, "confirm", "/settings")
        got = callback(b, idp.authorize(r.headers["location"], auth_time=auth_time))
        assert landed(got) == ("/settings", {"confirm_error": "token"})
    idp.drop = {"auth_time"}
    r = start(b, provider, "confirm", "/settings")
    got = callback(b, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/settings", {"confirm_error": "token"})
    assert b.get("/api/auth/me").json()["confirmed_until"] is None


def test_confirm_offered_only_where_the_provider_can(provider, idp):
    link(provider)
    b = signed_in(provider, idp)
    oidc.reset_memory()
    idp.discovery_extra = {"claims_supported": ["sub", "email"]}  # like Google
    assert b.get("/api/auth/me").json()["confirm_methods"] == ["password"]
    refused = start(b, provider, "confirm")
    assert refused.status_code == 403 and refused.json()["code"] == "not_qualified"


def test_profile_provider_never_confirms(github, idp):
    link(github, subject="4242", issuer=GITHUB)
    b = signed_in(github, idp)
    assert b.get("/api/auth/me").json()["confirm_methods"] == ["password"]
    refused = start(b, github, "confirm")
    assert refused.status_code == 403 and refused.json()["code"] == "not_qualified"
    # A confirm flow made by hand still can't pass the callback.
    db = _db()
    row = sso_config.provider(db, github)
    flow = oidc.start(
        row,
        intent="confirm",
        next_path="/settings",
        origin=BASE_URL,
        session_hash=common.digest(b.cookies.get(sessions.cookie_names()[0])),
    )
    db.close()
    b.cookies.set(sessions.flow_cookie_name(), flow.cookie, domain="testserver.local")
    got = callback(b, idp.authorize(flow.url))
    assert landed(got) == ("/settings", {"confirm_error": "not_qualified"})


# --- the device and browser cookies ------------------------------------------------------


def test_sso_sign_in_issues_no_device_cookie(provider, idp, monkeypatch):
    """CR-03: ten SSO sign-ins mint no known-device cookie, so a wrong
    password at confirm is throttled from the first."""
    link(provider)
    db = _db()
    devices_before = db.scalar(select(func.count()).select_from(KnownDevice))
    db.close()
    b = browser()
    for _ in range(10):
        r = round_trip(b, provider, idp)
        assert r.status_code == 303
        assert not any("cabinet_device" in c for c in r.headers.get_list("set-cookie"))
    assert b.cookies.get(sessions.cookie_names()[1]) is None
    db = _db()
    assert db.scalar(select(func.count()).select_from(KnownDevice)) == devices_before
    db.close()

    reserved = []
    monkeypatch.setattr(devices, "reserve", lambda db, row: reserved.append(row) or True)
    for _ in range(5):
        assert b.post("/api/auth/confirm", json={"password": "wrong"}).status_code == 403
        assert throttle.size() >= 1
    assert b.post("/api/auth/confirm", json={"password": "wrong"}).status_code == 429
    assert reserved == []


def test_browser_cookie_alerts_once(provider, idp, sent, monkeypatch):
    """R2-04: the alert is decided by the browser cookie, never the address:
    two browsers at one address each alert once, and a second sign-in in
    the same browser doesn't. The cookie never reaches `devices.find`."""
    link(provider)
    seen = []
    real = devices.find

    def find(db, secret, user_id):
        seen.append(secret)
        return real(db, secret, user_id)

    monkeypatch.setattr(devices, "find", find)
    one = browser(**{"X-Real-IP": "192.0.2.7"})
    two = browser(**{"X-Real-IP": "192.0.2.7"})
    for c in (one, one, two, two):
        assert round_trip(c, provider, idp).status_code == 303
    assert [key for key, _ in sent] == ["sign_in_new_device", "sign_in_new_device"]
    names = sessions.browser_cookie_name()
    cookies = {one.cookies.get(names), two.cookies.get(names)}
    assert None not in cookies and not cookies & set(seen)
    assert [d["new_browser"] for d in rejected("sign_in")[-4:]] == [True, False, True, False]


def test_password_sign_in_issues_the_browser_cookie(client, sent):
    b = browser()
    r = b.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert r.status_code == 200
    assert b.cookies.get(sessions.browser_cookie_name()) is not None
    r = b.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert not any("cabinet_browser" in c for c in r.headers.get_list("set-cookie"))


def test_me_hands_over_failed_notice_once(provider, idp):
    link(provider)
    wrong = browser()
    for _ in range(2):
        r = wrong.post("/api/auth/login", json={"username": "owner", "password": "nope"})
        assert r.status_code == 401
    b = signed_in(provider, idp)
    first = b.get("/api/auth/me").json()
    assert first["failed_since_previous"] == 2 and first["previous_sign_in_at"] is not None
    again = b.get("/api/auth/me").json()
    assert again["failed_since_previous"] is None and again["previous_sign_in_at"] is None


# --- the flow cookie and state ----------------------------------------------------------------


def test_callback_without_a_flow_cookie_is_refused(provider, idp):
    """Login CSRF: a callback URL handed to a browser that never started the
    flow fails on the cookie; one completed in another jar fails on state."""
    link(provider)
    a, b = browser(), browser()
    r = start(a, provider)
    query = idp.authorize(r.headers["location"])
    assert landed(callback(b, query)) == ("/login", {"error": "cookie"})
    start(b, provider)  # b has a flow cookie of its own now
    assert landed(callback(b, query)) == ("/login", {"error": "state"})
    assert b.cookies.get(sessions.cookie_names()[0]) is None


def test_flow_replay_refused(provider, idp):
    link(provider)
    b = browser()
    r = start(b, provider)
    flow = b.cookies.get(sessions.flow_cookie_name())
    query = idp.authorize(r.headers["location"])
    assert landed(callback(b, query)) == ("/collection", {})
    b.cookies.set(sessions.flow_cookie_name(), flow, domain="testserver.local")
    assert landed(callback(b, query)) == ("/login", {"error": "state"})
    assert rejected()[-1]["check"] == "replay"

    # A cookie older than ten minutes.
    c = browser()
    r = start(c, provider)
    raw = crypto.get_cipher().decrypt(c.cookies.get(sessions.flow_cookie_name()).encode())
    old = crypto.get_cipher().encrypt_at_time(raw, int(time.time()) - 700).decode()
    c.cookies.set(sessions.flow_cookie_name(), old, domain="testserver.local")
    got = callback(c, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/login", {"error": "expired"})

    # Another purpose, sealed with the same key.
    d = browser()
    r = start(d, provider)
    body = json.loads(raw)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    body.update(purpose="something_else", state=state)
    other = crypto.get_cipher().encrypt(json.dumps(body).encode()).decode()
    d.cookies.set(sessions.flow_cookie_name(), other, domain="testserver.local")
    got = callback(d, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/login", {"error": "cookie"})


def test_code_redeemed_only_at_the_cookies_provider(provider, idp):
    """The mix-up rule: a provider named in the callback's query changes
    nothing; the code goes to the token endpoint of the provider the flow
    cookie recorded."""
    link(provider)
    other = add_provider(display_name="Other", issuer="https://other.test", client_id="x")
    b = browser()
    r = start(b, provider)
    query = {**idp.authorize(r.headers["location"]), "provider": str(other)}
    assert landed(callback(b, query)) == ("/collection", {})
    posts = [str(q.url) for q in idp.requests if q.method == "POST"]
    assert posts == [f"{ISSUER}/token"]
    assert not any("other.test" in str(q.url) for q in idp.requests)


def test_provider_disabled_mid_flow(provider, idp):
    link(provider)
    b = browser()
    r = start(b, provider)
    db = _db()
    sso_config.provider(db, provider).enabled = False
    db.commit()
    db.close()
    got = callback(b, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/login", {"error": "provider"})


def test_only_a_top_level_navigation_completes(provider, idp):
    link(provider)
    b = browser()
    r = start(b, provider)
    headers = {**NAV, "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
    got = callback(b, idp.authorize(r.headers["location"]), headers)
    assert landed(got) == ("/login", {"error": "navigation"})
    assert b.cookies.get(sessions.cookie_names()[0]) is None


def test_access_denied_is_not_throttled(provider, idp):
    b = browser()
    r = start(b, provider)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    got = callback(b, {"error": "access_denied", "state": state})
    assert landed(got) == ("/login", {"error": "denied"})
    assert throttle.oidc_size() == 0
    assert rejected()[-1]["reason"] == "denied"


def test_iss_parameter_checked_when_advertised(provider, idp):
    link(provider)
    idp.discovery_extra = {"authorization_response_iss_parameter_supported": True}
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    idp.send_iss = "https://evil.test"
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    idp.send_iss = ISSUER
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})


# --- the ID token --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "knobs",
    [
        {"claims": {"nonce": "not-the-nonce"}},
        {"claims": {"aud": "someone-else"}},
        {"claims": {"exp": int(time.time()) - 3600}},
        {"claims": {"iss": "https://evil.test"}},
        {"claims": {"sub": ""}},
        {"kid": "unknown-kid"},
        {"sign": "none"},
        {"sign": "hs256"},
        {"drop": {"iat"}},
    ],
    ids=["nonce", "aud", "expired", "iss", "empty-sub", "kid", "alg-none", "hs256", "no-iat"],
)
def test_bad_id_tokens_are_refused(provider, idp, knobs):
    link(provider)
    for name, value in knobs.items():
        setattr(idp, name, value)
    b = browser()
    assert landed(round_trip(b, provider, idp)) == ("/login", {"error": "token"})
    assert b.cookies.get(sessions.cookie_names()[0]) is None


def test_an_ec_key_verifies(provider, idp):
    link(provider)
    idp.sign = "ec"
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})


def test_token_without_exp_refused(provider, idp):
    link(provider)
    idp.drop = {"exp"}
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "MissingRequiredClaimError"


def test_oct_key_refused(provider, idp):
    link(provider)
    idp.extra_keys = [{"kty": "oct", "kid": "oct-1", "k": "c2VjcmV0LWtleS1ieXRlcw", "use": "sig"}]
    idp.kid = "oct-1"  # an RS256 header naming a symmetric key
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "oct"
    idp.sign = "hs256"  # signed with the client secret
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "alg"


def test_jwks_refetch_at_most_once_a_minute(provider, idp):
    link(provider)
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})
    assert idp.jwks_fetches == 1
    idp.kid = "rotated-1"
    for _ in range(3):
        assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert idp.jwks_fetches == 1  # inside the cooldown: no refetch
    oidc._keys[f"{ISSUER}/jwks"]._last_successful_fetch -= 61
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert idp.jwks_fetches == 2
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert idp.jwks_fetches == 2


def test_extra_audience_refused(provider, idp):
    link(provider)
    idp.claims = {"aud": [CLIENT_ID, "another-app"]}
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "aud"
    idp.claims = {"aud": [CLIENT_ID]}
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})


def test_azp_mismatch_refused(provider, idp):
    link(provider)
    idp.claims = {"azp": "another-app"}
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "azp"
    idp.claims = {"azp": CLIENT_ID}
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})


# --- the provider's answers -------------------------------------------------------------------


@pytest.mark.parametrize("where", ["discovery", "token", "jwks"])
def test_redirects_and_oversized_answers_fail(provider, idp, where):
    link(provider)
    for knob in ("redirect", "oversize"):
        oidc.reset_memory()
        setattr(idp, knob, {where})
        b = browser()
        r = start(b, provider)
        if where == "discovery":
            assert landed(r) == ("/login", {"error": "provider"})
            continue
        got = callback(b, idp.authorize(r.headers["location"]))
        assert landed(got) == ("/login", {"error": "provider"})
        setattr(idp, knob, set())


def test_discovery_issuer_must_match(provider, idp):
    idp.discovery_issuer = "https://idp.test/"
    assert landed(start(browser(), provider)) == ("/login", {"error": "provider"})


def test_discovery_is_cached_a_day(provider, idp):
    link(provider)
    for _ in range(3):
        round_trip(browser(), provider, idp)
    found = [q for q in idp.requests if q.url.path.endswith("openid-configuration")]
    assert len(found) == 1


def test_credentials_rejected_is_an_alert_condition(provider, idp, client):
    link(provider)
    idp.client_secret = "the secret was rotated"
    assert landed(round_trip(browser(), provider, idp)) == ("/login", {"error": "provider"})
    db = _db()
    assert f"sso_provider_{provider}" in alerts.failing(db)
    db.close()
    config = client.get("/api/auth/signin-config").json()
    assert config["providers"][0]["credentials_failing"] is True
    shown = {a["key"]: a for a in client.get("/api/settings").json()["alerts"]}
    assert shown[f"sso_provider_{provider}"]["failing"] is True
    assert shown[f"sso_provider_{provider}"]["label"] == f"Sign-in provider {provider} credentials"
    db = _db()
    gauge = next(f for f in metrics.collect(db) if f.name == "cabinet_alert_failing")
    db.close()
    key = f"sso_provider_{provider}"
    assert any(s.labels == {"alert": key} and s.value == 1 for s in gauge.samples)
    idp.client_secret = CLIENT_SECRET
    assert landed(round_trip(browser(), provider, idp)) == ("/collection", {})
    db = _db()
    assert f"sso_provider_{provider}" not in alerts.failing(db)
    assert alerts.states(db)[f"sso_provider_{provider}"]["failing"] is False
    db.close()


def test_logout_redirects_to_provider_when_switched_on(provider, idp):
    link(provider)
    b = signed_in(provider, idp)
    assert b.post("/api/auth/logout").status_code == 204

    db = _db()
    sso_config.provider(db, provider).logout_at_provider = True
    db.commit()
    db.close()
    b = signed_in(provider, idp)
    r = b.post("/api/auth/logout")
    assert r.status_code == 200
    url = urlsplit(r.json()["redirect"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/logout"
    assert parse_qs(url.query) == {
        "client_id": [CLIENT_ID],
        "post_logout_redirect_uri": ["https://testserver/login"],
    }
    assert b.get("/api/auth/me").status_code == 401


# --- GitHub -------------------------------------------------------------------------------------


def test_github_profile_with_no_scope(github, idp):
    link(github, subject="4242", issuer=GITHUB)
    b = browser()
    r = start(b, github)
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.headers["location"].startswith("https://github.com/login/oauth/authorize?")
    assert "scope" not in q and "nonce" not in q
    assert landed(callback(b, idp.authorize(r.headers["location"]))) == ("/collection", {})
    token = next(q for q in idp.requests if q.method == "POST")
    assert token.headers["accept"] == "application/json"
    # GitHub takes the client id and secret as form fields, never Basic.
    assert "authorization" not in token.headers
    form = parse_qs(token.content.decode())
    assert form["client_id"] and "client_secret" in form
    profile = next(q for q in idp.requests if q.url.host == "api.github.com")
    assert profile.headers["authorization"].startswith("Bearer at-")
    assert b.get("/api/auth/me").json()["auth_method"] == "oidc"


@pytest.mark.parametrize("profile", [{"id": "4242", "login": "x"}, {"login": "x"}, {"id": True}])
def test_github_profile_needs_a_numeric_id(github, idp, profile):
    link(github, subject="4242", issuer=GITHUB)
    idp.profile = profile
    assert landed(round_trip(browser(), github, idp)) == ("/login", {"error": "profile"})


def test_github_error_body_is_a_failure(github, idp):
    link(github, subject="4242", issuer=GITHUB)
    idp.token_body = {"error": "bad_verification_code"}  # with a 200
    assert landed(round_trip(browser(), github, idp)) == ("/login", {"error": "token"})
    idp.token_body = {"error": "incorrect_client_credentials"}
    assert landed(round_trip(browser(), github, idp)) == ("/login", {"error": "provider"})
    db = _db()
    assert f"sso_provider_{github}" in alerts.failing(db)
    db.close()


@pytest.mark.parametrize("kind,ok", [("bearer", True), ("BEARER", True), ("mac", False)])
def test_bearer_case_insensitive(github, idp, kind, ok):
    link(github, subject="4242", issuer=GITHUB)
    idp.token_type = kind
    want = ("/collection", {}) if ok else ("/login", {"error": "token"})
    assert landed(round_trip(browser(), github, idp)) == want


def test_github_form_answer_without_accept_is_not_json(github, idp, monkeypatch):
    """The fake answers form-encoded without `Accept: application/json`, as
    GitHub does; Cabinet always asks for JSON, and a form answer fails."""
    link(github, subject="4242", issuer=GITHUB)
    real = idp.handle

    def no_accept(request):
        if request.method == "POST":
            request.headers["accept"] = "*/*"
        return real(request)

    monkeypatch.setattr(idp, "handle", no_accept)
    assert landed(round_trip(browser(), github, idp)) == ("/login", {"error": "token"})
    assert rejected()[-1]["check"] == "not_json"


# --- small rules --------------------------------------------------------------------------------


def test_next_rules():
    for bad in (
        "//e.x",
        "/\\e.x",
        "/\t/e.x",
        "https://e.x",
        "/api/backup.zip",
        "/s/x",
        "/photos/a.jpg",
        "e.x",
        "",
        None,
    ):
        assert oidc.safe_next(bad) == "/", bad
    for good in ("/", "/collection", "/items/3?tab=values", "/settings/signin"):
        assert oidc.safe_next(good) == good


def test_next_is_checked_at_start(provider, idp):
    link(provider)
    b = browser()
    r = start(b, provider, next="//evil.example")
    got = callback(b, idp.authorize(r.headers["location"]))
    assert landed(got) == ("/", {})


def test_callback_origin_follows_host(provider, idp, monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGINS", "https://testserver,https://cabinet.example.com")
    get_settings.cache_clear()
    assert oidc.callback_origin("cabinet.example.com") == "https://cabinet.example.com"
    assert oidc.callback_origin("testserver") == "https://testserver"
    assert oidc.callback_origin("elsewhere") == "https://testserver"
    hosts = (("cabinet.example.com", "https://cabinet.example.com"), ("testserver", BASE_URL))
    for host, want in hosts:
        r = start(browser(), provider, Host=host)
        q = parse_qs(urlsplit(r.headers["location"]).query)
        assert q["redirect_uri"] == [f"{want}/api/auth/oidc/callback"]


def test_callback_query_redacted():
    flt = _RedactSecrets()
    targets = [
        ("GET", "/api/auth/oidc/callback?code=SECRETCODE&state=SECRETSTATE"),
        ("HEAD", "/api/auth/oidc/callback?code=SECRETCODE&state=SECRETSTATE"),
        ("GET", "/api/auth/oidc/callback/?code=SECRETCODE&state=SECRETSTATE"),
        ("GET", "/api/auth/oidc/callback?error=x&error_description=SECRET+words&state=SECRET"),
    ]
    for method, target in targets:
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("192.0.2.1:5000", method, target, "1.1", 303),
            None,
        )
        assert flt.filter(record)
        line = record.getMessage()
        assert "SECRET" not in line, line
        assert "/api/auth/oidc/callback?[redacted]" in line
    assert oidc.redact("/api/share/share_abc/items") == "/api/share/share_abc/items"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", ("/api/share/share_abc",), None
    )
    flt.filter(record)
    assert "share_abc" not in record.getMessage()


def test_sso_ca_file_adds_to_public_roots(tmp_path, monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Cabinet Test Homelab CA")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "homelab-ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    def names(context):
        found = set()
        for ca in context.get_ca_certs():
            for rdn in ca["subject"]:
                for field, value in rdn:
                    if field == "commonName":
                        found.add(value)
        return found

    public = names(oidc.ssl_context())
    assert "Cabinet Test Homelab CA" not in public and len(public) > 50
    monkeypatch.setenv("SSO_CA_FILE", str(path))
    get_settings.cache_clear()
    both = names(oidc.ssl_context())
    assert "Cabinet Test Homelab CA" in both
    assert public <= both  # added to the public roots, never in place of them


# --- the throttle -------------------------------------------------------------------------------


def test_oidc_failures_never_evict_sign_in_buckets(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(common, "monotonic", lambda: clock[0])
    throttle.fail("user", "owner")
    throttle.fail("addr", "192.0.2.1")
    throttle.share_failure("192.0.2.2")
    for n in range(10_001):
        clock[0] += 0.25  # 240 a minute, under the global cap
        assert throttle.oidc_failure(f"10.{n // 65536}.{n // 256 % 256}.{n % 256}") == 0
    assert throttle.size() == 2
    assert throttle.share_size() == 1
    assert throttle.oidc_size() == throttle.MAX_KEYS


def test_oidc_global_cap(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(common, "monotonic", lambda: clock[0])
    for n in range(throttle.OIDC_GLOBAL_PER_MINUTE):
        assert throttle.oidc_failure(f"10.0.{n // 256}.{n % 256}") == 0
    assert throttle.oidc_failure("10.9.9.9") > 0  # a new address, still refused
    assert throttle.oidc_size() == throttle.OIDC_GLOBAL_PER_MINUTE  # not counted
    clock[0] += 61
    assert throttle.oidc_failure("10.9.9.9") == 0
    # An address's own wait, past 20, keyed by /64 for IPv6.
    for n in range(20):
        assert throttle.oidc_failure(f"2001:db8::{n}") == 0
    assert throttle.oidc_failure("2001:db8::ffff") > 0


def test_callback_failures_are_throttled_per_address(provider, idp):
    b = browser(**{"X-Real-IP": "198.51.100.9"})
    for _ in range(20):
        assert landed(callback(b, {"code": "x", "state": "y"})) == ("/login", {"error": "cookie"})
    r = callback(b, {"code": "x", "state": "y"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    other = browser(**{"X-Real-IP": "198.51.100.10"})
    assert callback(other, {"code": "x", "state": "y"}).status_code == 303


# --- the frontend-facing shapes and the configuration routes ------------------------------------


def test_state_lists_the_ways_in(anon_client, client, idp):
    off = add_provider(enabled=False, display_name="Off")
    on = add_provider(display_name="Keycloak", client_id="kc")
    state = anon_client.get("/api/auth/state").json()
    assert state == {
        "setup_required": False,
        "methods": {
            "password": True,
            "providers": [{"id": on, "name": "Keycloak", "preset": "custom"}],
            "trusted_header": None,
        },
    }
    assert off != on


def test_me_shape_for_a_password_session_and_a_token(client, token_client):
    me = client.get("/api/auth/me").json()
    assert me["auth_method"] == "password" and me["confirm_methods"] == ["password"]
    assert me["failed_since_previous"] is None and me["previous_sign_in_at"] is None
    me = token_client("read").get("/api/auth/me").json()
    assert me["auth_method"] is None and me["confirm_methods"] == []


def test_signin_config_shape(client, idp):
    provider = add_provider()
    link(provider)
    body = client.get("/api/auth/signin-config").json()
    assert set(body) == {
        "providers",
        "identities",
        "trusted_header",
        "password_sign_in_alerts",
        "presets",
        "callback_urls",
    }
    row = body["providers"][0]
    assert row["has_secret"] is True and "client_secret" not in row
    assert CLIENT_SECRET not in json.dumps(body)
    assert row["credentials_failing"] is False and row["linked"] is True
    assert body["identities"][0]["subject"] == "owner-sub"
    assert body["trusted_header"] == {
        "configured": False,
        "enabled": True,
        "header_name": None,
        "issuer": None,
        "link_ready": False,
    }
    assert body["password_sign_in_alerts"] is True  # the first provider switched it on
    assert body["callback_urls"] == ["https://testserver/api/auth/oidc/callback"]
    presets = {p["name"]: p for p in body["presets"]}
    assert presets["github"]["kind"] == "oauth2_profile"
    assert presets["microsoft"]["needs_tenant"] is True and presets["microsoft"]["issuer"] is None
    assert presets["google"]["issuer"] == "https://accounts.google.com"


def test_put_signin_config(client, stale_client):
    body = {"password_sign_in_alerts": True}
    assert stale_client.put("/api/auth/signin-config", json=body).status_code == 403
    r = client.put("/api/auth/signin-config", json=body)
    assert r.status_code == 200 and r.json()["password_sign_in_alerts"] is True
    assert rejected("sso_configured")[-1] == {"changed": ["password_sign_in_alerts"]}
    r = client.put("/api/auth/signin-config", json={"trusted_header_enabled": False})
    assert r.json()["trusted_header"]["enabled"] is False
    assert client.put("/api/auth/signin-config", json={"other": 1}).status_code == 422


def test_add_a_provider(client, idp, sent):
    body = {
        "preset": "custom",
        "display_name": "Authentik",
        "client_id": "cab",
        "client_secret": "a secret typed once",
        "issuer": ISSUER,
        "enabled": True,
    }
    r = client.post("/api/auth/providers", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["enabled"] is True and out["has_secret"] is True
    assert out["callback_urls"] == ["https://testserver/api/auth/oidc/callback"]
    assert "a secret typed once" not in r.text
    added = rejected("sso_configured")
    assert any(d.get("added") and "client_secret" in d["changed"] for d in added)
    assert "sso_configured" in [key for key, _ in sent]
    assert client.post("/api/auth/providers", json=body).status_code == 409  # same pair

    r = client.post(
        "/api/auth/providers",
        json={"preset": "microsoft", "display_name": "Work", "client_id": "m", "tenant": "t-1"},
    )
    assert r.json()["issuer"] == "https://login.microsoftonline.com/t-1/v2.0"
    for bad in (
        {"preset": "microsoft", "display_name": "W", "client_id": "m2"},
        {"preset": "google", "display_name": "G", "client_id": "g", "issuer": ISSUER},
        {"preset": "custom", "display_name": "C", "client_id": "c", "issuer": "ftp://x"},
        {"preset": "custom", "display_name": "C", "client_id": "c"},
    ):
        assert client.post("/api/auth/providers", json=bad).status_code == 422, bad


def test_dry_run_saves_nothing(client, idp):
    body = {"preset": "custom", "display_name": "A", "client_id": "a", "issuer": ISSUER}
    r = client.post("/api/auth/providers", json={**body, "dry_run": True})
    assert r.json() == {
        "ok": True,
        "issuer": ISSUER,
        "claims_supported_auth_time": True,
        "prompt_login": True,
    }
    idp.discovery_issuer = "https://wrong.test"
    r = client.post("/api/auth/providers", json={**body, "dry_run": True})
    assert r.json() == {"ok": False, "issuer": ISSUER, "error": "issuer"}
    assert client.get("/api/auth/signin-config").json()["providers"] == []


def test_two_origins_on_one_host_refuse_a_provider(client, idp, monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGINS", "https://testserver,http://testserver:8080")
    get_settings.cache_clear()
    body = {"preset": "custom", "display_name": "A", "client_id": "a", "issuer": ISSUER}
    r = client.post("/api/auth/providers", json=body)
    assert r.status_code == 409 and "testserver" in r.json()["detail"]


def test_change_a_provider(client, idp):
    provider = add_provider()
    r = client.patch(
        f"/api/auth/providers/{provider}",
        json={"display_name": "Renamed", "client_secret": "new secret"},
    )
    assert r.status_code == 200 and r.json()["display_name"] == "Renamed"
    db = _db()
    assert sso_config.client_secret(sso_config.provider(db, provider)) == "new secret"
    db.close()
    detail = rejected("sso_configured")[-1]
    assert detail["changed"] == ["display_name", "client_secret"]

    link(provider)
    r = client.patch(f"/api/auth/providers/{provider}", json={"issuer": "https://other.test"})
    assert r.status_code == 409  # R2-13
    r = client.patch(f"/api/auth/providers/{provider}", json={"client_id": "other"})
    assert r.status_code == 409


def test_switching_a_provider_off_ends_its_sessions(client, idp):
    provider = add_provider()
    link(provider)
    b = signed_in(provider, idp)
    r = client.patch(f"/api/auth/providers/{provider}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert b.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200  # the password session stays
    assert rejected("sso_configured")[-1]["sessions_ended"] == 1


def test_delete_provider_and_identity_routes(client, idp):
    provider = add_provider()
    identity = link(provider)
    b = signed_in(provider, idp)
    assert client.delete(f"/api/auth/identities/{identity}").status_code == 204
    assert b.get("/api/auth/me").status_code == 401
    assert client.delete(f"/api/auth/identities/{identity}").status_code == 404
    db = _db()
    alerts.fail(db, f"sso_provider_{provider}", "rejected")
    db.close()
    assert client.delete(f"/api/auth/providers/{provider}").status_code == 204
    assert client.delete(f"/api/auth/providers/{provider}").status_code == 404
    db = _db()
    assert f"sso_provider_{provider}" not in alerts.states(db)
    db.close()


def test_configuration_routes_need_a_fresh_admin(stale_client, token_client):
    provider = add_provider()
    calls = [
        ("post", "/api/auth/providers", {"json": {}}),
        ("patch", f"/api/auth/providers/{provider}", {"json": {}}),
        ("delete", f"/api/auth/providers/{provider}", {}),
        ("delete", "/api/auth/identities/1", {}),
    ]
    for method, path, kwargs in calls:
        r = getattr(stale_client, method)(path, **kwargs)
        assert r.json().get("reauth_required") is True, path
        assert getattr(token_client("write"), method)(path, **kwargs).status_code == 403
    assert token_client("write").get("/api/auth/signin-config").status_code == 403
    assert stale_client.get("/api/auth/signin-config").status_code == 200
