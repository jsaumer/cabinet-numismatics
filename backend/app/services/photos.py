"""Photo file storage on the shared volume. The DB stores only relative keys.

Uploads are validated as real images with Pillow (the declared content-type is
not trusted), EXIF orientation is corrected, and a JPEG thumbnail is generated
alongside the original. Images can also be fetched from a public URL, with
private and local network addresses refused.

Nothing written here carries metadata (v0.32.0): every original is
re-encoded with its orientation applied and only its colour profile (and a
palette's transparency) kept, so no EXIF, GPS, XMP, IPTC, or text chunk
reaches a share, nginx's `/photos/`, or a backup. Files written before that
are cleaned once by `strip_existing`, which leaves the marker
`photos_clean` beside `auth_claimed` on the state volume when it is done.
"""

import io
import ipaddress
import logging
import os
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Image formats accepted for upload, mapped to the stored extension.
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
THUMB_MAX = (400, 400)
QUALITY = 95
# All an original keeps of what it arrived with: its colour, nothing about
# where, when, or on what it was taken.
KEEP_INFO = ("icc_profile", "transparency")
# What Pillow reports for a file that carries nothing identifying, including
# all that `clean_bytes` itself writes (so a second pass rewrites nothing).
HARMLESS_INFO = frozenset(
    {
        *KEEP_INFO,
        "dpi",
        "jfif",
        "jfif_version",
        "jfif_unit",
        "jfif_density",
        "adobe",
        "adobe_transform",
        "progressive",
        "progression",
        "background",
        "loop",
        "duration",
        "timestamp",
        "gamma",
        "srgb",
        "chromaticity",
        "aspect",
        "interlace",
    }
)
CLEAN_MARKER = "photos_clean"
THUMB_SUFFIX = "_thumb.jpg"


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


def clean_bytes(img: Image.Image, fmt: str) -> bytes:
    """The image re-encoded with no metadata: EXIF, XMP, IPTC, comments,
    and PNG text chunks all dropped, the ICC profile and a palette's
    transparency kept. `img` is already turned upright (`open_validated`)."""
    kept = {key: img.info[key] for key in KEEP_INFO if key in img.info}
    img.info = dict(kept)  # nothing else can reach an encoder by default
    extra = {"icc_profile": kept["icc_profile"]} if "icc_profile" in kept else {}
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=QUALITY, exif=b"", xmp=b"", **extra)
    elif fmt == "PNG":
        img.save(buf, "PNG", **extra)
    elif fmt == "WEBP":
        img.save(buf, "WEBP", quality=QUALITY, exif=b"", xmp=b"", **extra)
    else:
        raise ValueError(f"Unsupported image format {fmt!r}")
    return buf.getvalue()


def save_photo(
    item_id: uuid.UUID, photo_id: uuid.UUID, data: bytes, stem: str | None = None
) -> tuple[str, str, int, int]:
    """Validate, write original + thumbnail, return (file_key, thumb_key, w, h).
    `stem` names the files (default: the photo id). A replaced image gets a
    fresh one so browsers don't keep showing the cached old file. The
    original is written re-encoded without metadata (`clean_bytes`), never
    as the bytes that arrived."""
    img, fmt = open_validated(data)
    ext = FORMATS[fmt]
    width, height = img.width, img.height
    cleaned = clean_bytes(img, fmt)

    name = stem or str(photo_id)
    file_key = f"{item_id}/{name}{ext}"
    thumb_key = f"{item_id}/{name}{THUMB_SUFFIX}"
    path = _root() / file_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cleaned)

    thumb = img.convert("RGB") if img.mode != "RGB" else img
    thumb.thumbnail(THUMB_MAX)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=85)
    (_root() / thumb_key).write_bytes(buf.getvalue())

    return file_key, thumb_key, width, height


# --- cleaning what was stored before v0.32.0 -----------------------------------------


def _marker_path() -> Path:
    from app.services import archive_keys

    return archive_keys.state_dir() / CLEAN_MARKER


def marker_exists() -> bool:
    return _marker_path().exists()


def remove_marker() -> None:
    """Before a restore swaps in an archive's photos, which may carry
    metadata: the pass after it writes the marker again."""
    _marker_path().unlink(missing_ok=True)


def _write_marker() -> None:
    path = _marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Every stored photo has had its metadata removed.\n", "utf-8")


def carries_metadata(img: Image.Image) -> bool:
    """True when the file holds anything past its colour and layout: EXIF
    (orientation included), XMP, IPTC, a comment, or a PNG text chunk."""
    return any(key not in HARMLESS_INFO for key in img.info)


def _originals(root: Path):
    """Every stored original: no thumbnail, nothing under a dot-folder (a
    restore's `.restore-*` work), never through a symlink."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            path = Path(folder) / name
            if name.startswith(".strip-") and not path.is_symlink():
                yield path  # a pass that stopped halfway left it; strip_existing tidies
                continue
            if name.startswith(".") or name.endswith(THUMB_SUFFIX) or path.is_symlink():
                continue
            if path.suffix.lower() in FORMATS.values():
                yield path


class _Unreadable(Exception):
    """Pillow can't read the file as an image (corrupt, truncated, not one)."""


def _strip_one(path: Path) -> bool:
    """Rewrite one original without its metadata; False when it had none.
    Written beside it under a dot-name, then put in its place in one step.
    Raises _Unreadable when the file can't be decoded, anything else when it
    can't be written."""
    try:
        with Image.open(path) as probe:
            fmt = probe.format
            probe.load()
            if fmt not in FORMATS or not carries_metadata(probe):
                return False
            data = clean_bytes(ImageOps.exif_transpose(probe), fmt)
    except FileNotFoundError:
        return False  # deleted since the walk
    except PermissionError:
        raise  # readable to nginx, maybe: a failure, so the next start retries
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise _Unreadable(str(exc)) from exc
    temp = path.with_name(f".strip-{uuid.uuid4().hex}{path.suffix}")
    try:
        temp.write_bytes(data)
        if not path.exists():  # deleted meanwhile: don't bring it back
            return False
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return True


STALE_TEMP = 10 * 60  # seconds; a live pass in another process is far quicker


def _drop_stale(path: Path) -> None:
    try:
        if time.time() - path.stat().st_mtime > STALE_TEMP:
            path.unlink(missing_ok=True)
    except OSError:
        pass


_pass_lock = threading.Lock()


def strip_existing() -> dict:
    """Remove the metadata from every original in PHOTO_DIR that still has
    some, then write the marker. Never raises: a file that can't be read or
    rewritten is logged and skipped. The marker is left unwritten when a
    rewrite failed, so the next start tries again; a file Pillow can't open
    at all doesn't hold it back. Safe to run again: a clean file is left
    alone."""
    found = {"checked": 0, "rewritten": 0, "unreadable": 0, "failed": 0}
    with _pass_lock:
        root = _root()
        try:
            paths = list(_originals(root)) if root.is_dir() else []
        except OSError:
            logger.exception("Photo metadata: could not list the photo folder")
            found["failed"] += 1
            paths = []
        for path in paths:
            if path.name.startswith(".strip-"):
                _drop_stale(path)
                continue
            found["checked"] += 1
            try:
                if _strip_one(path):
                    found["rewritten"] += 1
            except _Unreadable:
                found["unreadable"] += 1
                logger.warning("Photo metadata: %s isn't a readable image; left alone", path.name)
            except Exception:
                found["failed"] += 1
                logger.exception("Photo metadata: could not rewrite %s", path.name)
        if found["failed"] == 0:
            try:
                _write_marker()
            except OSError:
                logger.exception("Photo metadata: could not write the marker")
        logger.info(
            "Photo metadata: rewrote %s of %s stored photos (%s unreadable, %s failed)",
            found["rewritten"],
            found["checked"],
            found["unreadable"],
            found["failed"],
        )
    return found


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="photo-metadata").start()


def _pass_quietly() -> None:
    try:
        strip_existing()
    except Exception:  # strip_existing logs its own; this is the last net
        logger.exception("Photo metadata: the pass failed")


def clean_in_background(force: bool = False) -> bool:
    """Start a pass on a background thread unless the marker says every
    photo is already clean (`force`: after a restore swapped photos in).
    True when one was started."""
    if not force and marker_exists():
        return False
    _spawn(_pass_quietly)
    return True


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
