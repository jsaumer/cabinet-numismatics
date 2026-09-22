"""In-app backups: one zip holding the database dump, the photo and document
volumes, and a manifest that makes the archive checkable rather than merely
present, encrypted with the backup key (v0.30.0).

The zip is streamed straight into `age` (X25519, the key in
`archive_keys`), which writes the only file: `<name>.zip.age.partial` in the
backup directory, renamed when complete. No plain archive, member, or
partial ever touches the backup directory. The manifest carries a MAC keyed
by the backup key (`archive_keys.sign`), and every archive written is
recorded in `cabinet_auth.backup_ledger`, which no restore rewrites.
Decrypting happens only in the private staging folder.

The dump never holds the `cabinet_auth` schema: an archive carries no
credential, so restoring one can't add, change, or revoke one.
`SHA256SUMS` lets a shell verify the decrypted zip with `sha256sum -c`.
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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.models import Document, Item, ItemPhoto, PriceEstimate
from app.models.auth import BackupRecord
from app.services import alerts, archive_keys, schema
from app.services import app_settings as store

logger = logging.getLogger(__name__)

FORMAT = "cabinet-backup"
FORMAT_VERSION = 1
# `.zip.age` from v0.30.0; a plain `.zip` is an unencrypted archive from an
# earlier release, listed (and deletable) but never restored.
NAME_RE = re.compile(r"^cabinet-backup-\d{8}-\d{6}(-data|-prerestore)?\.zip(\.age)?$")
ENCRYPTED = ".zip.age"
AGE_MAGIC = b"age-encryption.org/v1\n"
# Safety archives written before an in-app restore: outside `backup_keep`.
PRERESTORE_MARK = "-prerestore.zip"
PRERESTORE_KEEP = 3
# Working directories a restore makes inside the photo and document volumes
# (`.restore-new`, `.restore-old`) and the backup directory (`.restore-staging`).
RESTORE_PREFIX = ".restore-"
SCHEDULES = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
# The scheduler checks hourly; the slack keeps a daily run from slipping a
# whole tick when the previous one started a few seconds late.
SCHEDULE_SLACK = timedelta(minutes=10)
RETRY_AFTER = timedelta(hours=1)
STALE_TEMP_AGE = timedelta(days=1)
CHUNK = 1024 * 1024
# One pg_dump/pg_restore per supported server major (see backend/Dockerfile).
PG_CLIENT_ROOT = Path("/usr/local/lib/pgclient")
# Sign-in data: never dumped, never restored (see app/models/auth.py).
AUTH_SCHEMA = "cabinet_auth"
# Room kept free beyond what an unpacked member needs.
ROOM_MARGIN = 1.05
# The archive record keeps 180 days, and never fewer than the newest 50.
LEDGER_DAYS = 180
LEDGER_KEEP = 50
LEDGER_KINDS = ("scheduled", "manual", "download", "prerestore")
# manifest.json and SHA256SUMS are read before the MAC is checked.
MAX_SMALL_MEMBER = 1024 * 1024

_run_lock = threading.Lock()


class BackupError(Exception):
    """No archive could be produced: pg_dump missing or failed, or the
    destination is unwritable."""


class BackupBusy(BackupError):
    """Another backup into the backup directory is already running."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def archive_name(now: datetime, include_photos: bool) -> str:
    return f"cabinet-backup-{now:%Y%m%d-%H%M%S}{'' if include_photos else '-data'}{ENCRYPTED}"


def is_data_only(path: Path) -> bool:
    return "-data.zip" in path.name


def is_prerestore(path: Path) -> bool:
    return PRERESTORE_MARK in path.name


def is_encrypted(path: Path) -> bool:
    return path.name.endswith(ENCRYPTED)


def looks_encrypted(path: Path) -> bool:
    """Whether a file starts like an age file (whatever its name says)."""
    try:
        with path.open("rb") as fh:
            return fh.read(len(AGE_MAGIC)) == AGE_MAGIC
    except OSError:
        return False


def signing_key() -> archive_keys.Identity:
    """The identity new archives are encrypted to and signed with. A key that
    can't be read fails the backup (and alerts); it is never replaced."""
    try:
        return archive_keys.primary()
    except archive_keys.KeyUnavailable as exc:
        raise BackupError(str(exc)) from None


# --- age, called as a program ----------------------------------------------------


def _age() -> str:
    found = shutil.which("age")
    if found is None:
        raise BackupError("The age program is not installed, so no archive can be encrypted.")
    return found


@contextmanager
def encrypt_stream(dst, recipient: str):
    """A writable stream whose bytes `age` encrypts to `recipient` into `dst`
    (a path, or a binary file object such as stdout). Nothing unencrypted is
    written anywhere. A monkeypatch point for tests (no age binary there)."""
    command = [_age(), "--encrypt", "--recipient", recipient]
    if isinstance(dst, (str, Path)):
        command += ["--output", str(dst)]
        stdout = subprocess.DEVNULL
    else:
        stdout = dst
    with tempfile.TemporaryFile() as err:

        def failure() -> BackupError:
            err.seek(0)
            return BackupError(f"age failed: {err.read().decode(errors='replace').strip()[-300:]}")

        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=err)
        try:
            yield proc.stdin
            proc.stdin.close()
        except BrokenPipeError:
            # age exited early: its own message says why, not the pipe.
            proc.wait()
            raise failure() from None
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if proc.wait() != 0:
            raise failure()


def decrypt_stream(src, dst, key_file: Path) -> None:
    """Decrypt `src` (a path or binary file object) into the binary file
    object `dst` with the identities in `key_file` (never on a command line).
    Raises BackupError when no identity matches or the file was altered: age
    authenticates every chunk. A monkeypatch point for tests."""
    command = [_age(), "--decrypt", "--identity", str(key_file)]
    from_file = isinstance(src, (str, Path))
    if from_file:
        command.append(str(src))
    with tempfile.TemporaryFile() as err:
        result = subprocess.run(command, stdin=None if from_file else src, stdout=dst, stderr=err)
        if result.returncode != 0:
            err.seek(0)
            detail = err.read().decode(errors="replace").strip()[-300:]
            raise BackupError(f"age could not open the archive: {detail}")


def _skip_restore_dirs(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Leave a restore's working directories out of the file archives."""
    parts = Path(member.name).parts
    return None if any(part.startswith(RESTORE_PREFIX) for part in parts) else member


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


def dump_command(pg_dump: str) -> list[str]:
    """The collection, never the sign-in schema."""
    return [pg_dump, "--format=custom", f"--exclude-schema={AUTH_SCHEMA}"]


def dump_database(out, server_major: int) -> str:
    """Stream a custom-format pg_dump of the collection into `out` (every
    schema but `cabinet_auth`); return the pg_dump version used."""
    pg_dump = pg_tool("pg_dump", server_major)
    version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True).stdout
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            dump_command(pg_dump), stdout=subprocess.PIPE, stderr=err, env=_pg_env()
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
    everything = {"include_deleted": True}  # the archive holds the trash too
    return {
        "items": db.scalar(select(func.count()).select_from(Item).execution_options(**everything)),
        "in_trash": db.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.deleted_at.is_not(None))
            .execution_options(**everything)
        ),
        "photos": db.scalar(select(func.count()).select_from(ItemPhoto)),
        "documents": db.scalar(select(func.count()).select_from(Document)),
        "estimates": db.scalar(select(func.count()).select_from(PriceEstimate)),
    }


def write_archive(out, db: Session, include_photos: bool = True) -> dict:
    """Write a backup zip into the stream `out` (it need not be seekable:
    the zip goes straight into age) and return its signed manifest."""
    created = utcnow()
    counts = _counts(db)
    connection = db.connection()
    revision = schema.current_revision(connection)
    server_version = connection.dialect.server_version_info or (0,)
    signer = signing_key()  # before anything is written: no key, no archive
    members: dict[str, dict] = {}
    with zipfile.ZipFile(out, "w", allowZip64=True) as zf:
        # Both payloads are already compressed, so they're stored, not deflated.
        with zf.open("db.dump", "w", force_zip64=True) as raw:
            writer = _HashingWriter(raw)
            dump_version = dump_database(writer, server_version[0])
            members["db.dump"] = writer.summary()
        if include_photos:
            # Photos and attached documents travel together: "data only"
            # leaves out every file, keeping the archive small.
            settings = get_settings()
            for member, folder in (
                ("photos.tar.gz", Path(settings.photo_dir)),
                ("documents.tar.gz", Path(settings.document_dir)),
            ):
                with zf.open(member, "w", force_zip64=True) as raw:
                    writer = _HashingWriter(raw)
                    with tarfile.open(fileobj=writer, mode="w|gz") as tar:
                        if folder.is_dir():
                            tar.add(folder, arcname=".", filter=_skip_restore_dirs)
                    members[member] = writer.summary()
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "schema_revision": revision,
            "server_version": ".".join(map(str, server_version)),
            "pg_dump_version": dump_version,
            "created_at": created.isoformat(),
            "includes_photos": include_photos,
            "includes_documents": include_photos,
            "counts": counts,
            # Informational: the dump's own table of contents is what a restore
            # checks (restore.refuse_auth).
            "auth_excluded": True,
            "members": members,
            "restore": "scripts/restore.sh <this archive> (see docs/backup-restore.md)",
        }
        sums = "".join(f"{m['sha256']}  {name}\n" for name, m in members.items()).encode()
        archive_keys.sign(manifest, sums, signer)
        zf.writestr(
            "manifest.json", json.dumps(manifest, indent=2), compress_type=zipfile.ZIP_DEFLATED
        )
        zf.writestr("SHA256SUMS", sums)
    return manifest


def list_dump(path: Path, server_major: int) -> list[str]:
    """The dump's table of contents (`pg_restore --list`), one entry a line.
    Reads the file only; no database is touched. Tests monkeypatch this (no
    pg_restore on the dev machine), like `dump_database`."""
    pg_restore = pg_tool("pg_restore", server_major)
    listing = subprocess.run([pg_restore, "--list", str(path)], capture_output=True, text=True)
    if listing.returncode != 0:
        raise BackupError(f"pg_restore can't read the dump: {listing.stderr.strip()[-500:]}")
    return listing.stdout.splitlines()


def _copy_unescape(field: str) -> str | None:
    """One field of COPY's text format."""
    if field == "\\N":
        return None
    out, chars = [], iter(field)
    for ch in chars:
        if ch != "\\":
            out.append(ch)
            continue
        nxt = next(chars, "")
        out.append({"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}.get(nxt, nxt))
    return "".join(out)


def dump_settings(path: Path, server_major: int) -> dict:
    """The `app_settings` rows a dump holds, as {key: value}, read without a
    database (`pg_restore --data-only` to text). Used to name the secrets an
    archive would set. Tests monkeypatch this, like `list_dump`."""
    pg_restore = pg_tool("pg_restore", server_major)
    result = subprocess.run(
        [pg_restore, "--data-only", "--schema=public", "--table=app_settings", "-f", "-"]
        + [str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BackupError(f"pg_restore can't read the dump: {result.stderr.strip()[-500:]}")
    rows: dict = {}
    columns: list[str] | None = None
    for line in result.stdout.splitlines():
        if columns is None:
            match = re.match(r"^COPY \S*app_settings \(([^)]*)\) FROM stdin;$", line)
            if match:
                columns = [c.strip().strip('"') for c in match.group(1).split(",")]
            continue
        if line == "\\.":
            break
        fields = dict(zip(columns, (_copy_unescape(f) for f in line.split("\t")), strict=False))
        key, raw = fields.get("key"), fields.get("value")
        if key is None:
            continue
        try:
            rows[key] = json.loads(raw) if raw is not None else None
        except ValueError:
            rows[key] = raw
    return rows


# --- the private staging folder ----------------------------------------------


def staging_dir() -> Path:
    """The private folder an archive's dump is unpacked into: 0700, owned by
    the app's user, and apart from the backup, photo, document, and state
    directories in both directions: not inside one, since what lands here is
    the collection in plain form, and not around one, since it is emptied on
    every start."""
    config = get_settings()
    path = Path(config.staging_dir).resolve()
    for name, other in (
        ("backup", config.backup_dir),
        ("photo", config.photo_dir),
        ("document", config.document_dir),
        ("state", str(Path(config.secret_key_file).parent)),
    ):
        other = Path(other).resolve()
        if path.is_relative_to(other) or other.is_relative_to(path):
            raise BackupError(
                f"The staging folder {path} must be apart from the {name} directory {other}."
            )
    try:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    except OSError as exc:
        raise BackupError(f"The staging folder {path} is not usable: {exc}") from exc
    return path


CLI_PREFIX = ".cli-"  # a container command's own working files


def empty_staging(everything: bool = False) -> None:
    """Remove what is inside the staging folder (never the folder: it is a
    mount point). A container command running in another process keeps its
    `.cli-` files unless `everything` (at startup, when none can be running)."""
    try:
        entries = list(staging_dir().iterdir())
    except (BackupError, OSError):
        return
    for entry in entries:
        if not everything and entry.name.startswith(CLI_PREFIX):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def ensure_room(folder: Path, needed: int, what: str) -> None:
    free = shutil.disk_usage(folder).free
    if free < needed * ROOM_MARGIN:
        raise BackupError(
            f"Not enough space to open this archive: {what} needs {needed} bytes in "
            f"{folder}, which has {free} free."
        )


def private_file(path: Path):
    """A new file only the app's user can read (0600), opened for writing."""
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def verify_archive(path: Path) -> dict:
    """Check a decrypted archive: its MAC first (made with this deployment's
    backup key, nothing altered), then every member against the manifest.
    Returns the manifest."""
    try:
        with zipfile.ZipFile(path) as zf:
            # Read before the MAC, so bounded: anyone can encrypt to the public
            # key, so an unverified manifest may be anything.
            for small in ("manifest.json", "SHA256SUMS"):
                if zf.getinfo(small).file_size > MAX_SMALL_MEMBER:
                    raise BackupError(f"Not a Cabinet backup archive: {small} is too large.")
            manifest = json.loads(zf.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
                raise BackupError("Not a Cabinet backup archive.")
            sums = zf.read("SHA256SUMS")
            try:
                archive_keys.verify(manifest, sums)
            except (archive_keys.NotOurs, archive_keys.KeyUnavailable) as exc:
                raise BackupError(str(exc)) from None
            # Exactly the members the MAC covers, each once, and nothing else:
            # zipfile reads the last of two same-named entries and unzip keeps
            # the first, so an extra or doubled member could be restored by a
            # tool that saw different bytes from the ones verified here.
            members = manifest["members"]
            names = zf.namelist()
            if len(names) != len(set(names)):
                raise BackupError("Not a Cabinet backup archive: a member appears twice.")
            if set(names) != set(members) | {"manifest.json", "SHA256SUMS"}:
                raise BackupError("Not a Cabinet backup archive: its members don't match.")
            listed = "".join(f"{m['sha256']}  {name}\n" for name, m in members.items()).encode()
            if sums != listed:
                raise BackupError("Not a Cabinet backup archive: SHA256SUMS doesn't match.")
            for name, expected in members.items():
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


def decrypt_to_staging(archive: Path, stem: str) -> Path:
    """Decrypt an archive into the private staging folder as `<stem>.zip`
    (0600), after checking there is room for it. The only place a decrypted
    archive ever exists."""
    folder = staging_dir()
    ensure_room(folder, archive.stat().st_size, "the archive")
    target = folder / f"{stem}.zip"
    target.unlink(missing_ok=True)
    try:
        with private_file(target) as out:
            decrypt_stream(archive, out, archive_keys.key_path())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def self_test() -> None:
    """At startup: encrypt a few bytes to the backup key and decrypt them
    again with the real age, in private staging. A key age refuses, or no
    age at all, is found now rather than at the first restore. Raises
    BackupError; the caller logs it (startup goes on)."""
    folder = staging_dir()
    probe, plain = folder / ".self-test.age", folder / ".self-test.out"
    payload = b"cabinet backup key self-test"
    try:
        probe.unlink(missing_ok=True)
        plain.unlink(missing_ok=True)
        with encrypt_stream(probe, signing_key().recipient) as out:
            out.write(payload)
        with private_file(plain) as out:
            decrypt_stream(probe, out, archive_keys.key_path())
        if plain.read_bytes() != payload:
            raise BackupError("the backup key self-test got different bytes back")
    except OSError as exc:
        raise BackupError(f"the backup key self-test failed: {exc}") from None
    finally:
        probe.unlink(missing_ok=True)
        plain.unlink(missing_ok=True)


def record_key_mismatch(db: Session) -> str | None:
    """The public key of the newest recorded archive, when this deployment no
    longer has that key: those archives can't be opened here any more. None
    when all is well or nothing is recorded."""
    newest = db.execute(
        select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if newest is None:
        return None
    known = {identity.recipient for identity in archive_keys.identities()}
    return None if newest.mac_recipient in known else newest.mac_recipient


# --- the archive record (cabinet_auth.backup_ledger) ------------------------------


def record_archive(db: Session, name: str, kind: str, manifest: dict, size: int) -> None:
    """Note an archive this Cabinet wrote, by its MAC, and prune the record
    (180 days, never below the newest 50). Commits."""
    assert kind in LEDGER_KINDS
    # Names are to the second, so a download and a stored backup made in the
    # same second share one; the newer archive takes the row over. Archives
    # are recognised by their MAC, never their name, so nothing depends on it.
    row = db.execute(select(BackupRecord).where(BackupRecord.name == name)).scalar_one_or_none()
    if row is None:
        row = BackupRecord(name=name)
        db.add(row)
    row.kind = kind
    row.created_at = datetime.fromisoformat(manifest["created_at"])
    row.mac_recipient = manifest["mac_recipient"]
    row.mac_digest = archive_keys.mac_digest(manifest)
    row.size = size
    db.flush()
    keep = select(BackupRecord.id).order_by(BackupRecord.created_at.desc()).limit(LEDGER_KEEP)
    db.execute(
        delete(BackupRecord).where(
            BackupRecord.created_at < utcnow() - timedelta(days=LEDGER_DAYS),
            BackupRecord.id.not_in(keep.scalar_subquery()),
        )
    )
    db.commit()


def _write_encrypted(final: Path, db: Session, include_photos: bool, kind: str) -> dict:
    """Write an encrypted archive to `final` by way of `<final>.partial`, which
    only ever holds ciphertext and is removed on any failure; record it."""
    partial = final.with_name(final.name + ".partial")
    try:
        with encrypt_stream(partial, signing_key().recipient) as out:
            manifest = write_archive(out, db, include_photos)
        partial.replace(final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    record_archive(db, final.name, kind, manifest, final.stat().st_size)
    return manifest


def verify_stored(path: Path) -> dict:
    """Decrypt a stored archive in staging and verify it end to end; the
    decrypted copy is removed whatever happens."""
    try:
        return verify_archive(decrypt_to_staging(path, ".verify"))
    finally:
        (staging_dir() / ".verify.zip").unlink(missing_ok=True)


def write_download(db: Session, include_photos: bool) -> tuple[Path, str]:
    """Build an encrypted archive for a one-off download. The temp file sits
    in the backup directory (sized for archives, unlike the container's own
    layer) and only ever holds ciphertext; the caller deletes it once sent."""
    dest = backup_dir()
    name = archive_name(utcnow(), include_photos)
    fd, tmp = tempfile.mkstemp(dir=dest, prefix=".download-", suffix=ENCRYPTED)
    os.close(fd)
    path = Path(tmp)
    path.unlink()  # age writes it; mkstemp only reserved a unique name
    try:
        with encrypt_stream(path, signing_key().recipient) as out:
            manifest = write_archive(out, db, include_photos)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    record_archive(db, name, "download", manifest, path.stat().st_size)
    return path, name


def stored_backups(dest: Path) -> list[Path]:
    """Archives in the backup directory, newest first."""
    return sorted(
        (p for p in dest.iterdir() if p.is_file() and NAME_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )


def prune(dest: Path, keep: int) -> list[str]:
    """Delete archives beyond the newest `keep`, and leftovers from
    interrupted runs. Only files matching Cabinet's own names are touched.
    Full and data-only archives are counted separately, so a run of quick
    data-only backups can never push out the last archives that hold the
    photos and documents. Pre-restore safety archives don't count toward
    `keep`; they have their own limit."""
    removed = []
    stored = stored_backups(dest)
    regular = [p for p in stored if not is_prerestore(p)]
    full = [p for p in regular if not is_data_only(p)]
    data_only = [p for p in regular if is_data_only(p)]
    safety = [p for p in stored if is_prerestore(p)]
    keep = max(keep, 1)
    for old in full[keep:] + data_only[keep:] + safety[PRERESTORE_KEEP:]:
        old.unlink()
        removed.append(old.name)
    cutoff = (utcnow() - STALE_TEMP_AGE).timestamp()
    for leftover in dest.glob("cabinet-backup-*.partial"):
        leftover.unlink(missing_ok=True)  # only ever written under _run_lock
    for leftover in dest.glob(".download-*.zip*"):
        if leftover.stat().st_mtime < cutoff:
            leftover.unlink(missing_ok=True)
    return removed


def write_prerestore(db: Session, include_photos: bool, protect: Path | None = None) -> Path:
    """The safety archive a restore takes first. The caller holds `_run_lock`.
    Nothing is recorded in settings: that database is about to be replaced.
    `protect` is the archive being restored, never pruned here."""
    dest = backup_dir()
    final = dest / f"cabinet-backup-{utcnow():%Y%m%d-%H%M%S}-prerestore{ENCRYPTED}"
    try:
        _write_encrypted(final, db, include_photos, "prerestore")
        verify_stored(final)  # decrypted only in staging, and removed again
    except OSError as exc:
        final.unlink(missing_ok=True)
        raise BackupError(str(exc)) from exc
    except BaseException:
        final.unlink(missing_ok=True)
        raise
    for old in [p for p in stored_backups(dest) if is_prerestore(p)][PRERESTORE_KEEP:]:
        if old != protect:
            old.unlink(missing_ok=True)
    return final


def run_backup(db: Session, include_photos: bool | None = None, kind: str = "manual") -> dict:
    """Write an encrypted archive into the backup directory, prune to the
    retention count, and record the outcome in settings (`backup_last_run`)."""
    if not _run_lock.acquire(blocking=False):
        raise BackupBusy("A backup is already running.")
    started = utcnow()
    if include_photos is None:
        include_photos = bool(store.get_setting(db, "backup_include_photos"))
    try:
        try:
            dest = backup_dir()
            final = dest / archive_name(started, include_photos)
            _write_encrypted(final, db, include_photos, kind)
            pruned = prune(dest, int(store.get_setting(db, "backup_keep")))
        except (BackupError, OSError) as exc:
            db.rollback()
            _record(db, {"at": started.isoformat(), "ok": False, "error": str(exc)})
            alerts.fail(db, "backup", f"Backup failed: {exc}")
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
        alerts.recover(db, "backup")
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
    return run_backup(db, kind="scheduled")
