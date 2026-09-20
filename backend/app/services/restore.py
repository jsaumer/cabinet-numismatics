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
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.services import alerts, backup, maintenance, metrics, schema

logger = logging.getLogger(__name__)

CONFIRM_PHRASE = "RESTORE"
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

_lock = threading.Lock()  # held for the length of a restore
_state_lock = threading.Lock()
_state: dict = {"state": "idle", "step": None, "started_at": None}
_pending: dict[str, dict] = {}
_memory_last: dict | None = None  # if the state volume can't be written


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


def staging_dir() -> Path:
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


def reset_memory() -> None:
    """Forget in-memory state (tests)."""
    global _memory_last
    _memory_last = None
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


def check_archive(path: Path) -> dict:
    """Verify an archive end to end; return its manifest."""
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


def _will_migrate(manifest: dict) -> bool:
    return manifest["schema_revision"] != schema.script_revisions()[0]


def _replaces_files(manifest: dict) -> bool:
    return any(member != "db.dump" for member in manifest["members"])


# --- staging and inspecting -------------------------------------------------


def clean_staging() -> None:
    """Drop staged uploads (and unpacked dumps) older than a day."""
    cutoff = (datetime.now(timezone.utc) - STALE_UPLOAD_AGE).timestamp()
    try:
        staged = list(staging_dir().iterdir())
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
    return restore_id, staging_dir() / f"{restore_id}.zip"


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
    upload that fails the check is deleted."""
    try:
        manifest = check_archive(path)
    except BaseException:
        if staged:
            path.unlink(missing_ok=True)
        raise
    check_movable(manifest)  # say so now, not after the database has gone
    restore_id = restore_id or uuid.uuid4().hex
    _pending[restore_id] = {"path": path, "name": name, "staged": staged}
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
    }


def discard(restore_id: str) -> None:
    """Forget a restore id; delete the file only if it was a staged upload.
    An archive in the backup directory is never deleted from here."""
    entry = _pending.pop(restore_id, None)
    if entry is None:
        # Staged before a restart: the id is the file's name.
        if not ID_RE.match(restore_id):
            raise Unknown("No such restore")
        path = staging_dir() / f"{restore_id}.zip"
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
    schema.upgrade_to_head(engine)


def _dump_tables(pg_restore: str, dump_path: Path) -> set[str]:
    listing = subprocess.run(
        [pg_restore, "--list", str(dump_path)], capture_output=True, text=True, check=False
    )
    if listing.returncode != 0:
        raise RestoreError(f"pg_restore can't read the dump: {listing.stderr.strip()[-500:]}")
    return set(re.findall(r"^\d+; \d+ \d+ TABLE public (\S+) ", listing.stdout, re.MULTILINE))


def restore_database(dump_path: Path) -> None:
    """pg_restore the dump over the live database in ONE transaction, so a
    failure leaves the database as it was (but see PartialDatabase, for an
    archive older than some of the tables here). Tests monkeypatch this
    (SQLite has no pg_restore), like `backup.dump_database`."""
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
        present = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        dropped = sorted(set(present) - tables)
        for leftover in dropped:
            logger.info("Restore: dropping %s, which the archive predates", leftover)
            conn.execute(text(f'DROP TABLE IF EXISTS public."{leftover}" CASCADE'))
    engine.dispose()

    env = backup._pg_env()
    env["PGOPTIONS"] = f"{env.get('PGOPTIONS', '')} -c lock_timeout={LOCK_TIMEOUT}".strip()
    database = make_url(get_settings().database_url).database
    result = subprocess.run(
        [
            pg_restore,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--single-transaction",
            f"--dbname={database}",
            str(dump_path),
        ],
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


# --- running ----------------------------------------------------------------


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="restore").start()


def start(restore_id: str, engine: Engine) -> None:
    """Begin a restore on a background thread, or raise Unknown / Busy."""
    entry = _pending.get(restore_id)
    if entry is None or not entry["path"].is_file():
        raise Unknown("No such restore; inspect the archive again.")
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
    _set_state(state="running", step="safety_backup", started_at=_now())
    try:
        _spawn(lambda: _run(restore_id, entry, engine))
    except BaseException:
        _release()
        _set_state(state="idle", step=None, started_at=None)
        raise


def _release() -> None:
    backup._run_lock.release()
    _lock.release()


def _sentence(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message if message.endswith((".", "!", "?")) else message + "."


def _run(restore_id: str, entry: dict, engine: Engine) -> None:
    archive: Path = entry["path"]
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
    }
    swaps: list[_Swap] = []
    dump: Path | None = None
    database_restored = False
    try:
        maintenance.enter()
        if not maintenance.drain():
            logger.warning("Restore: requests still running after the wait; going ahead")
        try:
            _step("safety_backup")
            manifest = check_archive(archive)  # again: time has passed since the summary
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
                safety = backup.write_prerestore(db, _replaces_files(manifest), protect=archive)
            except backup.BackupError as exc:
                raise RestoreError(
                    f"The safety backup failed, so the restore didn't start: {exc}"
                ) from exc
            finally:
                db.close()
            outcome["safety_backup"] = safety.name

            # Unpack first, swap last: unpacking is what can run out of room
            # or meet a bad member, and it touches nothing live.
            _clear_workdirs()
            for member, step_name, folder in _file_targets():
                if member in manifest["members"]:
                    _step(step_name)
                    _extract(archive, member, folder)
                    swaps.append(_Swap(folder))

            _step("database")
            dump = staging_dir() / f"{restore_id}.dump"
            with zipfile.ZipFile(archive) as zf, zf.open("db.dump") as src, open(dump, "wb") as out:
                shutil.copyfileobj(src, out, backup.CHUNK)
            dispose_engine(engine)
            restore_database(dump)
        except Exception as exc:
            for swap in swaps:
                shutil.rmtree(swap.new, ignore_errors=True)
            if isinstance(exc, PartialDatabase):
                raise RestoreError(
                    f"{exc} Restore {outcome['safety_backup']} to return to how things were."
                ) from exc
            raise RestoreError(f"{_sentence(exc)} {NOTHING_CHANGED}") from exc
        database_restored = True
        _write_json(_journal_path(), {"phase": "swapping", **outcome})
        go_back = f"Restore {outcome['safety_backup']} to return to how things were."

        migration_error = None
        if _will_migrate(manifest):
            _step("migrations")
            try:
                dispose_engine(engine)
                migrate(engine)
            except Exception as exc:
                logger.exception("Restore: migrating the restored database failed")
                migration_error = exc

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
        if migration_error is not None:
            raise RestoreError(
                "The archive was restored, but bringing its database up to this version "
                f"failed: {_sentence(migration_error)} Restart the backend to try the "
                f"migration again. {go_back}"
            )
        outcome["ok"] = True
        logger.info("Restore: done (%s)", outcome["archive"])
    except BaseException as exc:
        if not isinstance(exc, RestoreError):
            logger.exception("Restore failed unexpectedly")
        else:
            logger.error("Restore failed: %s", exc)
        tail = "" if isinstance(exc, RestoreError) or database_restored else f" {NOTHING_CHANGED}"
        outcome["error"] = _sentence(exc) + tail
    finally:
        _finish(restore_id, entry, engine, dump, outcome)


def _finish(restore_id: str, entry: dict, engine: Engine, dump: Path | None, outcome: dict):
    """Always runs: tidy up, record the outcome, reopen the API, and only
    then report done or failed, so whoever sees that state can read the rest."""
    try:
        if dump is not None:
            dump.unlink(missing_ok=True)
        if outcome["ok"] and entry["staged"]:
            entry["path"].unlink(missing_ok=True)
        if outcome["ok"] or not entry["path"].is_file():
            _pending.pop(restore_id, None)
        _journal_path().unlink(missing_ok=True)
        dispose_engine(engine)
        metrics.reset_cache()
        alerts.reset_memory()
    except Exception:
        logger.exception("Restore: tidying up failed")
    _record(outcome)
    maintenance.leave()
    _set_state(state="done" if outcome["ok"] else "failed", step=None)
    _release()


def recover() -> None:
    """On startup: deal with a restore the last process didn't finish. Once
    the database had been replaced the file swap is rolled forward (renames
    that `_Swap.apply` can repeat); before that, the unpacked files are
    dropped and nothing had changed."""
    journal = _read_json(_journal_path())
    if journal is None:
        return
    phase = journal.pop("phase", None)
    outcome = {**journal, "ok": False}
    try:
        folders = [folder for _m, _s, folder in _file_targets()]
        if phase == "swapping":
            for folder in folders:
                swap = _Swap(folder)
                if swap.new.is_dir():
                    swap.apply()
                swap.finish()
            outcome["ok"] = True
            logger.warning("Finished a restore that was interrupted while replacing files")
        else:
            for folder in folders:
                shutil.rmtree(folder / NEW_DIR, ignore_errors=True)
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
    try:
        for leftover in staging_dir().glob("*.dump"):
            leftover.unlink(missing_ok=True)
    except (backup.BackupError, OSError):
        pass
