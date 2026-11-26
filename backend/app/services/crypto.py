"""Encryption at rest for stored secrets (price-source API keys/tokens).

Uses Fernet from `cryptography`: AES-128-CBC with an HMAC-SHA256 authentication
tag, so ciphertext is tamper-evident as well as confidential. Keys are supplied
via the `SECRET_KEY` environment variable, comma-separated to support rotation:
the first key encrypts, any listed key may decrypt (MultiFernet).

If `SECRET_KEY` is unset, a key is generated once and persisted with 0600
permissions to `SECRET_KEY_FILE`, which lives on the backend's private state
volume. It must never be placed under `PHOTO_DIR`: nginx serves that directory
publicly, which would expose the key over HTTP.
"""

import logging
import os
import secrets
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"  # marks an encrypted value; anything else is legacy plaintext

_cipher: MultiFernet | None = None
_cipher_lock = threading.Lock()


def reset_cache() -> None:
    """Drop the cached cipher (used by tests after changing key settings)."""
    global _cipher
    _cipher = None


def _load_key_material() -> list[bytes]:
    settings = get_settings()
    configured = [k.strip() for k in settings.secret_key.split(",") if k.strip()]
    if configured:
        return [k.encode() for k in configured]

    # No SECRET_KEY: fall back to a generated key persisted on the state volume.
    path = Path(settings.secret_key_file)
    if path.is_file():
        return [path.read_bytes().strip()]

    path.parent.mkdir(parents=True, exist_ok=True)
    if _create_exclusively(path, Fernet.generate_key()):
        logger.warning(
            "SECRET_KEY not set; generated one at %s. Set SECRET_KEY in .env to control "
            "key management and survive loss of this volume.",
            path,
        )
    # Whatever the file holds now is the key: this process's, or the one
    # another process (a container command at first start) created first.
    return [path.read_bytes().strip()]


def _create_exclusively(path: Path, key: bytes) -> bool:
    """Write the key file only if there is none, whole or not at all: it is
    written under another name (owner-only from the start, never briefly
    world-readable) and hard-linked into place, which fails when the name is
    taken. An existing key is never replaced, even when the check above
    wrongly said there was none; replacing it would silently lose every
    stored secret. True if this call created it."""
    partial = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(partial, path)
        except FileExistsError:
            return False
        except OSError:
            # A filesystem without hard links: create-if-absent the plain way.
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return False
            with os.fdopen(fd, "wb") as fh:
                fh.write(key)
        return True
    finally:
        partial.unlink(missing_ok=True)


def get_cipher() -> MultiFernet:
    global _cipher
    if _cipher is None:
        with _cipher_lock:  # two first uses at once must end with one key
            if _cipher is None:
                keys = _load_key_material()
                try:
                    _cipher = MultiFernet([Fernet(k) for k in keys])
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        "SECRET_KEY is not a valid Fernet key. Generate one with: "
                        'python -c "from cryptography.fernet import Fernet; '
                        'print(Fernet.generate_key().decode())"'
                    ) from exc
    return _cipher


def is_encrypted(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith(PREFIX)


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Empty input stays empty (means 'unset')."""
    if not plaintext:
        return ""
    return PREFIX + get_cipher().encrypt(plaintext.encode()).decode()


def decrypt(stored: str) -> str:
    """Decrypt a stored secret. Returns "" when the value cannot be decrypted
    (e.g. the key was rotated away or lost) so the app degrades to 'not
    configured' rather than crashing. Never raises, never logs the value."""
    if not stored:
        return ""
    if not is_encrypted(stored):
        # Plain text was never written by this deployment: an archive or a
        # hand edit could plant it, so it is never used (v0.30.0).
        return ""
    try:
        return get_cipher().decrypt(stored[len(PREFIX) :].encode()).decode()
    except (InvalidToken, ValueError):
        logger.warning(
            "A stored secret could not be decrypted with the current SECRET_KEY; "
            "treating it as unset. Re-enter it in Settings."
        )
        return ""
