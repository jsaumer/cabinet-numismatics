"""Backups from inside the app. Unauthenticated like the rest of the API — and
these endpoints hand over the whole collection in one request, so the
deployment guidance (trusted LAN or an authenticating proxy) matters here most.
"""

import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db import get_db
from app.services import app_settings as store
from app.services import backup

router = APIRouter(prefix="/api", tags=["backup"])


class StoredBackup(BaseModel):
    name: str
    size: int
    created_at: datetime


class BackupList(BaseModel):
    directory: str
    free_bytes: int | None
    last_run: dict | None
    backups: list[StoredBackup]


def _unavailable(exc: backup.BackupError) -> HTTPException:
    return HTTPException(409 if isinstance(exc, backup.BackupBusy) else 500, str(exc))


@router.get("/backup.zip", response_class=FileResponse)
def download_backup(photos: bool = True, db: Session = Depends(get_db)):
    """A fresh archive: `db.dump`, `photos.tar.gz` (unless `photos=false`),
    `manifest.json`, and `SHA256SUMS`."""
    try:
        path, name = backup.write_download(db, include_photos=photos)
    except backup.BackupError as exc:
        raise _unavailable(exc) from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(path.unlink, missing_ok=True),
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
            )
            for p in backup.stored_backups(dest)
        ],
    )


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
    return FileResponse(path, media_type="application/zip", filename=name)
