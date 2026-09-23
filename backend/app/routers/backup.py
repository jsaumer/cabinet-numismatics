"""Backups from inside the app. Every archive is encrypted with the backup
key (v0.30.0; see services/archive_keys.py), and the key itself never
crosses the API: only its public fingerprint does."""

import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth import events
from app.auth.permissions import permission
from app.db import get_db
from app.services import app_settings as store
from app.services import archive_keys, backup

router = APIRouter(prefix="/api", tags=["backup"])


class StoredBackup(BaseModel):
    name: str
    size: int
    created_at: datetime
    # The safety archive an in-app restore took first.
    prerestore: bool = False


class BackupKey(BaseModel):
    fingerprint: str  # the public key (age1...), safe to show
    saved: bool  # the owner ticked "I have saved it" for this key
    supplied: bool  # from BACKUP_KEY_FILE or BACKUP_KEY rather than generated
    # separate | shared | not_verified | secret | environment (nothing to check)
    location: str
    location_message: str | None = None


class BackupList(BaseModel):
    directory: str
    free_bytes: int | None
    last_run: dict | None
    backups: list[StoredBackup]
    key: BackupKey


class DeletedArchive(BaseModel):
    deleted: str


def _unavailable(exc: backup.BackupError) -> HTTPException:
    return HTTPException(409 if isinstance(exc, backup.BackupBusy) else 500, str(exc))


@router.get("/backup.zip", response_class=FileResponse)
@permission("admin", fresh=True)
def download_backup(request: Request, photos: bool = True, db: Session = Depends(get_db)):
    """A fresh encrypted archive, `cabinet-backup-....zip.age`: inside, once
    decrypted with the backup key, `db.dump`, `photos.tar.gz` and
    `documents.tar.gz` (unless `photos=false`), `manifest.json`, and
    `SHA256SUMS`. Built as ciphertext, then sent."""
    try:
        path, name = backup.write_download(db, include_photos=photos)
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    events.record(
        db, request, "backup_downloaded", target=name, alert=f"A backup ({name}) was downloaded."
    )
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=name,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


def _key_status(db: Session) -> BackupKey:
    try:
        primary = backup.signing_key()
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    where = archive_keys.location()
    return BackupKey(
        fingerprint=primary.recipient,
        saved=store.get_setting(db, "backup_key_saved") == primary.recipient,
        supplied=archive_keys.supplied(),
        location=where,
        location_message=archive_keys.LOCATION_MESSAGES.get(where),
    )


@router.get("/backups", response_model=BackupList)
@permission("admin")
def list_backups(db: Session = Depends(get_db)):
    try:
        dest = backup.backup_dir()
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    return BackupList(
        directory=str(dest),
        free_bytes=shutil.disk_usage(dest).free,
        last_run=store.get_setting(db, "backup_last_run"),
        backups=[
            StoredBackup(
                name=p.name,
                size=p.stat().st_size,
                created_at=backup.archive_time(p),
                prerestore=backup.is_prerestore(p),
            )
            for p in backup.stored_backups(dest)
        ],
        key=_key_status(db),
    )


@router.post("/backups/key/saved", response_model=BackupKey)
@permission("admin")
def backup_key_saved(request: Request, db: Session = Depends(get_db)):
    """The owner says they have saved the backup key outside Cabinet (the
    setup checklist stops asking). Only the public key is recorded."""
    try:
        recipient = backup.signing_key().recipient
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    store.set_setting(db, "backup_key_saved", recipient)
    db.commit()
    events.record(db, request, "backup_key_saved", target=recipient)
    return _key_status(db)


@router.post("/backups")
@permission("admin")
def run_backup_now(photos: bool | None = None, db: Session = Depends(get_db)) -> dict:
    """Write an archive into the backup directory now, then apply retention.
    `photos` defaults to the scheduled-backup setting."""
    try:
        return backup.run_backup(db, include_photos=photos)
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc


@router.get("/backups/{name}", response_class=FileResponse)
@permission("admin", fresh=True)
def download_stored_backup(name: str, request: Request, db: Session = Depends(get_db)):
    path = backup.backup_dir() / name
    if not backup.NAME_RE.match(name) or not path.is_file():
        raise HTTPException(404, "No such backup")
    events.record(
        db, request, "backup_downloaded", target=name, alert=f"The backup {name} was downloaded."
    )
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.delete("/backups/{name}", response_model=DeletedArchive)
@permission("admin", fresh=True)
def delete_stored_backup(name: str, request: Request, db: Session = Depends(get_db)):
    """Delete one stored archive (v0.30.1). Refused while a backup or a
    restore holds the backup directory, so an archive being written or
    restored can't go out from under it. Audited and alerted."""
    try:
        path = backup.backup_dir() / name
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    if not backup.NAME_RE.match(name) or not path.is_file():
        raise HTTPException(404, "No such backup")
    if not backup._run_lock.acquire(blocking=False):
        raise HTTPException(409, "A backup or restore is running; try again when it has finished.")
    try:
        path.unlink()
    finally:
        backup._run_lock.release()
    events.record(
        db, request, "backup_deleted", target=name, alert=f"The backup {name} was deleted."
    )
    return DeletedArchive(deleted=name)
