"""Photo file storage on the shared volume. The DB stores only relative keys.

Uploads are validated as real images with Pillow (the declared content-type is
not trusted), EXIF orientation is corrected, and a JPEG thumbnail is generated
alongside the original. Images can also be fetched from a public URL, with
private and local network addresses refused.
"""

import io
import ipaddress
import shutil
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

# Image formats accepted for upload, mapped to the stored extension.
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
THUMB_MAX = (400, 400)


def _root() -> Path:
    return Path(get_settings().photo_dir)


def path_of(key: str) -> Path:
    """The file behind a stored key, for the share view, which serves photos
    itself rather than through nginx's `/photos/`."""
    return _root() / key


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


def save_photo(
    item_id: uuid.UUID, photo_id: uuid.UUID, data: bytes, stem: str | None = None
) -> tuple[str, str, int, int]:
    """Validate, write original + thumbnail, return (file_key, thumb_key, w, h).
    `stem` names the files (default: the photo id). A replaced image gets a
    fresh one so browsers don't keep showing the cached old file."""
    img, fmt = open_validated(data)
    ext = FORMATS[fmt]
    width, height = img.width, img.height

    name = stem or str(photo_id)
    file_key = f"{item_id}/{name}{ext}"
    thumb_key = f"{item_id}/{name}_thumb.jpg"
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


REMOTE_MAX_BYTES = 25 * 1024 * 1024  # the same ceiling nginx puts on uploads
REMOTE_TIMEOUT = 15.0
REMOTE_REDIRECTS = 3


class RemoteImageUnavailable(Exception):
    """The URL could not be fetched: network error or timeout."""


def _require_public_host(host: str, port: int) -> None:
    """Refuse hosts resolving to private, loopback, link-local, or other
    non-public addresses, so an import can't reach the LAN or the stack's own
    services. (A DNS answer that changes between this check and the fetch
    isn't covered, which is acceptable for a single-user app behind its own proxy.)"""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Can't resolve {host}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("Importing from private or local network addresses isn't allowed")


def fetch_remote_image(url: str) -> bytes:
    """Download an image from a public http(s) URL, following up to three
    redirects (each re-checked) and stopping at 25 MB. ValueError when the URL
    isn't allowed or doesn't answer with a file; RemoteImageUnavailable when
    it can't be reached."""
    for _ in range(REMOTE_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Only http:// and https:// URLs can be imported")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        _require_public_host(parsed.hostname, port)
        try:
            with httpx.stream(
                "GET",
                url,
                timeout=REMOTE_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": "Cabinet"},
            ) as resp:
                if resp.is_redirect:
                    url = urljoin(url, resp.headers.get("location", ""))
                    continue
                if resp.status_code != 200:
                    raise ValueError(f"The URL answered HTTP {resp.status_code}")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > REMOTE_MAX_BYTES:
                        raise ValueError("The image is larger than 25 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise RemoteImageUnavailable(f"Couldn't fetch the image: {exc}") from exc
    raise ValueError("Too many redirects")
