"""Importing a collection from another tool (v0.18.0).

Every source — Numista (account or export file), OpenNumismat, a spreadsheet
with its columns matched to Cabinet's fields — is read by a format module in
`import_formats` into `Candidate`s: item fields as plain values, the grade as
the source wrote it, tags, catalogue refs, and photos. This module turns a
candidate into a validated `ItemCreate` (the same path the item form and CSV
import take), previews the lot without writing anything, and imports it one
item per commit, so a bad row never undoes the rows before it.

Re-importing never duplicates: each candidate carries a key that is stable
within its source (Numista's collected-item id, OpenNumismat's record id, a
row fingerprint for files), stored on the item as `import_source` +
`import_key`, and a candidate whose origin is already present is skipped.

Uploaded files are staged on disk under `IMPORT_DIR` (a temp directory by
default) so the preview and the import read the same file without a second
upload; staged files expire after a day.
"""

import hashlib
import json
import re
import shutil
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Grade, Item
from app.schemas import DESIGNATIONS, ItemCreate
from app.services import photos as photo_store

UPLOAD_MAX_BYTES = 1024 * 1024 * 1024  # an OpenNumismat file carries its photos
UPLOAD_TTL_SECONDS = 24 * 3600
PREVIEW_ROWS = 200

# Numista's grade buckets, recorded as the lowest grade of each band on both
# scales (Sheldon and PMG share the 1–70 numbers).
BUCKET_RANKS = {"g": 4, "vg": 8, "f": 12, "vf": 20, "xf": 40, "au": 50, "unc": 60}

# Schema limits, so an overlong value is trimmed with a note instead of failing the row.
TEXT_LIMITS = {
    "country": 100, "denomination": 100, "mint_mark": 20, "series": 200, "variety": 200,
    "composition": 100, "edge": 100, "shape": 50, "cert_service": 50, "cert_number": 50,
    "grade_details": 100, "serial_number": 50, "prefix_block": 50, "signatures": 200,
    "issuer": 200, "acquired_from": 200, "storage_location": 200, "sold_to": 200,
}  # fmt: skip


# ---------------------------------------------------------------- candidates


@dataclass
class Candidate:
    """One item as a source describes it, before validation."""

    row: int  # record or line number in the source, for messages
    key: str | None  # stable within the source; None = never deduplicated
    fields: dict = field(default_factory=dict)  # ItemCreate fields, loosely typed
    grade: str | None = None  # grade text as written ("MS-64", "XF", "PMG 64 EPQ")
    grade_bucket: str | None = None  # Numista's g…unc
    tags: list[str] = field(default_factory=list)
    refs: list[dict] = field(default_factory=list)  # {"catalog", "ref_code"}
    # (angle, data): bytes, a URL to fetch, or a callable that reads the bytes
    photos: list[tuple[str | None, object]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    extra_notes: list[str] = field(default_factory=list)  # appended to notes
    # Already validated by the source's own reader: (ItemCreate, grade_id).
    ready: tuple | None = None

    @property
    def label(self) -> str:
        f = self.fields
        parts = [str(f.get(k)) for k in ("country", "denomination", "year") if f.get(k)]
        if f.get("mint_mark"):
            parts.append(f'"{f["mint_mark"]}"')
        return " ".join(parts) or f"Row {self.row}"


@dataclass
class Prepared:
    candidate: Candidate
    payload: ItemCreate | None
    grade_id: int | None
    grade_label: str | None
    duplicate: bool


def fingerprint_keys(rows: list[dict]) -> list[str]:
    """Stable keys for rows that have no id of their own: a hash of the row's
    content, with an ordinal so identical rows (two of the same coin) stay
    distinct — and re-importing the same file still matches them one to one."""
    seen: Counter = Counter()
    keys = []
    for row in rows:
        digest = hashlib.sha1(
            json.dumps(row, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:20]
        seen[digest] += 1
        keys.append(f"{digest}:{seen[digest]}")
    return keys


# ---------------------------------------------------------------- value parsing


def clean(value, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit] if limit else text


def to_decimal(value) -> Decimal | None:
    """A number from a cell: 12, 12.5, "1,234.50", "1.234,50", "$ 12", "12 €"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        # the later separator is the decimal point
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        whole, _, frac = text.rpartition(",")
        text = f"{whole.replace(',', '')}.{frac}" if len(frac) != 3 else text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def to_float(value) -> float | None:
    number = to_decimal(value)
    return float(number) if number is not None else None


def to_int(value) -> int | None:
    number = to_decimal(value)
    if number is None:
        return None
    try:
        return int(number)
    except (ValueError, OverflowError):
        return None


def to_year(value) -> int | None:
    """A year from 1978, "1978", "1978-D", "1982-1993" (the first), 1978.0."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d{1,4}", str(value))
    return int(match.group()) if match else None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m", "%Y")


def to_date(value) -> date | None:
    """A date from a cell: a real date, ISO text (with or without a time), or
    D.M.Y / M/D/Y text. Slashed dates read month-first unless the first
    number can't be a month."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    text = re.split(r"[T ]", text, maxsplit=1)[0] if re.match(r"\d{4}-", text) else text
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if match:
        a, b, y = (int(g) for g in match.groups())
        y += 2000 if y < 100 else 0
        month, day = (b, a) if a > 12 else (a, b)
        try:
            return date(y, month, day)
        except ValueError:
            return None
    return None


def title_series(title: str | None) -> str | None:
    """Numista-style titles read "1 Dollar - Eisenhower Moon Landing"; the part
    after the denomination is the series."""
    text = clean(title)
    if not text:
        return None
    return text.split(" - ", 1)[1] if " - " in text else text


_REF_RE = re.compile(r"([A-Za-zÀ-ÿ][\w.À-ÿ]*)\s*#\s*([\w./\-]+)")


def parse_refs(text) -> list[dict]:
    """Catalogue references written as "KM# 203, Schön# 204" or "N# 1340"."""
    refs = []
    for catalog, number in _REF_RE.findall(str(text or "")):
        name = "numista" if catalog.upper() == "N" else catalog.lower()
        code = f"N#{number}" if name == "numista" else f"{catalog}#{number}"
        refs.append({"catalog": name[:50], "ref_code": code[:100]})
    return refs


# ---------------------------------------------------------------- grades

_ADJECTIVAL = [  # longest first, so "very fine" wins over "fine"
    ("about uncirculated", 50), ("extremely fine", 40), ("very fine", 20), ("very good", 8),
    ("uncirculated", 60), ("about good", 3), ("fine", 12), ("good", 4), ("fair", 2),
    ("poor", 1),
]  # fmt: skip
_ABBREVIATED = {
    "BU": 60, "UNC": 60, "AU": 50, "XF": 40, "EF": 40, "VF": 20, "F": 12, "VG": 8,
    "G": 4, "AG": 3, "FR": 2, "FA": 2, "PO": 1, "P": 1,
}  # fmt: skip
_NUMBERED = re.compile(r"\b(PR|PF|SP|MS|AU|XF|EF|VF|VG|F|G|AG|FR|PO|P)\s*-?\s*(\d{1,2})(\+)?")
_BARE_NUMBER = re.compile(r"(?<![\d.])(\d{1,2})(\+)?(?![\d.])")


@dataclass
class GradeMatch:
    rank: int
    strike: str | None = None
    plus: bool = False
    star: bool = False
    designations: list[str] = field(default_factory=list)
    approximate: bool = False  # an adjective or bucket, not a number


def parse_grade(text: str | None) -> GradeMatch | None:
    """Read a grade as collectors write it: "MS-64", "MS64+", "PR 69 DCAM",
    "PMG 64 EPQ", "64★", "XF", "Choice VF", "Uncirculated". None when there's
    no grade in it."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    upper = raw.upper()
    words = set(re.findall(r"[A-Z]+", upper))
    designations = [d for d in DESIGNATIONS if d in words]
    star = "★" in raw or "*" in raw or "STAR" in words
    if match := _NUMBERED.search(upper):
        prefix, number, plus = match.groups()
        strike = {"PR": "proof", "PF": "proof", "SP": "specimen"}.get(prefix)
        return GradeMatch(int(number), strike, bool(plus), star, designations)
    if match := _BARE_NUMBER.search(upper):
        number = int(match.group(1))
        if 1 <= number <= 70:
            return GradeMatch(number, None, bool(match.group(2)), star, designations)
    lower = raw.lower()
    for words_, rank in _ADJECTIVAL:
        if words_ in lower:
            return GradeMatch(rank, None, False, star, designations, approximate=True)
    for token in re.findall(r"[A-Z]+", upper):
        if token in _ABBREVIATED:
            return GradeMatch(_ABBREVIATED[token], None, False, star, designations, True)
    if "PROOF" in words:
        return GradeMatch(60, "proof", False, star, designations, approximate=True)
    return None


class GradeTable:
    """Grade rows by scale, snapping a rank to the nearest one the scale has
    at or below it (VF-22 → VF-20)."""

    def __init__(self, db: Session):
        self.rows: dict[str, list[Grade]] = {"sheldon": [], "pmg": []}
        for grade in db.execute(select(Grade).order_by(Grade.rank)).scalars():
            self.rows.setdefault(grade.scale, []).append(grade)

    def code(self, grade_id: int | None) -> str | None:
        for rows in self.rows.values():
            for grade in rows:
                if grade.id == grade_id:
                    return grade.code
        return None

    def find(self, scale: str, rank: int) -> tuple[Grade | None, bool]:
        """(grade, exact) — the grade at `rank`, or the nearest lower one."""
        rows = self.rows.get(scale) or []
        below = [g for g in rows if g.rank <= rank]
        if not below:
            return (rows[0], False) if rows else (None, False)
        return below[-1], below[-1].rank == rank


def _scale(item_type: str) -> str:
    return "pmg" if item_type == "note" else "sheldon"


def resolve_grade(candidate: Candidate, grades: GradeTable) -> tuple[int | None, str | None]:
    """Apply the candidate's grade to its fields; returns (grade_id, label)."""
    f = candidate.fields
    scale = _scale(f.get("type") or "coin")
    if candidate.grade_bucket:
        bucket = candidate.grade_bucket.lower()
        rank = BUCKET_RANKS.get(bucket)
        grade, _ = grades.find(scale, rank) if rank else (None, False)
        if grade is None:
            candidate.messages.append(f"Grade {candidate.grade_bucket!r} not recognized")
            return None, None
        if not candidate.grade:
            candidate.messages.append(
                f"Numista's {bucket.upper()} band recorded as {grade.code}, its lowest grade"
            )
            return grade.id, grade.code
    if not candidate.grade:
        return None, None
    match = parse_grade(candidate.grade)
    if match is None:
        candidate.messages.append(f"Grade {candidate.grade!r} not recognized — kept in the notes")
        candidate.extra_notes.append(f"Grade as imported: {candidate.grade}")
        return None, None
    if match.strike and scale == "sheldon":
        f.setdefault("strike", match.strike)
    grade, exact = grades.find(scale, match.rank)
    if grade is None:
        return None, None
    if match.plus:
        f.setdefault("grade_plus", True)
    if match.star:
        f.setdefault("grade_star", True)
    if match.designations:
        f.setdefault("designations", match.designations)
    if match.approximate or not exact:
        candidate.messages.append(f"Grade {candidate.grade!r} recorded as {grade.code}")
    return grade.id, grade.code


# ---------------------------------------------------------------- validation


def prepare(db: Session, source: str, candidates: list[Candidate]) -> list[Prepared]:
    """Validate each candidate into an ItemCreate and flag ones already
    imported. Nothing is written."""
    grades = GradeTable(db)
    keys = [c.key for c in candidates if c.key]
    existing = set()
    for start in range(0, len(keys), 500):
        existing.update(
            db.execute(
                select(Item.import_key).where(
                    Item.import_source == source, Item.import_key.in_(keys[start : start + 500])
                )
            ).scalars()
        )
    if source == "cabinet":
        # An export taken from this very Cabinet: its ids are already here.
        ids = []
        for key in keys:
            try:
                ids.append(uuid.UUID(key))
            except ValueError:
                continue
        for start in range(0, len(ids), 500):
            existing.update(
                str(i)
                for i in db.execute(
                    select(Item.id).where(Item.id.in_(ids[start : start + 500]))
                ).scalars()
            )
    out = []
    for cand in candidates:
        if cand.error:
            out.append(Prepared(cand, None, None, None, False))
            continue
        if cand.ready is not None:
            payload, grade_id = cand.ready
            grade_id = grade_id if grade_id is not None else payload.grade_id
            label = grades.code(grade_id)
            duplicate = bool(cand.key and cand.key in existing)
            out.append(Prepared(cand, payload, grade_id, label, duplicate))
            continue
        grade_id, grade_label = resolve_grade(cand, grades)
        f = cand.fields
        for key, limit in TEXT_LIMITS.items():
            value = f.get(key)
            if isinstance(value, str) and len(value) > limit:
                f[key] = value[:limit]
                cand.messages.append(f"{key.replace('_', ' ')} shortened to {limit} characters")
        if cand.extra_notes:
            f["notes"] = "\n".join([n for n in [f.get("notes"), *cand.extra_notes] if n])
        payload = None
        try:
            payload = ItemCreate(**f, tags=cand.tags[:50], catalog_refs=_dedupe(cand.refs))
        except ValidationError as exc:
            err = exc.errors()[0]
            where = ".".join(str(p) for p in err.get("loc", ()))
            cand.error = f"{where}: {err['msg']}" if where else err["msg"]
        out.append(
            Prepared(cand, payload, grade_id, grade_label, bool(cand.key and cand.key in existing))
        )
    return out


def _dedupe(refs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for ref in refs:
        key = (ref["catalog"].lower(), ref["ref_code"])
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def preview(prepared: list[Prepared]) -> dict:
    """Counts plus the first rows, as the preview shows them."""
    rows = []
    for p in prepared[:PREVIEW_ROWS]:
        c = p.candidate
        status = "error" if c.error else "duplicate" if p.duplicate else "new"
        f = p.payload.model_dump() if p.payload else c.fields
        rows.append(
            {
                "row": c.row,
                "status": status,
                "label": c.label,
                "grade": p.grade_label,
                "status_value": f.get("status"),
                "type": f.get("type"),
                "quantity": f.get("quantity"),
                "price": f.get("acquisition_price"),
                "currency": f.get("currency"),
                "photos": len(c.photos),
                "messages": c.messages,
                "error": c.error,
            }
        )
    return {
        "total": len(prepared),
        "new": sum(1 for p in prepared if not p.candidate.error and not p.duplicate),
        "duplicates": sum(1 for p in prepared if not p.candidate.error and p.duplicate),
        "errors": sum(1 for p in prepared if p.candidate.error),
        "warnings": sum(1 for p in prepared if p.candidate.messages),
        "photos": sum(len(p.candidate.photos) for p in prepared),
        "rows": rows,
    }


# ---------------------------------------------------------------- import


def run(
    db: Session,
    source: str,
    source_label: str,
    prepared: list[Prepared],
    fetch_remote_photos: bool = False,
) -> dict:
    """Create the new items, one commit each. Photos given as bytes are always
    stored; photos given as URLs only when `fetch_remote_photos`."""
    from app.routers.items import _build_item, record_event
    from app.routers.photos import _create_photo

    # Anything the readers had to create for validation (a Cabinet export's
    # sets) is kept before the first item, so one failing row can't take it back.
    db.commit()
    created = skipped = photos_added = photos_failed = 0
    errors: list[dict] = []
    for p in prepared:
        c = p.candidate
        if c.error or p.payload is None:
            errors.append({"row": c.row, "error": c.error or "invalid"})
            continue
        if p.duplicate:
            skipped += 1
            continue
        try:
            item = _build_item(db, p.payload, p.grade_id)
            item.import_source = source
            item.import_key = c.key
            db.add(item)
            db.flush()
            record_event(db, item.id, "created", {"via": ["import", source_label]})
            db.commit()
        except (ValueError, HTTPException) as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            errors.append({"row": c.row, "error": str(detail)})
            continue
        created += 1
        for angle, data in c.photos:
            if callable(data):
                data = data()
                if not data:
                    photos_failed += 1
                    continue
            if isinstance(data, str):
                if not fetch_remote_photos:
                    continue
                try:
                    data = photo_store.fetch_remote_image(data)
                except (ValueError, photo_store.RemoteImageUnavailable):
                    photos_failed += 1
                    continue
            try:
                _create_photo(db, item.id, data, angle)
                photos_added += 1
            except HTTPException:
                db.rollback()
                photos_failed += 1
    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "photos_added": photos_added,
        "photos_failed": photos_failed,
    }


# ---------------------------------------------------------------- staged uploads


def upload_dir() -> Path:
    configured = get_settings().import_dir
    path = Path(configured) if configured else Path(tempfile.gettempdir()) / "cabinet-imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prune(directory: Path) -> None:
    cutoff = time.time() - UPLOAD_TTL_SECONDS
    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        except OSError:
            pass


def stage_upload(stream, filename: str | None) -> dict:
    """Copy an upload to disk (refusing more than UPLOAD_MAX_BYTES) and return
    its id. Older staged files are pruned on the way."""
    directory = upload_dir()
    _prune(directory)
    upload_id = uuid.uuid4().hex
    folder = directory / upload_id
    folder.mkdir()
    target = folder / "upload"
    size = 0
    with target.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > UPLOAD_MAX_BYTES:
                out.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise ValueError("The file is larger than 1 GB")
            out.write(chunk)
    name = clean(filename, 200) or "upload"
    (folder / "name").write_text(name, encoding="utf-8")
    return {"upload_id": upload_id, "filename": name, "size": size, "path": target}


def staged(upload_id: str) -> tuple[Path, str]:
    """The staged file and its original name. Raises LookupError."""
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise LookupError("Unknown upload")
    folder = upload_dir() / upload_id
    target = folder / "upload"
    if not target.exists():
        raise LookupError("That upload has expired — choose the file again")
    name_file = folder / "name"
    name = name_file.read_text(encoding="utf-8") if name_file.exists() else "upload"
    return target, name


def discard(upload_id: str) -> None:
    if re.fullmatch(r"[0-9a-f]{32}", upload_id):
        shutil.rmtree(upload_dir() / upload_id, ignore_errors=True)
