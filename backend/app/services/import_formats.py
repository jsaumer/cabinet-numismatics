"""Readers for each import source (v0.18.0), producing `importing.Candidate`s.

- `spreadsheet` — any CSV or Excel file, its columns matched to Cabinet's
  fields (suggested from the header names, adjustable in the preview). Covers
  tools without a dedicated reader: uCoin, CoinSnap, Colnect (whose export has
  a few lines above the header), PCGS's registry, a hand-kept sheet.
- `cabinet` — Cabinet's own export (CSV or XLSX), read in full by the same
  row reader as `POST /api/items/import`.
- `numista_file` — the CSV/XLSX export from numista.com ("My coins" → export).
  Users choose its columns, so it is read by header name.
- `opennumismat` — an OpenNumismat collection (`.db`, SQLite). Up to schema
  10 the purchase and sale live in `coins`; schema 11 (OpenNumismat 1.11)
  moved them to a `prices` table. Both are read, and photos come along.
- `numista_account` — the user's own collection through the Numista API
  (`numista.fetch_collection`), with catalogue details per type.
"""

import csv
import io
import re
import sqlite3
import zipfile
from datetime import date, datetime, time
from functools import partial
from pathlib import Path

from app.services.importing import (
    Candidate,
    clean,
    fingerprint_keys,
    parse_refs,
    title_series,
    to_date,
    to_decimal,
    to_float,
    to_int,
    to_year,
)

FORMATS = ("spreadsheet", "cabinet", "numista_file", "opennumismat")
# Columns only Cabinet's own export has, together.
CABINET_HEADERS = {"type", "denomination", "grade_scale", "catalog_refs", "custom_fields"}
HEADER_SCAN_ROWS = 15


class FormatError(ValueError):
    """The file isn't what the chosen format expects."""


# ---------------------------------------------------------------- reading tables


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_grid(path: Path) -> list[list]:
    """Every row of the file's first sheet (XLSX) or of the CSV, as lists."""
    with path.open("rb") as fh:
        magic = fh.read(4)
    if magic.startswith(b"PK"):
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException

        # A file object, not the path: openpyxl judges a path by its extension,
        # and staged uploads have none.
        with path.open("rb") as fh:
            try:
                wb = load_workbook(fh, read_only=True, data_only=True)
            except (zipfile.BadZipFile, KeyError, OSError, InvalidFileException) as exc:
                raise FormatError(f"Couldn't read the Excel file: {exc}") from None
            try:
                sheet = wb.worksheets[0]
                return [list(row) for row in sheet.iter_rows(values_only=True)]
            finally:
                wb.close()
    text = _decode(path.read_bytes())
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def guess_header_row(grid: list[list]) -> int:
    """The first row that looks like a header: at least 60% as many filled
    cells as the fullest of the first rows (skips Colnect-style preambles)."""
    head = grid[:HEADER_SCAN_ROWS]
    counts = [sum(1 for cell in row if clean(cell)) for row in head]
    if not counts or max(counts) == 0:
        return 0
    threshold = max(counts) * 0.6
    return next(i for i, n in enumerate(counts) if n >= threshold)


def read_table(path: Path, skip_rows: int | None = None) -> tuple[list[str], list[dict], int]:
    """(headers, rows as dicts, header row index). Blank rows are dropped;
    blank or repeated headers get a column letter."""
    grid = read_grid(path)
    if not grid:
        raise FormatError("The file is empty")
    start = guess_header_row(grid) if skip_rows is None else max(0, skip_rows)
    if start >= len(grid):
        raise FormatError("There is no header row after the skipped lines")
    headers: list[str] = []
    for index, cell in enumerate(grid[start]):
        name = clean(cell) or f"Column {index + 1}"
        while name in headers:
            name = f"{name} ({index + 1})"
        headers.append(name)
    rows = []
    for raw in grid[start + 1 :]:
        if not any(clean(cell) for cell in raw):
            continue
        rows.append({h: (raw[i] if i < len(raw) else None) for i, h in enumerate(headers)})
    return headers, rows, start


def detect(path: Path) -> str:
    """The likeliest format for a file."""
    with path.open("rb") as fh:
        magic = fh.read(16)
    if magic.startswith(b"SQLite format 3\x00"):
        return "opennumismat"
    try:
        headers, _, _ = read_table(path)
    except (FormatError, UnicodeDecodeError, csv.Error):
        return "spreadsheet"
    lowered = {h.lower() for h in headers}
    if CABINET_HEADERS <= lowered:
        return "cabinet"
    if (
        any(h.startswith("n# number") for h in lowered)
        or {
            "face value",
            "gregorian year",
        }
        <= lowered
    ):
        return "numista_file"
    return "spreadsheet"


# ---------------------------------------------------------------- spreadsheet

# Cabinet fields a column can fill: (key, label, kind, header names that suggest it).
FIELDS = [
    ("type", "Type (coin / note)", "type", ["type", "category", "item type", "kind"]),
    ("status", "Status", "status", ["status", "state"]),
    ("country", "Country", "text", ["country", "issuer", "issuing country", "land", "nation"]),
    ("denomination", "Denomination", "text",
     ["denomination", "face value", "value", "nominal", "facevalue", "denom"]),
    ("year", "Year", "year", ["year", "gregorian year", "date", "issued on", "issue year"]),
    ("mint_mark", "Mint mark", "text", ["mint mark", "mintmark", "mint"]),
    ("series", "Series", "text", ["series", "title", "name", "subject", "description"]),
    ("variety", "Variety", "text", ["variety", "variant"]),
    ("composition", "Composition", "text", ["composition", "material", "metal"]),
    ("weight_g", "Weight (g)", "float", ["weight", "weight (g)", "weight g"]),
    ("fineness", "Fineness", "fineness", ["fineness", "purity"]),
    ("diameter_mm", "Diameter (mm)", "float", ["diameter", "diameter (mm)", "size"]),
    ("mintage", "Mintage", "int", ["mintage"]),
    ("grade", "Grade", "grade", ["grade", "condition", "quality"]),
    ("cert_service", "Grading service", "text",
     ["grading service", "grader", "third-party grading", "grading company", "tpg"]),
    ("cert_number", "Cert number", "text",
     ["cert", "cert number", "certification", "slab number", "cert #", "certificate"]),
    ("serial_number", "Serial number", "text", ["serial number", "serial"]),
    ("signatures", "Signatures", "text", ["signatures", "signature"]),
    ("quantity", "Quantity", "int", ["quantity", "qty", "count", "number of items"]),
    ("acquisition_date", "Acquired on", "date",
     ["acquisition date", "purchase date", "bought", "date acquired", "paydate"]),
    ("acquisition_price", "Price paid", "money",
     ["price paid", "purchase price", "buying price", "cost", "paid", "price"]),
    ("currency", "Currency of the price", "currency", ["price currency", "currency code"]),
    ("acquired_from", "Acquired from", "text",
     ["acquired from", "acquisition place", "seller", "source", "bought from", "dealer"]),
    ("storage_location", "Storage location", "text", ["storage location", "storage", "location"]),
    ("sold_date", "Sold on", "date", ["sold date", "sale date", "date sold"]),
    ("sold_price", "Sold for", "money", ["sold price", "sale price", "sold for"]),
    ("sold_to", "Sold to", "text", ["sold to", "buyer"]),
    ("catalog_refs", "Catalogue numbers (KM# 203…)", "refs",
     ["catalog", "catalogue", "catalog number", "catalog codes", "references", "reference",
      "km", "km#", "krause"]),
    ("numista", "Numista number", "numista", ["n# number", "numista", "numista number", "n#"]),
    ("tags", "Tags (comma-separated)", "tags", ["tags", "labels", "collection"]),
    ("notes", "Notes", "notes", ["notes", "note", "comment", "comments", "remarks", "my comments"]),
]  # fmt: skip
FIELD_KEYS = [f[0] for f in FIELDS]
_KINDS = {key: kind for key, _, kind, _ in FIELDS}


def _norm(header: str) -> str:
    """Lower case, with underscores and punctuation as spaces ("Cert_Number" →
    "cert number")."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w#]+|_", " ", header.lower())).strip()


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Cabinet field → column, by exact header synonyms first, then by a
    synonym appearing inside the header. Each column is used at most once."""
    normalized = {h: _norm(h) for h in headers}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for exact in (True, False):
        for key, _, _, synonyms in FIELDS:
            if key in mapping:
                continue
            for synonym in [key.replace("_", " "), *synonyms]:
                target = _norm(synonym)
                found = next(
                    (
                        h
                        for h in headers
                        if h not in used
                        and (
                            normalized[h] == target
                            if exact
                            else len(target) > 3 and target in normalized[h]
                        )
                    ),
                    None,
                )
                if found:
                    mapping[key] = found
                    used.add(found)
                    break
    return mapping


def _item_type(value, default: str) -> str:
    text = (clean(value) or "").lower()
    if any(word in text for word in ("banknote", "bank note", "paper", "note", "bill")):
        return "note"
    if "coin" in text:
        return "coin"
    return default


def _status(value, default: str) -> str:
    text = (clean(value) or "").lower()
    if not text:
        return default
    if "sold" in text:
        return "sold"
    if any(word in text for word in ("wish", "want", "missing", "ordered", "bidding")):
        return "wishlist"
    return "owned"


def _fineness(value) -> float | None:
    number = to_decimal(value)
    if number is None or number <= 0:
        return None
    if number > 1000:  # 9999
        number /= 10000
    elif number > 1:  # 900, 999.9, or a percentage like 90
        number /= 1000 if number > 100 else 100
    return float(number) if 0 < number <= 1 else None


def _currency_code(value) -> str | None:
    text = (clean(value) or "").upper()
    return text if re.fullmatch(r"[A-Z]{3}", text) else None


def spreadsheet_candidates(
    rows: list[dict], mapping: dict[str, str], defaults: dict
) -> list[Candidate]:
    """Rows of any table, read through a field → column mapping. `defaults`
    fill what the file doesn't say: type, status, currency, country."""
    keys = fingerprint_keys(rows)
    out = []
    for index, row in enumerate(rows):
        cand = Candidate(row=index + 1, key=keys[index])
        f = cand.fields
        get = _mapped_getter(row, mapping)
        f["type"] = _item_type(get("type"), defaults.get("type") or "coin")
        f["status"] = _status(get("status"), defaults.get("status") or "owned")
        f["currency"] = _currency_code(get("currency")) or defaults.get("currency") or "USD"
        for key in FIELD_KEYS:
            if key in ("type", "status", "currency") or key not in mapping:
                continue
            value, kind = get(key), _KINDS[key]
            if kind == "text":
                if (text := clean(value)) is not None:
                    f[key] = text
            elif kind == "year":
                if (year := to_year(value)) is not None:
                    f[key] = year
            elif kind == "int":
                if (number := to_int(value)) is not None:
                    f[key] = number
            elif kind in ("float", "money"):
                if (number := to_float(value)) is not None:
                    f[key] = number
            elif kind == "fineness":
                if (number := _fineness(value)) is not None:
                    f[key] = number
            elif kind == "date":
                if (day := to_date(value)) is not None:
                    f[key] = day
                elif clean(value):
                    cand.messages.append(
                        f"{key.replace('_', ' ')} {value!r} isn't a date — skipped"
                    )
            elif kind == "grade":
                cand.grade = clean(value)
            elif kind == "refs":
                refs = parse_refs(value)
                if not refs and clean(value):
                    refs = [
                        {
                            "catalog": _norm(mapping[key])[:50] or "ref",
                            "ref_code": clean(value, 100),
                        }
                    ]
                cand.refs.extend(refs)
            elif kind == "numista":
                if digits := re.search(r"\d+", str(value or "")):
                    cand.refs.append({"catalog": "numista", "ref_code": f"N#{digits.group()}"})
            elif kind == "tags":
                cand.tags.extend(
                    t for t in (clean(x, 50) for x in re.split(r"[,;|]", str(value or ""))) if t
                )
            elif kind == "notes":
                if text := str(value or "").strip():
                    f["notes"] = text
        if "country" not in f and defaults.get("country"):
            f["country"] = defaults["country"]
        if "quantity" in f and f["quantity"] < 1:
            f.pop("quantity")
        _require(cand)
        out.append(cand)
    return out


def _mapped_getter(row: dict, mapping: dict[str, str]):
    return lambda key: row.get(mapping[key]) if key in mapping else None


def _first_getter(row: dict):
    """The first of several header names that has a value in this row."""
    return lambda *names: next((row[n] for n in names if clean(row.get(n)) is not None), None)


def _column_getter(row: sqlite3.Row, columns: set[str]):
    return lambda col: row[col] if col in columns else None


def _require(cand: Candidate) -> None:
    missing = [k for k in ("country", "denomination", "year") if cand.fields.get(k) in (None, "")]
    if missing:
        cand.error = "Missing " + ", ".join(m.replace("_", " ") for m in missing)


# ---------------------------------------------------------------- Cabinet export


def _cell_text(value) -> str:
    """A cell as the CSV export writes it: Excel's numbers and dates back to text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def cabinet_candidates(rows: list[dict], db) -> list[Candidate]:
    """Rows of Cabinet's own export, every field included. The exported `id`
    is the import key, so a second import — here or into another Cabinet —
    skips what's already there."""
    from pydantic import ValidationError

    from app.routers.items import _row_to_payload

    out = []
    for index, raw in enumerate(rows):
        row = {(k or "").strip(): _cell_text(v) for k, v in raw.items()}
        cand = Candidate(row=index + 1, key=clean(row.get("id"), 300))
        for key in ("country", "denomination", "mint_mark"):
            if value := clean(row.get(key)):
                cand.fields[key] = value
        if (year := to_year(row.get("year"))) is not None:
            cand.fields["year"] = year
        try:
            with db.no_autoflush:
                cand.ready = _row_to_payload(row, db)
        except (ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                err = exc.errors()[0]
                where = ".".join(str(p) for p in err.get("loc", ()))
                cand.error = f"{where}: {err['msg']}" if where else err["msg"]
            else:
                cand.error = str(exc)
        out.append(cand)
    return out


# ---------------------------------------------------------------- numista export file


def numista_file_candidates(rows: list[dict], defaults: dict) -> list[Candidate]:
    """Rows of numista.com's collection export (CSV or XLSX), by header name."""
    keys = fingerprint_keys(rows)
    out = []
    for index, raw in enumerate(rows):
        row = {(k or "").strip().lower(): v for k, v in raw.items()}
        get = _first_getter(row)
        cand = Candidate(row=index + 1, key=keys[index])
        f = cand.fields
        kind = (clean(get("type")) or "").lower()
        f["type"] = "note" if "banknote" in kind or "note" in kind else "coin"
        f["status"] = "owned"
        f["country"] = clean(get("country", "issuer", "ruling authority"))
        face, unit = clean(get("face value")), clean(get("currency"))
        f["denomination"] = " ".join(p for p in (face, unit) if p) or clean(get("title"))
        f["year"] = to_year(get("gregorian year", "year", "year range"))
        if clean(get("year range")) and not clean(get("year", "gregorian year")):
            cand.messages.append(
                f"Undated issue ({get('year range')}) — recorded as its first year"
            )
        if mark := clean(get("mintmark", "mint mark")):
            f["mint_mark"] = mark
        if series := title_series(get("title")):
            f["series"] = series
        for key, header in (("composition", "composition"), ("shape", "shape")):
            if value := clean(get(header)):
                f[key] = value
        if (weight := to_float(get("weight"))) and weight > 0:
            f["weight_g"] = weight
        if f["type"] == "coin" and (size := to_float(get("diameter"))) and 0 < size <= 1000:
            f["diameter_mm"] = size
        if (quantity := to_int(get("quantity"))) and quantity >= 1:
            f["quantity"] = quantity
        grade = (clean(get("grade")) or "").lower()
        if grade in ("g", "vg", "f", "vf", "xf", "au", "unc"):
            cand.grade_bucket = grade
        elif grade:
            cand.grade = grade
        for header, value in row.items():
            if price := re.fullmatch(r"buying price \(([a-z]{3})\)", header):
                if (amount := to_float(value)) is not None:
                    f["acquisition_price"] = amount
                    f["currency"] = price.group(1).upper()
        f.setdefault("currency", defaults.get("currency") or "USD")
        if day := to_date(get("acquisition date")):
            f["acquisition_date"] = day
        if place := clean(get("acquisition place")):
            f["acquired_from"] = place
        if storage := clean(get("storage location")):
            f["storage_location"] = storage
        if serial := clean(get("serial number")):
            f["serial_number" if f["type"] == "note" else "cert_number"] = serial
        if company := clean(get("third-party grading", "grading company")):
            f["cert_service"] = company.split()[0]
            if parsed := re.sub(r"^\S+\s*", "", company):
                cand.grade = cand.grade or parsed
        if slab := clean(get("slab number")):
            f["cert_number"] = slab
        if slab_grade := clean(get("slab grade")):
            cand.grade = slab_grade
        if cac := (clean(get("cac sticker")) or "").lower():
            if cac in ("green", "gold"):
                f["cac_sticker"] = cac
        notes = [clean(get(h)) for h in ("comment", "private comment", "public comment", "details")]
        if any(notes):
            f["notes"] = "\n".join(n for n in notes if n)
        for header in row:
            if header.startswith("n# number") and (
                digits := re.search(r"\d+", str(row[header] or ""))
            ):
                cand.refs.append({"catalog": "numista", "ref_code": f"N#{digits.group()}"})
        cand.refs.extend(parse_refs(get("references", "reference")))
        if collection := clean(get("collection"), 50):
            cand.tags.append(collection)
        _require(cand)
        out.append(cand)
    return out


# ---------------------------------------------------------------- OpenNumismat

ON_STATUS = {
    "owned": "owned", "duplicate": "owned", "replacement": "owned", "sale": "owned",
    "sold": "sold",
    "wish": "wishlist", "ordered": "wishlist", "bidding": "wishlist", "missing": "wishlist",
}  # fmt: skip
ON_SKIPPED_STATUS = {"pass": "lost at auction", "demo": "a demo record"}
ON_PHOTO_COLUMNS = [
    ("obverseimg", "obverse"), ("reverseimg", "reverse"), ("edgeimg", "edge"),
    *((f"photo{n}", "other") for n in range(1, 7)),
]  # fmt: skip
ON_EMPTY_DATE = "2000-01-01"  # OpenNumismat's old "no date" placeholder
CATALOG_FIELD_IDS = {27: "catalognum1", 28: "catalognum2", 29: "catalognum3", 30: "catalognum4"}


def _on_date(value):
    text = clean(value)
    return None if not text or text == ON_EMPTY_DATE else to_date(text)


def _on_money(value) -> float | None:
    number = to_float(value)
    return number if number is not None and number > 0 else None


def open_sqlite(path: Path) -> sqlite3.Connection:
    """Open an uploaded SQLite file read-only, checking it's an OpenNumismat
    collection."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise FormatError(f"Not a readable SQLite database: {exc}") from None
    if "coins" not in tables:
        conn.close()
        raise FormatError("Not an OpenNumismat collection (it has no coins table)")
    return conn


class BlobReader:
    """Reads OpenNumismat photos one at a time, only when an item is actually
    imported — a collection file can hold hundreds of megabytes of them."""

    def __init__(self, path: Path):
        self.path = path
        self.conn: sqlite3.Connection | None = None

    def read(self, photo_id: int) -> bytes:
        if self.conn is None:
            self.conn = open_sqlite(self.path)
        row = self.conn.execute("select image from photos where id = ?", (photo_id,)).fetchone()
        return bytes(row[0]) if row is not None and row[0] else b""

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def opennumismat_candidates(path: Path, defaults: dict) -> tuple[list[Candidate], BlobReader]:
    """Candidates whose photos are read lazily through the returned reader;
    close it when done."""
    conn = open_sqlite(path)
    reader = BlobReader(path)
    try:
        return _opennumismat(conn, defaults, reader), reader
    finally:
        conn.close()


def _opennumismat(
    conn: sqlite3.Connection, defaults: dict, reader: "BlobReader"
) -> list[Candidate]:
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    columns = {r[1] for r in conn.execute("pragma table_info(coins)")}
    has = columns.__contains__

    # Catalogue column labels the user gave ("Krause"), when renamed from "1#".
    labels: dict[str, str] = {}
    if "fields" in tables:
        for fid, title in conn.execute("select id, title from fields"):
            column = CATALOG_FIELD_IDS.get(fid)
            name = re.sub(r"[#\s]+$", "", str(title or "")).strip()
            if column and name and not name.isdigit():
                labels[column] = name

    prices: dict[tuple[int, str], sqlite3.Row] = {}
    if "prices" in tables:
        price_cols = {r[1] for r in conn.execute("pragma table_info(prices)")}
        if {"coin_id", "action"} <= price_cols:
            for row in conn.execute("select * from prices order by id"):
                prices.setdefault((row["coin_id"], row["action"]), row)

    tags: dict[int, list[str]] = {}
    if {"tags", "coins_tags"} <= tables:
        for coin_id, tag in conn.execute(
            "select ct.coin_id, t.tag from coins_tags ct join tags t on t.id = ct.tag_id"
        ):
            if name := clean(tag, 50):
                tags.setdefault(coin_id, []).append(name)

    photo_ids = [col for col, _ in ON_PHOTO_COLUMNS if has(col)]
    angles = dict(ON_PHOTO_COLUMNS)
    with_images: set[int] = set()
    if "photos" in tables:
        with_images = {r[0] for r in conn.execute("select id from photos where image is not null")}
    out = []
    for index, row in enumerate(conn.execute("select * from coins order by id")):
        v = _column_getter(row, columns)
        cand = Candidate(row=index + 1, key=f"{row['id']}:{clean(v('createdat')) or ''}")
        f = cand.fields
        status = (clean(v("status")) or "owned").lower()
        if status in ON_SKIPPED_STATUS:
            cand.error = f"Skipped: {ON_SKIPPED_STATUS[status]} (status {status!r})"
        f["status"] = ON_STATUS.get(status, "owned")
        category = (clean(v("category")) or "").lower()
        is_note = "note" in category or (
            not category
            and (clean(v("signature")) or to_float(v("width")))
            and not to_float(v("diameter"))
        )
        f["type"] = "note" if is_note else "coin"
        f["country"] = clean(v("country"))
        amount, unit = to_decimal(v("value")), clean(v("unit"))
        amount_text = format(amount.normalize(), "f") if amount is not None else None
        f["denomination"] = " ".join(p for p in (amount_text, unit) if p) or clean(v("title"))
        f["year"] = to_year(v("year")) or to_year(v("issuedate")) or to_year(v("dateemis"))
        for key, col in (
            ("mint_mark", "mintmark"), ("variety", "variety"), ("edge", "edge"),
            ("shape", "shape"), ("storage_location", "storage"), ("issuer", "emitent"),
            ("signatures", "signature"), ("cert_service", "grader"),
        ):  # fmt: skip
            if value := clean(v(col)):
                f[key] = value
        if series := clean(v("series")) or clean(v("subjectshort")):
            f["series"] = series
        material = [clean(v(c)) for c in ("material", "material2") if clean(v(c))]
        if material or clean(v("composition")):
            f["composition"] = ", ".join(material) or clean(v("composition"))
        if fineness := _fineness(v("fineness")):
            f["fineness"] = fineness
        for key, col in (
            ("weight_g", "weight"),
            ("diameter_mm", "diameter"),
            ("thickness_mm", "thickness"),
        ):
            if (number := to_float(v(col))) and number > 0:
                f[key] = number
        if f["type"] == "note":
            f.pop("diameter_mm", None)
            f.pop("thickness_mm", None)
        if (mintage := to_int(v("mintage"))) is not None and mintage >= 0:
            f["mintage"] = mintage
        if (quantity := to_int(v("quantity"))) and quantity >= 1:
            f["quantity"] = quantity
        cand.grade = clean(v("grade"))
        if quality := clean(v("quality")):
            if "proof" in quality.lower() and f["type"] == "coin":
                f["strike"] = "proof"
        if f.get("cert_service") and (barcode := clean(v("barcode"))):
            f["cert_number"] = barcode
        if defect := clean(v("defect")):
            f["grade_details"] = defect

        # Purchase and sale: columns on coins (schema ≤10), or `prices` rows (11).
        buy, sell = prices.get((row["id"], "buy")), prices.get((row["id"], "sell"))
        currency = defaults.get("currency") or "USD"
        if buy is not None:
            price, total = _on_money(buy["price"]), _on_money(_col(buy, "total_price"))
            f["acquisition_date"] = _on_date(buy["date"])
            f["acquired_from"] = clean(_col(buy, "counterparty")) or clean(_col(buy, "place"))
            currency = (clean(_col(buy, "currency")) or "").upper() or currency
        else:
            price, total = _on_money(v("payprice")), _on_money(v("totalpayprice"))
            f["acquisition_date"] = _on_date(v("paydate"))
            f["acquired_from"] = clean(v("saller")) or clean(v("payplace"))
        if price is not None or total is not None:
            f["acquisition_price"] = price if price is not None else total
            if price is not None and total is not None and total > price:
                f["acquisition_fees"] = round(total - price, 2)
        if sell is not None:
            sold, net = _on_money(sell["price"]), _on_money(_col(sell, "total_price"))
            f["sold_date"] = _on_date(sell["date"])
            f["sold_to"] = clean(_col(sell, "counterparty")) or clean(_col(sell, "place"))
        else:
            sold, net = _on_money(v("saleprice")), _on_money(v("totalsaleprice"))
            f["sold_date"] = _on_date(v("saledate"))
            f["sold_to"] = clean(v("buyer")) or clean(v("saleplace"))
        if sold is not None:
            f["sold_price"] = sold
            if net is not None and net < sold:
                f["sold_fees"] = round(sold - net, 2)
        f["currency"] = currency if re.fullmatch(r"[A-Z]{3}", currency) else "USD"
        if currency != f["currency"]:
            cand.messages.append(f"Currency {currency!r} isn't an ISO code — recorded as USD")
        for key in ("acquisition_date", "acquired_from", "sold_date", "sold_to"):
            if f.get(key) is None:
                f.pop(key, None)

        for col in ("catalognum1", "catalognum2", "catalognum3", "catalognum4"):
            text = clean(v(col))
            if not text:
                continue
            refs = parse_refs(text)
            if not refs:
                catalog = labels.get(col, "ref")
                refs = [{"catalog": catalog.lower()[:50], "ref_code": f"{catalog}#{text}"[:100]}]
            cand.refs.extend(refs)
        notes = [str(v(col) or "").strip() for col in ("note", "features", "url")]
        if any(notes):
            f["notes"] = "\n".join(n for n in notes if n)
        cand.tags.extend(tags.get(row["id"], []))

        for col in photo_ids:
            if photo_id := to_int(v(col)):
                if photo_id in with_images:
                    cand.photos.append((angles[col], partial(reader.read, photo_id)))
        if not cand.error:
            _require(cand)
        out.append(cand)
    return out


def _col(row: sqlite3.Row, name: str):
    return row[name] if name in row.keys() else None


# ---------------------------------------------------------------- Numista account


def numista_account_candidates(items: list[dict], types: dict[int, dict]) -> list[Candidate]:
    """The user's Numista collection (`/users/{id}/collected_items`), with
    catalogue fields per type where `types` has them (`numista.catalogue_fields`)."""
    out = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        type_ = item.get("type") if isinstance(item.get("type"), dict) else {}
        issue = item.get("issue") if isinstance(item.get("issue"), dict) else {}
        type_id = type_.get("id")
        cand = Candidate(row=index + 1, key=str(item.get("id")) if item.get("id") else None)
        f = cand.fields
        category = str(type_.get("category") or "coin")
        if category == "exonumia":
            cand.error = "Skipped: exonumia (tokens, medals) — Cabinet holds coins and notes"
        details = types.get(type_id, {}) if isinstance(type_id, int) else {}
        f.update({k: v for k, v in details.items() if k not in ("year",)})
        f["type"] = "note" if category == "banknote" else "coin"
        f["status"] = "owned"
        issuer = type_.get("issuer") if isinstance(type_.get("issuer"), dict) else {}
        f.setdefault("country", clean(issuer.get("name"), 100))
        if not f.get("denomination"):
            title = clean(type_.get("title"))
            f["denomination"] = (title or "").split(" - ", 1)[0] or None
            if title and isinstance(type_id, int):
                cand.messages.append("Denomination taken from the type's title")
        if not f.get("series") and (series := title_series(type_.get("title"))):
            if series != f.get("denomination"):
                f["series"] = series
        f["year"] = (
            _int(issue.get("gregorian_year"))
            or _int(issue.get("year"))
            or _int(issue.get("min_year"))
        )
        if not issue.get("is_dated", True) and issue.get("min_year"):
            cand.messages.append("Undated issue — recorded as its first year")
        if mark := clean(issue.get("mint_letter")):
            f["mint_mark"] = mark
        if isinstance(issue.get("mintage"), int) and issue["mintage"] >= 0:
            f["mintage"] = issue["mintage"]
        if (quantity := _int(item.get("quantity"))) and quantity >= 1:
            f["quantity"] = quantity
        if isinstance(item.get("weight"), (int, float)) and item["weight"] > 0:
            f["weight_g"] = float(item["weight"])
        if (
            f["type"] == "coin"
            and isinstance(item.get("size"), (int, float))
            and 0 < item["size"] <= 1000
        ):
            f["diameter_mm"] = float(item["size"])
        if f["type"] == "note":
            f.pop("diameter_mm", None)
        grade = str(item.get("grade") or "").lower()
        if grade in ("g", "vg", "f", "vf", "xf", "au", "unc"):
            cand.grade_bucket = grade
        grading = (
            item.get("grading_details") if isinstance(item.get("grading_details"), dict) else {}
        )
        company = (
            grading.get("grading_company")
            if isinstance(grading.get("grading_company"), dict)
            else {}
        )
        slab = grading.get("slab_grade") if isinstance(grading.get("slab_grade"), dict) else {}
        if name := clean(company.get("name"), 50):
            f["cert_service"] = name
        if number := clean(grading.get("slab_number"), 50):
            f["cert_number"] = number
        if slab_value := clean(slab.get("value")):
            strike = (
                grading.get("grading_strike")
                if isinstance(grading.get("grading_strike"), dict)
                else {}
            )
            cand.grade = " ".join(p for p in (clean(strike.get("value")), slab_value) if p)
        designations = [
            clean(d.get("value"))
            for d in grading.get("grading_designations") or []
            if isinstance(d, dict)
        ]
        if designations := [d.upper() for d in designations if d]:
            cand.grade = " ".join(p for p in (cand.grade, *designations) if p)
        if (cac := str(grading.get("cac_sticker") or "").lower()) in ("green", "gold"):
            f["cac_sticker"] = cac
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        if isinstance(price.get("value"), (int, float)) and price["value"] >= 0:
            f["acquisition_price"] = float(price["value"])
        f["currency"] = (clean(price.get("currency")) or "").upper() or "USD"
        if day := to_date(item.get("acquisition_date")):
            f["acquisition_date"] = day
        if place := clean(item.get("acquisition_place")):
            f["acquired_from"] = place
        if storage := clean(item.get("storage_location")):
            f["storage_location"] = storage
        if serial := clean(item.get("serial_number")):
            if f["type"] == "note":
                f["serial_number"] = serial
            else:
                cand.extra_notes.append(f"Serial number: {serial}")
        notes = [str(item.get(k) or "").strip() for k in ("private_comment", "public_comment")]
        if internal := clean(item.get("internal_id")):
            notes.append(f"Numista internal id: {internal}")
        if any(notes):
            f["notes"] = "\n".join(n for n in notes if n)
        if isinstance(type_id, int):
            cand.refs.append({"catalog": "numista", "ref_code": f"N#{type_id}"})
        collection = item.get("collection") if isinstance(item.get("collection"), dict) else {}
        if name := clean(collection.get("name"), 50):
            cand.tags.append(name)
        if item.get("for_swap"):
            cand.tags.append("for swap")
        for picture in item.get("pictures") or []:
            if isinstance(picture, dict) and clean(picture.get("url")):
                cand.photos.append((None, picture["url"]))
        if not cand.error:
            _require(cand)
        out.append(cand)
    return out


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value)
    return None
