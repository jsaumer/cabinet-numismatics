"""Layer 2 of the gate: every API route declares who may call it.

    @router.get("/items")
    @permission("read")
    def list_items(...): ...

`@permission` goes directly above `def`, below the router decorator, so the
attribute lands on the function FastAPI registers. `require_permission`
runs for every matched API route (an app-level dependency) and reads the
declaration from `request.scope["endpoint"]`; a route that declares none is
refused (under pytest it raises, so the completeness test names it).

| Principal      | public | read | write | admin | metrics_ok routes |
| -------------- | ------ | ---- | ----- | ----- | ----------------- |
| admin session  | yes    | yes  | yes   | yes   | yes               |
| write token    | yes    | yes  | yes   | 403   | if read or write  |
| read token     | yes    | yes  | 403   | 403   | if read           |
| metrics token  | yes    | 403  | 403   | 403   | yes               |

`fresh` also needs the session's recent-password window; a token never has
one. Layer 1 (`gate.py`) has already refused anonymous callers everywhere
but the public routes.
"""

import logging
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

CLASSES = ("public", "read", "write", "admin")
ATTRIBUTE = "__cabinet_permission__"
REAUTH_DETAIL = "Confirm your password to continue."


@dataclass(frozen=True)
class Declared:
    cls: str
    metrics_ok: bool = False
    fresh: bool = False


@dataclass(frozen=True)
class Principal:
    """Who is calling, as layer 1 found them. `session_hash` is the SHA-256
    of the session cookie (for the restore grant); `confirmed` is whether the
    session is inside its recent-password window."""

    user_id: int
    username: str
    kind: str  # session | token
    scope: str | None = None  # a token's scope
    session_id: int | None = None
    token_id: int | None = None
    confirmed: bool = False
    session_hash: bytes | None = None
    address: str | None = None
    user_agent: str | None = None


def permission(cls: str, *, metrics_ok: bool = False, fresh: bool = False):
    if cls not in CLASSES:
        raise ValueError(f"unknown permission class {cls!r}")

    def mark(func):
        setattr(func, ATTRIBUTE, Declared(cls, metrics_ok, fresh))
        return func

    return mark


def declared(endpoint) -> Declared | None:
    return getattr(endpoint, ATTRIBUTE, None)


def principal(request: Request) -> Principal | None:
    return request.scope.get("state", {}).get("principal")


class ReauthRequired(HTTPException):
    """403 with `reauth_required: true` at the top level of the body (a
    handler in main.py renders it), so the frontend asks for the password
    and retries once."""

    def __init__(self):
        super().__init__(403, detail=REAUTH_DETAIL)


def reauth_body() -> dict:
    return {"detail": REAUTH_DETAIL, "reauth_required": True}


def check(who: Principal | None, cls: str, *, metrics_ok: bool = False, fresh: bool = False):
    """Raise 401 or 403 unless `who` may call a route of this class."""
    if cls == "public":
        return
    if who is None:
        raise HTTPException(401, detail="Sign in to continue.")
    if who.kind == "session":
        if fresh and not who.confirmed:
            raise ReauthRequired()
        return
    # A token: never admin (bar the metrics route), never fresh.
    scope = who.scope
    allowed = (
        (cls == "read" and scope in ("read", "write"))
        or (cls == "write" and scope == "write")
        or (metrics_ok and scope == "metrics")
    )
    if not allowed or fresh:
        raise HTTPException(403, detail="This API token's scope doesn't allow that.")


def require(request: Request, cls: str, *, fresh: bool = False) -> Principal | None:
    """For a handler whose permission depends on its arguments (deleting an
    item for good)."""
    who = principal(request)
    check(who, cls, fresh=fresh)
    return who


def require_permission(request: Request) -> None:
    """The app-level dependency: every API route passes through here."""
    endpoint = request.scope.get("endpoint")
    found = declared(endpoint)
    if found is None:
        name = getattr(endpoint, "__qualname__", repr(endpoint))
        if os.environ.get("PYTEST_CURRENT_TEST"):
            raise RuntimeError(f"route {name} declares no @permission")
        logger.error("Refused a call to %s: the route declares no permission", name)
        raise HTTPException(403, detail="Forbidden.")
    check(principal(request), found.cls, metrics_ok=found.metrics_ok, fresh=found.fresh)
