"""Sign-in and account alerts through the existing webhook: each is one
`alerts.event`, sent only when a webhook is saved, carrying no collection
data. Repeated failed sign-ins alert when FAILURE_BURST happen within 15
minutes, at most once an hour."""

import threading
from collections import deque

from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.services import alerts

TITLES = {
    "sign_in_new_device": "New sign-in to Cabinet",
    "sign_in_failures": "Repeated failed sign-ins to Cabinet",
    "password_changed": "Cabinet password changed",
    "password_reset": "Cabinet password reset from the container",
    "token_created": "Cabinet API token created",
    "backup_downloaded": "Cabinet backup downloaded",
    "export_downloaded": "Cabinet collection exported",
    "restore_started": "Cabinet restore started",
    "restore_finished": "Cabinet restore finished",
    "secrets_cleared": "Cabinet cleared stored secrets",
}
FAILURE_BURST = 20
FAILURE_WINDOW = 15 * 60
FAILURE_ALERT_EVERY = 60 * 60

_lock = threading.Lock()
_failures: deque[float] = deque()
_last_failure_alert: float | None = None


def send(db: DbSession, key: str, message: str) -> None:
    alerts.event(db, key, TITLES[key], message)


def failed_sign_in(db: DbSession) -> bool:
    """Count one failure; alert when the burst threshold is reached. True
    when this call sent the alert."""
    global _last_failure_alert
    t = common.monotonic()
    with _lock:
        _failures.append(t)
        while _failures and t - _failures[0] >= FAILURE_WINDOW:
            _failures.popleft()
        if len(_failures) < FAILURE_BURST:
            return False
        if _last_failure_alert is not None and t - _last_failure_alert < FAILURE_ALERT_EVERY:
            return False
        _last_failure_alert = t
        count = len(_failures)
    send(
        db,
        "sign_in_failures",
        f"{count} failed sign-ins in the past 15 minutes. "
        "Check the audit log in Settings, Account.",
    )
    return True


def reset_memory() -> None:
    global _last_failure_alert
    with _lock:
        _failures.clear()
        _last_failure_alert = None
