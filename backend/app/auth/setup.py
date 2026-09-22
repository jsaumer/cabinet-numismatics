"""The setup code and the claimed marker.

While no admin exists (no row in `cabinet_auth.claim`), the setup page asks
for a one-time code. It comes from SETUP_CODE_FILE, then SETUP_CODE, or is
generated (20 random bytes, base32: 160 bits) and printed once in the log.
It lives in memory only; a restart generates a new one unless a supplied
code applies.

Once claimed, the marker file `auth_claimed` on the state volume (beside
SECRET_KEY_FILE) makes SETUP_CODE and SETUP_CODE_FILE inert for good: an
unclaimed database with the marker present (the schema lost) only ever gets
a generated code. A claimed database with no marker (a lost state volume)
writes it.
"""

import base64
import hmac
import logging
import secrets
import threading
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app.auth import accounts
from app.config import get_settings, normalize_setup_code, supplied_setup_code

logger = logging.getLogger(__name__)

MARKER = "auth_claimed"

_lock = threading.Lock()
_code: str | None = None  # the compact form compared against
_generated = False
_prepared = False


def marker_path() -> Path:
    from app.services import archive_keys

    return archive_keys.state_dir() / MARKER


def marker_exists() -> bool:
    return marker_path().exists()


def _write_marker() -> None:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Cabinet has its admin; SETUP_CODE is ignored from now on.\n", "utf-8")


def _generate() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")  # 32 characters


def grouped(code: str) -> str:
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def prepare(db: DbSession, force: bool = True) -> None:
    """At startup after migrations (and lazily before the first setup call
    when migrations are off): decide the code, or write the marker."""
    global _code, _generated, _prepared
    with _lock:
        if _prepared and force is False:
            return  # another request prepared it while this one waited
        if accounts.claimed(db):
            if not marker_exists():
                _write_marker()
            _code, _generated, _prepared = None, False, True
            return
        supplied = None if marker_exists() else supplied_setup_code(get_settings())
        if supplied is not None:
            _code, _generated = normalize_setup_code(supplied), False
            logger.warning(
                "Cabinet is not set up yet. Open it in a browser and enter the setup code "
                "you supplied (SETUP_CODE_FILE or SETUP_CODE)."
            )
        else:
            code = _generate()
            _code, _generated = code, True
            logger.warning(
                "Cabinet is not set up yet. Open it in a browser and enter this setup code: %s",
                grouped(code),
            )
        _prepared = True


def ensure_prepared(db: DbSession) -> None:
    if not _prepared:
        prepare(db, force=False)


def check(typed: str) -> bool:
    """Constant time. Spaces and dashes don't count; a generated code is
    compared uppercased, a supplied one as the operator wrote it."""
    with _lock:
        expected = _code
        generated = _generated
    if expected is None or not isinstance(typed, str):
        return False
    compact = normalize_setup_code(typed)
    if generated:
        compact = compact.upper()
    return hmac.compare_digest(compact.encode("utf-8"), expected.encode("utf-8"))


def claimed(username: str) -> None:
    """After a successful setup: the code stops working and the marker is
    written."""
    global _code, _generated
    with _lock:
        _code, _generated = None, False
    try:
        _write_marker()
    except OSError as exc:
        # The admin exists either way; the next start writes the marker for a
        # claimed database.
        logger.error(
            "Could not write the claimed marker (%s); it is written on the next start", exc
        )
    logger.warning("Cabinet was set up by %s. The setup code no longer works.", username)


def reset_memory() -> None:
    global _code, _generated, _prepared
    with _lock:
        _code, _generated, _prepared = None, False, False
