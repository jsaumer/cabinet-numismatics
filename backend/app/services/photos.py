"""Photo file storage on the shared volume. The DB stores only relative keys.

Uploads are validated as real images with Pillow (the declared content-type is
not trusted), EXIF orientation is corrected, and a JPEG thumbnail is generated
alongside the original.
"""

import io
import shutil
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

# Image formats accepted for upload, mapped to the stored extension.
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
THUMB_MAX = (400, 400)


def _root() -> Path:
    return Path(get_settings().photo_dir)


def open_validated(data: bytes) -> tuple[Image.Image, str]:
    """Open upload bytes as an EXIF-corrected image plus its format name;
    ValueError if not a real, supported image."""
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()  # integrity check; invalidates the handle
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("File is not a readable image") from exc
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported image format {fmt!r}; use JPEG, PNG, or WebP")
    img = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(img), fmt


def save_photo(item_id: uuid.UUID, photo_id: uuid.UUID, data: bytes) -> tuple[str, str, int, int]:
    """Validate, write original + thumbnail, return (file_key, thumb_key, w, h)."""
    img, fmt = open_validated(data)
    ext = FORMATS[fmt]
    width, height = img.width, img.height

    file_key = f"{item_id}/{photo_id}{ext}"
    thumb_key = f"{item_id}/{photo_id}_thumb.jpg"
    path = _root() / file_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    thumb = img.convert("RGB") if img.mode != "RGB" else img
    thumb.thumbnail(THUMB_MAX)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=85)
    (_root() / thumb_key).write_bytes(buf.getvalue())

    return file_key, thumb_key, width, height


def delete_photo_files(file_key: str, thumb_key: str | None) -> None:
    for key in (file_key, thumb_key):
        if not key:
            continue
        path = _root() / key
        if path.is_file():
            path.unlink()


def delete_item_dir(item_id: uuid.UUID) -> None:
    """Remove an item's whole photo directory (used when the item is deleted)."""
    path = _root() / str(item_id)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
