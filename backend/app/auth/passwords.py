"""Passwords: Argon2id with the parameters pinned here, and two verification
slots so a flood of guesses can't keep the owner out.

Each Argon2 check takes 64 MiB. One slot serves any sign-in; the other is
reserved for a request presenting a valid known-device cookie for the
account it signs in to (the caller decides, from a cheap hash lookup, before
any Argon2 work). Two slots is 128 MiB at worst, inside the backend's 1024M
limit. The routes are plain `def` handlers, so this already runs in a worker
thread, never on the event loop.
"""

import re
import threading
from contextlib import contextmanager

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

TIME_COST = 3
MEMORY_COST = 65536  # KiB
PARALLELISM = 4
HASHER = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST,
    parallelism=PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

MIN_LENGTH = 12
MAX_LENGTH = 256
USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
SLOT_WAIT = 10.0  # seconds; longer gives 503
BUSY_RETRY_AFTER = 5

PASSWORD_RULE = f"A password is {MIN_LENGTH} to {MAX_LENGTH} characters."
USERNAME_RULE = "A username is 1 to 64 letters, digits, dots, underscores, or dashes."


class PasswordRejected(ValueError):
    """A new password or username that breaks the rules; the message says which."""


class Busy(Exception):
    """Both verification slots stayed taken for SLOT_WAIT: answer 503."""

    retry_after = BUSY_RETRY_AFTER


def check_password_rules(password: str) -> None:
    if not isinstance(password, str) or not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise PasswordRejected(PASSWORD_RULE)


def normalize_username(name: str) -> str:
    """The stored form, lowercased. Raises PasswordRejected with the rule."""
    if not isinstance(name, str) or USERNAME_RE.fullmatch(name) is None:
        raise PasswordRejected(USERNAME_RULE)
    return name.lower()


_slots = {False: threading.BoundedSemaphore(1), True: threading.BoundedSemaphore(1)}


@contextmanager
def slot(reserved: bool = False):
    semaphore = _slots[bool(reserved)]
    if not semaphore.acquire(timeout=SLOT_WAIT):
        raise Busy()
    try:
        yield
    finally:
        semaphore.release()


_dummy_hash: str | None = None
_dummy_lock = threading.Lock()


def _dummy() -> str:
    """A real hash of nothing anyone knows, verified for an unknown name so its
    answer takes as long as a wrong password."""
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = HASHER.hash("cabinet: no such account")
        return _dummy_hash


def hash_password(password: str, reserved: bool = False) -> str:
    with slot(reserved):
        return HASHER.hash(password)


def verify(stored: str | None, password: str, reserved: bool = False) -> bool:
    """True only for the right password. `stored` None (no such account, or
    one without a password) still costs one Argon2 check."""
    if not isinstance(password, str) or len(password) > MAX_LENGTH:
        return False  # the rule is public, so its length check leaks nothing
    with slot(reserved):
        if stored is None:
            try:
                HASHER.verify(_dummy(), password)
            except VerificationError:
                pass
            return False
        try:
            return HASHER.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False


def needs_rehash(stored: str) -> bool:
    return HASHER.check_needs_rehash(stored)
