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
    "comps_enabled": True,
    # Numista's sales records need its paid API plan; off until the user opts in.
    "numista_sales_enabled": False,
    "value_strategy": "latest",
    "preferred_source": None,
    "numista_refresh_days": None,  # None = off; else 7 | 14 | 30
    "pcgs_auto_refresh": False,
    "backup_schedule": None,  # None = off; else "daily" | "weekly"
    # Days scheduled and on-demand archives are kept (v0.30.1; 0 = forever).
    "backup_retention_days": 90,
    # Days an item stays in the trash before it's deleted for good; 0 = never.
    "trash_retention_days": 30,
    "backup_include_photos": True,
    # Alerts: a webhook URL (secret, because it often carries a token) and its format.
    "alert_webhook_url": "",
    "alert_webhook_format": "generic",
    # Uptime Kuma push URL, pinged hourly.
    "heartbeat_url": "",
    "metrics_enabled": False,
    # Spot-price thresholds: [{metal, direction, price, currency}], at most 12.
    "spot_alerts": [],
    # Written by the services, not through PUT /api/settings.
    "spot_alert_state": None,  # {threshold key: met bool}
    "backup_last_run": None,
    "refresh_last_run": None,  # {source: {at, updated, skipped, failed, ...}}
    "alert_state": None,  # {condition: {failing, since, message}}
    # The dashboard layout (services/dashboard.py). Written by its own
    # endpoints (routers/dashboard.py), never by PUT /api/settings.
    "dashboard_layout": None,
    # Secrets cleared because they were not encrypted with this deployment's
    # key (clear_unusable_secrets), until each is entered again.
    "secrets_cleared": [],
    # The public key of the backup key the owner said they saved ("I have
    # saved it" in Settings); a rotated key asks again.
    "backup_key_saved": None,
}

# Their names in messages, logs, and alerts; never their values.
SECRET_LABELS = {
    "numista_api_key": "Numista API key",
    "pcgs_api_token": "PCGS API token",
    "alert_webhook_url": "alert webhook",
    "heartbeat_url": "heartbeat URL",
}
SECRET_KEYS = set(SECRET_LABELS)


def get_setting(db: Session, key: str):
    """Read a setting. Secrets are decrypted transparently; one that isn't
    encrypted with this deployment's key reads as unset, never as its value
    (see clear_unusable_secrets)."""
    if key not in DEFAULTS:
        raise KeyError(key)
    row = db.get(AppSetting, key)
    if row is None or row.value is None:
        return DEFAULTS[key]
    if key not in SECRET_KEYS:
        return row.value
    return crypto.decrypt(str(row.value))


def clear_unusable_secrets(db: Session, undecryptable: bool = False) -> list[str]:
    """Clear every stored secret this deployment would refuse to use, and
    return their keys. Plain text is always cleared: Cabinet only ever writes
    encrypted values, so plain text came from somewhere else (an edited
    archive could plant a webhook address), and it is never encrypted in
    place. With `undecryptable` (after a restore), values encrypted under
    another key are cleared too. The keys are added to `secrets_cleared` for
    Settings to name until each is entered again. The caller commits."""
    cleared = []
    for key in sorted(SECRET_KEYS):
        row = db.get(AppSetting, key)
        stored = str(row.value or "") if row is not None else ""
        if not stored:
            continue
        usable = crypto.is_encrypted(stored) and (not undecryptable or crypto.decrypt(stored))
        if usable:
            continue
        row.value = ""
        cleared.append(key)
    if cleared:
        pending = [k for k in get_setting(db, "secrets_cleared") or [] if k in SECRET_KEYS]
        set_setting(db, "secrets_cleared", sorted(set(pending) | set(cleared)))
        logger.warning(
            "Cleared stored secrets not encrypted with this deployment's key: %s. "
            "Enter them again in Settings.",
            ", ".join(SECRET_LABELS[k] for k in cleared),
        )
    return cleared


def set_setting(db: Session, key: str, value) -> None:
    """Write a setting. Secrets are encrypted before they touch the database;
    an empty string clears the secret."""
    if key not in DEFAULTS:
        raise KeyError(key)
    if key in SECRET_KEYS:
        value = crypto.encrypt(str(value or ""))
        logger.info("Secret %r %s.", key, "cleared" if not value else "updated")
        # Entered again (or deliberately cleared): no longer worth a banner.
        pending = get_setting(db, "secrets_cleared") or []
        if key in pending:
            set_setting(db, "secrets_cleared", [k for k in pending if k != key])
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
