"""Maintenance commands, run inside the backend container: shell access to
the machine running Cabinet is the proof of ownership.

    docker compose exec backend python -m app.cli <command>

Commands (v0.30.0):

    backup-key show           print the backup key, to keep outside Cabinet
    backup-key rotate         put a new backup key first (older archives stay readable)
    decrypt-archive           decrypt an archive from stdin to stdout (restore.sh)
    verify-archive PATH|-     check a decrypted archive was made with this key
    write-archive --name N    write an encrypted archive to stdout (backup.sh)

Started as root (as `docker compose exec` does), a command first drops to
the app's own user (PUID:PGID), so any file it writes keeps its owner.
Nothing here prints a secret except `backup-key show`, which exists to.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _drop_privileges() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    uid = int(os.environ.get("PUID", "1000"))
    gid = int(os.environ.get("PGID", "1000"))
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def _fail(message: str, code: int = 1) -> int:
    print(f"cabinet: {message}", file=sys.stderr)
    return code


def backup_key_show(_args) -> int:
    from app.services import archive_keys

    try:
        identities = archive_keys.identities()
    except archive_keys.KeyUnavailable as exc:
        return _fail(str(exc))
    print("# Cabinet backup key. Keep it in a password manager, outside Cabinet:")
    print("# without it the encrypted archives can't be opened by anyone.")
    if archive_keys.supplied():
        print(f"# From BACKUP_KEY_FILE ({archive_keys.key_path()}).")
    for identity in identities:
        print(f"# public key: {identity.recipient}")
        print(identity.text)
    return 0


ROTATE_STEPS = """The backup key comes from BACKUP_KEY_FILE, which Cabinet never changes.
To rotate it:
  1. Make a new key:  age-keygen -o new.key   (or: docker compose exec backend age-keygen)
  2. Make a new secret holding the NEW identity first and the old one after it,
     so archives made with the old key stay readable.
  3. Point BACKUP_KEY_FILE at the new secret and redeploy.
Nothing was changed."""


def backup_key_rotate(_args) -> int:
    from app.services import archive_keys

    fresh = archive_keys.rotate()
    if fresh is None:
        print(ROTATE_STEPS)
        return 0
    print(f"New backup key (public key {fresh.recipient}) is now first; new archives use it.")
    print("Older archives stay readable while the old key stays in the file.")
    print("Save the new key outside Cabinet: python -m app.cli backup-key show")
    return 0


def decrypt_archive(_args) -> int:
    from app.services import archive_keys, backup

    try:
        backup.decrypt_stream(sys.stdin.buffer, sys.stdout.buffer, archive_keys.key_path())
    except backup.BackupError as exc:
        return _fail(str(exc))
    sys.stdout.buffer.flush()
    return 0


def verify_archive(args) -> int:
    """Exit 0 only for a decrypted archive whose MAC checks out with this
    deployment's key and whose members match their checksums."""
    from app.services import backup, restore

    spooled = None
    try:
        if args.path == "-":
            # A zip needs a seekable file: spool stdin into private staging,
            # under a name of its own (0600).
            fd, name = tempfile.mkstemp(dir=backup.staging_dir(), prefix=backup.CLI_PREFIX)
            spooled = Path(name)
            with os.fdopen(fd, "wb") as out:
                while chunk := sys.stdin.buffer.read(backup.CHUNK):
                    out.write(chunk)
            path = spooled
        else:
            path = Path(args.path)
        manifest = restore.check_archive(path)
    except (restore.RestoreError, backup.BackupError, OSError) as exc:
        return _fail(f"not verified: {exc}")
    finally:
        if spooled is not None:
            spooled.unlink(missing_ok=True)
    print(f"verified: made with backup key {manifest['mac_recipient']} on {manifest['created_at']}")
    return 0


def write_archive(args) -> int:
    """For backup.sh: an encrypted archive on stdout, recorded as a manual
    backup under the name the script saves it as. Only ciphertext leaves."""
    from app.db import SessionLocal
    from app.services import backup

    if not backup.NAME_RE.match(args.name) or not backup.is_encrypted(Path(args.name)):
        return _fail("--name must be a cabinet-backup-YYYYMMDD-HHMMSS.zip.age name")
    db = SessionLocal()
    # Ciphertext only, even here: written into private staging under a name of
    # its own so its size can be recorded, then copied to stdout and removed.
    fd, name = tempfile.mkstemp(dir=backup.staging_dir(), prefix=backup.CLI_PREFIX)
    os.close(fd)
    temp = Path(name)
    temp.unlink()  # age writes it; mkstemp only reserved the name
    try:
        with backup.encrypt_stream(temp, backup.signing_key().recipient) as out:
            manifest = backup.write_archive(out, db, include_photos=not args.data_only)
        backup.record_archive(db, args.name, "manual", manifest, temp.stat().st_size)
        with temp.open("rb") as src:
            while chunk := src.read(backup.CHUNK):
                sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    except (backup.BackupError, OSError) as exc:
        return _fail(str(exc))
    finally:
        temp.unlink(missing_ok=True)
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    key = commands.add_parser("backup-key", help="show or rotate the backup key")
    key_commands = key.add_subparsers(dest="action", required=True)
    key_commands.add_parser("show").set_defaults(run=backup_key_show)
    key_commands.add_parser("rotate").set_defaults(run=backup_key_rotate)

    commands.add_parser("decrypt-archive", help="stdin to stdout").set_defaults(run=decrypt_archive)
    verify = commands.add_parser("verify-archive", help="check a decrypted archive")
    verify.add_argument("path", help="the decrypted .zip, or - for stdin")
    verify.set_defaults(run=verify_archive)
    write = commands.add_parser("write-archive", help="an encrypted archive to stdout")
    write.add_argument("--name", required=True)
    write.add_argument("--data-only", action="store_true", help="leave photos and documents out")
    write.set_defaults(run=write_archive)

    args = parser.parse_args(argv)
    _drop_privileges()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
