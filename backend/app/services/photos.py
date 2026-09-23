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
The marker only spares the share view work (v0.32.1): it serves a file from
disk only when the marker exists and `checked_bytes` passes that one file
(an allowlist walk of its whole structure, v0.32.2), and then serves the
bytes it checked; anything else is re-encoded as it is served
(`cleaned_file`) or refused. The marker lists the files the pass couldn't
decode, and the share view refuses those outright.
"""

import io
import ipaddress
import json
import logging
import os
import shutil
import socket
import threading
import time
import uuid
import zlib
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


def _icc_ok(profile) -> bool:
    """Whether bytes are shaped like an ICC profile: its declared size is its
    length, the `acsp` signature is in place, and every tag lies inside it.
    Anything else in a profile's place is not a colour profile, and is
    dropped (v0.32.2). A real profile's own text, such as its description,
    is kept with it by design."""
    if not isinstance(profile, bytes) or len(profile) < 132:
        return False
    if int.from_bytes(profile[:4], "big") != len(profile) or profile[36:40] != b"acsp":
        return False
    count = int.from_bytes(profile[128:132], "big")
    if 132 + 12 * count > len(profile):
        return False
    for entry in range(132, 132 + 12 * count, 12):
        offset = int.from_bytes(profile[entry + 4 : entry + 8], "big")
        if offset + int.from_bytes(profile[entry + 8 : entry + 12], "big") > len(profile):
            return False
    return True


def clean_bytes(img: Image.Image, fmt: str, quality: int = QUALITY) -> bytes:
    """The image re-encoded with no metadata: EXIF, XMP, IPTC, comments,
    and PNG text chunks all dropped, the ICC profile (when it is shaped like
    one) and a palette's transparency kept. `img` is already turned upright
    (`open_validated`)."""
    kept = {key: img.info[key] for key in KEEP_INFO if key in img.info}
    if "icc_profile" in kept and not _icc_ok(kept["icc_profile"]):
        del kept["icc_profile"]
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


def marker_unreadable() -> frozenset[str] | None:
    """None without the marker; otherwise the keys of the files the pass
    couldn't decode, which the share view refuses (v0.32.2). A marker from
    before that (a line of prose) lists none, so an upgrade doesn't re-run
    the pass. One that can't be read or parsed counts as no marker, so
    every photo goes the slow, safe way."""
    try:
        text = _marker_path().read_text("utf-8")
    except OSError:
        return None
    if not text.lstrip().startswith("{"):
        return frozenset()
    try:
        listed = json.loads(text)["unreadable"]
        return frozenset(key for key in listed if isinstance(key, str))
    except (ValueError, KeyError, TypeError):
        return None


# Moves on every `remove_marker`, so a pass that was already walking when
# photos of unknown cleanliness arrived doesn't write the marker over them.
# Per process: `restore.sh`'s removal from another process isn't seen, which
# the per-file check when serving covers.
_marker_lock = threading.Lock()
_marker_generation = 0


def _generation() -> int:
    with _marker_lock:
        return _marker_generation


def remove_marker() -> None:
    """Before a restore swaps in an archive's photos, which may carry
    metadata: the pass after it writes the marker again."""
    global _marker_generation
    with _marker_lock:
        _marker_generation += 1
        _marker_path().unlink(missing_ok=True)


def _write_marker(unreadable=()) -> None:
    """The marker, as JSON listing the keys the pass couldn't decode.
    Written beside it and renamed in, so a half-written list is never read."""
    path = _marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{CLEAN_MARKER}-{uuid.uuid4().hex}")
    try:
        temp.write_text(json.dumps({"unreadable": sorted(unreadable)}) + "\n", "utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_marker_unless_moved(generation: int, unreadable=()) -> bool:
    """Write the marker only if no `remove_marker` ran since `generation`
    was read; checked and written under the lock so one can't slip between."""
    with _marker_lock:
        if _marker_generation != generation:
            return False
        _write_marker(unreadable)
        return True


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
    carrying something). Header only: nothing here decodes the pixels, so
    `looks_clean` can ask it on every request. The one-time pass doesn't ask
    this: it rewrites every file."""
    if any(key not in HARMLESS_INFO for key in img.info):
        return True
    if "icc_profile" in img.info and not _icc_ok(img.info["icc_profile"]):
        return True
    if img.format == "JPEG":
        return any(
            not any(name == seg and body.startswith(lead) for seg, lead in HARMLESS_JPEG)
            for name, body in getattr(img, "applist", ())
        )
    if img.format == "PNG":
        # Not `img.text`: it decodes the whole image to find text after the
        # pixels, and the chunk walk below already counts every text chunk.
        if getattr(img, "private_chunks", None):
            return True
        if data is None:
            try:
                data = Path(img.filename).read_bytes()
            except (OSError, TypeError):
                return True
        return any(kind not in HARMLESS_PNG for kind in _png_chunks(data))
    return False


# --- the per-file check: an allowlist walk of the whole file (v0.32.2) ---------------
#
# Only what describes the pixels passes; anything else (a marker or chunk
# this doesn't know, a container longer than its kind allows, a length past
# the end of the file, bytes after the image) answers "not clean", which
# sends the file through `cleaned_file`. Structure only: data hidden inside
# the compressed pixel stream itself can't be seen without decoding it.

_SOS, _EOI, _DHT, _DQT, _DRI, _DNL = 0xDA, 0xD9, 0xC4, 0xDB, 0xDD, 0xDC
_SOF = (0xC0, 0xC1, 0xC2)  # baseline, extended, and progressive Huffman
_PROGRESSIVE = 0xC2
_APP0, _APP2, _APP14 = 0xE0, 0xE2, 0xEE


def _jpeg_segment_ok(marker: int, body: bytes) -> bool:
    """Whether a segment's body is exactly what its kind specifies, so none
    carries bytes past the data it describes."""
    size = len(body)
    if marker in _SOF:
        return size >= 6 and size == 6 + 3 * body[5]
    if marker == _SOS:
        return size >= 1 and size == 4 + 2 * body[0]
    if marker in (_DRI, _DNL):
        return size == 2
    if marker == _DQT:
        pos = 0
        while pos < size:
            if body[pos] >> 4 > 1:
                return False
            pos += 1 + 64 * (1 + (body[pos] >> 4))
        return pos == size
    if marker == _DHT:
        pos = 0
        while pos < size:
            if pos + 17 > size:
                return False
            pos += 17 + sum(body[pos + 1 : pos + 17])
        return pos == size
    if marker == _APP0:  # JFIF with no thumbnail
        return size == 14 and body.startswith(b"JFIF\0") and body[12] == body[13] == 0
    if marker == _APP2:
        return body.startswith(b"ICC_PROFILE\0")
    if marker == _APP14:
        return size == 12 and body.startswith(b"Adobe")
    return False


def _jpeg_scan_end(data: bytes, pos: int) -> int | None:
    """Where a scan's entropy-coded data ends: the first 0xFF not followed
    by a stuffed zero or a restart marker. None when the file ends first."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            return None
        following = data[pos + 1]
        if following == 0 or 0xD0 <= following <= 0xD7:
            pos += 2
            continue
        return pos


def _jpeg_icc_ok(fragments: list[bytes]) -> bool:
    """A JPEG's APP2 ICC fragments, if any, number 1 to n with n in every
    one, and join into a profile (`_icc_ok`). Pillow drops fragments that
    don't add up without a word, which would leave their bytes unchecked."""
    if not fragments:
        return True
    count = len(fragments)
    if any(len(body) < 14 or body[13] != count for body in fragments):
        return False
    ordered = sorted(fragments, key=lambda body: body[12])
    if [body[12] for body in ordered] != list(range(1, count + 1)):
        return False
    return _icc_ok(b"".join(body[14:] for body in ordered))


def _jpeg_walk(data: bytes) -> int | None:
    """Walk a JPEG from SOI to its one EOI, the scans' coded data included,
    and return how many application segments come before the first scan
    (for a cross-check with Pillow's own header read); None when anything
    isn't on the allowlist, is longer than its kind allows, runs past the
    file, or follows the EOI. Before the first scan: one SOF (0, 1, or 2),
    DHT, DQT, DRI, one APP0 JFIF with no thumbnail, APP2 ICC, one APP14
    Adobe. After it: DHT, DQT, DRI, DNL, and more scans only in a
    progressive file. No fill bytes, no restart outside a scan."""
    size = len(data)
    if not data.startswith(b"\xff\xd8"):
        return None
    pos, apps, sof, scanned, seen, icc = 2, 0, None, False, set(), []
    while pos + 2 <= size:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == _EOI:
            return apps if scanned and pos + 2 == size and _jpeg_icc_ok(icc) else None
        if scanned:
            allowed = marker in (_DHT, _DQT, _DRI, _DNL) or (marker == _SOS and sof == _PROGRESSIVE)
        else:
            allowed = (
                marker in (_SOS, _DHT, _DQT, _DRI, _APP2)
                or (marker in _SOF and sof is None)
                or (marker in (_APP0, _APP14) and marker not in seen)
            )
        if not allowed or pos + 4 > size:
            return None
        end = pos + 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
        if end < pos + 4 or end > size or not _jpeg_segment_ok(marker, data[pos + 4 : end]):
            return None
        if marker in _SOF:
            sof = marker
        elif marker in (_APP0, _APP2, _APP14):
            apps += 1
            seen.add(marker)
            if marker == _APP2:
                icc.append(data[pos + 4 : end])
        pos = end
        if marker == _SOS:
            if sof is None:
                return None
            scanned = True
            pos = _jpeg_scan_end(data, pos)
            if pos is None:
                return None
    return None


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Chunks whose length the PNG and APNG specifications fix.
_PNG_LENGTHS = {
    b"IHDR": 13,
    b"IEND": 0,
    b"pHYs": 9,
    b"gAMA": 4,
    b"cHRM": 32,
    b"sRGB": 1,
    b"cICP": 4,
    b"acTL": 8,
    b"fcTL": 26,
}
# ... and those whose length follows from the colour type (IHDR's byte 9).
_PNG_BY_COLOUR = {
    b"sBIT": {0: 1, 2: 3, 3: 3, 4: 2, 6: 4},
    b"bKGD": {0: 2, 2: 6, 3: 1, 4: 2, 6: 6},
    b"tRNS": {0: 2, 2: 6},  # a palette's is checked against the palette
}
# The profile name Pillow writes, and compression method 0: a profile's
# name is free text, so it is held to what Cabinet itself writes.
_PNG_ICC_NAME = b"ICC Profile\0\0"


def _png_walk(data: bytes) -> bool:
    """Walk a PNG's chunks from the signature to IEND: every chunk on the
    allowlist (`HARMLESS_PNG`), fitting the file, with a correct CRC (a bad
    one is a file `cleaned_file` would refuse), at its specified length, IHDR
    first, and nothing after IEND."""
    size = len(data)
    if not data.startswith(_PNG_SIGNATURE):
        return False
    view = memoryview(data)
    pos, colour, palette = 8, None, 0
    while pos + 12 <= size:
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > size or kind not in HARMLESS_PNG or (colour is None) != (kind == b"IHDR"):
            return False
        if zlib.crc32(view[pos + 4 : end - 4]) != int.from_bytes(data[end - 4 : end], "big"):
            return False
        if kind in _PNG_LENGTHS and length != _PNG_LENGTHS[kind]:
            return False
        if kind == b"IHDR":
            colour = data[pos + 17]
            if colour not in (0, 2, 3, 4, 6):
                return False
        elif kind == b"PLTE":
            if length % 3 or not 3 <= length <= 768:
                return False
            palette = length // 3
        elif kind == b"tRNS" and colour == 3:
            if not 1 <= length <= palette:
                return False
        elif kind in _PNG_BY_COLOUR:
            if length != _PNG_BY_COLOUR[kind].get(colour):
                return False
        elif kind == b"iCCP" and not data.startswith(_PNG_ICC_NAME, pos + 8):
            return False
        pos = end
        if kind == b"IEND":
            return pos == size
    return False


_WEBP_TOP = frozenset({b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ICCP", b"ANIM", b"ANMF"})
_WEBP_FRAME = frozenset({b"ALPH", b"VP8 ", b"VP8L"})
_WEBP_BITSTREAMS = (b"VP8 ", b"VP8L")
# VP8X flag bits that must be clear: EXIF, XMP, and the reserved ones.
_WEBP_REFUSED_FLAGS = 0x08 | 0x04 | 0xC1


def _riff_chunks(data: bytes, pos: int, end: int) -> list[tuple[bytes, int, int]] | None:
    """(fourcc, payload start, payload end) for each chunk from `pos` to
    exactly `end`; None when one runs past it, or an odd-sized chunk's pad
    byte is missing or isn't zero."""
    chunks = []
    while pos < end:
        if pos + 8 > end:
            return None
        start = pos + 8
        stop = start + int.from_bytes(data[pos + 4 : start], "little")
        padded = stop + (stop - start) % 2
        if padded > end or (padded > stop and data[stop] != 0):
            return None
        chunks.append((data[pos : pos + 4], start, stop))
        pos = padded
    return chunks


def _webp_walk(data: bytes) -> bool:
    """A WebP whose RIFF size matches the file and which holds only the
    chunks that describe the image: one bitstream on its own, or VP8X (EXIF
    and XMP flags clear) with an ICCP holding a profile, ALPH, ANIM, and
    frames (ANMF, whose own chunks are walked too); each once but the
    frames, nothing after the last."""
    size = len(data)
    if size < 20 or not data.startswith(b"RIFF") or data[8:12] != b"WEBP":
        return False
    if int.from_bytes(data[4:8], "little") != size - 8:
        return False
    chunks = _riff_chunks(data, 12, size)
    if not chunks:
        return False
    kinds = [kind for kind, _, _ in chunks]
    if any(kind not in _WEBP_TOP for kind in kinds):
        return False
    if any(kinds.count(kind) > 1 for kind in set(kinds) if kind != b"ANMF"):
        return False
    if kinds[0] != b"VP8X":
        return len(kinds) == 1 and kinds[0] in _WEBP_BITSTREAMS
    _, start, stop = chunks[0]
    if stop - start != 10 or data[start] & _WEBP_REFUSED_FLAGS:
        return False
    if data[start + 1 : start + 4] != b"\0\0\0":
        return False
    for kind, start, stop in chunks:
        if kind == b"ICCP" and not _icc_ok(data[start:stop]):
            return False
        if kind != b"ANMF":
            continue
        inner = _riff_chunks(data, start + 16, stop) if stop - start >= 16 else None
        if not inner or any(sub not in _WEBP_FRAME for sub, _, _ in inner):
            return False
    return True


def checked_bytes(path: Path) -> tuple[bytes, str] | None:
    """A stored photo's bytes and media type when they may be sent as they
    are: the whole file passes its format's allowlist walk and, for a JPEG
    or PNG, Pillow's own header read agrees and finds no metadata. Never
    decodes the pixels, since the share view asks on every request. The
    caller serves these bytes rather than reopening the path, so a file
    replaced meanwhile is never sent unchecked. None for anything else (any
    other format, any error), which sends the file through `cleaned_file`."""
    try:
        data = path.read_bytes()
        if data.startswith(b"RIFF"):
            return (data, MEDIA_TYPES["WEBP"]) if _webp_walk(data) else None
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as img:
            if img.format == "JPEG":
                apps = _jpeg_walk(data)
                # A segment Pillow read that the walk didn't count, or the
                # reverse, means the two parsers disagree: not trusted.
                clean = apps is not None and apps == len(getattr(img, "applist", ()))
            else:
                clean = _png_walk(data)
            if clean and not carries_metadata(img, data):
                return data, MEDIA_TYPES[img.format]
            return None
    except Exception:  # unreadable in any way: not trusted
        return None


def looks_clean(path: Path) -> bool:
    """Whether a stored photo may be sent from disk as it is (`checked_bytes`)."""
    return checked_bytes(path) is not None


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
    unwritten when a rewrite failed, so the next start tries again, and when
    `remove_marker` ran during the pass (photos may have arrived behind the
    walk). A file Pillow can't open at all doesn't hold it back: that would
    put every start on the slow path. Its key goes into the marker instead,
    and the share view refuses it (v0.32.2)."""
    found = {"checked": 0, "rewritten": 0, "unreadable": 0, "failed": 0}
    unreadable: list[str] = []
    with _pass_lock:
        generation = _generation()
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
                unreadable.append(path.relative_to(root).as_posix())
                logger.warning("Photo metadata: %s isn't a readable image; left alone", path.name)
            except Exception:
                found["failed"] += 1
                logger.exception("Photo metadata: could not rewrite %s", path.name)
        if found["failed"]:
            logger.warning("Photo metadata: marker not written; the next start tries again")
        else:
            try:
                if not _write_marker_unless_moved(generation, unreadable):
                    logger.info(
                        "Photo metadata: marker not written; photos were restored during "
                        "the pass, and the pass after the restore writes it"
                    )
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
