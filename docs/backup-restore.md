# Backup & Restore

A Cabinet backup is **three things captured together**: the postgres database
(catalog data, estimate history, settings, the trash), the photo volume
(originals + thumbnails), and the document volume (attached receipts,
certificates, invoices). Restoring the database without the files leaves
items pointing at missing files, so every path here handles all three.

There are two ways to make one:

- **From the app**: Settings → Backups. Download an archive, or schedule
  archives into a backup directory. The everyday path; no shell needed.
- **From the host**: `scripts/backup.sh`. Needs Docker on the host; stays the
  disaster-recovery path.

And two ways to restore one:

- **From the app**: Settings → Backups → Restore, for an in-app archive
  (stored or uploaded). See
  [Restore from inside the app](#restore-from-inside-the-app).
- **From the host**: `scripts/restore.sh` restores either kind, and is the
  disaster-recovery path for when the app itself won't start.

## In-app backups

### Download

**Download backup** (`GET /api/backup.zip`) builds a fresh archive and
downloads it. The download starts once the archive is built, so allow a
minute for a large photo collection. **Data only** (`?photos=false`) leaves the
photos and documents out: a small archive for moving a catalog between
machines, not a full backup.

### Scheduled

Pick **Daily** or **Weekly** and how many archives to keep. Archives are
written to the backend's backup directory, `/data/backups` (`BACKUP_DIR`).
Compose mounts the `backup_data` volume there; to get archives off the host,
bind-mount a NAS path instead (see [deployment.md](deployment.md#2-storage)).

- The schedule counts from the last run. The backend checks hourly (first a
  few minutes after it starts), so a daily backup runs about 24 hours after
  the previous one, whenever that was.
- A failed run is retried within the hour. The outcome of the last run
  (file and size, or the error) shows in Settings, and a failure raises the
  backup alert if a webhook is set ([monitoring.md](monitoring.md)).
- After each successful run, archives beyond **Keep newest** are deleted.
  Only files named `cabinet-backup-*.zip` are ever touched.
- **Back up now** writes one immediately and counts toward the same
  retention. **Include photos** applies to scheduled and on-demand archives,
  and covers the documents too.
- Stored archives are listed with download links and a **Restore…** button.
- The safety backups an in-app restore takes (`-prerestore`, below) are
  listed with a "before restore" badge. They don't count toward **Keep
  newest** and aren't removed by it; the newest three are kept.

The backup directory must not be inside the photo directory (nginx serves
that publicly), and the backend refuses to write there.

### What an archive contains

Named `cabinet-backup-YYYYMMDD-HHMMSS.zip` (UTC), with a `-data` suffix when
photos are left out, or `-prerestore` for the safety backup taken before an
in-app restore:

| Member | Contents |
|--------|----------|
| `db.dump` | `pg_dump` custom-format dump of the whole database |
| `photos.tar.gz` | the entire photo volume (absent from data-only archives) |
| `documents.tar.gz` | the entire document volume (v0.19.0+; absent from data-only archives) |
| `manifest.json` | format version, app version, schema revision, server and `pg_dump` versions, created-at, whether photos and documents are included, counts (items, of which in the trash, photos, documents, estimates), and size + SHA-256 of each member |
| `SHA256SUMS` | the same checksums in `sha256sum -c` format |

`db.dump`, `photos.tar.gz`, and `documents.tar.gz` are the same files
`backup.sh` writes. To check an archive by hand:

```bash
unzip cabinet-backup-20260914-031500.zip -d check
(cd check && sha256sum -c SHA256SUMS)
```

`manifest.json` itself is not listed in `SHA256SUMS` (the format has always
worked that way): the checksums catch a corrupted or truncated archive, not
one that was deliberately rewritten.

The backend image carries PostgreSQL 14–18 clients and dumps with the one
matching the server's major version, so an archive restores with that
server's own `pg_restore`. (A newer `pg_dump` writes settings an older server
rejects on restore.) Against a server newer than 18 the in-app backup
refuses and points at `backup.sh`, which uses the db container's own
`pg_dump`.

## Backing up from the host

With the compose stack running:

```bash
./scripts/backup.sh            # writes ./backups/<timestamp>/
./scripts/backup.sh /mnt/nas   # or write to another root, e.g. a NAS mount
```

Each backup directory contains `db.dump`, `photos.tar.gz`, and
`documents.tar.gz`, as above (no manifest or checksums). The script reads
`DB_USER` and `DB_NAME` from `.env`.

On Windows run the scripts from Git Bash. `backups/` is gitignored; copy
backups somewhere off the machine (NAS, cloud): a backup on the same disk as
the data protects against mistakes, not disk failure.

## Restore from inside the app

Settings → Backups → **Restore** replaces the whole collection with a
Cabinet archive: the database, and the photos and documents when the archive
carries them. A data-only archive restores the database and leaves the files
as they are. It takes archives made by the app (download, **Back up now**,
scheduled, or an earlier safety backup), not `backup.sh` directories.

**Destructive**, and as open as the rest of the app until login ships (see
[security.md](security.md)), so it is fenced, and a deployment can switch it
off.

### The procedure

1. Click **Restore…** on a stored archive, or **Restore from a file** to
   upload one. An upload is written straight into
   `BACKUP_DIR/.restore-staging/`, never through the container's temp
   folder, and may be up to `RESTORE_MAX_GB` (default 20).
2. Cabinet verifies the archive and changes nothing: it must be a zip with a
   `cabinet-backup` manifest, every member must match its checksum, the
   schema revision must be one this build knows, and the photo and document
   archives may hold only plain files and folders (links, devices, absolute
   paths, and `..` are refused). An archive from a **newer** Cabinet is
   refused: upgrade first. An **older** one is fine: it is migrated after
   the restore. An upload that fails the check is deleted at once.
3. A summary shows the archive beside what is here now: items, photos,
   documents, trashed items, schema revision, app version, and the archive's
   date, with notes when it will be migrated or carries no files.
4. Type `RESTORE` and click **Restore this archive**. **Cancel** discards a
   staged upload; it never deletes a stored archive.
5. The page follows the run and reloads its data when it ends.

### What a run does, in order

1. **Safety backup.** The app goes into maintenance (below), the archive is
   verified again, and the current state is written to the backup directory
   as `cabinet-backup-YYYYMMDD-HHMMSS-prerestore.zip`, with photos and
   documents whenever the incoming archive replaces them, and verified. If
   it fails, the restore doesn't start.
2. **Photos, documents.** The archive's files are unpacked into a hidden
   `.restore-new` folder inside each volume, after a free-space check.
   Nothing live is touched.
3. **Database.** `pg_restore --clean --if-exists --no-owner
   --single-transaction`, with the client matching the server and a
   120-second lock timeout: it either commits whole or leaves the database
   as it was. One change is made just before it, outside that transaction:
   tables that exist here but not in the dump (added by a migration newer
   than the archive) are dropped, because they would block the restore and
   collide with the migration later.
4. **Migrations**, when the archive's revision is older than this build's.
5. **Finishing.** Only now, with the database committed, are the files
   swapped in, by renames inside each volume: the current entries move to
   `.restore-old`, the unpacked ones move in, and `.restore-old` is deleted
   once everything held.

The outcome (archive, counts, safety backup, or the error) is written to
`restore_last.json` on the state volume beside the key file, not to the
database, which was just replaced. Settings shows it as the last restore. A
staged upload is removed after a successful run and kept after a failed one,
for a retry; uploads left staged are cleared after a day.

### While it runs

- Every API request except `GET /api/health` and `GET /api/restore/status`
  answers `503` ("Cabinet is restoring a backup; try again in a moment").
  Requests already in flight get up to 30 seconds to finish first.
- The scheduled loops (backups, price refreshes, the trash clear-out, the
  heartbeat) skip their turn.
- `/api/health` answers `db: "restoring"` with the schema `unknown`, without
  touching the database, so a container healthcheck doesn't hang behind
  `pg_restore`'s locks and get the backend killed mid-restore.
- A restore is refused (`409`) while another restore, a backup, or a
  scheduled task is running, and no backup starts until it ends.

### When it fails

- **Before or in the database step** (a bad archive, a failed safety backup,
  no room to unpack, `pg_restore` failing): the unpacked files are removed
  and the error ends "Nothing was changed."
- **The one exception**: if `pg_restore` fails after tables newer than the
  archive were dropped, the error names those tables and the safety backup
  to restore. The rest of the database is as it was.
- **The file swap fails**: the previous files are put back, and the error
  says so and names the safety backup, since the database has already been
  replaced.
- **A migration fails** after the restore: the files are still swapped in
  (they belong to the restored database), the run is reported failed, and
  the error says to restart the backend to try the migration again, or
  restore the safety backup.
- **The backend stops mid-run**: a journal on the state volume
  (`restore_journal.json`) lets the next start finish a swap that was cut
  short, or clear the unpacked files if the database hadn't been replaced
  yet. If putting files back ever failed, a non-empty `.restore-old` is
  left in the volume and the next restore refuses until a person has moved
  those files back or removed the folder: it may hold the only copy.

To go back after a restore you regret, restore the `-prerestore` archive.

### Switching it off, and limits

| Variable | Default | |
|----------|---------|---|
| `RESTORE_ENABLED` | `true` | `false`: the restore endpoints answer 404, `GET /api/restore/status` says `enabled: false`, and the Restore block disappears. `restore.sh` is then the only way |
| `RESTORE_MAX_GB` | `20` | Largest archive that may be uploaded. The bundled nginx allows 20 GB under `/api/restore`; raising this means raising that too |

A reverse proxy in front of the stack needs the same allowance for large
bodies and long requests; see
[deployment.md](deployment.md#3-reverse-proxy-tls-and-authentication).

### What to know before relying on it

- After a restore, everything in the database is the archive's, settings
  included: the backup schedule, the "last backup" line, and alert state are
  whatever they were when the archive was made. The safety backup is never
  recorded as the last backup run.
- Saved API keys and webhook addresses work only with the `SECRET_KEY` in
  force when the archive was made; see
  [Secrets in backups](#secrets-in-backups).
- The volumes need room for a second copy of the photos and documents while
  the swap is pending, and the backup directory room for the safety backup
  (and an upload).
- The checksums catch corruption, not tampering: the manifest isn't itself
  signed or summed. Restore archives you made.
- **Every folder under the photo and document volumes must be writable by
  the user the backend runs as**: the swap moves them, and moving a folder
  needs write permission on the folder itself. Folders made before v0.23.1,
  when the backend ran as root, may still belong to root. Restore checks
  this before it changes anything and says which folder is in the way, and
  from v0.26.1 the backend's startup hands such folders over, so a restart
  usually clears it; otherwise `chown -R` the volume to `PUID`:`PGID`.
- **On NFS** the first real restore (v0.26.0) found exactly that: the
  database was restored, the file swap was refused, and the files were put
  back. The swap is renames within one volume, and `.nfs*` placeholder files
  (an NFS client's stand-ins for open files) are skipped.
- **Not tested with an archive made by a genuinely older release.** The
  older-revision path (dropping newer tables, then migrating) was exercised
  with an archive whose manifest was rewritten to an older revision.
- Rehearsed in CI on every push, against real Postgres (see Notes). If it
  goes wrong, or the app won't start, use the script below.

## Restoring from the host

The disaster-recovery path: it needs only the host, Docker, and a running
`db` container, not a working app.

```bash
./scripts/restore.sh backups/<timestamp>                  # a backup.sh directory
./scripts/restore.sh cabinet-backup-20260914-031500.zip   # an in-app archive
```

**Destructive**: this replaces the current database contents (`pg_restore
--clean`), all photo files, and all documents with the backup's state. The
stack must be running, and restoring an archive needs `unzip` and
`sha256sum` on the host. After a restore, the app reflects the backup
immediately, with no restart needed. The backend runs unprivileged while
`docker compose exec` enters as root, so the script gives the extracted
files to whoever owns the volume. Unlike the in-app restore, the script
takes no safety backup and doesn't pause the app: take a backup first if
the current state matters, and don't use the app while it runs.

For an archive, the script verifies the checksums first and restores nothing
if any member doesn't match. A data-only archive restores the database and
leaves the photos and documents as they are; an archive from before v0.19.0,
which has no `documents.tar.gz`, leaves the documents as they are.

Restoring into a *fresh* deployment works the same way: bring the stack up,
wait until `/api/health` reports `schema.status: "ok"` (the backend creates
the schema on startup), then restore, from the app or with the script.

### On a Swarm

`restore.sh` drives `docker compose`, so on a Swarm run its steps by hand
(the database step on the node running the `db` task, the photo and document
steps on the node running the `backend` task):

```bash
unzip cabinet-backup-20260914-031500.zip -d restore
(cd restore && sha256sum -c SHA256SUMS)
db=$(docker ps -q -f name=cabinet_db)
docker exec -i "$db" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < restore/db.dump
backend=$(docker ps -q -f name=cabinet_backend)
docker exec "$backend" sh -c 'find /data/photos -mindepth 1 -delete'
docker exec -i "$backend" sh -c 'tar xzf - -C /data/photos' < restore/photos.tar.gz
docker exec "$backend" sh -c 'chown -R "$(stat -c %u:%g /data/photos)" /data/photos'
docker exec "$backend" sh -c 'find /data/documents -mindepth 1 -delete'
docker exec -i "$backend" sh -c 'tar xzf - -C /data/documents' < restore/documents.tar.gz
docker exec "$backend" sh -c 'chown -R "$(stat -c %u:%g /data/documents)" /data/documents'
```

These are the same commands the script runs; they are rehearsed under
Compose, not on a multi-node Swarm. `docker exec` enters as root, which is
why the `chown` lines hand the files back to the volume's owner (on NFS
with root squash they may fail; fix the ownership on the server instead).
Skip the photo and document steps for a data-only archive.

## Secrets in backups

The database dump contains price-source API credentials, and the alert
webhook and heartbeat URLs, **encrypted at rest** (see
[security.md](security.md)); the encryption key is *not* in the backup:
it lives in `.env` (`SECRET_KEY`) or on the private `backend_state` volume.
Restoring onto a host without the matching key works fine, from the app or
with the script; the affected sources and alerts simply show as not
configured, and you re-enter them in Settings.

Back up `.env` separately and treat it as sensitive: it holds both the
database password and the encryption key.

## Notes

- Single-user means no write-concurrency concerns: any moment is a consistent
  moment to back up, as long as you aren't mid-upload.
- The dump format is version-tolerant; moving to a newer postgres image is
  supported (dump on old, restore on new).
- Restore is rehearsed: CI attaches a PDF to an item, downloads an in-app
  archive, deletes the item for good, restores the archive with
  `restore.sh`, and checks the item is back and the PDF matches byte for
  byte, on every push. It then rehearses the in-app route: back up, add a
  marker item, restore that backup through `/api/restore` (a wrong phrase is
  refused first), and check the marker is gone, the earlier items are
  still there, a `-prerestore` archive is listed, and health is back to
  `ok`. A Playwright test does the same from Settings. An untested backup is
  a hope, not a backup.
