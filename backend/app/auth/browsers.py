"""The new-browser alert's rows (`known_browsers`, v0.33.0, R2-04). The
cookie only decides whether a sign-in alerts as a new browser: it is never
read by `devices`, `throttle`, or `_check_password`, and lifts nothing.

A browser secret is 32 random bytes, stored as its SHA-256, for 90 days. It
is issued on every successful sign-in of any method when the browser
brought no valid one.
"""

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.models.auth import KnownBrowser

LIFETIME_DAYS = 90
LIFETIME = timedelta(days=LIFETIME_DAYS)


def issue(db: DbSession, user_id: int) -> str:
    """A new browser secret for this account; the caller commits and sets
    the cookie."""
    secret = common.new_secret()
    at = common.now()
    db.add(
        KnownBrowser(
            user_id=user_id,
            secret_hash=common.digest(secret),
            created_at=at,
            last_seen_at=at,
            expires_at=at + LIFETIME,
        )
    )
    db.flush()
    return secret


def find(db: DbSession, secret: str | None, user_id: int) -> KnownBrowser | None:
    """This cookie's row, only if it is unexpired and for this account; its
    `last_seen_at` is touched (the caller commits)."""
    if not common.well_formed(secret):
        return None
    row = db.scalar(select(KnownBrowser).where(KnownBrowser.secret_hash == common.digest(secret)))
    if row is None or row.user_id != user_id or common.now() >= common.aware(row.expires_at):
        return None
    row.last_seen_at = common.now()
    return row


def revoke_all(db: DbSession, user_id: int) -> int:
    """Forget every browser of this account, so the next sign-in from
    anywhere alerts."""
    result = db.execute(delete(KnownBrowser).where(KnownBrowser.user_id == user_id))
    return result.rowcount or 0


def prune(db: DbSession) -> None:
    db.execute(
        delete(KnownBrowser).where(KnownBrowser.expires_at < common.now()),
        execution_options={"synchronize_session": "fetch"},
    )
