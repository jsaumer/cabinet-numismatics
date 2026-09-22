"""Database-backed sessions and the two sign-in cookies.

A session secret is 32 random bytes (base64url) made here, never taken from
a caller, and stored only as its SHA-256. A session is valid while it is not
revoked, is less than 7 days old, was used in the past day, and its account
is active. The recent-password window (`confirmed_until`, 5 minutes) belongs
to one session and is never granted to a token.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.config import get_settings
from app.models.auth import Session, User

LIFETIME = timedelta(days=7)
IDLE = timedelta(days=1)
CONFIRM_WINDOW = timedelta(minutes=5)
TOUCH_EVERY = timedelta(minutes=1)
DEVICE_MAX_AGE = 7 * 24 * 3600


def create(
    db: DbSession,
    user: User,
    *,
    address: str | None = None,
    user_agent: str | None = None,
    method: str = "password",
) -> tuple[str, Session]:
    secret = common.new_secret()
    at = common.now()
    row = Session(
        secret_hash=common.digest(secret),
        user_id=user.id,
        auth_method=method,
        created_at=at,
        last_seen_at=at,
        expires_at=at + LIFETIME,
        user_agent=common.clip(user_agent, 256),
        address=common.clip(address, 45),
    )
    db.add(row)
    db.flush()
    return secret, row


def valid(row: Session, user: User | None, at=None) -> bool:
    at = at or common.now()
    return (
        row.revoked_at is None
        and user is not None
        and user.is_active
        and at < common.aware(row.expires_at)
        and at < common.aware(row.last_seen_at) + IDLE
    )


def find(db: DbSession, secret: str | None) -> tuple[Session, User] | None:
    """The live session this cookie value names, with its account."""
    if not common.well_formed(secret):
        return None
    found = db.execute(
        select(Session, User)
        .join(User, User.id == Session.user_id)
        .where(Session.secret_hash == common.digest(secret))
    ).first()
    if found is None or not valid(found[0], found[1]):
        return None
    return found[0], found[1]


def touch(row: Session) -> bool:
    """Note the session's use, at most once a minute. True when it wrote."""
    at = common.now()
    if at - common.aware(row.last_seen_at) < TOUCH_EVERY:
        return False
    row.last_seen_at = at
    return True


def confirm(row: Session) -> None:
    row.confirmed_until = common.now() + CONFIRM_WINDOW


def confirmed(row: Session) -> bool:
    until = common.aware(row.confirmed_until)
    return until is not None and common.now() < until


def revoke(row: Session) -> None:
    if row.revoked_at is None:
        row.revoked_at = common.now()
    row.confirmed_until = None


def revoke_all(db: DbSession, user_id: int) -> int:
    result = db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=common.now(), confirmed_until=None)
    )
    return result.rowcount or 0


def live(db: DbSession, user_id: int) -> list[Session]:
    user = db.get(User, user_id)
    rows = db.scalars(
        select(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .order_by(Session.last_seen_at.desc(), Session.id.desc())
    ).all()
    at = common.now()
    return [row for row in rows if valid(row, user, at)]


# --- cookies --------------------------------------------------------------------


def cookie_names() -> tuple[str, str]:
    """(session, device). The `__Host-` prefix needs Secure, so a plain-http
    local stack (AUTH_INSECURE_HTTP) uses the bare names."""
    if get_settings().auth_insecure_http:
        return "cabinet_session", "cabinet_device"
    return "__Host-cabinet_session", "__Host-cabinet_device"


def set_cookies(response, session_secret: str | None, device_secret: str | None) -> None:
    session_name, device_name = cookie_names()
    secure = not get_settings().auth_insecure_http
    if session_secret is not None:
        # No Max-Age: the server decides when a session ends.
        response.set_cookie(
            session_name, session_secret, path="/", secure=secure, httponly=True, samesite="lax"
        )
    if device_secret is not None:
        response.set_cookie(
            device_name,
            device_secret,
            max_age=DEVICE_MAX_AGE,
            path="/",
            secure=secure,
            httponly=True,
            samesite="strict",
        )


def clear_cookies(response) -> None:
    session_name, device_name = cookie_names()
    secure = not get_settings().auth_insecure_http
    response.delete_cookie(session_name, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(device_name, path="/", secure=secure, httponly=True, samesite="strict")
