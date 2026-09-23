"""Photo file storage on the shared volume. The DB stores only relative keys.

Uploads are validated as real images with Pillow (the declared content-type is
not trusted), EXIF orientation is corrected, and a JPEG thumbnail is generated
alongside the original. Images can also be fetched from a public URL, with
private and local network addresses refused.

Nothing written here carries metadata (v0.32.0): every original is
re-encoded with its orientation applied and only its colour profile (and a
palette's transparency) kept, so no EXIF, GPS, XMP, IPTC, or text chunk
reaches a share, nginx's `/photos/`, or a backup. Files written before that,
thumbnails included (an old thumbnail could carry the source's JPEG
comment), are re-encoded once by `strip_existing`, which leaves the marker
`photos_clean` beside `auth_claimed` on the state volume when it is done.
Until the marker exists the share view cleans each photo as it serves it
(`cleaned_file`), so it never trusts the disk.
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
MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
THUMB_MAX = (400, 400)
QUALITY = 95
THUMB_QUALITY = 85
# All an original keeps of what it arrived with: its colour, nothing about
# where, when, or on what it was taken.
KEEP_INFO = ("icc_profile", "transparency")
# What Pillow reports in `info` for a file that carries nothing identifying,
# including all that `clean_bytes` itself writes. A PNG's text is checked
# apart (`carries_metadata`), so a text keyword named like one of these
# (`timestamp`, `dpi`) still counts.
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
# JPEG segments that describe only the pixels: JFIF's layout, the colour
# profile, Adobe's colour transform. Any other APPn, and any comment, counts.
HARMLESS_JPEG = (("APP0", b"JFIF"), ("APP2", b"ICC_PROFILE\0"), ("APP14", b"Adobe"))
# PNG chunks that describe only the pixels. Anything else counts: text,
# `tIME`, `eXIf`, a private chunk, one this list doesn't know.
HARMLESS_PNG = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"iCCP",
        b"sRGB",
        b"gAMA",
        b"cHRM",
        b"cICP",
        b"sBIT",
        b"pHYs",
        b"bKGD",
        b"acTL",
        b"fcTL",
        b"fdAT",
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


def clean_bytes(img: Image.Image, fmt: str, quality: int = QUALITY) -> bytes:
    """The image re-encoded with no metadata: EXIF, XMP, IPTC, comments,
    and PNG text chunks all dropped, the ICC profile and a palette's
    transparency kept. `img` is already turned upright (`open_validated`)."""
    kept = {key: img.info[key] for key in KEEP_INFO if key in img.info}
    img.info = dict(kept)  # nothing else can reach an encoder by default
    extra = {"icc_profile": kept["icc_profile"]} if "icc_profile" in kept else {}
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=quality, exif=b"", xmp=b"", **extra)
    elif fmt == "PNG":
        img.save(buf, "PNG", **extra)
    elif fmt == "WEBP":
        img.save(buf, "WEBP", quality=quality, exif=b"", xmp=b"", **extra)
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
    # Pillow's JPEG encoder takes a comment from `info` by default: a
    # thumbnail goes through clean_bytes too, with no profile, as before.
    thumb.info = {}
    (_root() / thumb_key).write_bytes(clean_bytes(thumb, "JPEG", THUMB_QUALITY))

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


def _png_chunks(data: bytes):
    """The chunk types of a PNG file, in order, read from its bytes: Pillow
    skips (and doesn't report) the public chunks it has no reader for, such
    as `tIME`. Bytes after `IEND` are reported as `b"trailing"`."""
    pos = 8  # past the signature
    while pos + 8 <= len(data):
        kind = data[pos + 4 : pos + 8]
        yield kind
        pos += 12 + int.from_bytes(data[pos : pos + 4], "big")
        if kind == b"IEND":
            if pos < len(data):
                yield b"trailing"
            return


def carries_metadata(img: Image.Image, data: bytes | None = None) -> bool:
    """True when the file holds anything past its pixels, colour, and
    layout: EXIF (orientation included), XMP, IPTC, a comment, a JPEG
    application segment other than JFIF, ICC, or Adobe, or a PNG chunk
    other than those that describe the pixels. For a PNG, `data` is the
    file's bytes (read from `img.filename` when not given; unknown counts as
    carrying something). The one-time pass doesn't ask this: it rewrites
    every file; this is the tests' check that the result is clean."""
    if any(key not in HARMLESS_INFO for key in img.info):
        return True
    if img.format == "JPEG":
        return any(
            not any(name == seg and body.startswith(lead) for seg, lead in HARMLESS_JPEG)
            for name, body in getattr(img, "applist", ())
        )
    if img.format == "PNG":
        if img.text or getattr(img, "private_chunks", None):
            return True
        if data is None:
            try:
                data = Path(img.filename).read_bytes()
            except (OSError, TypeError):
                return True
        return any(kind not in HARMLESS_PNG for kind in _png_chunks(data))
    return False


def _stored_files(root: Path):
    """Every stored photo, originals and thumbnails, nothing under a
    dot-folder (a restore's `.restore-*` work), never through a symlink."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            path = Path(folder) / name
            if name.startswith(".strip-") and not path.is_symlink():
                yield path  # a pass that stopped halfway left it; strip_existing tidies
                continue
            if name.startswith(".") or path.is_symlink():
                continue
            if path.suffix.lower() in FORMATS.values():
                yield path


def _quality(path: Path) -> int:
    return THUMB_QUALITY if path.name.endswith(THUMB_SUFFIX) else QUALITY


def cleaned_file(path: Path) -> tuple[bytes, str]:
    """A stored photo re-encoded without metadata, and its media type: what
    the share view serves while the marker is missing, so a file the pass
    hasn't reached (or couldn't rewrite) is never sent as it is. ValueError
    when it isn't a readable image."""
    try:
        img, fmt = open_validated(path.read_bytes())
        return clean_bytes(img, fmt, _quality(path)), MEDIA_TYPES[fmt]
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("File is not a readable image") from exc


class _Unreadable(Exception):
    """Pillow can't read the file as an image (corrupt, truncated, not one)."""


def _strip_one(path: Path) -> bool:
    """Rewrite one stored photo without its metadata, whatever it seems to
    carry (no check is trusted to find everything); False when it was
    deleted meanwhile. Written beside it under a dot-name, then put in its
    place in one step. Raises _Unreadable when the file can't be decoded,
    anything else when it can't be written."""
    try:
        with Image.open(path) as probe:
            fmt = probe.format
            if fmt not in FORMATS:
                raise _Unreadable(f"{fmt} is not a stored photo format")
            probe.load()
            data = clean_bytes(ImageOps.exif_transpose(probe), fmt, _quality(path))
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
    """Re-encode every stored photo in PHOTO_DIR, originals and thumbnails,
    without its metadata, then write the marker (which is what stops a
    repeat; this function itself always rewrites). Never raises: a file that
    can't be read or rewritten is logged and skipped. The marker is left
    unwritten when a rewrite failed, so the next start tries again; a file
    Pillow can't open at all doesn't hold it back."""
    found = {"checked": 0, "rewritten": 0, "unreadable": 0, "failed": 0}
    with _pass_lock:
        root = _root()
        try:
            paths = list(_stored_files(root)) if root.is_dir() else []
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
