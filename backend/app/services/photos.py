"""Photo file storage on the shared volume. The DB stores only relative keys."""

import shutil
import uuid
from pathlib import Path

from app.config import get_settings

# Content types accepted for upload, mapped to the stored extension.
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _root() -> Path:
    return Path(get_settings().photo_dir)


def save_photo(item_id: uuid.UUID, photo_id: uuid.UUID, content_type: str, data: bytes) -> str:
    """Write photo bytes under PHOTO_DIR and return the relative file key."""
    ext = EXTENSIONS[content_type]
    key = f"{item_id}/{photo_id}{ext}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def delete_photo_file(file_key: str) -> None:
    path = _root() / file_key
    if path.is_file():
        path.unlink()


def delete_item_dir(item_id: uuid.UUID) -> None:
    """Remove an item's whole photo directory (used when the item is deleted)."""
    path = _root() / str(item_id)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
