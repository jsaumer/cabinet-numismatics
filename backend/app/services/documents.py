"""Attached documents (v0.19.0): receipts, certificates of authenticity,
invoices, grading-label scans.

Files live under DOCUMENT_DIR — a volume of their own, never the photo volume
nginx serves — and are served only through the API, with headers chosen from
the type detected here (see `routers/documents.py`). The type is read from the
bytes: PDFs must start with `%PDF-` *and* open in PDFium; images must open in
Pillow as JPEG, PNG, or WebP. Everything else — SVG and HTML above all, since
they can run script — is refused.

Each document gets a JPEG thumbnail: the image itself, or a PDF's first page
rendered by PDFium (pypdfium2, Apache/BSD-licensed). A password-protected PDF
is kept, without a thumbnail or page count.
"""

import hashlib
import io
import os
import re
import shutil
import uuid
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.services import photos as photo_store

MAX_BYTES = 25 * 1024 * 1024  # the proxy's upload limit
THUMB_MAX = (400, 560)
KINDS = ("receipt", "invoice", "certificate", "grading_label", "appraisal",
         "correspondence", "other")  # fmt: skip
PDF = "application/pdf"
IMAGE_TYPES = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
               "WEBP": ("image/webp", ".webp")}  # fmt: skip
PDFIUM_PASSWORD_ERROR = 4  # FPDF_ERR_PASSWORD


class StorageUnavailable(RuntimeError):
    """DOCUMENT_DIR isn't a mounted volume (or can't be written)."""


def root() -> Path:
    return Path(get_settings().document_dir)


def _mount_points() -> set[str] | None:
    """Mount points from /proc/self/mountinfo, or None where there is none."""
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return None
    points = set()
    for line in lines:
        fields = line.split()
        if len(fields) > 4:
            # mountinfo escapes spaces and friends as octal (\040)
            points.add(re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), fields[4]))
    return points


def storage_status() -> str:
    """Whether documents can be stored: `ok`, or why not — `inside_photos`,
    `not_mounted`, `unwritable` (uploads are refused)."""
    settings = get_settings()
    path = root()
    if path.resolve().is_relative_to(Path(settings.photo_dir).resolve()):
        return "inside_photos"  # nginx serves the photo volume publicly
    if settings.require_document_mount:
        points = _mount_points()
        mounted = str(path.resolve()) in points if points is not None else os.path.ismount(path)
        if not mounted:
            return "not_mounted"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return "unwritable"
    return "ok"


def require_storage() -> None:
    status = storage_status()
    if status == "not_mounted":
        raise StorageUnavailable(
            f"Documents can't be stored: {root()} isn't a mounted volume, so they would be "
            "lost when the container is recreated. Mount a volume there (see "
            "docs/deployment.md), or set REQUIRE_DOCUMENT_MOUNT=false for local development."
        )
    if status == "inside_photos":
        raise StorageUnavailable(
            f"Documents can't be stored: {root()} is inside the photo directory, which is "
            "served publicly. Give DOCUMENT_DIR its own volume."
        )
    if status == "unwritable":
        raise StorageUnavailable(f"Documents can't be stored: {root()} isn't writable.")


# ---------------------------------------------------------------- validation


def _is_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heif")


def _pdf_thumbnail(data: bytes) -> tuple[bytes | None, int | None]:
    """(JPEG thumbnail of page one, page count) — (None, None) for a PDF that
    needs a password. ValueError if PDFium can't read it."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if getattr(exc, "err_code", None) == PDFIUM_PASSWORD_ERROR:
            return None, None
        raise ValueError("The file isn't a readable PDF") from exc
    try:
        pages = len(doc)
        if pages == 0:
            raise ValueError("The PDF has no pages")
        page = doc[0]
        try:
            width, height = page.get_size()
            scale = min(THUMB_MAX[0] / max(width, 1), THUMB_MAX[1] / max(height, 1), 4)
            image = page.render(scale=scale).to_pil()
        finally:
            page.close()
    finally:
        doc.close()
    return _jpeg(image), pages


def _jpeg(image: Image.Image) -> bytes:
    image = image.convert("RGB") if image.mode != "RGB" else image
    image.thumbnail(THUMB_MAX)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def inspect(data: bytes) -> dict:
    """What an upload is, from its bytes: content type, extension, thumbnail,
    pages. ValueError for anything that isn't a PDF, JPEG, PNG, or WebP."""
    if not data:
        raise ValueError("The file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError("The file is larger than 25 MB")
    if data.startswith(b"%PDF-"):
        thumb, pages = _pdf_thumbnail(data)
        return {"content_type": PDF, "ext": ".pdf", "thumb": thumb, "pages": pages}
    if _is_heic(data):
        raise ValueError(
            "HEIC photos aren't supported yet — export or share the photo as JPEG and upload that"
        )
    try:
        image, fmt = photo_store.open_validated(data)
    except ValueError:
        raise ValueError("Only PDF, JPEG, PNG, and WebP files can be attached") from None
    content_type, ext = IMAGE_TYPES[fmt]
    return {"content_type": content_type, "ext": ext, "thumb": _jpeg(image), "pages": None}


def clean_filename(name: str | None, ext: str) -> str:
    """The uploaded name, reduced to something safe to echo in a download
    header, with the extension matching the detected type."""
    stem = Path(name or "").stem
    stem = re.sub(r"[\x00-\x1f\x7f/\\\\]+", "", stem).strip(" .") or "document"
    return f"{stem[:200]}{ext}"


# ---------------------------------------------------------------- files


def save(document_id: uuid.UUID, data: bytes, info: dict) -> tuple[str, str | None]:
    """Write the file (and thumbnail) under the document's own folder;
    returns (file_key, thumb_key)."""
    folder = root() / str(document_id)
    folder.mkdir(parents=True, exist_ok=True)
    file_key = f"{document_id}/original{info['ext']}"
    (root() / file_key).write_bytes(data)
    thumb_key = None
    if info["thumb"]:
        thumb_key = f"{document_id}/thumb.jpg"
        (root() / thumb_key).write_bytes(info["thumb"])
    return file_key, thumb_key


def path_of(key: str) -> Path:
    """The file for a stored key, refusing anything that escapes DOCUMENT_DIR."""
    base = root().resolve()
    path = (base / key).resolve()
    if not path.is_relative_to(base):
        raise FileNotFoundError(key)
    return path


def delete_files(document_id: uuid.UUID) -> None:
    shutil.rmtree(root() / str(document_id), ignore_errors=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
