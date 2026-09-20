"""Maintenance mode: while a restore replaces the database and the files,
the API answers 503 and the scheduled loops sit out. In memory, which is
enough because the backend is one process (see docs/architecture.md)."""

import threading
import time
from contextlib import contextmanager

from starlette.responses import JSONResponse

DETAIL = "Cabinet is restoring a backup; try again in a moment"
# Always answered, so a health check or the restore page's poll never sees 503.
EXEMPT = {("GET", "/api/health"), ("GET", "/api/restore/status")}

_on = threading.Event()
_lock = threading.Lock()
_in_flight = 0
_scheduled = threading.Lock()


def active() -> bool:
    return _on.is_set()


def enter() -> None:
    _on.set()


def leave() -> None:
    _on.clear()


def drain(timeout: float = 30.0) -> bool:
    """Wait for requests that began before maintenance to finish. True once
    none are left; False if the wait ran out (the restore goes ahead: the
    database step waits on locks of its own)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if _in_flight == 0:
                return True
        time.sleep(0.1)
    return False


@contextmanager
def scheduled_task():
    """Held by a scheduled loop while it works; yields False (do nothing)
    during maintenance."""
    if active() or not _scheduled.acquire(blocking=False):
        yield False
        return
    try:
        yield not active()
    finally:
        _scheduled.release()


def scheduled_busy() -> bool:
    return _scheduled.locked()


class MaintenanceMiddleware:
    """Plain ASGI rather than BaseHTTPMiddleware, so streamed responses
    (archive downloads, documents) pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _in_flight
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        if (scope["method"], path) in EXEMPT:
            await self.app(scope, receive, send)
            return
        if active():
            response = JSONResponse(
                {"detail": DETAIL}, status_code=503, headers={"Retry-After": "5"}
            )
            await response(scope, receive, send)
            return
        # The restore endpoints aren't counted: the request that starts a
        # restore would otherwise be waited on by the restore it started.
        counted = not path.startswith("/api/restore")
        if counted:
            with _lock:
                _in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if counted:
                with _lock:
                    _in_flight -= 1
