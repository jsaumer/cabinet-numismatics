# Backup & Restore

A Cabinet backup is **two things captured together**: the postgres database
(catalog data, estimate history, settings) and the photo volume (originals +
thumbnails). Restoring one without the other leaves items pointing at missing
files, so every path here handles both.

There are two ways to make one:

- **From the app** — Settings → Backups. Download an archive, or schedule
  archives into a backup directory. The everyday path; no shell needed.
- **From the host** — `scripts/backup.sh`. Needs Docker on the host; stays the
  disaster-recovery path.

`scripts/restore.sh` restores either kind.

## In-app backups

### Download

**Download backup** (`GET /api/backup.zip`) builds a fresh archive and
downloads it. The download starts once the archive is built, so allow a
minute for a large photo collection. **Data only** (`?photos=false`) leaves the
photos and documents out — a small archive for moving a catalog between
machines, not a full backup.

### Scheduled

Pick **Daily** or **Weekly** and how many archives to keep. Archives are
written to the backend's backup directory, `/data/backups` (`BACKUP_DIR`).
Compose mounts the `backup_data` volume there; to get archives off the host,
bind-mount a NAS path instead (see [deployment.md](deployment.md#2-storage)).

- The schedule counts from the last run. The backend checks hourly, so a daily
  backup runs about 24 hours after the previous one, whenever that was.
- A failed run is retried within the hour. The outcome of the last run —
  file and size, or the error — shows in Settings and in the backend log.
- After each successful run, archives beyond **Keep newest** are deleted.
  Only files named `cabinet-backup-*.zip` are ever touched.
- **Back up now** writes one immediately and counts toward the same
  retention. **Include photos** applies to scheduled and on-demand archives.
- Stored archives are listed with download links.

The backup directory must not be inside the photo directory — nginx serves
that publicly — and the backend refuses to write there.

### What an archive contains

Named `cabinet-backup-YYYYMMDD-HHMMSS.zip` (UTC), with a `-data` suffix when
photos are left out:

| Member | Contents |
|--------|----------|
| `db.dump` | `pg_dump` custom-format dump of the whole database |
| `photos.tar.gz` | the entire photo volume (absent from data-only archives) |
| `documents.tar.gz` | the entire document volume (v0.19.0+; absent from data-only archives) |
| `manifest.json` | format version, app version, schema revision, `pg_dump` version, created-at, item/photo/estimate counts, and size + SHA-256 of each member |
| `SHA256SUMS` | the same checksums in `sha256sum -c` format |

`db.dump`, `photos.tar.gz`, and `documents.tar.gz` are the same files `backup.sh` writes. To check
an archive by hand:

```bash
unzip cabinet-backup-20260914-031500.zip -d check
(cd check && sha256sum -c SHA256SUMS)
```

The backend image carries PostgreSQL 14–18 clients and dumps with the one
matching the server's major version, so an archive restores with that
server's own `pg_restore`. (A newer `pg_dump` writes settings an older server
rejects on restore.)

## Backing up from the host

With the compose stack running:

```bash
./scripts/backup.sh            # writes ./backups/<timestamp>/
./scripts/backup.sh /mnt/nas   # or write to another root, e.g. a NAS mount
```

Each backup directory contains `db.dump`, `photos.tar.gz`, and
`documents.tar.gz`, as above.

On Windows run the scripts from Git Bash. `backups/` is gitignored; copy
backups somewhere off the machine (NAS, cloud) — a backup on the same disk as
the data protects against mistakes, not disk failure.

## Restoring

```bash
./scripts/restore.sh backups/<timestamp>                  # a backup.sh directory
./scripts/restore.sh cabinet-backup-20260914-031500.zip   # an in-app archive
```

**Destructive**: this replaces the current database contents (`pg_restore
--clean`), all photo files, and all documents with the backup's state. The stack must be
running. After a restore, the app reflects the backup immediately — no
restart needed.

For an archive, the script verifies the checksums first and restores nothing
if any member doesn't match. A data-only archive restores the database and
leaves the photos and documents as they are; an archive from before v0.19.0,
which has no `documents.tar.gz`, leaves the documents as they are.

Restoring into a *fresh* deployment works the same way: bring the stack up,
wait until `/api/health` reports `schema.status: "ok"` (the backend creates
the schema on startup), then restore.

There is no restore button in the app. Restore is destructive and Cabinet has
no login, so it stays a host-side step (roadmap Phase 5.6, B3).

### On a Swarm

`restore.sh` drives `docker compose`, so on a Swarm run its steps by hand —
the database step on the node running the `db` task, the photo and document
steps on the node running the `backend` task:

```bash
unzip cabinet-backup-20260914-031500.zip -d restore
(cd restore && sha256sum -c SHA256SUMS)
db=$(docker ps -q -f name=cabinet_db)
docker exec -i "$db" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < restore/db.dump
backend=$(docker ps -q -f name=cabinet_backend)
docker exec "$backend" sh -c 'find /data/photos -mindepth 1 -delete'
docker exec -i "$backend" sh -c 'tar xzf - -C /data/photos' < restore/photos.tar.gz
docker exec "$backend" sh -c 'find /data/documents -mindepth 1 -delete'
docker exec -i "$backend" sh -c 'tar xzf - -C /data/documents' < restore/documents.tar.gz
```

These are the same commands the script runs; they are rehearsed under
Compose, not on a multi-node Swarm.

## Secrets in backups

The database dump contains price-source API credentials **encrypted at rest**
(see [security.md](security.md)); the encryption key is *not* in the backup —
it lives in `.env` (`SECRET_KEY`) or on the private `backend_state` volume.
Restoring onto a host without the matching key works fine; the affected
sources simply show as not configured, and you re-enter the keys in Settings.

Back up `.env` separately and treat it as sensitive: it holds both the
database password and the encryption key.

## Notes

- Single-user means no write-concurrency concerns: any moment is a consistent
  moment to back up, as long as you aren't mid-upload.
- The dump format is version-tolerant; moving to a newer postgres image is
  supported (dump on old, restore on new).
- Restore is rehearsed: CI downloads an in-app archive, deletes an item,
  restores the archive with `restore.sh`, and checks the item is back — on
  every push. An untested backup is a hope, not a backup.
