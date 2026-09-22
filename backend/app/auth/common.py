"""The clock and the secret helpers every credential service shares. Tests
freeze time by patching `now` and `monotonic` here, so callers always use
`common.now()`, never a name imported from this module."""

import hashlib
import re
import secrets
import time
from datetime import datetime, timezone

# 32 random bytes as base64url, without padding: 43 characters.
SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")


def now() -> datetime:
    return datetime.now(timezone.utc)


def monotonic() -> float:
    return time.monotonic()


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands timestamps back without a zone; they were written as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def well_formed(value: str | None) -> bool:
    return bool(value) and SECRET_RE.fullmatch(value) is not None


def digest(secret: str) -> bytes:
    """What is stored for a session, device, or token secret: its SHA-256.
    The secrets are 256 random bits, so they need no work factor."""
    return hashlib.sha256(secret.encode("ascii")).digest()


def clip(text: str | None, length: int) -> str | None:
    return None if text is None else text[:length]
