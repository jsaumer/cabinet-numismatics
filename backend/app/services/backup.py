"""In-app backups: one zip holding the database dump, the photo volume, and a
manifest that makes the archive checkable rather than merely present.

`db.dump` and `photos.tar.gz` are the same two files `scripts/backup.sh`
writes, so `scripts/restore.sh` restores either kind. `SHA256SUMS` lets a
shell verify an archive with `sha256sum -c`; `manifest.json` carries the same
checksums plus the app version and schema revision for a future in-app
restore to validate against.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.models import Item, ItemPhoto, PriceEstimate
from app.services import app_settings as store
from app.services import schema

logger = logging.getLogger(__name__)

FORMAT = "cabinet-backup"
FORMAT_VERSION = 1
NAME_RE = re.compile(r"^cabinet-backup-\d{8}-\d{6}(-data)?\.zip$")
SCHEDULES = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
# The scheduler checks hourly; the slack keeps a daily run from slipping a
# whole tick when the previous one started a few seconds late.
SCHEDULE_SLACK = timedelta(minutes=10)
RETRY_AFTER = timedelta(hours=1)
STALE_TEMP_AGE = timedelta(days=1)
CHUNK = 1024 * 1024
# One pg_dump/pg_restore per supported server major (see backend/Dockerfile).
PG_CLIENT_ROOT = Path("/usr/local/lib/pgclient")

_run_lock = threading.Lock()


class BackupError(Exception):
    """No archive could be produced: pg_dump missing or failed, or the
    destination is unwritable."""


class BackupBusy(BackupError):
    """Another backup into the backup directory is already running."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def archive_name(now: datetime, include_photos: bool) -> str:
    return f"cabinet-backup-{now:%Y%m%d-%H%M%S}{'' if include_photos else '-data'}.zip"


def backup_dir() -> Path:
    config = get_settings()
    path = Path(config.backup_dir).resolve()
    if path.is_relative_to(Path(config.photo_dir).resolve()):
        # nginx serves the photo volume publicly; archives there would be too.
        raise BackupError(f"Backup directory {path} must not be inside the photo directory.")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"Backup directory {path} is not usable: {exc}") from exc
    return path


class _HashingWriter:
    """Pass-through writer that records size and SHA-256 of what went by."""

    def __init__(self, raw):
        self.raw = raw
        self.sha = hashlib.sha256()
        self.size = 0

    def write(self, data) -> int:
        self.raw.write(data)
        self.sha.update(data)
        self.size += len(data)
        return len(data)

    def flush(self) -> None:
        self.raw.flush()

    def summary(self) -> dict:
        return {"sha256": self.sha.hexdigest(), "size": self.size}


def _pg_env() -> dict[str, str]:
    """libpq connection settings from DATABASE_URL, passed as environment so
    the password never appears on a command line."""
    url = make_url(get_settings().database_url)
    env = dict(os.environ)
    for var, value in (
        ("PGHOST", url.host),
        ("PGPORT", url.port),
        ("PGUSER", url.username),
        ("PGPASSWORD", url.password),
        ("PGDATABASE", url.database),
        ("PGSSLMODE", url.query.get("sslmode")),
    ):
        if value is not None:
            env[var] = str(value)
    return env


def pg_tool(name: str, server_major: int) -> str:
    """The client binary for the server's major version, or the nearest newer
    one. Matching matters beyond pg_dump refusing newer servers: a newer
    pg_dump writes settings an older server rejects on restore."""
    if PG_CLIENT_ROOT.is_dir():
        majors = sorted(int(p.name) for p in PG_CLIENT_ROOT.iterdir() if p.name.isdigit())
        for major in majors:
            if major >= server_major:
                return str(PG_CLIENT_ROOT / str(major) / name)
        raise BackupError(
            f"PostgreSQL {server_major} is newer than this image's clients "
            f"({', '.join(map(str, majors)) or 'none'}); use scripts/backup.sh instead."
        )
    found = shutil.which(name)  # running outside the container image
    if found is None:
        raise BackupError(f"{name} is not installed; use scripts/backup.sh instead.")
    return found


def dump_database(out, server_major: int) -> str:
    """Stream a custom-format pg_dump of the whole database into `out`;
    return the pg_dump version used."""
    pg_dump = pg_tool("pg_dump", server_major)
    version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True).stdout
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            [pg_dump, "--format=custom"], stdout=subprocess.PIPE, stderr=err, env=_pg_env()
        )
        try:
            for chunk in iter(lambda: proc.stdout.read(CHUNK), b""):
                out.write(chunk)
        except BaseException:
            proc.kill()
            raise
        finally:
            proc.stdout.close()
        if proc.wait() != 0:
            err.seek(0)
            message = err.read().decode(errors="replace").strip()
            raise BackupError(f"pg_dump failed: {message[-500:] or 'no output'}")
    return version.strip()


def _counts(db: Session) -> dict:
    return {
        "items": db.scalar(select(func.count()).select_from(Item)),
        "photos": db.scalar(select(func.count()).select_from(ItemPhoto)),
        "estimates": db.scalar(select(func.count()).select_from(PriceEstimate)),
    }


def write_archive(path: Path, db: Session, include_photos: bool = True) -> dict:
    """Write a backup zip to `path` and return its manifest."""
    created = utcnow()
    counts = _counts(db)
    connection = db.connection()
    revision = schema.current_revision(connection)
    server_version = connection.dialect.server_version_info or (0,)
    members: dict[str, dict] = {}
    with zipfile.ZipFile(path, "w", allowZip64=True) as zf:
        # Both payloads are already compressed, so they're stored, not deflated.
        with zf.open("db.dump", "w", force_zip64=True) as raw:
            writer = _HashingWriter(raw)
            dump_version = dump_database(writer, server_version[0])
            members["db.dump"] = writer.summary()
        if include_photos:
            photo_dir = Path(get_settings().photo_dir)
            with zf.open("photos.tar.gz", "w", force_zip64=True) as raw:
                writer = _HashingWriter(raw)
                with tarfile.open(fileobj=writer, mode="w|gz") as tar:
                    if photo_dir.is_dir():
                        tar.add(photo_dir, arcname=".")
                members["photos.tar.gz"] = writer.summary()
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "schema_revision": revision,
            "server_version": ".".join(map(str, server_version)),
            "pg_dump_version": dump_version,
            "created_at": created.isoformat(),
            "includes_photos": include_photos,
            "counts": counts,
            "members": members,
            "restore": "scripts/restore.sh <this archive> — see docs/backup-restore.md",
        }
        zf.writestr(
            "manifest.json", json.dumps(manifest, indent=2), compress_type=zipfile.ZIP_DEFLATED
        )
        zf.writestr(
            "SHA256SUMS", "".join(f"{m['sha256']}  {name}\n" for name, m in members.items())
        )
    return manifest


def verify_archive(path: Path) -> dict:
    """Check an archive against its own manifest; return the manifest."""
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("format") != FORMAT:
                raise BackupError("Not a Cabinet backup archive.")
            for name, expected in manifest["members"].items():
                sha = hashlib.sha256()
                size = 0
                with zf.open(name) as member:
                    for chunk in iter(lambda m=member: m.read(CHUNK), b""):
                        sha.update(chunk)
                        size += len(chunk)
                if sha.hexdigest() != expected["sha256"] or size != expected["size"]:
                    raise BackupError(f"{name} does not match its checksum.")
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise BackupError(f"Unreadable backup archive: {exc}") from exc
    return manifest


def write_download(db: Session, include_photos: bool) -> tuple[Path, str]:
    """Build an archive for a one-off download. The temp file sits in the
    backup directory (sized for archives, unlike the container's own layer);
    the caller deletes it once sent."""
    dest = backup_dir()
    fd, tmp = tempfile.mkstemp(dir=dest, prefix=".download-", suffix=".zip")
    os.close(fd)
    path = Path(tmp)
    try:
        write_archive(path, db, include_photos)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, archive_name(utcnow(), include_photos)


def stored_backups(dest: Path) -> list[Path]:
    """Archives in the backup directory, newest first."""
    return sorted(
        (p for p in dest.iterdir() if p.is_file() and NAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )


def prune(dest: Path, keep: int) -> list[str]:
    """Delete archives beyond the newest `keep`, and leftovers from
    interrupted runs. Only files matching Cabinet's own names are touched."""
    removed = []
    for old in stored_backups(dest)[max(keep, 1) :]:
        old.unlink()
        removed.append(old.name)
    cutoff = (utcnow() - STALE_TEMP_AGE).timestamp()
    for leftover in dest.glob("cabinet-backup-*.zip.partial"):
        leftover.unlink(missing_ok=True)  # only ever written under _run_lock
    for leftover in dest.glob(".download-*.zip"):
        if leftover.stat().st_mtime < cutoff:
            leftover.unlink(missing_ok=True)
    return removed


def run_backup(db: Session, include_photos: bool | None = None) -> dict:
    """Write an archive into the backup directory, prune to the retention
    count, and record the outcome in settings (`backup_last_run`)."""
    if not _run_lock.acquire(blocking=False):
        raise BackupBusy("A backup is already running.")
    started = utcnow()
    if include_photos is None:
        include_photos = bool(store.get_setting(db, "backup_include_photos"))
    try:
        try:
            dest = backup_dir()
            final = dest / archive_name(started, include_photos)
            partial = final.with_name(final.name + ".partial")
            try:
                write_archive(partial, db, include_photos)
                partial.replace(final)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            pruned = prune(dest, int(store.get_setting(db, "backup_keep")))
        except (BackupError, OSError) as exc:
            db.rollback()
            _record(db, {"at": started.isoformat(), "ok": False, "error": str(exc)})
            if isinstance(exc, BackupError):
                raise
            raise BackupError(str(exc)) from exc
        outcome = {
            "at": started.isoformat(),
            "ok": True,
            "file": final.name,
            "size": final.stat().st_size,
            "includes_photos": include_photos,
            "pruned": pruned,
        }
        _record(db, outcome)
        return outcome
    finally:
        _run_lock.release()


def _record(db: Session, outcome: dict) -> None:
    store.set_setting(db, "backup_last_run", outcome)
    db.commit()


def backup_due(schedule: str | None, last_run: dict | None, now: datetime) -> bool:
    interval = SCHEDULES.get(schedule or "")
    if interval is None:
        return False
    if not last_run:
        return True
    elapsed = now - datetime.fromisoformat(last_run["at"])
    if last_run.get("ok"):
        return elapsed >= interval - SCHEDULE_SLACK
    return elapsed >= RETRY_AFTER


def run_scheduled(db: Session) -> dict | None:
    """One scheduler tick: back up if the cadence says so. Returns the outcome,
    or None when nothing was due."""
    schedule = store.get_setting(db, "backup_schedule")
    if not backup_due(schedule, store.get_setting(db, "backup_last_run"), utcnow()):
        return None
    return run_backup(db)
