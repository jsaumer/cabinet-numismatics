"""Encryption at rest for stored secrets (price-source API keys/tokens).

Uses Fernet from `cryptography`: AES-128-CBC with an HMAC-SHA256 authentication
tag, so ciphertext is tamper-evident as well as confidential. Keys are supplied
via the `SECRET_KEY` environment variable, comma-separated to support rotation
— the first key encrypts, any listed key may decrypt (MultiFernet).

If `SECRET_KEY` is unset, a key is generated once and persisted with 0600
permissions to `SECRET_KEY_FILE`, which lives on the backend's private state
volume. It must never be placed under `PHOTO_DIR`: nginx serves that directory
publicly, which would expose the key over HTTP.
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"  # marks an encrypted value; anything else is legacy plaintext

_cipher: MultiFernet | None = None


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

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with owner-only permissions rather than chmod-after-write, so the
    # key is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    logger.warning(
        "SECRET_KEY not set; generated one at %s. Set SECRET_KEY in .env to control "
        "key management and survive loss of this volume.",
        path,
    )
    return [key]


def get_cipher() -> MultiFernet:
    global _cipher
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
    configured' rather than crashing — never raises, never logs the value."""
    if not stored:
        return ""
    if not is_encrypted(stored):
        return stored  # legacy plaintext; callers re-encrypt on read
    try:
        return get_cipher().decrypt(stored[len(PREFIX) :].encode()).decode()
    except (InvalidToken, ValueError):
        logger.warning(
            "A stored secret could not be decrypted with the current SECRET_KEY; "
            "treating it as unset. Re-enter it in Settings."
        )
        return ""
