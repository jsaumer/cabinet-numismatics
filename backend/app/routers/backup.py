"""Backups from inside the app. Every archive is encrypted with the backup
key (v0.30.0; see services/archive_keys.py), and the key itself never
crosses the API: only its public fingerprint does."""

import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db import get_db
from app.services import alerts, archive_keys, backup
from app.services import app_settings as store

router = APIRouter(prefix="/api", tags=["backup"])


class StoredBackup(BaseModel):
    name: str
    size: int
    created_at: datetime
    # The safety archive an in-app restore took first.
    prerestore: bool = False
    # False for a plain .zip from before v0.30.0: readable by anyone who can
    # read the backup directory, and never restorable.
    encrypted: bool = True


class BackupKey(BaseModel):
    fingerprint: str  # the public key (age1...), safe to show
    saved: bool  # the owner ticked "I have saved it" for this key
    supplied: bool  # from BACKUP_KEY_FILE rather than generated
    # separate | shared | not_verified | secret (nothing to check)
    location: str
    location_message: str | None = None


class BackupList(BaseModel):
    directory: str
    free_bytes: int | None
    last_run: dict | None
    backups: list[StoredBackup]
    key: BackupKey


class DeletedArchives(BaseModel):
    deleted: list[str]


def _unavailable(exc: backup.BackupError) -> HTTPException:
    return HTTPException(409 if isinstance(exc, backup.BackupBusy) else 500, str(exc))


@router.get("/backup.zip", response_class=FileResponse)
def download_backup(photos: bool = True, db: Session = Depends(get_db)):
    """A fresh encrypted archive, `cabinet-backup-....zip.age`: inside, once
    decrypted with the backup key, `db.dump`, `photos.tar.gz` and
    `documents.tar.gz` (unless `photos=false`), `manifest.json`, and
    `SHA256SUMS`. Built as ciphertext, then sent."""
    try:
        path, name = backup.write_download(db, include_photos=photos)
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
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
                created_at=datetime.strptime(p.name[15:30], "%Y%m%d-%H%M%S").replace(
                    tzinfo=timezone.utc
                ),
                prerestore=backup.is_prerestore(p),
                encrypted=backup.is_encrypted(p),
            )
            for p in backup.stored_backups(dest)
        ],
        key=_key_status(db),
    )


@router.post("/backups/key/saved", response_model=BackupKey)
def backup_key_saved(db: Session = Depends(get_db)):
    """The owner says they have saved the backup key outside Cabinet (the
    setup checklist stops asking). Only the public key is recorded."""
    try:
        recipient = backup.signing_key().recipient
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    store.set_setting(db, "backup_key_saved", recipient)
    db.commit()
    return _key_status(db)


@router.delete("/backups/unencrypted", response_model=DeletedArchives)
def delete_unencrypted(db: Session = Depends(get_db)):
    """Delete every plain `.zip` archive from before v0.30.0 in the backup
    directory: each is a readable copy of the whole collection, and none can
    be restored. Encrypted archives and a restore's working folders are
    never touched."""
    try:
        dest = backup.backup_dir()
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    deleted = []
    for path in backup.stored_backups(dest):
        if not backup.is_encrypted(path):
            path.unlink(missing_ok=True)
            deleted.append(path.name)
    if deleted:
        alerts.event(
            db,
            "unencrypted_deleted",
            "Cabinet deleted unencrypted archives",
            f"{len(deleted)} unencrypted archive(s) from before v0.30.0 were deleted.",
        )
    return DeletedArchives(deleted=deleted)


@router.post("/backups")
def run_backup_now(photos: bool | None = None, db: Session = Depends(get_db)) -> dict:
    """Write an archive into the backup directory now, then apply retention.
    `photos` defaults to the scheduled-backup setting."""
    try:
        return backup.run_backup(db, include_photos=photos)
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc


@router.get("/backups/{name}", response_class=FileResponse)
def download_stored_backup(name: str):
    path = backup.backup_dir() / name
    if not backup.NAME_RE.match(name) or not path.is_file():
        raise HTTPException(404, "No such backup")
    media = "application/octet-stream" if backup.is_encrypted(path) else "application/zip"
    return FileResponse(path, media_type=media, filename=name)
