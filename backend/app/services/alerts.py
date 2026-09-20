"""Alerts: a webhook when something starts failing and again when it
recovers, and an optional Uptime Kuma push heartbeat.

Each watched condition (a failing backup, a rejected key, an exhausted quota,
a scheduled refresh with failures) keeps its state in the `alert_state`
setting, so an alert fires on the change only: a rejected key doesn't
re-alert every refresh. Webhook delivery runs on a background thread so it
never slows the request or task that noticed the problem; the last delivery
and heartbeat outcomes are kept in memory for Settings and /api/metrics.
"""

import logging
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy.orm import Session

from app.services import app_settings as store

logger = logging.getLogger(__name__)

FORMATS = ("generic", "ntfy", "discord", "slack", "gotify")

# Every condition an alert can be raised for, with its label.
CONDITIONS = {
    "backup": "Backups",
    "numista_key": "Numista API key",
    "numista_quota": "Numista request quota",
    "pcgs_key": "PCGS API token",
    "pcgs_quota": "PCGS request quota",
    "refresh_melt": "Scheduled melt refresh",
    "refresh_numista": "Scheduled Numista refresh",
    "refresh_pcgs": "Scheduled PCGS refresh",
}

TIMEOUT = 10.0

# In-memory outcomes of the last webhook delivery and heartbeat ping.
_status: dict[str, dict | None] = {"delivery": None, "heartbeat": None}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_hint(url: str) -> str | None:
    """Where a stored URL points, without the path or query that may carry a
    token (ntfy topics, Discord and Kuma tokens, Gotify's ?token=)."""
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/…"


def valid_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def states(db: Session) -> dict:
    return dict(store.get_setting(db, "alert_state") or {})


def last_delivery() -> dict | None:
    return _status["delivery"]


def last_heartbeat() -> dict | None:
    return _status["heartbeat"]


def failing(db: Session) -> dict:
    """The conditions failing right now, keyed like CONDITIONS."""
    return {key: s for key, s in states(db).items() if s.get("failing")}


def fail(db: Session, key: str, message: str) -> None:
    """Mark `key` failing. Alerts only when it wasn't already; a repeat just
    refreshes the message. Commits."""
    state = states(db)
    current = state.get(key) or {}
    changed = not current.get("failing")
    if not changed and current.get("message") == message:
        return
    state[key] = {
        "failing": True,
        "since": current["since"] if not changed else _now(),
        "message": message[:500],
    }
    store.set_setting(db, "alert_state", state)
    db.commit()
    if changed:
        logger.warning("Alert: %s failing: %s", CONDITIONS[key], message)
        _notify(db, key, "failing", message)


def recover(db: Session, key: str) -> None:
    """Mark `key` healthy, alerting only if it was failing. Commits then."""
    state = states(db)
    current = state.get(key)
    if not current or not current.get("failing"):
        return
    state[key] = {"failing": False, "since": _now(), "message": current.get("message")}
    store.set_setting(db, "alert_state", state)
    db.commit()
    logger.info("Alert: %s recovered", CONDITIONS[key])
    _notify(db, key, "recovered", f"Working again (was: {current.get('message')})")


def source_failed(db: Session, source: str, kind: str, message: str) -> None:
    """A price source refused its key (`kind` "key") or quota ("quota")."""
    key = f"{source}_{kind}"
    if key in CONDITIONS:
        fail(db, key, message)


def source_ok(db: Session, source: str) -> None:
    """A price source answered, so its key and quota are fine again."""
    for kind in ("key", "quota"):
        if f"{source}_{kind}" in CONDITIONS:
            recover(db, f"{source}_{kind}")


def _title(key: str, status: str) -> str:
    label = CONDITIONS.get(key, key)
    if status == "test":
        return "Cabinet: test alert"
    return f"Cabinet: {label} {'failing' if status == 'failing' else 'recovered'}"


def build_request(fmt: str, key: str, status: str, message: str) -> dict:
    """The keyword arguments for httpx.post for one alert in `fmt`."""
    title = _title(key, status)
    if fmt == "ntfy":
        # Plain text to the topic URL; titles are ASCII so they fit a header.
        return {
            "content": message.encode(),
            "headers": {
                "Title": title,
                "Priority": {"failing": "high", "recovered": "default"}.get(status, "low"),
                "Tags": {"failing": "warning", "recovered": "white_check_mark"}.get(
                    status, "test_tube"
                ),
            },
        }
    if fmt == "discord":
        return {"json": {"username": "Cabinet", "content": f"**{title}**\n{message}"[:2000]}}
    if fmt == "slack":
        return {"json": {"text": f"*{title}*\n{message}"}}
    if fmt == "gotify":
        return {
            "json": {
                "title": title,
                "message": message,
                "priority": {"failing": 8, "recovered": 4}.get(status, 2),
            }
        }
    return {
        "json": {
            "app": "cabinet",
            "alert": key,
            "label": CONDITIONS.get(key, "Test"),
            "status": status,
            "title": title,
            "message": message,
            "at": _now(),
        }
    }


def _describe(exc: Exception, url: str) -> str:
    """An error message that never repeats the URL (it may hold a token)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return text.replace(url, url_hint(url) or "")


def deliver(url: str, fmt: str, key: str, status: str, message: str) -> dict:
    """POST one alert. Returns and records {at, ok, detail}."""
    try:
        resp = httpx.post(url, timeout=TIMEOUT, **build_request(fmt, key, status, message))
        resp.raise_for_status()
        outcome = {"at": _now(), "ok": True, "detail": f"{status} alert delivered"}
    except httpx.HTTPError as exc:
        outcome = {"at": _now(), "ok": False, "detail": _describe(exc, url)}
        logger.error("Alert delivery failed: %s", outcome["detail"])
    with _lock:
        _status["delivery"] = outcome
    return outcome


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _notify(db: Session, key: str, status: str, message: str) -> None:
    url = str(store.get_setting(db, "alert_webhook_url") or "")
    if not url:
        return
    fmt = str(store.get_setting(db, "alert_webhook_format"))
    _spawn(lambda: deliver(url, fmt, key, status, message))


def send_test(db: Session) -> dict:
    url = str(store.get_setting(db, "alert_webhook_url") or "")
    if not url:
        return {"at": _now(), "ok": False, "detail": "No webhook URL is saved"}
    fmt = str(store.get_setting(db, "alert_webhook_format"))
    return deliver(url, fmt, "test", "test", "Alerts from Cabinet reach this webhook.")


def heartbeat_url(url: str, up: bool, message: str) -> str:
    """Kuma's push URL with our status and message in place of its defaults."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("status", "msg", "ping")]
    query += [("status", "up" if up else "down"), ("msg", message[:200])]
    return urlunsplit(parts._replace(query=urlencode(query)))


def ping_heartbeat(db: Session, test: bool = False) -> dict | None:
    """Push to the heartbeat URL: up when nothing is failing, down with the
    failing conditions otherwise. None when no URL is saved."""
    url = str(store.get_setting(db, "heartbeat_url") or "")
    if not url:
        return None
    problems = failing(db)
    up = not problems
    message = (
        "OK"
        if up
        else "; ".join(f"{CONDITIONS.get(k, k)}: {s.get('message')}" for k, s in problems.items())
    )
    if test:
        message = f"Test from Cabinet: {message}"
    target = heartbeat_url(url, up, message)
    try:
        resp = httpx.get(target, timeout=TIMEOUT)
        resp.raise_for_status()
        # Kuma answers 200 {"ok": false, "msg": ...} for an unknown or paused monitor.
        try:
            body = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("ok") is False:
            raise httpx.HTTPError(str(body.get("msg") or "the monitor refused the push"))
        outcome = {"at": _now(), "ok": True, "detail": f"pushed {'up' if up else 'down'}"}
    except httpx.HTTPError as exc:
        outcome = {"at": _now(), "ok": False, "detail": _describe(exc, target)}
        logger.error("Heartbeat failed: %s", outcome["detail"])
    with _lock:
        _status["heartbeat"] = outcome
    return outcome


def reset_memory() -> None:
    """Forget in-memory outcomes (tests)."""
    _status.update(delivery=None, heartbeat=None)
