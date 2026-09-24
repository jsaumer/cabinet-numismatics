"""The new-browser alert's rows (`known_browsers`, v0.33.0, R2-04). The
cookie only decides whether a sign-in alerts as a new browser: it is never
read by `devices`, `throttle`, or `_check_password`, and lifts nothing.
Stage 1 has only what a password change, a reset, and sign-out-everywhere
need (delete a user's rows) and the hourly prune.
"""

from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.models.auth import KnownBrowser

LIFETIME_DAYS = 90


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
