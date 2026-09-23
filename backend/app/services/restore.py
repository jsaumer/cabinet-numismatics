"""In-app restore: replace the whole collection (database, and photos and
documents when the archive carries them) with a Cabinet backup archive.

Destructive, so the order is deliberate. Nothing live changes until the
archive has been verified, a safety backup of the current state is on disk,
and the archive's files have been unpacked into a hidden folder inside each
volume. Then the database is restored in one transaction (a failure leaves it
as it was), and only then are the files swapped in, by renames that can be
undone. A journal on the state volume lets a backend that was stopped halfway
through the swap finish it on the next start.

One restore at a time, on a background thread, with its state in memory: the
backend is a single process. The outcome goes to a JSON file beside the key
file, not the database, because the database is what was just replaced.

Only encrypted archives made with this deployment's backup key are restored
(v0.30.0): an archive is decrypted into the private staging folder
(`backup.staging_dir`), its MAC checked before anything in it is read, and
every later step reads that decrypted copy. A plain `.zip` from an earlier
release is refused by every path. An archive older than the newest one this
Cabinet recorded (`cabinet_auth.backup_ledger`, matched by its verified MAC)
needs the typed confirmation `RESTORE OLDER`.

Sign-in data is never part of it (v0.30.0): dumps leave out `cabinet_auth`,
pg_restore takes `public` only, and an archive whose dump holds anything in
`cabinet_auth` is refused. The dump is unpacked only in the private staging
folder (`backup.staging_dir`), never in the backup directory. A marker row
written just before the database step tells a restarted backend whether the
database had been replaced when it stopped (`recover`).

Share links are access grants, so they are kept like sign-in data (v0.32.0):
the live `share_links` rows and the `share_enabled` switch are read after
the safety backup, and put back after the database step and the migrations,
replacing whatever the archive held; a revoked link can't come back with an
older archive, and an archive can't switch sharing on. A backend restarted
after the database step leaves the snapshot in `pending_sharing.json`, put
back by `apply_pending_sharing` once startup has migrated. A put-back that
fails deletes every link and switches sharing off, and keeps the snapshot
there to try again. An archive's photos may carry metadata, so the photo
marker is removed before they are swapped in and a cleaning pass runs after.
"""

import hmac
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import inspect as inspect_db
from sqlalchemy import select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import AppSetting, Checklist, ItemSet, ShareLink
from app.models.auth import BackupRecord
from app.services import (
    alerts,
    archive_keys,
    backup,
    crypto,
    maintenance,
    metrics,
    photos,
    scheduled,
    schema,
    share,
)
from app.services import app_settings as store

logger = logging.getLogger(__name__)

CONFIRM_PHRASE = "RESTORE"
OLDER_PHRASE = "RESTORE OLDER"
LEGACY_REFUSED = (
    "This is an unencrypted archive from before v0.30.0. Cabinet only restores "
    "encrypted archives made with its backup key; take a new backup instead."
)
NOT_AN_ARCHIVE = "Not a Cabinet backup archive."
UNOPENABLE = (
    "This archive can't be opened with your backup key: it was made with another "
    "key, or it has been altered."
)
STEPS = ("safety_backup", "database", "migrations", "photos", "documents", "finishing")
STAGING_DIR = backup.RESTORE_PREFIX + "staging"
NEW_DIR = backup.RESTORE_PREFIX + "new"
OLD_DIR = backup.RESTORE_PREFIX + "old"
TRASH_DIR = backup.RESTORE_PREFIX + "trash"  # OLD_DIR once it is no longer needed
# Inside OLD_DIR once every current entry has been moved out: from then on
# whatever is live came from the archive.
MOVED_OUT = backup.RESTORE_PREFIX + "moved-out"
STALE_UPLOAD_AGE = timedelta(days=1)
KNOWN_MEMBERS = {"db.dump", "photos.tar.gz", "documents.tar.gz"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
# pg_restore takes exclusive locks; give up rather than wait for ever behind
# something that never lets go.
LOCK_TIMEOUT = "120s"
SECRETS_NOTE = (
    "Saved API keys and webhook addresses in the archive were encrypted with the "
    "SECRET_KEY in use when it was made. With the same key they keep working; with "
    "a different one they will read as not set and need entering again in Settings."
)
NOTHING_CHANGED = "Nothing was changed."
CREDENTIALS_NOTE = "Your sign-in, sessions, API tokens, and audit log are kept."
AUTH_REFUSED = (
    "This archive contains sign-in data, which Cabinet never restores. "
    "It was not made by Cabinet's own backup."
)
# An app_settings row written just before the database step, by direct ORM
# (never through get_setting: it isn't a setting). pg_restore replaces
# app_settings wholesale, so the row survives only if the database was not
# replaced, and an archive can't carry this restore's value. It must stay in
# `public`: in cabinet_auth it would survive every restore.
MARKER_KEY = "restore_marker"

_lock = threading.Lock()  # held for the length of a restore
_state_lock = threading.Lock()
_state: dict = {"state": "idle", "step": None, "started_at": None}
_pending: dict[str, dict] = {}
_memory_last: dict | None = None  # if the state volume can't be written

# The restore grant: the session that started a restore may keep reading the
# status while maintenance refuses everything else. In memory only; checked
# by the gate with no database access. Ends 10 minutes after the restore
# does, and 2 hours after it was issued at the latest.
GRANT_AFTER_END = 10 * 60
GRANT_MAX = 2 * 60 * 60
_grant: dict | None = None


class RestoreError(Exception):
    """The archive can't be restored, or a step of the restore failed."""


class PartialDatabase(RestoreError):
    """The database step failed after something had already changed."""


class Unknown(RestoreError):
    """No such restore id or archive."""


class TooLarge(RestoreError):
    """The upload is over RESTORE_MAX_GB."""


class Busy(RestoreError):
    """A restore, a backup, or a scheduled task is running."""


def enabled() -> bool:
    return get_settings().restore_enabled


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- where things live -----------------------------------------------------


def _state_dir() -> Path:
    return Path(get_settings().secret_key_file).resolve().parent


def _outcome_path() -> Path:
    return _state_dir() / "restore_last.json"


def _journal_path() -> Path:
    return _state_dir() / "restore_journal.json"


def _pending_path() -> Path:
    """The live share links and switch still to be put back (v0.32.0)."""
    return _state_dir() / "pending_sharing.json"


def upload_dir() -> Path:
    """Where uploaded archives wait, in the backup directory (sized for
    archives). Uploads only: a dump is never unpacked here, since this may be
    a share (see backup.staging_dir)."""
    path = backup.backup_dir() / STAGING_DIR
    path.mkdir(exist_ok=True)
    return path


def _file_targets() -> tuple[tuple[str, str, Path], ...]:
    """(archive member, step, the volume it replaces)."""
    config = get_settings()
    return (
        ("photos.tar.gz", "photos", Path(config.photo_dir)),
        ("documents.tar.gz", "documents", Path(config.document_dir)),
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(data, indent=2), encoding="utf-8")
    partial.replace(path)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- status ----------------------------------------------------------------


def last_outcome() -> dict | None:
    return _read_json(_outcome_path()) or _memory_last


def _record(outcome: dict) -> None:
    global _memory_last
    _memory_last = outcome
    try:
        _write_json(_outcome_path(), outcome)
    except OSError:
        logger.exception("Could not write the restore outcome to %s", _outcome_path())


def status() -> dict:
    if not enabled():
        return {
            "enabled": False,
            "state": "idle",
            "step": None,
            "started_at": None,
            "last": None,
            "confirm_phrase": CONFIRM_PHRASE,
        }
    with _state_lock:
        current = dict(_state)
    return {"enabled": True, **current, "last": last_outcome(), "confirm_phrase": CONFIRM_PHRASE}


def _set_state(**changes) -> None:
    with _state_lock:
        _state.update(changes)


def _step(name: str) -> None:
    logger.info("Restore: %s", name)
    _set_state(step=name)


def issue_grant(session_hash: bytes, restore_id: str, principal) -> None:
    global _grant
    _grant = {
        "hash": session_hash,
        "restore_id": restore_id,
        "principal": principal,
        "issued": time.monotonic(),
        "ended": None,
    }


def drop_grant() -> None:
    global _grant
    _grant = None


def granted(session_hash: bytes):
    """The principal holding the grant, if this session is it and the grant
    is still live; otherwise None."""
    grant = _grant
    if grant is None or not session_hash:
        return None
    now = time.monotonic()
    if now - grant["issued"] > GRANT_MAX:
        return None
    if grant["ended"] is not None and now - grant["ended"] > GRANT_AFTER_END:
        return None
    if not hmac.compare_digest(grant["hash"], session_hash):
        return None
    return grant["principal"]


def _end_grant(restore_id: str) -> None:
    grant = _grant
    if grant is not None and grant["restore_id"] == restore_id and grant["ended"] is None:
        grant["ended"] = time.monotonic()


def reset_memory() -> None:
    """Forget in-memory state (tests)."""
    global _memory_last
    _memory_last = None
    drop_grant()
    _pending.clear()
    _set_state(state="idle", step=None, started_at=None)
    maintenance.leave()


# --- checking an archive ---------------------------------------------------


def _safe_target(root: Path, info: tarfile.TarInfo) -> Path | None:
    """Where a tar member lands under `root`; None for the root entry itself
    and for a restore's own working folders. Anything that could land
    elsewhere, or isn't a plain file or folder, is refused."""
    name = info.name
    posix = PurePosixPath(name.replace("\\", "/"))
    if posix.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in posix.parts:
        raise RestoreError(f"The archive holds an unsafe path ({name}).")
    parts = [part for part in posix.parts if part != "."]
    if not parts:
        return None
    if not (info.isdir() or info.isreg()):
        # Cabinet never writes links or devices; a link is how a tar escapes.
        raise RestoreError(f"The archive holds {name}, which is not a plain file or folder.")
    if any(part.startswith(backup.RESTORE_PREFIX) for part in parts):
        return None
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise RestoreError(f"The archive holds an unsafe path ({name}).")
    return target


@contextmanager
def _open_tar(zf: zipfile.ZipFile, member: str):
    with zf.open(member) as raw, tarfile.open(fileobj=raw, mode="r|gz") as tar:
        yield tar


def _scan_tar(path: Path, member: str) -> None:
    try:
        with zipfile.ZipFile(path) as zf, _open_tar(zf, member) as tar:
            for info in tar:
                _safe_target(Path("."), info)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise RestoreError(f"{member} in the archive can't be read: {exc}") from exc


def require_age_header(head: bytes) -> None:
    """Refuse, from its first bytes, anything that isn't an age file."""
    if not head.startswith(backup.AGE_MAGIC):
        raise RestoreError(LEGACY_REFUSED if head.startswith(b"PK") else NOT_AN_ARCHIVE)


def open_archive(archive: Path, stem: str) -> Path:
    """Decrypt an archive into the private staging folder and return the
    decrypted zip. Refuses a plain (pre-v0.30.0) archive and anything that
    isn't an age file, before decrypting anything."""
    if not backup.looks_encrypted(archive):
        if zipfile.is_zipfile(archive):
            raise RestoreError(LEGACY_REFUSED)
        raise RestoreError(NOT_AN_ARCHIVE)
    try:
        return backup.decrypt_to_staging(archive, stem)
    except backup.BackupError as exc:
        if str(exc).startswith("Not enough space"):
            raise RestoreError(str(exc)) from None
        logger.warning("Restore: %s", exc)
        raise RestoreError(UNOPENABLE) from None


def check_archive(path: Path) -> dict:
    """Verify a decrypted archive end to end, its MAC first; return its
    manifest."""
    if not zipfile.is_zipfile(path):
        raise RestoreError("Not a Cabinet backup archive: the file is not a zip.")
    try:
        manifest = backup.verify_archive(path)
    except backup.BackupError as exc:
        raise RestoreError(str(exc)) from exc
    except Exception as exc:  # a manifest of the wrong shape
        raise RestoreError(f"Unreadable backup archive: {exc}") from exc
    members = manifest.get("members")
    if not isinstance(members, dict) or "db.dump" not in members:
        raise RestoreError("The archive has no database dump.")
    if unknown := set(members) - KNOWN_MEMBERS:
        raise RestoreError(f"The archive holds something unexpected: {', '.join(sorted(unknown))}.")
    revision = manifest.get("schema_revision")
    head, known = schema.script_revisions()
    if not revision:
        raise RestoreError("The archive doesn't say which schema revision it holds.")
    if revision not in known:
        raise RestoreError(
            f"This archive was made by a newer Cabinet (schema {revision}; this one knows "
            f"up to {head}). Upgrade Cabinet first, then restore."
        )
    for member in members:
        if member != "db.dump":
            _scan_tar(path, member)
    return manifest


def extract_dump(archive: Path, restore_id: str) -> Path:
    """Unpack the archive's database dump into the private staging folder
    (0600), after checking there is room for it."""
    folder = backup.staging_dir()
    with zipfile.ZipFile(archive) as zf:
        backup.ensure_room(folder, zf.getinfo("db.dump").file_size, "its database dump")
        target = folder / f"{restore_id}.dump"
        with zf.open("db.dump") as src, backup.private_file(target) as out:
            shutil.copyfileobj(src, out, backup.CHUNK)
    return target


def refuse_auth(dump: Path, server_major: int) -> None:
    """Refuse a dump holding anything in cabinet_auth. Cabinet's own dumps
    leave that schema out, so such an archive was made some other way."""
    for line in backup.list_dump(dump, server_major):
        if not line.startswith(";") and re.search(r"\bcabinet_auth\b", line):
            raise RestoreError(AUTH_REFUSED)


def _server_major(engine: Engine) -> int:
    with engine.connect() as conn:
        return (conn.dialect.server_version_info or (0,))[0]


def carried_secrets(settings: dict) -> tuple[list[str], list[str]]:
    """By name only: the stored secrets an archive would set, and those it
    holds that this deployment would clear (plain text, or encrypted with
    another key)."""
    sets, cleared = [], []
    for key in sorted(store.SECRET_KEYS):
        value = settings.get(key)
        if not isinstance(value, str) or not value:
            continue
        usable = crypto.is_encrypted(value) and bool(crypto.decrypt(value))
        (sets if usable else cleared).append(store.SECRET_LABELS[key])
    return sets, cleared


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def provenance(db: Session, manifest: dict) -> dict:
    """Whether this Cabinet made the (verified) archive, how many newer ones
    it recorded, and the phrase a restore of it needs. The archive is matched
    by its verified MAC, never its file name or time, and "older" compares its
    verified `created_at` with the newest in the record, so a renamed or
    re-dated old archive, or one whose own row was pruned, is still older."""
    created = _aware(datetime.fromisoformat(manifest["created_at"]))
    records = db.execute(select(BackupRecord)).scalars().all()
    if not records:
        return {
            "made_here": False,
            "made_at": None,
            "newer": 0,
            "older": False,
            "record_empty": True,
            "message": "Cabinet has no record of its own backups here, so it cannot tell "
            "whether this is the newest.",
            "confirm_phrase": CONFIRM_PHRASE,
        }
    digest = archive_keys.mac_digest(manifest)
    mine = next(
        (
            r
            for r in records
            if r.mac_digest == digest and r.mac_recipient == manifest["mac_recipient"]
        ),
        None,
    )
    newest = max(_aware(r.created_at) for r in records)
    newer = sum(1 for r in records if _aware(r.created_at) > created)
    older = created < newest
    if mine is not None:
        message = f"Made by this Cabinet on {created.day} {created:%B %Y}."
    else:
        message = "Not made by this Cabinet."
    if newer == 1:
        message += " 1 newer backup exists."
    elif newer:
        message += f" {newer} newer backups exist."
    return {
        "made_here": mine is not None,
        "made_at": created.isoformat() if mine is not None else None,
        "newer": newer,
        "older": older,
        "record_empty": False,
        "message": message,
        "confirm_phrase": OLDER_PHRASE if older else CONFIRM_PHRASE,
    }


def _will_migrate(manifest: dict) -> bool:
    return manifest["schema_revision"] != schema.script_revisions()[0]


def _replaces_files(manifest: dict) -> bool:
    return any(member != "db.dump" for member in manifest["members"])


# --- staging and inspecting -------------------------------------------------


def clean_staging() -> None:
    """Drop staged uploads older than a day."""
    cutoff = (datetime.now(timezone.utc) - STALE_UPLOAD_AGE).timestamp()
    try:
        staged = list(upload_dir().iterdir())
    except (backup.BackupError, OSError):
        return
    for path in staged:
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            _pending.pop(path.stem, None)


def new_staging_file() -> tuple[str, Path]:
    """(restore id, path) for an upload about to be written. Uploads go
    straight into the backup volume, which is sized for archives; the
    container's own temp folder is not."""
    clean_staging()
    restore_id = uuid.uuid4().hex
    return restore_id, upload_dir() / f"{restore_id}.upload"


def upload_limit() -> int:
    return int(get_settings().restore_max_gb * 1024**3)


def too_large() -> TooLarge:
    return TooLarge(
        f"The archive is larger than {get_settings().restore_max_gb:g} GB (RESTORE_MAX_GB)."
    )


def shown_name(filename: str | None) -> str:
    return (Path((filename or "").replace("\\", "/")).name or "uploaded archive")[:200]


def stored_archive(name: str) -> Path:
    path = backup.backup_dir() / name
    if not backup.NAME_RE.match(name) or not path.is_file():
        raise Unknown("No such backup")
    return path


def inspect(db: Session, path: Path, name: str, staged: bool, restore_id: str | None = None):
    """Verify an archive and describe what restoring it would do. A staged
    upload that fails the check is deleted. Its dump is unpacked only into
    the private staging folder, checked there, and removed again."""
    if not _lock.acquire(blocking=False):
        if staged:
            path.unlink(missing_ok=True)
        raise Busy("A restore is running; try again when it has finished.")
    try:
        return _inspect(db, path, name, staged, restore_id or uuid.uuid4().hex)
    finally:
        _lock.release()


def _inspect(db: Session, path: Path, name: str, staged: bool, restore_id: str) -> dict:
    backup.empty_staging()
    try:
        plain = open_archive(path, restore_id)
        manifest = check_archive(plain)
        major = (db.connection().dialect.server_version_info or (0,))[0]
        dump = extract_dump(plain, restore_id)
        refuse_auth(dump, major)
        sets, cleared = carried_secrets(backup.dump_settings(dump, major))
        origin = provenance(db, manifest)
    except BaseException:
        if staged:
            path.unlink(missing_ok=True)
        raise
    finally:
        backup.empty_staging()
    check_movable(manifest)  # say so now, not after the database has gone
    _pending[restore_id] = {
        "path": path,
        "name": name,
        "staged": staged,
        "phrase": origin["confirm_phrase"],
    }
    counts = manifest.get("counts") or {}
    here = backup._counts(db)
    return {
        "restore_id": restore_id,
        "archive": {
            "name": name,
            "size": path.stat().st_size,
            "created_at": manifest.get("created_at"),
            "app_version": manifest.get("app_version"),
            "revision": manifest["schema_revision"],
            "includes_photos": "photos.tar.gz" in manifest["members"],
            "includes_documents": "documents.tar.gz" in manifest["members"],
            "items": counts.get("items"),
            "photos": counts.get("photos"),
            "documents": counts.get("documents"),
            "trashed": counts.get("in_trash"),
        },
        "current": {
            "revision": schema.current_revision(db.connection()),
            "items": here["items"],
            "photos": here["photos"],
            "documents": here["documents"],
            "trashed": here["in_trash"],
        },
        "will_migrate": _will_migrate(manifest),
        "replaces_files": _replaces_files(manifest),
        "secrets_note": SECRETS_NOTE,
        "credentials_note": CREDENTIALS_NOTE,
        # By name only: what the archive would set, and what would be cleared.
        "secrets": sets,
        "secrets_cleared": cleared,
        "provenance": origin,
        "confirm_phrase": origin["confirm_phrase"],
    }


def discard(restore_id: str) -> None:
    """Forget a restore id; delete the file only if it was a staged upload.
    An archive in the backup directory is never deleted from here."""
    entry = _pending.pop(restore_id, None)
    if entry is None:
        # Staged before a restart: the id is the file's name.
        if not ID_RE.match(restore_id):
            raise Unknown("No such restore")
        path = upload_dir() / f"{restore_id}.upload"
        if not path.is_file():
            raise Unknown("No such restore")
        path.unlink(missing_ok=True)
        return
    if entry["staged"]:
        entry["path"].unlink(missing_ok=True)


# --- the file swap ----------------------------------------------------------


def check_movable(manifest: dict) -> None:
    """Refuse up front when the file swap couldn't work. Moving a folder to
    another parent needs write permission on the folder itself, so one left
    owned by root (photos uploaded before v0.23.1, when the backend ran as
    root) would stop the swap after the database had already been replaced."""
    for member, _step_name, folder in _file_targets():
        if member not in manifest["members"] or not folder.is_dir():
            continue
        stuck = [folder] if not os.access(folder, os.W_OK | os.X_OK) else []
        for root, dirs, _files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(backup.RESTORE_PREFIX)]
            stuck += [
                Path(root) / d for d in dirs if not os.access(Path(root) / d, os.W_OK | os.X_OK)
            ]
        if stuck:
            raise RestoreError(
                f"Cabinet can't replace the files in {folder}: {len(stuck)} folder(s) there, such "
                f"as {stuck[0].name}, aren't writable by the user the backend runs as (usually "
                "because they were created as root before v0.23.1). Restart the backend on "
                "v0.26.1 or later, which hands them over on startup, or run chown -R on the "
                "folder, then try again."
            )


def _live_entries(folder: Path) -> list[Path]:
    # `.nfs*` are an NFS client's placeholders for open files; they can't move.
    return [
        entry
        for entry in folder.iterdir()
        if not entry.name.startswith((backup.RESTORE_PREFIX, ".nfs"))
    ]


class _Swap:
    """Replace a volume's contents with what was unpacked into NEW_DIR, by
    renames inside the volume. The folder itself is a mount point and is
    never renamed or removed. `apply` can be repeated after an interruption;
    `undo` puts the previous entries back."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.new = folder / NEW_DIR
        self.old = folder / OLD_DIR

    def apply(self) -> None:
        self.old.mkdir(exist_ok=True)
        marker = self.old / MOVED_OUT
        if not marker.exists():
            for entry in _live_entries(self.folder):
                entry.rename(self.old / entry.name)
            marker.touch()
        for entry in list(self.new.iterdir()):
            entry.rename(self.folder / entry.name)

    def undo(self) -> None:
        if not self.old.is_dir():
            return
        marker = self.old / MOVED_OUT
        if marker.exists():
            # Everything live came from the archive: move it back out first.
            self.new.mkdir(exist_ok=True)
            for entry in _live_entries(self.folder):
                entry.rename(self.new / entry.name)
            marker.unlink()
        for entry in list(self.old.iterdir()):
            entry.rename(self.folder / entry.name)
        self.old.rmdir()
        shutil.rmtree(self.new, ignore_errors=True)

    def finish(self) -> None:
        """The swap held: the previous files can go. Renamed first, so a
        half-deleted folder is never mistaken for files that still matter."""
        trash = self.folder / TRASH_DIR
        shutil.rmtree(trash, ignore_errors=True)
        if self.old.is_dir():
            self.old.rename(trash)
        for leftover in (self.new, trash):
            shutil.rmtree(leftover, ignore_errors=True)


def _clear_workdirs() -> None:
    """Remove working folders an earlier restore left behind. OLD_DIR is the
    exception: it only survives when putting the previous files back failed,
    so it may hold the only copy of them and a person has to look."""
    for _member, _step_name, folder in _file_targets():
        old = folder / OLD_DIR
        if old.is_dir() and any(old.iterdir()):
            raise RestoreError(
                f"An earlier restore left files in {old}. Move them back into "
                f"{folder} or remove that folder, then try again."
            )
        for name in (NEW_DIR, OLD_DIR, TRASH_DIR):
            shutil.rmtree(folder / name, ignore_errors=True)


def _extract(archive: Path, member: str, folder: Path) -> None:
    """Unpack a tar member into NEW_DIR inside the volume. Written by hand
    rather than `extractall`: only plain files and folders, no ownership, no
    modes, nothing outside the target."""
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        needed = zf.getinfo(member).file_size
        free = shutil.disk_usage(folder).free
        if free < needed * 1.05:
            raise RestoreError(
                f"Not enough free space in {folder} to unpack {member} "
                f"({needed} bytes needed, {free} free)."
            )
        new = folder / NEW_DIR
        new.mkdir()
        try:
            with _open_tar(zf, member) as tar:
                for info in tar:
                    target = _safe_target(new, info)
                    if target is None:
                        continue
                    if info.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, backup.CHUNK)
        except (tarfile.TarError, EOFError) as exc:
            raise RestoreError(f"{member} in the archive can't be read: {exc}") from exc


# --- the database -----------------------------------------------------------


def dispose_engine(engine: Engine) -> None:
    """Close pooled connections so none holds a lock, or a stale view."""
    engine.dispose()


def migrate(engine: Engine) -> None:
    """The collection chain only: the restore never touched cabinet_auth."""
    schema.upgrade_to_head(engine, auth=False)


def _dump_tables(pg_restore: str, dump_path: Path) -> set[str]:
    listing = subprocess.run(
        [pg_restore, "--list", str(dump_path)], capture_output=True, text=True, check=False
    )
    if listing.returncode != 0:
        raise RestoreError(f"pg_restore can't read the dump: {listing.stderr.strip()[-500:]}")
    return set(re.findall(r"^\d+; \d+ \d+ TABLE public (\S+) ", listing.stdout, re.MULTILINE))


def restore_command(pg_restore: str, database: str, dump_path: Path) -> list[str]:
    """The collection only (`public`), in one transaction; never cabinet_auth."""
    return [
        pg_restore,
        "--schema=public",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--single-transaction",
        f"--dbname={database}",
        str(dump_path),
    ]


def restore_database(dump_path: Path, on_drop=None) -> None:
    """pg_restore the dump's `public` schema over the live database in ONE
    transaction, so a failure leaves the database as it was (but see
    PartialDatabase, for an archive older than some of the tables here).
    `on_drop(names)` is called before leftover tables are dropped, so the
    journal names them first. cabinet_auth is never touched. Tests
    monkeypatch this (SQLite has no pg_restore), like `backup.dump_database`."""
    from app.db import engine

    with engine.connect() as conn:
        major = (conn.dialect.server_version_info or (0,))[0]
    engine.dispose()
    try:
        pg_restore = backup.pg_tool("pg_restore", major)
    except backup.BackupError as exc:
        raise RestoreError(str(exc)) from exc
    tables = _dump_tables(pg_restore, dump_path)
    if "alembic_version" not in tables or "items" not in tables:
        raise RestoreError("The dump doesn't hold a Cabinet database.")
    # `--clean` drops only what the dump holds. A table added by a migration
    # newer than the archive would survive, block the drop of the tables its
    # foreign keys point at, and collide with that migration when it runs
    # again. Those go first; it is the one change made outside pg_restore's
    # transaction, so a failure after it says so (PartialDatabase).
    with engine.begin() as conn:
        conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        # `public` only: cabinet_auth holds sign-in data and must never be
        # dropped, whatever the archive holds.
        present = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        dropped = sorted(set(present) - tables)
        if dropped and on_drop is not None:
            on_drop(dropped)
        for leftover in dropped:
            logger.info("Restore: dropping %s, which the archive predates", leftover)
            conn.execute(text(f'DROP TABLE IF EXISTS public."{leftover}" CASCADE'))
    engine.dispose()

    env = backup._pg_env()
    env["PGOPTIONS"] = f"{env.get('PGOPTIONS', '')} -c lock_timeout={LOCK_TIMEOUT}".strip()
    database = make_url(get_settings().database_url).database
    result = subprocess.run(
        restore_command(pg_restore, database, dump_path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    engine.dispose()
    if result.returncode != 0:
        message = f"pg_restore failed: {result.stderr.strip()[-500:] or 'no output'}"
        if dropped:
            raise PartialDatabase(
                f"{_sentence(message)} The rest of the database is as it was, but tables "
                f"newer than the archive had already been removed ({', '.join(dropped)})."
            )
        raise RestoreError(message)


# --- the marker ---------------------------------------------------------------


def _write_marker(engine: Engine) -> str:
    value = secrets.token_hex(16)
    with Session(engine) as db:
        db.merge(AppSetting(key=MARKER_KEY, value=value))
        db.commit()
    return value


def _read_marker(engine: Engine):
    """The marker row's value, or None when there is no row, or no
    app_settings at all (an archive from before it existed replaced it)."""
    with engine.connect() as conn:
        if not inspect_db(conn).has_table(AppSetting.__tablename__):
            return None
    with Session(engine) as db:
        row = db.get(AppSetting, MARKER_KEY)
        return None if row is None else row.value


def _delete_marker(engine: Engine) -> None:
    """Remove any marker row, this restore's or one an archive brought in."""
    with Session(engine) as db:
        db.execute(AppSetting.__table__.delete().where(AppSetting.key == MARKER_KEY))
        db.commit()


def _after_database(engine: Engine) -> list[str]:
    """Once the database is the archive's: drop any marker row it brought,
    and clear every stored secret this deployment wouldn't use (plain text,
    or encrypted with another key). Returns the cleared secrets' names."""
    try:
        with engine.connect() as conn:
            if not inspect_db(conn).has_table(AppSetting.__tablename__):
                return []  # an archive older than settings: migrations add them
        _delete_marker(engine)
        db = sessionmaker(bind=engine, autoflush=False)()
        try:
            cleared = scheduled.clear_secrets(db, undecryptable=True)
        finally:
            db.close()
    except Exception:
        logger.exception("Restore: checking the restored secrets failed")
        return []
    return [store.SECRET_LABELS[key] for key in cleared]


# --- share links, kept like sign-in data --------------------------------------------

_LINK_FIELDS = (
    "token_hash",
    "kind",
    "set_id",
    "checklist_id",
    "name",
    *share.OPTIONS,
    "created_by",
    "opens",
)
_LINK_TIMES = ("created_at", "last_opened_at")


def _target_name(db: Session, link: ShareLink) -> str | None:
    if link.kind == "set" and link.set_id is not None:
        found = db.get(ItemSet, link.set_id)
    elif link.kind == "checklist" and link.checklist_id is not None:
        found = db.get(Checklist, link.checklist_id)
    else:
        return None
    return found.name if found is not None else None


def _snapshot_sharing(engine: Engine) -> dict:
    """The live links and switch, as JSON (the journal carries them, so a
    restart can still put them back). Hashes only: no link's token is known."""
    with Session(engine) as db:
        links = []
        for row in db.scalars(select(ShareLink)):
            link = {"id": str(row.id), **{name: getattr(row, name) for name in _LINK_FIELDS}}
            for name in _LINK_TIMES:
                value = getattr(row, name)
                link[name] = value.isoformat() if value is not None else None
            link["target_name"] = _target_name(db, row)
            links.append(link)
        return {"enabled": bool(store.get_setting(db, "share_enabled")), "links": links}


def _fingerprint(link: dict) -> tuple:
    return (str(link["id"]), *(link[name] for name in _LINK_FIELDS if name != "opens"))


def _row_fingerprint(row: ShareLink) -> tuple:
    return _fingerprint({"id": row.id, **{name: getattr(row, name) for name in _LINK_FIELDS}})


def _as_row(link: dict) -> ShareLink:
    row = ShareLink(id=uuid.UUID(link["id"]), **{name: link[name] for name in _LINK_FIELDS})
    for name in _LINK_TIMES:
        value = link.get(name)
        setattr(row, name, datetime.fromisoformat(value) if value else None)
    return row


def _put_back_sharing(engine: Engine, snapshot: dict | None, actor) -> dict | None:
    """Replace the archive's links and switch with the snapshot. A set or
    checklist link is put back only when a target with the same id and name
    is in the restored database; otherwise it could open a different set. On
    any failure sharing is switched off (the archive's links are its own,
    and must not open). Audited as `restore_sharing`; the summary goes in
    the outcome."""
    if snapshot is None:
        return None
    result = {
        "links_kept": 0,
        "links_dropped": 0,
        "archive_links": 0,
        "archive_enabled": False,
        "enabled": bool(snapshot["enabled"]),
        "differed": False,
    }
    try:
        with engine.connect() as conn:
            found = inspect_db(conn)
            has_links = found.has_table(ShareLink.__tablename__)
            has_settings = found.has_table(AppSetting.__tablename__)
        with Session(engine) as db:
            archived = list(db.scalars(select(ShareLink))) if has_links else []
            result["archive_links"] = len(archived)
            if has_settings:
                result["archive_enabled"] = bool(store.get_setting(db, "share_enabled"))
            result["differed"] = result["archive_enabled"] != result["enabled"] or {
                _row_fingerprint(row) for row in archived
            } != {_fingerprint(link) for link in snapshot["links"]}
            db.expunge_all()  # the snapshot's rows reuse the archive's ids
            if has_links:
                db.execute(ShareLink.__table__.delete())
            for link in snapshot["links"]:
                if not has_links:
                    result["links_dropped"] += 1
                    continue
                if link["kind"] != "collection":
                    probe = ShareLink(
                        kind=link["kind"], set_id=link["set_id"], checklist_id=link["checklist_id"]
                    )
                    if _target_name(db, probe) != link.get("target_name"):
                        result["links_dropped"] += 1
                        continue
                db.add(_as_row(link))
                result["links_kept"] += 1
            if has_settings:
                store.set_setting(db, "share_enabled", result["enabled"])
            db.commit()
    except Exception:
        logger.exception("Restore: putting the share links back failed; switching sharing off")
        result["error"] = (
            "The share links could not be put back, so they were removed and sharing was "
            "switched off. Check Settings, Sharing."
        )
        result["enabled"] = False
        result["links_kept"] = 0
        _switch_sharing_off(engine)
    _audit_sharing(engine, result, actor)
    return result


def _switch_sharing_off(engine: Engine) -> None:
    """After a failed put-back: the rows in the table are the archive's (the
    transaction rolled back), so none may stay behind a switch the owner
    could turn on. In a transaction of its own; memory is set off whatever
    the database says."""
    try:
        with engine.connect() as conn:
            found = inspect_db(conn)
            has_links = found.has_table(ShareLink.__tablename__)
            has_settings = found.has_table(AppSetting.__tablename__)
        with Session(engine) as db:
            if has_links:
                db.execute(ShareLink.__table__.delete())
            if has_settings:
                store.set_setting(db, "share_enabled", False)
            db.commit()
    except Exception:
        logger.exception("Restore: could not remove the share links or switch sharing off")
    share.set_enabled(False)


def _audit_sharing(engine: Engine, result: dict, actor) -> None:
    from app.auth import audit

    detail = {key: value for key, value in result.items() if key != "error"}
    try:
        with Session(engine) as db:
            audit.record(db, "restore_sharing", actor or audit.Actor.system(), detail=detail)
            db.commit()
    except Exception:
        logger.exception("Restore: could not record restore_sharing")


def _sharing_sentence(sharing: dict | None) -> str:
    """For the restore's alert: said only when the archive differed."""
    if not sharing:
        return ""
    if sharing.get("error"):
        return " " + sharing["error"]
    words = ""
    if sharing.get("differed"):
        words = (
            " The archive held other share links or another sharing switch; this "
            "Cabinet's were kept."
        )
    if sharing.get("links_dropped"):
        words += (
            f" {sharing['links_dropped']} share link(s) whose set or checklist the archive "
            "doesn't hold were removed."
        )
    return words


def _reload_sharing(engine: Engine, sharing: dict | None = None) -> None:
    """Memory from the database, unless the put-back failed: then it stays
    off, since the database may still hold the archive's switch."""
    if sharing and sharing.get("error"):
        share.set_enabled(False)
        return
    try:
        with Session(engine) as db:
            share.load(db)
    except Exception:
        logger.exception("Restore: could not read whether sharing is on")
        share.reset_memory()  # the gate reads it on first use


def _write_pending(snapshot: dict, archive: str | None) -> None:
    _write_json(_pending_path(), {"archive": archive, "at": _now(), "snapshot": snapshot})


def _pending_snapshot() -> dict | None:
    """A snapshot a restart or a failed put-back left: the owner's links
    from before, not whatever the table holds now."""
    data = _read_json(_pending_path())
    snapshot = data.get("snapshot") if data else None
    return snapshot if isinstance(snapshot, dict) else None


_pending_lock = threading.Lock()


def apply_pending_sharing(engine: Engine | None = None) -> dict | None:
    """Put back the share links and switch a restore left in
    `pending_sharing.json`: at startup right after the migrations (or where
    they would run, when the operator migrates by hand), and again every
    hourly tick and when Settings is opened while the file is there. The
    result goes into the last outcome's `sharing`. The file goes only on
    success; on a failure every link is removed and sharing switched off
    (`_put_back_sharing`), and the next try runs from the same snapshot.
    Never raises."""
    with _pending_lock:
        path = _pending_path()
        if not path.exists():
            return None
        if engine is None:
            from app.db import engine
        try:
            snapshot = _pending_snapshot()
            if snapshot is None:
                logger.error(
                    "Restore: %s can't be read, so the share links it holds can't be put "
                    "back; sharing is switched off until the file is removed",
                    path,
                )
                _switch_sharing_off(engine)
                return None
            result = _put_back_sharing(engine, snapshot, None)
            last = last_outcome()
            if last is not None:
                _record({**last, "sharing": result})
            if result.get("error"):
                return result
            path.unlink(missing_ok=True)
            _reload_sharing(engine)
            logger.info("Restore: the share links from before the restore were put back")
            return result
        except Exception:
            logger.exception("Restore: putting the pending share links back failed")
            share.set_enabled(False)
            return None


# --- running ----------------------------------------------------------------


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="restore").start()


def start(
    restore_id: str, engine: Engine, phrase: str | None = None, actor=None, grant=None
) -> None:
    """Begin a restore on a background thread, or raise Unknown / Busy.
    `phrase` is what was typed; the run checks it against the archive's age
    again, from the archive itself. `actor` (an audit Actor) is who asked;
    the start and the end are audited and alerted under that name. `grant`
    (session hash, principal) is issued once this run holds the locks, so a
    refused second run never touches the first run's grant."""
    entry = _pending.get(restore_id)
    if entry is None or not entry["path"].is_file():
        raise Unknown("No such restore; inspect the archive again.")
    entry = {
        **entry,
        "typed": phrase if phrase is not None else entry.get("phrase"),
        "actor": actor,
    }
    if not _lock.acquire(blocking=False):
        raise Busy("A restore is already running.")
    # Held to the end, so no backup starts while the restore runs.
    if not backup._run_lock.acquire(blocking=False):
        _lock.release()
        raise Busy("A backup is running; try again when it has finished.")
    if maintenance.scheduled_busy():
        backup._run_lock.release()
        _lock.release()
        raise Busy("A scheduled task is running; try again in a moment.")
    if grant is not None:
        issue_grant(grant[0], restore_id, grant[1])
    _set_state(state="running", step="safety_backup", started_at=_now())
    _announce(engine, "restore_started", actor, entry["name"], f"Restoring {entry['name']}.")
    try:
        _spawn(lambda: _run(restore_id, entry, engine))
    except BaseException:
        drop_grant()
        _release()
        _set_state(state="idle", step=None, started_at=None)
        raise


def _confirm_age(engine: Engine, manifest: dict, typed: str | None) -> None:
    """Refuse plain RESTORE for an archive older than the newest recorded
    one, whatever its name or file time; an older one is alerted."""
    with Session(engine) as db:
        origin = provenance(db, manifest)
        if typed != origin["confirm_phrase"]:
            raise RestoreError(
                f"This archive is older than the newest backup this Cabinet made; type "
                f"{OLDER_PHRASE} to restore it anyway."
                if origin["older"]
                else f"Type {CONFIRM_PHRASE} to confirm."
            )
        if origin["older"]:
            alerts.event(
                db,
                "restore_older",
                "Cabinet is restoring an older backup",
                f"An archive from {manifest['created_at'][:10]} is being restored; "
                f"{origin['newer']} newer backup(s) exist.",
            )


def _refresh_phrase(restore_id: str, engine: Engine, manifest: dict | None) -> None:
    """After a failed run the archive stays pending for another try, but the
    safety backup just written is now the newest archive, so a retry may need
    RESTORE OLDER. Ask again rather than let the next run refuse halfway."""
    entry = _pending.get(restore_id)
    if entry is None or manifest is None:
        return
    try:
        with Session(engine) as db:
            entry["phrase"] = provenance(db, manifest)["confirm_phrase"]
    except Exception:
        logger.exception("Restore: could not recheck the archive's age")


def _release() -> None:
    backup._run_lock.release()
    _lock.release()


def _sentence(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message if message.endswith((".", "!", "?")) else message + "."


def _run(restore_id: str, entry: dict, engine: Engine) -> None:
    stored: Path = entry["path"]  # the encrypted archive, never read directly
    archive: Path | None = None  # its decrypted copy, in private staging
    outcome = {
        "at": _now(),
        "ok": False,
        "archive": entry["name"],
        "archive_created_at": None,
        "safety_backup": None,
        "error": None,
        "items": None,
        "photos": None,
        "documents": None,
        "secrets_cleared": [],
    }
    swaps: list[_Swap] = []
    dump: Path | None = None
    marker: str | None = None
    manifest: dict | None = None
    sharing: dict | None = None
    database_restored = False
    try:
        maintenance.enter()
        if not maintenance.drain():
            logger.warning("Restore: requests still running after the wait; going ahead")
        try:
            backup.empty_staging()
            _step("safety_backup")
            # Again, from the file itself: time has passed since the summary.
            archive = open_archive(stored, restore_id)
            manifest = check_archive(archive)
            _confirm_age(engine, manifest, entry.get("typed"))
            check_movable(manifest)
            counts = manifest.get("counts") or {}
            outcome.update(
                archive_created_at=manifest.get("created_at"),
                items=counts.get("items"),
                photos=counts.get("photos"),
                documents=counts.get("documents"),
            )
            _write_json(_journal_path(), {"phase": "preparing", **outcome})
            db = sessionmaker(bind=engine, autoflush=False)()
            try:
                safety = backup.write_prerestore(db, _replaces_files(manifest), protect=stored)
            except backup.BackupError as exc:
                raise RestoreError(
                    f"The safety backup failed, so the restore didn't start: {exc}"
                ) from exc
            finally:
                db.close()
            outcome["safety_backup"] = safety.name
            # After the safety backup (which carries them too), before the
            # database step: what to put back. A snapshot an earlier restore
            # left unapplied is the owner's, not what the table holds now.
            sharing = _pending_snapshot() or _snapshot_sharing(engine)

            # Unpack first, swap last: unpacking is what can run out of room
            # or meet a bad member, and it touches nothing live.
            _clear_workdirs()
            for member, step_name, folder in _file_targets():
                if member in manifest["members"]:
                    _step(step_name)
                    _extract(archive, member, folder)
                    swaps.append(_Swap(folder))

            _step("database")
            dump = extract_dump(archive, restore_id)
            refuse_auth(dump, _server_major(engine))  # again, from the file about to be used
            if _swaps_photos(manifest):
                # The archive's photos may carry metadata: the pass after the
                # swap cleans them, and a restart before then runs one too.
                photos.remove_marker()
            # From here a restarted backend asks the database what happened.
            marker = _write_marker(engine)
            journal = {
                "phase": "database",
                "marker": marker,
                "dropped": [],
                "sharing_snapshot": sharing,
                **outcome,
            }
            _write_json(_journal_path(), journal)

            def journal_drop(names: list[str]) -> None:
                _write_json(_journal_path(), {**journal, "dropped": names})

            dispose_engine(engine)
            restore_database(dump, on_drop=journal_drop)
        except Exception as exc:
            for swap in swaps:
                shutil.rmtree(swap.new, ignore_errors=True)
            if marker is not None:
                try:
                    _delete_marker(engine)
                except Exception:
                    logger.exception("Restore: could not remove the marker row")
            if isinstance(exc, PartialDatabase):
                raise RestoreError(
                    f"{exc} Restore {outcome['safety_backup']} to return to how things were."
                ) from exc
            raise RestoreError(f"{_sentence(exc)} {NOTHING_CHANGED}") from exc
        database_restored = True
        put_back = False

        def put_sharing_back() -> None:
            nonlocal put_back
            if put_back:
                return
            put_back = True
            outcome["sharing"] = result = _put_back_sharing(engine, sharing, entry.get("actor"))
            try:
                if result is not None and result.get("error"):
                    _write_pending(sharing, outcome["archive"])  # tried again later
                else:
                    _pending_path().unlink(missing_ok=True)
            except OSError:
                logger.exception("Restore: could not update %s", _pending_path())

        try:
            _write_json(
                _journal_path(), {"phase": "swapping", "sharing_snapshot": sharing, **outcome}
            )
            go_back = f"Restore {outcome['safety_backup']} to return to how things were."
            outcome["secrets_cleared"] = _after_database(engine)

            migration_error = None
            if _will_migrate(manifest):
                _step("migrations")
                try:
                    dispose_engine(engine)
                    migrate(engine)  # the collection chain only
                except Exception as exc:
                    logger.exception("Restore: migrating the restored database failed")
                    migration_error = exc
            # After the migrations: an archive from before 0022 has no
            # share_links table until they run.
            put_sharing_back()

            _step("finishing")
            try:
                for swap in swaps:
                    swap.apply()
            except Exception as exc:
                logger.exception("Restore: replacing the files failed; putting them back")
                for swap in swaps:
                    try:
                        swap.undo()
                    except OSError:
                        logger.exception("Restore: could not put back %s", swap.folder)
                raise RestoreError(
                    f"The database was restored, but replacing the files failed "
                    f"({_sentence(exc)[:-1]}), so the previous files were put back. {go_back}"
                ) from exc
            for swap in swaps:
                swap.finish()
            if _swaps_photos(manifest):
                # Again, now that the archive's photos are in place: a pass that
                # started after the first removal, before the swap, would
                # otherwise write the marker over files it never saw.
                photos.remove_marker()
                photos.clean_in_background(force=True)
            if migration_error is not None:
                raise RestoreError(
                    "The archive was restored, but bringing its database up to this version "
                    f"failed: {_sentence(migration_error)} Restart the backend to try the "
                    f"migration again. {go_back}"
                )
        finally:
            # The database is the archive's: whatever failed after it (the
            # journal write, the secrets, the migrations), its links and
            # switch are never left in place.
            put_sharing_back()
        outcome["ok"] = True
        logger.info("Restore: done (%s)", outcome["archive"])
    except BaseException as exc:
        if not isinstance(exc, RestoreError):
            logger.exception("Restore failed unexpectedly")
        else:
            logger.error("Restore failed: %s", exc)
        tail = "" if isinstance(exc, RestoreError) or database_restored else f" {NOTHING_CHANGED}"
        outcome["error"] = _sentence(exc) + tail
        _refresh_phrase(restore_id, engine, manifest)
    finally:
        _finish(restore_id, entry, engine, dump, outcome)


def _finish(restore_id: str, entry: dict, engine: Engine, dump: Path | None, outcome: dict):
    """Always runs: tidy up, record the outcome, reopen the API, and only
    then report done or failed, so whoever sees that state can read the rest."""
    try:
        if dump is not None:
            dump.unlink(missing_ok=True)
        backup.empty_staging()
        if outcome["ok"] and entry["staged"]:  # the uploaded ciphertext
            entry["path"].unlink(missing_ok=True)
        if outcome["ok"] or not entry["path"].is_file():
            _pending.pop(restore_id, None)
        _journal_path().unlink(missing_ok=True)
        dispose_engine(engine)
        metrics.reset_cache()
        alerts.reset_memory()
        _reload_sharing(engine, outcome.get("sharing"))
    except Exception:
        logger.exception("Restore: tidying up failed")
        if (outcome.get("sharing") or {}).get("error"):
            share.set_enabled(False)
    _record(outcome)
    maintenance.leave()
    _end_grant(restore_id)
    _announce(
        engine,
        "restore_finished",
        entry.get("actor"),
        entry["name"],
        # Never the error itself: pg_restore's output can quote the
        # collection's rows. The reason is in Settings and the outcome file.
        (
            f"Restore of {entry['name']} finished."
            if outcome["ok"]
            else f"Restore of {entry['name']} failed. The reason is in Settings, Backups."
        )
        + _sharing_sentence(outcome.get("sharing")),
        {"ok": bool(outcome["ok"])},
    )
    _set_state(state="done" if outcome["ok"] else "failed", step=None)
    _release()


def _announce(engine: Engine, action: str, actor, target: str, message: str, detail=None):
    """Audit and alert a restore's start or end. Never fails the restore: the
    sign-in schema is untouched by it, but the database may be unreachable."""
    from app.auth import audit, notify

    try:
        with Session(engine) as db:
            audit.record(db, action, actor or audit.Actor.system(), target=target, detail=detail)
            db.commit()
            notify.send(db, action, message)
    except Exception:
        logger.exception("Restore: could not record %s", action)


def _roll_forward(folders: list[Path]) -> None:
    for folder in folders:
        swap = _Swap(folder)
        if swap.new.is_dir():
            swap.apply()
        swap.finish()


def _drop_unpacked(folders: list[Path]) -> None:
    for folder in folders:
        shutil.rmtree(folder / NEW_DIR, ignore_errors=True)


def recover(engine: Engine | None = None) -> None:
    """On startup: deal with a restore the last process didn't finish.

    `preparing`: nothing had changed; the unpacked files are dropped.
    `database`: the marker row answers whether the database was replaced.
    This restore's value still there means pg_restore's transaction never
    committed (nothing changed, unless leftover tables had been dropped
    first: partial). No row, or any other value, means the archive's database
    is in place: its marker rows and unusable secrets are cleared, the file
    swap is rolled forward, and startup migrates. If the database can't be
    reached, the journal is kept and the backend stays in maintenance until a
    restart can decide, rather than serve an old database with new files.
    `swapping`: the swap is rolled forward (renames `_Swap.apply` can repeat).
    Whenever the database is the archive's, the journal's share-link
    snapshot goes to `pending_sharing.json` first, for `apply_pending_sharing`
    after the migrations (an archive from before 0022 has no share_links
    table until then); if that file can't be written, the journal is kept
    and the backend stays in maintenance, as above.
    Staging is emptied entirely, and so are uploads a restart has orphaned."""
    backup.empty_staging(everything=True)
    _clear_uploads()
    journal = _read_json(_journal_path())
    if journal is None:
        _clear_legacy_dumps()
        return
    phase = journal.pop("phase", None)
    marker = journal.pop("marker", None)
    dropped = journal.pop("dropped", None) or []
    snapshot = journal.pop("sharing_snapshot", None)
    outcome = {**journal, "ok": False}
    folders = [folder for _m, _s, folder in _file_targets()]
    try:
        if phase == "database":
            if engine is None:
                from app.db import engine
            try:
                if not marker:
                    raise ValueError("the journal names no marker")
                schema.wait_for_database(engine)
                found = _read_marker(engine)
            except Exception:
                logger.exception(
                    "A restore was interrupted during the database step, and whether the "
                    "database was replaced can't be told yet; staying in maintenance until "
                    "a restart can decide"
                )
                maintenance.enter()
                return  # the journal stays
            _delete_marker(engine)
            if found == marker:
                _drop_unpacked(folders)
                safety = outcome.get("safety_backup")
                if dropped:
                    outcome["error"] = (
                        "The backend stopped during the restore after removing tables newer "
                        f"than the archive ({', '.join(dropped)}); the rest of the database is "
                        f"as it was. Restore {safety} to return to how things were."
                    )
                else:
                    outcome["error"] = f"The backend stopped during the restore. {NOTHING_CHANGED}"
                logger.warning("A restore was interrupted before the database was replaced")
            else:
                if not _keep_snapshot(snapshot, outcome):
                    return  # the journal stays
                outcome["secrets_cleared"] = _after_database(engine)
                photos.remove_marker()  # the startup pass cleans what comes in
                _roll_forward(folders)
                outcome["ok"] = True
                outcome["finished_after_restart"] = True
                logger.warning(
                    "Finished a restore that was interrupted after the database was replaced"
                )
        elif phase == "swapping":
            if not _keep_snapshot(snapshot, outcome):
                return  # the journal stays
            photos.remove_marker()
            _roll_forward(folders)
            outcome["ok"] = True
            logger.warning("Finished a restore that was interrupted while replacing files")
        else:
            _drop_unpacked(folders)
            outcome["error"] = f"The backend stopped during the restore. {NOTHING_CHANGED}"
            logger.warning("A restore was interrupted before the database was replaced")
    except OSError as exc:
        logger.exception("Could not finish the interrupted restore")
        outcome["error"] = (
            f"The backend stopped during the restore and the files could not be "
            f"put in place afterwards: {_sentence(exc)}"
        )
    _record(outcome)
    _journal_path().unlink(missing_ok=True)
    _clear_legacy_dumps()


def _keep_snapshot(snapshot: dict | None, outcome: dict) -> bool:
    """For a restore stopped after the database step: leave the snapshot
    for `apply_pending_sharing` (the put-back may or may not have run, and
    running it again gives the same result). False, with the backend in
    maintenance, when it can't be written: the journal must stay, or the
    archive's links would be left live."""
    if snapshot is None:
        return True
    try:
        _write_pending(snapshot, outcome.get("archive"))
    except OSError:
        logger.exception(
            "A restore was interrupted after the database step, and the share links to put "
            "back can't be saved; staying in maintenance until a restart can"
        )
        maintenance.enter()
        return False
    return True


def _swaps_photos(manifest: dict | None) -> bool:
    return manifest is not None and "photos.tar.gz" in manifest.get("members", {})


def _clear_uploads() -> None:
    """At startup: a staged upload's restore id lived in memory, so none can
    be run any more; don't leave them on the backup share."""
    try:
        folder = backup.backup_dir() / STAGING_DIR  # looked at, never created here
        for leftover in folder.glob("*.upload"):
            leftover.unlink(missing_ok=True)
    except (backup.BackupError, OSError):
        pass


def _clear_legacy_dumps() -> None:
    """Releases before v0.30.0 unpacked dumps beside the uploads, in the
    backup directory; remove any they left."""
    try:
        folder = backup.backup_dir() / STAGING_DIR  # looked at, never created here
        for leftover in folder.glob("*.dump"):
            leftover.unlink(missing_ok=True)
    except (backup.BackupError, OSError):
        pass
