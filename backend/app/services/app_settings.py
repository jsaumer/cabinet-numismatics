"""DB-backed application settings with defaults and env fallbacks.

Secrets (API keys/tokens) are encrypted at rest (see `crypto.py`) and are
write-only through the API: reads expose only whether a value is set and a
last-4 hint, never the value itself.
"""

import logging

from sqlalchemy.orm import Session

from app.config import get_settings as env_settings
from app.models import AppSetting
from app.services import crypto

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "display_currency": "USD",
    # None → fall back to the REESTIMATE_DAYS env var.
    "reestimate_days": None,
    "melt_enabled": True,
    "numista_enabled": False,
    "numista_api_key": "",
    "pcgs_enabled": False,
    "pcgs_api_token": "",
}

SECRET_KEYS = {"numista_api_key", "pcgs_api_token"}


def get_setting(db: Session, key: str):
    """Read a setting. Secrets are decrypted transparently; a value stored
    before encryption existed is re-encrypted in place on first read."""
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(AppSetting, key)
    if row is None or row.value is None:
        return DEFAULTS[key]
    if key not in SECRET_KEYS:
        return row.value

    stored = str(row.value)
    if stored and not crypto.is_encrypted(stored):
        row.value = crypto.encrypt(stored)  # self-heal legacy plaintext
        db.flush()
        logger.info("Re-encrypted legacy plaintext secret %r at rest.", key)
        return stored
    return crypto.decrypt(stored)


def set_setting(db: Session, key: str, value) -> None:
    """Write a setting. Secrets are encrypted before they touch the database;
    an empty string clears the secret."""
    if key not in DEFAULTS:
        raise KeyError(key)
    if key in SECRET_KEYS:
        value = crypto.encrypt(str(value or ""))
        logger.info("Secret %r %s.", key, "cleared" if not value else "updated")
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def display_currency(db: Session) -> str:
    return str(get_setting(db, "display_currency")).upper()


def effective_reestimate_days(db: Session) -> int:
    override = get_setting(db, "reestimate_days")
    return int(override) if override is not None else env_settings().reestimate_days


def secret_hint(value: str) -> str | None:
    """A masked hint for a stored secret (last 4 characters), or None if unset."""
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 4 else "…"
