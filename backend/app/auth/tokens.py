"""API tokens: `cabinet_<public_id>_<secret>`, one scope each.

`public_id` is 10 lowercase base32 characters and finds the row; the secret
is 43 base64url characters (256 bits), stored only as its SHA-256 and
compared with `hmac.compare_digest`. Not Argon2: a work factor protects
guessable secrets, and a 256-bit random one can't be guessed, so hashing it
slowly would only make every API call slower.

`read` and `write` tokens last one day or seven, never longer; a `metrics`
token, which sees only totals, may never expire. The secret is shown once,
in the answer that creates it.
"""

import base64
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.models.auth import ApiToken, User

PREFIX = "cabinet_"
TOKEN_RE = re.compile(PREFIX + r"([a-z2-7]{10})_([A-Za-z0-9_-]{43})")
SCOPES = ("read", "write", "metrics")
LIFETIMES = (1, 7)  # days
MAX_LIVE = 50
TOUCH_EVERY = timedelta(minutes=1)


class TokenRejected(ValueError):
    """A creation request that breaks the rules; the message says which."""


class InvalidToken(Exception):
    """A Cabinet token that is malformed, unknown, revoked, expired, or whose
    account is inactive: 401, never a fall back to the cookie."""


def _public_id() -> str:
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii").lower()[:10]


def expired(row: ApiToken, at=None) -> bool:
    at = at or common.now()
    expires = common.aware(row.expires_at)
    return expires is not None and at >= expires


def is_live(row: ApiToken, at=None) -> bool:
    return row.revoked_at is None and not expired(row, at)


def live(db: DbSession, user_id: int) -> list[ApiToken]:
    rows = db.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    ).all()
    at = common.now()
    return [row for row in rows if not expired(row, at)]


def create(
    db: DbSession, user: User, name: str, scope: str, days: int | None
) -> tuple[str, ApiToken]:
    name = (name or "").strip()
    if not 1 <= len(name) <= 100:
        raise TokenRejected("A token's name is 1 to 100 characters.")
    if scope not in SCOPES:
        raise TokenRejected("A token's scope is read, write, or metrics.")
    if days is None and scope != "metrics":
        raise TokenRejected("A read or write token lasts at most 7 days.")
    if days is not None and days not in LIFETIMES:
        raise TokenRejected("A token lasts 1 day or 7 days (a metrics token may never expire).")
    current = live(db, user.id)
    if len(current) >= MAX_LIVE:
        raise TokenRejected(f"At most {MAX_LIVE} tokens can be live at once; revoke one first.")
    if any(row.name == name for row in current):
        raise TokenRejected("A live token already has that name.")
    public_id = _public_id()
    while db.scalar(select(func.count()).where(ApiToken.public_id == public_id)):
        public_id = _public_id()  # 50 bits: a collision is theoretical
    secret = common.new_secret()
    at = common.now()
    row = ApiToken(
        public_id=public_id,
        secret_hash=common.digest(secret),
        user_id=user.id,
        name=name,
        scope=scope,
        created_at=at,
        expires_at=None if days is None else at + timedelta(days=days),
    )
    db.add(row)
    db.flush()
    return f"{PREFIX}{public_id}_{secret}", row


def bearer(header: str | None) -> str | None:
    """The credential when `Authorization` carries a Cabinet token; None for
    anything else (no header, another scheme, someone else's token), which
    the gate treats as a cookie request."""
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    credential = parts[1].strip()
    return credential if credential.startswith(PREFIX) else None


def authenticate(db: DbSession, credential: str) -> tuple[ApiToken, User]:
    match = TOKEN_RE.fullmatch(credential or "")
    if match is None:
        raise InvalidToken()
    found = db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .where(ApiToken.public_id == match.group(1))
    ).first()
    if found is None:
        raise InvalidToken()
    row, user = found
    if not hmac.compare_digest(row.secret_hash, common.digest(match.group(2))):
        raise InvalidToken()
    if not is_live(row) or not user.is_active:
        raise InvalidToken()
    return row, user


def touch(row: ApiToken) -> bool:
    at = common.now()
    last = common.aware(row.last_used_at)
    if last is not None and at - last < TOUCH_EVERY:
        return False
    row.last_used_at = at
    return True


def revoke(row: ApiToken) -> None:
    if row.revoked_at is None:
        row.revoked_at = common.now()


def revoke_all(db: DbSession, user_id: int) -> list[ApiToken]:
    """Every token of every scope; returns the ones this ended."""
    ended = live(db, user_id)
    db.execute(
        update(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
        .values(revoked_at=common.now())
    )
    return ended
