"""Layer 1 of the gate: plain ASGI, before routing, deny by default.

Reads only the method, the raw path, and headers, never the body. In order:

1. A raw path holding `%` is 400: a percent-encoded path can route to a
   handler whose bytes don't match anything below.
2. During maintenance only two requests get this far (the maintenance
   middleware runs first): health passes with no lookup, and the restore
   status passes only for the session holding the restore grant. No database.
3. While sharing is on, a `GET` or `HEAD` under an ANONYMOUS_PREFIXES path
   (the share view, v0.32.0) passes with no credential looked up at all: a
   cookie never touches `last_seen_at`, a token is never validated, and no
   Sec-Fetch-Site check applies (a share link is opened from anywhere).
   Layer 2 then finds the `share` class on every route there. While it is
   off there is no such rule: the request goes on as below like any other
   (anonymous is 401), with no database read and no throttle work, since
   the switch is held in memory (`share.enabled`). Other methods always go
   on as below.
4. `GET /api/auth/oidc/callback` (NO_LOOKUP, v0.33.0, CR-01) passes with no
   credential looked up: a provider's redirect back is a cross-site
   top-level navigation that a Lax session cookie rides along on, which
   step 8 would refuse before routing. No session is read or touched and
   no CSRF decision is made; the handler binds a link or confirm to the
   session that started it through the flow cookie, whose `state` is the
   route's CSRF protection.
5. The credential: `Authorization: Bearer cabinet_...` is a token (an invalid
   one is 401, never a fall back to the cookie); any other Authorization is
   ignored; otherwise the session cookie.
6. Anonymous callers reach only the ANONYMOUS pairs; everything else,
   unknown paths included, is 401. A read or metrics token is refused on
   any unsafe method (every such route is write or admin) before a body is
   read.
7. `/api/openapi.json` (the one framework route, never seen by layer 2): a
   session only, a token 403.
8. CSRF for a cookie request: `Sec-Fetch-Site: same-origin`, or no such
   header and an Origin (or Referer's origin) in PUBLIC_ORIGINS.
9. The principal goes on `scope["state"]["principal"]` for layer 2.
10. On the way out, a response with no Cache-Control gets `private, no-store`.

Database work runs in a worker thread, never on the event loop.
"""

import logging
import re
from urllib.parse import urlsplit

import anyio
from starlette.responses import JSONResponse

from app.auth import common, sessions, tokens
from app.auth.permissions import Principal
from app.config import get_settings, normalize_origin, public_origins
from app.services import maintenance

logger = logging.getLogger(__name__)

ANONYMOUS = {
    (b"GET", b"/api/health"),
    (b"GET", b"/api/auth/state"),
    (b"POST", b"/api/auth/setup"),
    (b"POST", b"/api/auth/login"),
    (b"GET", b"/api/auth/oidc/start"),  # v0.33.0; a session is looked up if sent
    (b"GET", b"/api/auth/oidc/callback"),
}
# Passed with no credential lookup at all (step 4).
NO_LOOKUP = {(b"GET", b"/api/auth/oidc/callback")}
# Anonymous GET and HEAD by prefix: the share view, whose token is in the
# path. Every route under it declares the `share` class.
ANONYMOUS_PREFIXES = (b"/api/share/",)
SMALL_BODY = {(b"POST", b"/api/auth/setup"), (b"POST", b"/api/auth/login")}
SMALL_BODY_LIMIT = 8 * 1024
OPENAPI = b"/api/openapi.json"
RESTORE_STATUS = (b"GET", b"/api/restore/status")
PHOTO_CHECK = (b"GET", b"/api/auth/photo")
DOCUMENT_FILE = re.compile(rb"/api/documents/[0-9A-Fa-f-]{1,64}/file")
CROSS_SITE = "Cross-site request refused."
SCOPE_REFUSED = "This API token's scope doesn't allow that."
SAFE_METHODS = {b"GET", b"HEAD", b"OPTIONS"}


def _json(status: int, detail, headers: dict | None = None) -> JSONResponse:
    base = {"Cache-Control": "no-store"}
    base.update(headers or {})
    return JSONResponse({"detail": detail}, status_code=status, headers=base)


def _headers(scope) -> dict[bytes, bytes]:
    found: dict[bytes, bytes] = {}
    for name, value in scope.get("headers", []):
        found.setdefault(name.lower(), value)
    return found


def _cookie(headers: dict[bytes, bytes], name: str) -> str | None:
    raw = headers.get(b"cookie")
    if not raw:
        return None
    for part in raw.decode("latin-1").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value.strip()
    return None


def _db_provider(scope):
    from app.db import get_db

    app = scope.get("app")
    overrides = getattr(app, "dependency_overrides", {}) if app is not None else {}
    return overrides.get(get_db, get_db)


def _lookup(provider, bearer: str | None, cookie: str | None, meta: dict, csrf_ok: bool):
    """In a worker thread: the principal for this credential, "invalid" for
    a bad Cabinet token, "cross-site" for a session request CSRF refuses
    (decided before `last_seen_at` moves, so a refused request never keeps a
    session alive), or None for no credential."""
    generator = provider()
    db = next(generator)
    try:
        if bearer is not None:
            try:
                row, user = tokens.authenticate(db, bearer)
            except tokens.InvalidToken:
                return "invalid"
            if tokens.touch(row):
                db.commit()
            return Principal(
                user_id=user.id,
                username=user.username,
                kind="token",
                scope=row.scope,
                token_id=row.id,
                **meta,
            )
        found = sessions.find(db, cookie)
        if found is None:
            return None
        row, user = found
        if not csrf_ok:
            return "cross-site"
        confirmed = sessions.confirmed(row)
        if sessions.touch(row):
            db.commit()
        return Principal(
            user_id=user.id,
            username=user.username,
            kind="session",
            session_id=row.id,
            confirmed=confirmed,
            session_hash=common.digest(cookie),
            **meta,
        )
    finally:
        generator.close()


def _load_sharing(provider) -> bool:
    """In a worker thread, once a process (or after a restore): the switch
    from the database. A failure reads as off and isn't remembered."""
    from app.services import share

    generator = provider()
    db = next(generator)
    try:
        return share.load(db)
    except Exception:
        logger.exception("Could not read whether sharing is on; treating it as off")
        return False
    finally:
        generator.close()


async def _sharing_on(scope) -> bool:
    from app.services import share

    known = share.cached()
    if known is not None:
        return known
    return await anyio.to_thread.run_sync(_load_sharing, _db_provider(scope))


def _origin_of(value: bytes | None) -> str | None:
    if not value:
        return None
    text = value.decode("latin-1").strip()
    if text == "null":
        return None
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return None
    return normalize_origin(f"{parts.scheme}://{parts.netloc}")


def _site(headers: dict[bytes, bytes]) -> str | None:
    return headers.get(b"sec-fetch-site", b"").decode("latin-1").strip().lower() or None


def csrf_allows(method: bytes, path: bytes, headers: dict[bytes, bytes]) -> bool:
    """For a cookie request (section 4 of SPEC_0300)."""
    site = _site(headers)
    if (method, path) == PHOTO_CHECK:
        return site != "cross-site"  # no side effects; "open in new tab" sends none
    if site == "same-origin":
        return True
    if site == "none":
        return method == b"GET" and (path == OPENAPI or DOCUMENT_FILE.fullmatch(path) is not None)
    if site is not None:
        return False  # cross-site, same-site, anything else
    origin = _origin_of(headers.get(b"origin")) or _origin_of(headers.get(b"referer"))
    return origin is not None and origin in public_origins(get_settings())


class AuthGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope["method"].encode("latin-1")
        raw = scope.get("raw_path") or scope["path"].encode("utf-8")
        path = raw.split(b"?", 1)[0]
        send = _no_store_by_default(send)

        if b"%" in path:
            await _json(400, "Encoded paths are not accepted.")(scope, receive, send)
            return
        headers = _headers(scope)
        if (method, path) in SMALL_BODY:
            length = headers.get(b"content-length", b"0")
            if not length.isdigit() or int(length) > SMALL_BODY_LIMIT:
                await _json(413, "Too large.")(scope, receive, send)
                return

        session_name, _ = sessions.cookie_names()
        cookie = _cookie(headers, session_name)

        if maintenance.active():
            who = None
            if (method, path) == RESTORE_STATUS:
                from app.services import restore

                who = restore.granted(common.digest(cookie) if common.well_formed(cookie) else b"")
                if who is None:
                    await _json(401, "Sign in to continue.")(scope, receive, send)
                    return
            elif (method, path) != (b"GET", b"/api/health"):
                await _json(503, maintenance.DETAIL)(scope, receive, send)
                return
            scope.setdefault("state", {})["principal"] = who
            await self.app(scope, receive, send)
            return

        if (
            method in (b"GET", b"HEAD")
            and path.startswith(ANONYMOUS_PREFIXES)
            and await _sharing_on(scope)
        ):
            scope.setdefault("state", {})["principal"] = None
            await self.app(scope, receive, send)
            return

        if (method, path) in NO_LOOKUP:
            scope.setdefault("state", {})["principal"] = None
            await self.app(scope, receive, send)
            return

        authorization = headers.get(b"authorization")
        bearer = tokens.bearer(authorization.decode("latin-1") if authorization else None)
        meta = {
            "address": headers.get(b"x-real-ip", b"").decode("latin-1")[:45] or None,
            "user_agent": headers.get(b"user-agent", b"").decode("latin-1")[:256] or None,
        }
        who = None
        if bearer is not None or common.well_formed(cookie):
            csrf_ok = csrf_allows(method, path, headers)
            who = await anyio.to_thread.run_sync(
                _lookup, _db_provider(scope), bearer, cookie, meta, csrf_ok
            )
            if who == "invalid":
                await _json(401, "This API token is not valid.")(scope, receive, send)
                return
            if who == "cross-site":
                await _json(403, CROSS_SITE)(scope, receive, send)
                return

        if who is None:
            if (method, path) not in ANONYMOUS:
                await _json(401, "Sign in to continue.")(scope, receive, send)
                return
            # Sign-in and setup are anonymous, but never from another site: a
            # hostile page can't make a visitor's browser post guesses.
            if (method, path) in SMALL_BODY and _site(headers) in ("cross-site", "same-site"):
                await _json(403, CROSS_SITE)(scope, receive, send)
                return
        elif who.kind == "token":
            if path == OPENAPI:
                await _json(403, "The API schema is for a signed-in session.")(scope, receive, send)
                return
            # Every unsafe-method route is write or admin (the appendix of
            # SPEC_0300), so a read or metrics token can never use one. Refused
            # here, before FastAPI reads a body: a low-scope token could
            # otherwise make the backend spool a multipart upload (nginx allows
            # 1 GB on imports) only to be told 403 by layer 2 afterwards.
            if (
                who.scope != "write"
                and method not in SAFE_METHODS
                and (method, path) not in ANONYMOUS  # public routes stay public
            ):
                await _json(403, SCOPE_REFUSED)(scope, receive, send)
                return

        scope.setdefault("state", {})["principal"] = who
        await self.app(scope, receive, send)


def _no_store_by_default(send):
    async def wrapped(message):
        if message["type"] == "http.response.start":
            names = {name.lower() for name, _ in message.get("headers", [])}
            if b"cache-control" not in names:
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"private, no-store")
                ]
        await send(message)

    return wrapped
