"""Sign-in and account alerts through the existing webhook: each is one
`alerts.event`, sent only when a webhook is saved, carrying no collection
data. Repeated failed sign-ins, and repeated rejected single sign-ons
(v0.33.0), each alert when FAILURE_BURST happen within 15 minutes, at most
once an hour."""

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
    "backup_deleted": "Cabinet backup deleted",
    "share_link_created": "Cabinet share link created",
    "share_link_regenerated": "Cabinet share link regenerated",
    "share_link_revoked": "Cabinet share link revoked",
    "share_link_changed": "Cabinet share link now shows more",
    "identity_linked": "Cabinet account linked to a sign-in provider",
    "identity_unlinked": "Cabinet account unlinked from a sign-in provider",
    "sso_configured": "Cabinet single sign-on settings changed",
    "sso_disabled": "Cabinet single sign-on switched off from the container",
    "password_sign_in": "Password sign-in to Cabinet",
    "sso_sign_in_failures": "Repeated rejected single sign-ons to Cabinet",
}
FAILURE_BURST = 20
FAILURE_WINDOW = 15 * 60
FAILURE_ALERT_EVERY = 60 * 60

_lock = threading.Lock()
# Per burst kind: the times inside the window, and when it last alerted.
_bursts: dict[str, deque[float]] = {}
_last_alert: dict[str, float] = {}


def send(db: DbSession, key: str, message: str) -> None:
    alerts.event(db, key, TITLES[key], message)


def _burst(kind: str) -> int | None:
    """Count one; the count when this one reaches the threshold and no
    alert of this kind went out in the past hour, else None."""
    t = common.monotonic()
    with _lock:
        times = _bursts.setdefault(kind, deque())
        times.append(t)
        while times and t - times[0] >= FAILURE_WINDOW:
            times.popleft()
        if len(times) < FAILURE_BURST:
            return None
        last = _last_alert.get(kind)
        if last is not None and t - last < FAILURE_ALERT_EVERY:
            return None
        _last_alert[kind] = t
        return len(times)


def failed_sign_in(db: DbSession) -> bool:
    """Count one failure; alert when the burst threshold is reached. True
    when this call sent the alert."""
    count = _burst("sign_in_failures")
    if count is None:
        return False
    send(
        db,
        "sign_in_failures",
        f"{count} failed sign-ins in the past 15 minutes. "
        "Check the audit log in Settings, Account.",
    )
    return True


def rejected_sso(db: DbSession) -> bool:
    """The same for single sign-ons refused (an unlinked identity, a bad
    token), counted apart from password failures."""
    count = _burst("sso_sign_in_failures")
    if count is None:
        return False
    send(
        db,
        "sso_sign_in_failures",
        f"{count} single sign-ons were refused in the past 15 minutes. "
        "Check the audit log in Settings, Account.",
    )
    return True


def reset_memory() -> None:
    with _lock:
        _bursts.clear()
        _last_alert.clear()
