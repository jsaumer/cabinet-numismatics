"""Maintenance commands, run inside the backend container: shell access to
the machine running Cabinet is the proof of ownership.

    docker compose exec backend python -m app.cli <command>

Commands (v0.30.0):

    status                    the account, its sessions and tokens, the backup key
    reset-password            set a new password (asked twice, never an argument)
    sign-out-everywhere       end every session and known device (a lost laptop)
    revoke-tokens [--name N]  revoke every API token, or the one named N
    backup-key new            print a fresh backup key, for a secret or BACKUP_KEY
    backup-key show           print the backup key, to keep outside Cabinet
    backup-key rotate         put a new backup key first (older archives stay readable)
    decrypt-archive           decrypt an archive from stdin to stdout (restore.sh)
    verify-archive PATH|-     check a decrypted archive was made with this key
    write-archive --name N    write an encrypted archive to stdout (backup.sh)

Started as root (as `docker compose exec` does), a command first drops to
the app's own user (PUID:PGID), so any file it writes keeps its owner.
Nothing here prints a secret except `backup-key show`, which exists to.
The account and backup-key commands refuse until Cabinet is set up, and
each change is audited as `cli`; the archive commands serve the scripts,
which work before setup too.
"""

import argparse
import getpass
import os
import sys
import tempfile
from contextlib import contextmanager
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


class Refused(Exception):
    pass


@contextmanager
def _database():
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _admin(db):
    """The account, or Refused when Cabinet can't be reached or isn't set up."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.auth import accounts

    try:
        user = accounts.admin(db)
    except SQLAlchemyError:
        raise Refused("the database can't be reached, so nothing was done") from None
    if user is None:
        raise Refused(accounts.NOT_CLAIMED)
    return user


def _admin_or_refuse() -> None:
    with _database() as db:
        _admin(db)


def _when(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "never"


def _token_line(token: dict) -> str:
    return f"{token['name']} ({token['scope']})"


def status(_args) -> int:
    from app.auth import accounts
    from app.services import app_settings as store
    from app.services import archive_keys

    with _database() as db:
        try:
            _admin(db)
        except Refused as exc:
            return _fail(str(exc))
        found = accounts.status(db)
        saved = store.get_setting(db, "backup_key_saved")
    print(f"Account:       {found['username']} (set up)")
    print(f"Last sign-in:  {_when(found['last_sign_in_at'])}")
    print(f"Failed sign-ins in the past 24 hours: {found['failed_sign_ins_24h']}")
    print(f"Sessions ({len(found['sessions'])}):")
    for row in found["sessions"]:
        where = row["address"] or "unknown address"
        print(f"  #{row['id']} last used {_when(row['last_seen_at'])} from {where}")
        if row["user_agent"]:
            print(f"      {row['user_agent']}")
    print(f"API tokens ({len(found['tokens'])}):")
    for row in found["tokens"]:
        expires = _when(row["expires_at"]) if row["expires_at"] else "never"
        print(f"  {_token_line(row)}, last used {_when(row['last_used_at'])}, expires {expires}")
    try:
        primary = archive_keys.primary()
    except archive_keys.KeyUnavailable as exc:
        print(f"Backup key:    unavailable ({exc})")
        return 0
    where = archive_keys.location()
    message = archive_keys.LOCATION_MESSAGES.get(where)
    print(f"Backup key:    {primary.recipient}")
    print(f"  saved outside Cabinet: {'yes' if saved == primary.recipient else 'not confirmed'}")
    print(f"  stored: {where}" + (f" ({message})" if message else ""))
    return 0


def _ask_new_password() -> str:
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Again: ")
    if first != second:
        raise Refused("the two passwords differ, so nothing was changed")
    return first


def reset_password(_args) -> int:
    from app.auth import accounts
    from app.auth.audit import Actor

    with _database() as db:
        try:
            user = _admin(db)
            password = _ask_new_password()
            revoked = accounts.reset_password(db, password, Actor.cli(user))
        except (Refused, accounts.PasswordRejected) as exc:
            return _fail(str(exc))
        name = user.username
    listed = ", ".join(map(_token_line, revoked)) or "none"
    print(f"The password of {name} was reset.")
    print("Every session and known device was ended; sign in again in the browser.")
    print(f"API tokens revoked ({len(revoked)}): {listed}")
    print("Sign-in delays in the running backend were cleared.")
    return 0


def sign_out_everywhere(_args) -> int:
    from app.auth import accounts
    from app.auth.audit import Actor

    with _database() as db:
        try:
            user = _admin(db)
        except Refused as exc:
            return _fail(str(exc))
        ended = accounts.sign_out_everywhere(db, user, Actor.cli(user))
    print(f"Ended {ended['sessions']} session(s) and forgot {ended['devices']} known device(s).")
    print("API tokens are unchanged: revoke-tokens ends those.")
    return 0


def revoke_tokens(args) -> int:
    from app.auth import accounts
    from app.auth.audit import Actor

    with _database() as db:
        try:
            user = _admin(db)
        except Refused as exc:
            return _fail(str(exc))
        ended = accounts.revoke_tokens(db, Actor.cli(user), name=args.name)
    if args.name is not None and not ended:
        return _fail(f"no live token is named {args.name!r}")
    print(f"Revoked ({len(ended)}): " + (", ".join(map(_token_line, ended)) or "none"))
    return 0


def _audit_key_event(action: str) -> None:
    from app.auth import audit

    with _database() as db:
        user = _admin(db)
        audit.record(db, action, audit.Actor.cli(user))
        db.commit()


def backup_key_show(_args) -> int:
    from app.services import archive_keys

    try:
        identities = archive_keys.identities()
    except archive_keys.KeyUnavailable as exc:
        return _fail(str(exc))
    try:
        _audit_key_event("backup_key_shown")
    except Refused as exc:
        return _fail(str(exc))
    print("# Cabinet backup key. Keep it in a password manager, outside Cabinet:")
    print("# without it the encrypted archives can't be opened by anyone.")
    if archive_keys.source() == "file":
        print(f"# From BACKUP_KEY_FILE ({archive_keys.key_path()}).")
    elif archive_keys.source() == "environment":
        print("# From BACKUP_KEY (the environment).")
    for identity in identities:
        print(f"# public key: {identity.recipient}")
        print(identity.text)
    return 0


ROTATE_STEPS = """The backup key is supplied (BACKUP_KEY_FILE or BACKUP_KEY), and Cabinet
never changes a supplied key. To rotate it:
  1. Make a new key:  python -m app.cli backup-key new
  2. Put the NEW identity first and the old one after it: a new secret file
     for BACKUP_KEY_FILE, or both identities in BACKUP_KEY separated by a
     comma, so archives made with the old key stay readable.
  3. Redeploy, then save the new key outside Cabinet.
Nothing was changed."""


def backup_key_new(_args) -> int:
    """A fresh backup key, printed and nothing else: save the whole output as
    the secret file for BACKUP_KEY_FILE, or put the AGE-SECRET-KEY line in
    BACKUP_KEY. Needs no database and works before setup."""
    from datetime import datetime, timezone

    from app.services import archive_keys

    identity = archive_keys.new_identity()
    print(f"# created: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"# public key: {identity.recipient}")
    print(identity.text)
    return 0


def backup_key_rotate(_args) -> int:
    from app.services import archive_keys

    try:
        _admin_or_refuse()
    except Refused as exc:
        return _fail(str(exc))
    fresh = archive_keys.rotate()
    if fresh is None:
        print(ROTATE_STEPS)
        return 0
    _audit_key_event("backup_key_rotated")
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

    if not backup.NAME_RE.match(args.name):
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

    commands.add_parser("status", help="the account, sessions, tokens, backup key").set_defaults(
        run=status
    )
    commands.add_parser("reset-password", help="asked twice, never an argument").set_defaults(
        run=reset_password
    )
    commands.add_parser(
        "sign-out-everywhere", help="end every session and known device"
    ).set_defaults(run=sign_out_everywhere)
    revoke = commands.add_parser("revoke-tokens", help="every API token, or one by name")
    revoke.add_argument("--name", help="only the live token with this name")
    revoke.set_defaults(run=revoke_tokens)

    key = commands.add_parser("backup-key", help="show or rotate the backup key")
    key_commands = key.add_subparsers(dest="action", required=True)
    key_commands.add_parser("new", help="print a fresh key; changes nothing").set_defaults(
        run=backup_key_new
    )
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
