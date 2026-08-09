# Backup & Restore

A Cabinet backup is **two artifacts captured together**: the postgres database
(catalog data, estimate history) and the photo volume (originals +
thumbnails). Restoring one without the other leaves items pointing at missing
files, so the scripts always handle both.

## Backing up

With the compose stack running:

```bash
./scripts/backup.sh            # writes ./backups/<timestamp>/
./scripts/backup.sh /mnt/nas   # or write to another root, e.g. a NAS mount
```

Each backup directory contains:

- `db.dump` — `pg_dump` custom-format dump of the whole database.
- `photos.tar.gz` — the entire photo volume.

On Windows run the scripts from Git Bash. `backups/` is gitignored; copy
backups somewhere off the machine (NAS, cloud) — a backup on the same disk as
the data protects against mistakes, not disk failure.

## Restoring

```bash
./scripts/restore.sh backups/<timestamp>
```

**Destructive**: this replaces the current database contents (`pg_restore
--clean`) and all photo files with the backup's state. The stack must be
running. After a restore, the app reflects the backup immediately — no
restart needed.

Restoring into a *fresh* deployment works the same way: bring the stack up,
run `docker compose exec backend alembic upgrade head` once so the database
exists, then restore.

## Notes

- Single-user means no write-concurrency concerns: any moment is a consistent
  moment to back up, as long as you aren't mid-upload.
- The dump format is version-tolerant; moving to a newer postgres image is
  supported (dump on old, restore on new).
- Restore is rehearsed as part of Phase 2 verification — an untested backup
  is a hope, not a backup. Re-rehearse after schema changes that touch photos
  or estimates.
