"""Importing a collection from other tools (v0.18.0). See services/importing.py.

A file is uploaded once (`POST /api/imports`), previewed as often as needed
while the column mapping or defaults change, then imported. The Numista
account import needs no file: it reads the key owner's collection.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ImportField,
    ImportOptions,
    ImportPreview,
    ImportRunResult,
    ImportUpload,
    NumistaImportOptions,
)
from app.services import import_formats as formats
from app.services import importing, numista
from app.services.pricing import NotApplicable, SourceUnavailable

router = APIRouter(prefix="/api/imports", tags=["imports"])

SOURCES = {"spreadsheet": "spreadsheet", "cabinet": "cabinet", "numista_file": "numista-file",
           "opennumismat": "opennumismat"}  # fmt: skip
FORMAT_NAMES = {"spreadsheet": "Spreadsheet", "cabinet": "Cabinet export",
                "numista_file": "Numista export", "opennumismat": "OpenNumismat"}  # fmt: skip


@router.post("", response_model=ImportUpload, status_code=201)
def upload(file: UploadFile):
    """Stage a file for preview and import (up to 1 GB, kept for a day)."""
    try:
        staged = importing.stage_upload(file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    try:
        fmt = formats.detect(staged["path"])
    except (formats.FormatError, sqlite3.DatabaseError):
        fmt = "spreadsheet"
    return ImportUpload(
        upload_id=staged["upload_id"], filename=staged["filename"], size=staged["size"], format=fmt
    )


# ---------------------------------------------------------------- Numista account
# Registered before the "/{upload_id}/…" routes, which would otherwise match "numista".


def _numista_candidates(db: Session, options: NumistaImportOptions, fetch_types: bool):
    try:
        items, fetched_at = numista.fetch_collection(db)
    except NotApplicable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    type_ids = {
        item["type"]["id"]
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("type"), dict)
        and isinstance(item["type"].get("id"), int)
        and item["type"].get("category") != "exonumia"  # not imported, so not looked up
    }
    types: dict[int, dict] = {}
    to_fetch = 0
    pending: set[int] = set()
    if options.catalogue_details:
        types, to_fetch = numista.type_fields(db, type_ids, fetch=fetch_types)
        if not fetch_types:
            pending = type_ids - set(types)
    candidates = formats.numista_account_candidates(items, types, pending)
    extra = {"types": len(type_ids), "types_to_fetch": to_fetch, "fetched_at": fetched_at}
    return candidates, extra


@router.post("/numista/preview", response_model=ImportPreview)
def numista_preview(options: NumistaImportOptions, db: Session = Depends(get_db)):
    """What importing your Numista collection would do. Spends two requests
    (cached for an hour); catalogue details only come from the cache here."""
    candidates, extra = _numista_candidates(db, options, fetch_types=False)
    prepared = importing.prepare(db, "numista", candidates)
    return {**importing.preview(prepared), **extra, "format": "numista_account"}


@router.post("/numista/run", response_model=ImportRunResult)
def numista_run(options: NumistaImportOptions, db: Session = Depends(get_db)):
    """Import your Numista collection's new items, looking up catalogue details
    for each type not already cached (one request each)."""
    candidates, _ = _numista_candidates(db, options, fetch_types=True)
    prepared = importing.prepare(db, "numista", candidates)
    return importing.run(
        db, "numista", "Numista collection", prepared, fetch_remote_photos=options.fetch_photos
    )


# ---------------------------------------------------------------- staged files


@router.delete("/{upload_id}", status_code=204)
def discard(upload_id: str):
    importing.discard(upload_id)


def _read(upload_id: str, options: ImportOptions, db: Session):
    """Candidates from a staged file, plus what the preview reports about it."""
    try:
        path, filename = importing.staged(upload_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    fmt = options.format or formats.detect(path)
    defaults = options.defaults.model_dump()
    extra: dict = {"format": fmt, "filename": filename}
    reader = None
    try:
        if fmt == "opennumismat":
            candidates, reader = formats.opennumismat_candidates(path, defaults)
        else:
            headers, rows, header_row = formats.read_table(path, options.skip_rows)
            if fmt == "cabinet":
                candidates = formats.cabinet_candidates(rows, db)
            elif fmt == "numista_file":
                candidates = formats.numista_file_candidates(rows, defaults)
            else:
                mapping = (
                    formats.suggest_mapping(headers) if options.mapping is None else options.mapping
                )
                unknown = [k for k in mapping if k not in formats.FIELD_KEYS]
                missing = [c for c in mapping.values() if c not in headers]
                if unknown or missing:
                    raise formats.FormatError(
                        "The column matching refers to "
                        + ", ".join(f"{x!r}" for x in unknown + missing)
                        + ", which isn't in this file"
                    )
                candidates = formats.spreadsheet_candidates(rows, mapping, defaults)
                extra.update(
                    headers=headers,
                    header_row=header_row,
                    mapping=mapping,
                    fields=[ImportField(key=k, label=label) for k, label, _, _ in formats.FIELDS],
                )
    except (formats.FormatError, sqlite3.DatabaseError, UnicodeDecodeError) as exc:
        if reader is not None:
            reader.close()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return candidates, reader, extra


@router.post("/{upload_id}/preview", response_model=ImportPreview)
def preview(upload_id: str, options: ImportOptions, db: Session = Depends(get_db)):
    """What importing the file would do. Nothing is written."""
    candidates, reader, extra = _read(upload_id, options, db)
    if reader is not None:
        reader.close()
    prepared = importing.prepare(db, SOURCES[extra["format"]], candidates)
    return {**importing.preview(prepared), **extra}


@router.post("/{upload_id}/run", response_model=ImportRunResult)
def run(upload_id: str, options: ImportOptions, db: Session = Depends(get_db)):
    """Import the file's new items (ones already imported are skipped)."""
    candidates, reader, extra = _read(upload_id, options, db)
    fmt = extra["format"]
    try:
        prepared = importing.prepare(db, SOURCES[fmt], candidates)
        label = f"{FORMAT_NAMES[fmt]}: {extra['filename']}"
        return importing.run(db, SOURCES[fmt], label, prepared)
    finally:
        if reader is not None:
            reader.close()
