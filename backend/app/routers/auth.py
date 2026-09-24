"""Sign-in routes (v0.30.0): setup, sign-in and out, the recent-password
window, the account, its sessions and tokens, the audit log, and the photo
check nginx asks before serving a photo.

Setup and sign-in are the only anonymous writes. Their bodies are read by
hand, at most 8 KiB (nginx and the gate cap them too), and every password
check runs in a worker thread through `accounts`.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session as DbSession

from app.auth import accounts, audit, oidc, sessions, setup, throttle, tokens
from app.auth import config as sso_config
from app.auth.events import actor_of
from app.auth.permissions import Principal, permission, principal, require
from app.db import get_db
from app.models.auth import ApiToken, AuthProvider, Identity, Session, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

BODY_LIMIT = 8 * 1024
NO_STORE = {"Cache-Control": "no-store"}
WRONG_CODE = "That setup code is not right."


# --- request helpers -----------------------------------------------------------------


def client_of(request: Request) -> accounts.Client:
    """The address nginx saw (it overwrites X-Real-IP on every request), the
    browser, the known-device cookie, and the new-browser alert cookie."""
    _, device_name = sessions.cookie_names()
    return accounts.Client(
        address=(request.headers.get("x-real-ip") or "")[:45] or None,
        user_agent=(request.headers.get("user-agent") or "")[:256] or None,
        device=request.cookies.get(device_name),
        browser=request.cookies.get(sessions.browser_cookie_name()),
    )


def _current(db: DbSession, who: Principal) -> tuple[Session, User]:
    row = db.get(Session, who.session_id)
    user = db.get(User, who.user_id)
    if row is None or user is None:
        raise HTTPException(401, "Sign in to continue.")
    return row, user


async def _small_json(request: Request, model: type[BaseModel]):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(415, "Send the form's fields as JSON.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > BODY_LIMIT:
            raise HTTPException(413, "Too large.")
    try:
        return model.model_validate(json.loads(body or b"null"))
    except (ValueError, ValidationError):
        raise HTTPException(422, "Send the form's fields as JSON.") from None


def _body_schema(model: type[BaseModel]) -> dict:
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


def _throttled(exc: throttle.Throttled) -> HTTPException:
    return HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)})


def _busy(exc: accounts.Busy) -> HTTPException:
    return HTTPException(
        503,
        "Cabinet is busy checking passwords; try again in a moment.",
        headers={"Retry-After": str(exc.retry_after)},
    )


def _iso(value: datetime | None) -> str | None:
    from app.auth import common

    value = common.aware(value)
    return value.isoformat() if value else None


# --- setup and sign-in -----------------------------------------------------------------


class SetupBody(BaseModel):
    code: str
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


@router.get("/state")
@permission("public")
def auth_state(db: DbSession = Depends(get_db)):
    """Whether setup is needed, and the ways to sign in: the password always,
    one button per enabled provider (read from the database, never cached,
    R2-01). `trusted_header` is filled by stage 3."""
    setup.ensure_prepared(db)
    providers = [
        {"id": row.id, "name": row.display_name, "preset": row.preset}
        for row in sso_config.providers(db, enabled_only=True)
    ]
    return JSONResponse(
        {
            "setup_required": not accounts.claimed(db),
            "methods": {"password": True, "providers": providers, "trusted_header": None},
        },
        headers=NO_STORE,
    )


@router.post("/setup", status_code=201, openapi_extra=_body_schema(SetupBody))
@permission("public")
async def auth_setup(request: Request, db: DbSession = Depends(get_db)):
    """Create the admin with the setup code. The code is compared first, and
    a right code is never throttled; a wrong one counts against the address."""
    body = await _small_json(request, SetupBody)
    client = client_of(request)

    def work():
        if accounts.claimed(db):
            raise HTTPException(409, accounts.ALREADY_CLAIMED)
        setup.ensure_prepared(db)
        address = client.address or "unknown"
        if not setup.check(body.code):
            wait = throttle.wait("setup", address)
            if wait > 0:
                raise _throttled(throttle.Throttled(wait))
            throttle.fail("setup", address)
            audit.record(db, "setup_failed", client.actor("anonymous"))
            db.commit()
            raise HTTPException(403, WRONG_CODE)
        try:
            started = accounts.create_admin(db, body.username, body.password, client)
        except accounts.PasswordRejected as exc:
            raise HTTPException(422, str(exc)) from None
        except accounts.AlreadyClaimed:
            raise HTTPException(409, accounts.ALREADY_CLAIMED) from None
        except accounts.Busy as exc:
            raise _busy(exc) from None
        setup.claimed(started.user.username)
        return started

    started = await run_in_threadpool(work)
    response = JSONResponse({"username": started.user.username}, 201, headers=NO_STORE)
    sessions.set_cookies(response, started.session_secret, started.device_secret)
    sessions.set_browser_cookie(response, started.browser_secret)
    return response


@router.post("/login", openapi_extra=_body_schema(LoginBody))
@permission("public")
async def auth_login(request: Request, db: DbSession = Depends(get_db)):
    body = await _small_json(request, LoginBody)
    client = client_of(request)
    session_name, _ = sessions.cookie_names()
    presented = request.cookies.get(session_name)

    def work():
        try:
            started = accounts.sign_in(db, body.username, body.password, client)
        except accounts.WrongPassword as exc:
            raise HTTPException(401, str(exc)) from None
        except throttle.Throttled as exc:
            raise _throttled(exc) from None
        except accounts.Busy as exc:
            raise _busy(exc) from None
        # A session this browser already held ends: sign-in always rotates.
        if (old := sessions.find(db, presented)) is not None:
            sessions.revoke(old[0])
            db.commit()
        return started

    started = await run_in_threadpool(work)
    response = JSONResponse(
        {
            "username": started.user.username,
            "previous_sign_in_at": _iso(started.previous_sign_in_at),
            "failed_since_previous": started.failed_since_previous,
        },
        headers=NO_STORE,
    )
    sessions.set_cookies(response, started.session_secret, started.device_secret)
    sessions.set_browser_cookie(response, started.browser_secret)
    return response


def _provider_of(db: DbSession, row: Session) -> AuthProvider | None:
    """The provider an `oidc` session signed in through, if it still exists."""
    if row.auth_method != "oidc" or row.identity_id is None:
        return None
    identity = db.get(Identity, row.identity_id)
    if identity is None or identity.provider_id is None:
        return None
    return db.get(AuthProvider, identity.provider_id)


@router.post("/logout", status_code=204)
@permission("admin")
def auth_logout(request: Request, db: DbSession = Depends(get_db)):
    """End this session: 204, or, for an `oidc` session whose provider has
    "sign out there too" on and publishes an end-session endpoint, 200
    `{"redirect": ...}` for the browser to follow (Q7)."""
    row, user = _current(db, principal(request))
    provider = _provider_of(db, row)
    redirect = None
    if provider is not None:
        origin = oidc.callback_origin(request.headers.get("host"))
        redirect = oidc.logout_url(provider, origin)
    accounts.sign_out(db, row, user, client_of(request))
    headers = {**NO_STORE, "Clear-Site-Data": '"cache"'}
    if redirect is not None:
        response = JSONResponse({"redirect": redirect}, headers=headers)
    else:
        response = Response(status_code=204, headers=headers)
    sessions.clear_cookies(response)
    return response


# --- the account -------------------------------------------------------------------


class MeOut(BaseModel):
    username: str
    role: str
    via: str
    scope: str | None
    confirmed_until: str | None
    auth_method: str | None = None
    confirm_methods: list[str] = []
    # Once after an external sign-in, then null (R2-10).
    failed_since_previous: int | None = None
    previous_sign_in_at: str | None = None


@router.get("/me", response_model=MeOut)
@permission("read")
def auth_me(request: Request, db: DbSession = Depends(get_db)):
    """Who is calling. For a session: how it signed in, how it may confirm
    (the password always; `provider` too on an `oidc` session whose provider
    can do it, Q11), and, the first time only after a single sign-on, the
    failed-sign-ins notice a password sign-in answers with."""
    who = principal(request)
    confirmed_until = None
    auth_method = None
    confirm_methods = []
    failed = previous = None
    if who.kind == "session":
        row = db.get(Session, who.session_id)
        if row is not None:
            if sessions.confirmed(row):
                confirmed_until = _iso(row.confirmed_until)
            auth_method = row.auth_method
            confirm_methods = ["password"]
            provider = _provider_of(db, row)
            if provider is not None and provider.enabled and oidc.qualifies_for_confirm(provider):
                confirm_methods.append("provider")
            if row.notice_failed is not None:
                failed, previous = row.notice_failed, _iso(row.notice_since)
                row.notice_failed = None
                row.notice_since = None
                db.commit()
    user = db.get(User, who.user_id)
    return MeOut(
        username=who.username,
        role=user.role if user else "admin",
        via=who.kind,
        scope=who.scope,
        confirmed_until=confirmed_until,
        auth_method=auth_method,
        confirm_methods=confirm_methods,
        failed_since_previous=failed,
        previous_sign_in_at=previous,
    )


class ConfirmBody(BaseModel):
    password: str


def _password_errors(call):
    try:
        return call()
    except accounts.WrongPassword as exc:
        # 403, not 401: the session is fine, the password typed was not.
        raise HTTPException(403, str(exc)) from None
    except accounts.PasswordRejected as exc:
        raise HTTPException(422, str(exc)) from None
    except throttle.Throttled as exc:
        raise _throttled(exc) from None
    except accounts.Busy as exc:
        raise _busy(exc) from None


@router.post("/confirm", status_code=204)
@permission("admin")
def auth_confirm(body: ConfirmBody, request: Request, db: DbSession = Depends(get_db)):
    """Open this session's 5-minute recent-password window."""
    row, user = _current(db, principal(request))
    _password_errors(lambda: accounts.confirm(db, row, user, body.password, client_of(request)))
    return Response(status_code=204, headers=NO_STORE)


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class RevokedToken(BaseModel):
    id: int
    name: str
    scope: str


class PasswordOut(BaseModel):
    revoked_tokens: list[RevokedToken]


# The current password in the body is the confirmation for these two, so they
# don't also ask for the recent-password window first.
@router.post("/password", response_model=PasswordOut)
@permission("admin")
def auth_password(body: PasswordBody, request: Request, db: DbSession = Depends(get_db)):
    """Every other session, every known device, and every API token end; this
    browser gets a new session."""
    row, user = _current(db, principal(request))
    changed = _password_errors(
        lambda: accounts.change_password(
            db, row, user, body.current_password, body.new_password, client_of(request)
        )
    )
    response = JSONResponse({"revoked_tokens": changed.revoked_tokens}, headers=NO_STORE)
    sessions.set_cookies(response, changed.started.session_secret, changed.started.device_secret)
    return response


class UsernameBody(BaseModel):
    current_password: str
    username: str


@router.post("/username", status_code=204)
@permission("admin")
def auth_username(body: UsernameBody, request: Request, db: DbSession = Depends(get_db)):
    row, user = _current(db, principal(request))
    _password_errors(
        lambda: accounts.change_username(
            db, row, user, body.current_password, body.username, client_of(request)
        )
    )
    return Response(status_code=204, headers=NO_STORE)


# --- sessions ----------------------------------------------------------------------


class SessionOut(BaseModel):
    id: int
    created_at: str | None
    last_seen_at: str | None
    address: str | None
    user_agent: str | None
    current: bool


@router.get("/sessions", response_model=list[SessionOut])
@permission("admin")
def auth_sessions(request: Request, db: DbSession = Depends(get_db)):
    who = principal(request)
    return [
        SessionOut(
            id=row.id,
            created_at=_iso(row.created_at),
            last_seen_at=_iso(row.last_seen_at),
            address=row.address,
            user_agent=row.user_agent,
            current=row.id == who.session_id,
        )
        for row in sessions.live(db, who.user_id)
    ]


def _signed_out(status: int = 204) -> Response:
    response = Response(status_code=status, headers={**NO_STORE, "Clear-Site-Data": '"cache"'})
    sessions.clear_cookies(response)
    return response


@router.delete("/sessions/{session_id}", status_code=204)
@permission("admin")
def auth_end_session(session_id: int, request: Request, db: DbSession = Depends(get_db)):
    """End one session. Ending another asks for the password again; ending
    this one is signing out."""
    who = principal(request)
    if session_id == who.session_id:
        row, user = _current(db, who)
        accounts.sign_out(db, row, user, client_of(request))
        return _signed_out()
    require(request, "admin", fresh=True)
    user = db.get(User, who.user_id)
    try:
        accounts.end_session(db, user, session_id, actor_of(who))
    except accounts.NotFound:
        raise HTTPException(404, "No such session.") from None
    return Response(status_code=204, headers=NO_STORE)


@router.delete("/sessions", status_code=204)
@permission("admin", fresh=True)
def auth_sign_out_everywhere(request: Request, db: DbSession = Depends(get_db)):
    """Every session, this one included, and every known device."""
    who = principal(request)
    accounts.sign_out_everywhere(db, db.get(User, who.user_id), actor_of(who))
    return _signed_out()


# --- tokens ------------------------------------------------------------------------


class TokenOut(BaseModel):
    id: int
    name: str
    scope: str
    created_at: str | None
    last_used_at: str | None
    expires_at: str | None


class TokenBody(BaseModel):
    name: str
    scope: str
    days: int | None = 1


class TokenCreated(TokenOut):
    token: str  # shown once, here only


def _token_out(row: ApiToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "scope": row.scope,
        "created_at": _iso(row.created_at),
        "last_used_at": _iso(row.last_used_at),
        "expires_at": _iso(row.expires_at),
    }


@router.get("/tokens", response_model=list[TokenOut])
@permission("admin")
def auth_tokens(request: Request, db: DbSession = Depends(get_db)):
    return [_token_out(row) for row in tokens.live(db, principal(request).user_id)]


@router.post("/tokens", status_code=201, response_model=TokenCreated)
@permission("admin", fresh=True)
def auth_create_token(body: TokenBody, request: Request, db: DbSession = Depends(get_db)):
    who = principal(request)
    user = db.get(User, who.user_id)
    try:
        plaintext, row = accounts.create_token(
            db, user, body.name, body.scope, body.days, actor_of(who)
        )
    except tokens.TokenRejected as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({**_token_out(row), "token": plaintext}, 201, headers=NO_STORE)


@router.delete("/tokens/{token_id}", status_code=204)
@permission("admin", fresh=True)
def auth_revoke_token(token_id: int, request: Request, db: DbSession = Depends(get_db)):
    who = principal(request)
    try:
        accounts.revoke_token(db, db.get(User, who.user_id), token_id, actor_of(who))
    except accounts.NotFound:
        raise HTTPException(404, "No such token.") from None
    return Response(status_code=204, headers=NO_STORE)


# --- the audit log and the photo check --------------------------------------------------


class AuditOut(BaseModel):
    id: int
    at: str | None
    actor_kind: str
    actor_label: str | None
    action: str
    target: str | None
    detail: dict | None
    address: str | None
    user_agent: str | None


@router.get("/audit", response_model=list[AuditOut])
@permission("admin")
def auth_audit(before: int | None = None, limit: int = 50, db: DbSession = Depends(get_db)):
    """Newest first; page with `before` (the last id seen), at most 200."""
    return [
        AuditOut(
            id=row.id,
            at=_iso(row.at),
            actor_kind=row.actor_kind,
            actor_label=row.actor_label,
            action=row.action,
            target=row.target,
            detail=row.detail,
            address=row.address,
            user_agent=row.user_agent,
        )
        for row in audit.page(db, before=before, limit=limit)
    ]


@router.get("/photo", status_code=204)
@permission("read")
async def auth_photo():
    """For nginx's `auth_request` before it serves anything under /photos/:
    204 for a session or a read or write token. Async (it waits on nothing),
    since a page of thumbnails asks it once per photo."""
    return Response(status_code=204, headers=NO_STORE)
