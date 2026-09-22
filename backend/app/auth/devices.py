"""The known-device cookie: proof that this browser signed in to this account
before, so the sign-in delays and the global limit don't apply to it and it
gets the reserved verification slot. It never skips the password check,
never lifts the setup throttle, and never authenticates a route.

Only the SHA-256 of its 32 random bytes is stored. Five failed sign-ins
presenting it delete it; a success replaces it.
"""

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.models.auth import KnownDevice

LIFETIME = timedelta(days=7)
MAX_FAILURES = 5


def issue(db: DbSession, user_id: int) -> str:
    secret = common.new_secret()
    at = common.now()
    db.add(
        KnownDevice(
            secret_hash=common.digest(secret),
            user_id=user_id,
            created_at=at,
            expires_at=at + LIFETIME,
            failures=0,
        )
    )
    db.flush()
    return secret


def find(db: DbSession, secret: str | None, user_id: int) -> KnownDevice | None:
    """This cookie's row, only if it is unexpired and for this account."""
    if not common.well_formed(secret):
        return None
    row = db.scalar(select(KnownDevice).where(KnownDevice.secret_hash == common.digest(secret)))
    if row is None or row.user_id != user_id or common.now() >= common.aware(row.expires_at):
        return None
    return row


def failed(db: DbSession, row: KnownDevice) -> None:
    row.failures = (row.failures or 0) + 1
    if row.failures >= MAX_FAILURES:
        db.delete(row)
    db.flush()


def forget(db: DbSession, row: KnownDevice) -> None:
    db.delete(row)
    db.flush()


def revoke_all(db: DbSession, user_id: int) -> int:
    result = db.execute(delete(KnownDevice).where(KnownDevice.user_id == user_id))
    return result.rowcount or 0
