# Backup & Restore

A Cabinet backup is **three things captured together**: the postgres database
(catalog data, estimate history, settings, the trash), the photo volume
(originals + thumbnails), and the document volume (attached receipts,
certificates, invoices). Restoring the database without the files leaves
items pointing at missing files, so every path here handles all three.

**Every backup Cabinet makes is encrypted** (v0.30.0) with the backup key,
because an archive is the whole collection: every item, value, storage
location, photo, and receipt. Without the key an archive can't be read, and
nobody without it can forge or alter one that restores. **Keep a copy of the
key outside Cabinet**; see [The backup key](#the-backup-key).

There are two ways to make one:

- **From the app**: Settings → Backups. Download an archive, or schedule
  archives into a backup directory. The everyday path; no shell needed.
- **From the host**: `scripts/backup.sh`. Needs Docker on the host; stays the
  disaster-recovery path.

And two ways to restore one:

- **From the app**: Settings → Backups → Restore, for an in-app archive
  (stored or uploaded). See
  [Restore from inside the app](#restore-from-inside-the-app).
- **From the host**: `scripts/restore.sh`, the disaster-recovery path.

Both take only encrypted archives made with this deployment's key.
Unencrypted `.zip` archives from before v0.30.0 can't be restored by any
path; see [Old unencrypted archives](#old-unencrypted-archives).

## In-app backups

### Download

**Download backup** (`GET /api/backup.zip`) builds a fresh encrypted archive
(`cabinet-backup-….zip.age`) and downloads it. The download starts once the archive is built, so allow a
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
- After each successful run, archives older than **Keep archives for** are
  deleted (v0.30.1). The choices follow the schedule (v0.30.2): 7, 14, 30, or
  90 days, 1 year, or forever for **Daily** (or no schedule); 4, 8, 13, or 26
  weeks, 52 weeks, or forever for **Weekly**. Changing the schedule snaps a
  now-invalid choice to the nearest one in the new set. The newest full
  archive and the newest data-only archive are never deleted by retention,
  whatever their age, so a schedule that stopped can't leave nothing.
  **Forever** shows a warning: the directory then grows without limit. Only
  files named `cabinet-backup-*.zip.age` are ever touched.
- **Back up now** writes one immediately and counts toward the same
  retention. **Include photos** applies to scheduled and on-demand archives,
  and covers the documents too.
- Stored archives are listed with download links, a **Restore…** button,
  and **Delete** (v0.30.1), which asks for your password again and is
  refused while a backup or restore is running.
- The safety backups an in-app restore takes (`-prerestore`, below) are
  listed with a "before restore" badge. They sit outside the retention;
  the newest three are kept.

The backup directory must not be inside the photo directory (nginx serves
that publicly), and the backend refuses to write there.

### What an archive contains

Named `cabinet-backup-YYYYMMDD-HHMMSS.zip.age` (UTC), with a `-data` suffix
when photos are left out, or `-prerestore` for the safety backup taken
before an in-app restore. It is a standard [age](https://age-encryption.org)
file (X25519) around a zip: the zip is streamed straight into `age`, which
writes the only file (`….zip.age.partial` while it's being written, renamed
when complete, removed on any failure), so no unencrypted archive, member,
or temporary file ever touches the backup directory. Inside, once decrypted:

| Member | Contents |
|--------|----------|
| `db.dump` | `pg_dump` custom-format dump of the collection: every schema but `cabinet_auth` (v0.30.0), so no password, session, token, or audit row is ever in an archive |
| `photos.tar.gz` | the entire photo volume (absent from data-only archives) |
| `documents.tar.gz` | the entire document volume (v0.19.0+; absent from data-only archives) |
| `manifest.json` | format version, app version, schema revision, server and `pg_dump` versions, created-at, whether photos and documents are included, counts (items, of which in the trash, photos, documents, estimates), `auth_excluded: true` (informational: the dump's own table of contents is what a restore checks), size + SHA-256 of each member, and `mac_recipient` + `mac` (below) |
| `SHA256SUMS` | the same checksums in `sha256sum -c` format |

**Tamper evidence.** age authenticates what it encrypts, but anyone who
knows the public key could encrypt a new archive to it. So the manifest
carries `mac_recipient` (the public key of the backup key that made the
archive) and `mac`: HMAC-SHA256, keyed by HKDF-SHA256 over that key's raw
32-byte X25519 secret (empty salt, info `cabinet-backup-mac-v1`), over the
manifest itself (JSON with sorted keys and no spaces, UTF-8, without `mac`,
so `mac_recipient` is covered) followed by `SHA256SUMS`. The manifest lists
every member's checksum and size, so the MAC covers every byte, and only
someone holding the private key can make one that verifies.

To open an archive by hand, without Cabinet:

```bash
age -d -i key.txt cabinet-backup-20260914-031500.zip.age > backup.zip
unzip backup.zip -d check && (cd check && sha256sum -c SHA256SUMS)
```

(`key.txt` is the key from `backup-key show`, below.) That checks the
contents; to check the MAC too, use the container's `verify-archive`
command, which is what `restore.sh` does.

The backend image carries PostgreSQL 14–18 clients and dumps with the one
matching the server's major version, so an archive restores with that
server's own `pg_restore`. (A newer `pg_dump` writes settings an older server
rejects on restore.) Against a server newer than 18 the in-app backup
refuses and points at `backup.sh`, which uses the db container's own
`pg_dump`.

## The backup key

One [age](https://age-encryption.org) identity (`AGE-SECRET-KEY-1…`)
encrypts every archive and keys its MAC.

- **Where it comes from.** One of three places. `BACKUP_KEY_FILE`, a file of
  identities (a Docker secret on a Swarm), is the recommended form: Cabinet
  never modifies it, and one it can't read or parse stops the backend at
  startup, before any backup is written. `BACKUP_KEY`, the identity text
  itself as a variable (identities separated by commas or newlines, the
  first encrypting), is for a secret manager that delivers variables: it
  is written at every start to a private file inside the container, never
  to a data volume, and it is visible to anything that can inspect the
  service, so guard it as you would the database password. Setting both
  stops startup. Otherwise Cabinet generates one on its first start, into
  `backup.key` on the state volume (mode 0600), and logs its public key.
- **Making one.** One command, for either form, needing no database and
  working before setup:

  ```bash
  docker compose run --rm backend python -m app.cli backup-key new
  ```

  (or `docker run --rm ghcr.io/jsaumer/cabinet-numismatics-backend:0.30.0
  python -m app.cli backup-key new` where the stack isn't running). It
  prints a key in `age-keygen`'s format: save the whole output as the
  secret file, or put the `AGE-SECRET-KEY-1...` line in `BACKUP_KEY`. Keep
  a copy in your password manager either way. Settings → Backups
  shows the public key (the fingerprint) and, until you tick **I have saved
  it**, a "Save your backup key" reminder; ticking records only the public
  key, so a new key asks again.
- **Saving it.** The key is never sent over the API. Print it inside the
  container (shell access to the machine is the proof of ownership) and put
  it in your password manager:

  ```bash
  docker compose exec backend python -m app.cli backup-key show
  ```

  On a Swarm, on the node running the backend task:
  `docker exec $(docker ps -q -f name=cabinet_backend) python -m app.cli backup-key show`.
  Both `backup-key` commands work once Cabinet is set up (they refuse
  before), and each use is written to the audit log.
- **Losing it.** If the key and the machine are both lost, the archives can't
  be opened by anyone, you included. There is no recovery, by design.
- **Rotating it.** `python -m app.cli backup-key rotate` puts a new identity
  first in a generated `backup.key` and keeps the old ones after it: new
  archives use the new key, and each older archive is checked with the
  identity its `mac_recipient` names, so it stays readable while that
  identity stays in the file. Save the new key afterwards. With a supplied
  key (`BACKUP_KEY_FILE` or `BACKUP_KEY`) the command changes nothing and
  prints the steps: make a new key with `backup-key new`, put it first and
  the old one after it (a new secret file, or both in `BACKUP_KEY` separated
  by a comma), and redeploy.
- **Where it lives.** A generated key is only as private as the state
  volume. When it shares storage with the backups, the key sits beside the
  archives it protects. On every start Cabinet reads the container's mounts
  and says one of three things, in the log, in Settings, and in the setup
  checklist: nothing (**separate**, said only when both sit on known local
  disk filesystems on different devices), "Your backup key is stored beside
  your backups; move it to a secret" (**shared**), or "Cabinet cannot tell
  where your backup key is stored relative to your backups" (**not
  verified**: two folders on one filesystem, whose parent may be shared; a
  network or FUSE filesystem, whose server may export them together; or
  anything Cabinet doesn't recognise). A default Compose install, with both
  volumes on the host's one disk, reads **not verified**: true, since
  Cabinet can't see how that disk is shared. A supplied key needs no check. The same check covers the
  generated `SECRET_KEY` file. For any deployment whose backups leave the
  host, supply the key as a secret.

## Old unencrypted archives

Archives from before v0.30.0 are plain `.zip` files: readable copies of the
whole collection by anyone who can read the backup directory. They **can't be
restored by any path** from v0.30.0 on, and from v0.30.1 Cabinet ignores
them altogether (not listed, not deleted, not counted by retention). Delete
any `cabinet-backup-*.zip` you still have from the backup directory by
hand, and copies made by the old `backup.sh` (directories of `db.dump` and
tar files) with them.

## Backing up from the host

With the compose stack running:

```bash
./scripts/backup.sh               # writes ./backups/cabinet-backup-<UTC stamp>.zip.age
./scripts/backup.sh /mnt/nas      # or another folder, e.g. a NAS mount
./scripts/backup.sh --data-only   # without photos and documents
```

The script asks the backend to write the archive (`python -m app.cli
write-archive`), so it is the same encrypted kind as the app's, recorded like
any other, and only ciphertext reaches the host.

On Windows run the scripts from Git Bash. `backups/` is gitignored; copy
backups somewhere off the machine (NAS, cloud): a backup on the same disk as
the data protects against mistakes, not disk failure.

## Restore from inside the app

Settings → Backups → **Restore** replaces the whole collection with a
Cabinet archive: the database, and the photos and documents when the archive
carries them. A data-only archive restores the database and leaves the files
as they are. It takes encrypted archives made with this deployment's backup
key (download, **Back up now**, scheduled, `backup.sh`, or an earlier safety
backup).

**Destructive**, so it is admin-only and asks for the password again (see
[security.md](security.md)), and a deployment can switch it off.

### The procedure

1. Click **Restore…** on a stored archive, or **Restore from a file** to
   upload one. An upload is written straight into
   `BACKUP_DIR/.restore-staging/`, never through the container's temp
   folder, and may be up to `RESTORE_MAX_GB` (default 20).
2. Cabinet verifies the archive and changes nothing. It is decrypted into
   the private staging folder (below), never the backup directory, after a
   free-space check; a plain `.zip` is refused ("This is an unencrypted
   archive from before v0.30.0…"), an upload on its first bytes, before
   any of it is stored, and one that another key made, or that was altered,
   can't be opened. Then its MAC is checked before anything in it is read
   ("This archive was not made with your backup key."); the zip must hold
   exactly the members the MAC covers, each once; every member must match
   its checksum, the
   schema revision must be one this build knows, and the photo and document
   archives may hold only plain files and folders (links, devices, absolute
   paths, and `..` are refused). An archive from a **newer** Cabinet is
   refused: upgrade first. An **older** one is fine: it is migrated after
   the restore. An upload that fails the check is deleted at once.
3. A summary shows the archive beside what is here now: items, photos,
   documents, trashed items, schema revision, app version, and the archive's
   date, with notes when it will be migrated or carries no files. It also
   says where the archive came from: "Made by this Cabinet on 18 September
   2026", with "3 newer backups exist" when there are; "Not made by this
   Cabinet" (another machine sharing the key, or a record that has lost
   it); or, with no record at all, that Cabinet can't tell whether it is the
   newest.
4. Type `RESTORE` and click **Restore this archive**. **An archive older than
   the newest backup this Cabinet recorded needs `RESTORE OLDER` instead**, so
   nobody can quietly roll the collection back. "Older" compares the
   archive's own verified creation time with the newest in the record of
   archives (`cabinet_auth.backup_ledger`, which no restore rewrites), and
   an archive is recognised by its verified MAC, never its file name or file
   time: renaming an old archive, giving it a new file time, or pruning its
   record doesn't make it newest. The run checks again from the archive
   itself, restoring an older one sends an alert, and after a failed run
   (which still took a safety backup, now the newest) a retry asks again. **Cancel** discards a
   staged upload; it never deletes a stored archive.
5. The page follows the run and reloads its data when it ends.

### Sign-in data is never restored

An archive carries no credential and a restore never adds, changes, or
revokes one (v0.30.0). Cabinet's dumps leave out the `cabinet_auth` schema,
where the admin, sessions, API tokens, the audit log, and the record of
archives live (see [data-model.md](data-model.md)); `pg_restore` runs with
`--schema=public`, and after a restore only the collection's migrations run.
Checking an archive (the summary, and again just before the database step)
reads the dump's table of contents with `pg_restore --list`, and **an archive
whose dump holds anything in `cabinet_auth` is refused** (`422`, "This
archive contains sign-in data, which Cabinet never restores. It was not made
by Cabinet's own backup."). `restore.sh` makes the same check before it
changes anything. So your sign-in, sessions, API tokens, and audit log are
kept through any restore, which the summary says, and an archive from
before v0.30.0 (which has no `cabinet_auth` at all) restores as before.

The summary also names, by name only, the stored secrets the archive would
set (price-source keys, the alert webhook, the heartbeat URL), and any it
holds that this deployment would clear because they aren't encrypted with
its key.

### The private staging folder

To be checked and restored, an archive is decrypted, and its database dump
unpacked, into `/data/staging`, a volume of its own (`staging_data`), owned
by the app's user with mode 0700 and each file 0600, never inside the
backup, photo, or document directories. It is emptied at the start and end
of every check and every restore, whatever the outcome, and on every start.
There must be room there for the archive and its dump (the check says "Not
enough space to open this archive" otherwise). What lands there is the collection in plain form, as in the
database itself, so keep the volume on the host's own disk, not on the
share your backups go to. Uploaded archives still wait in the backup
directory (`.restore-staging`), as uploads only.

### What a run does, in order

1. **Safety backup.** The app goes into maintenance (below), the archive is
   decrypted and verified again from the file itself, and the current state
   is written to the backup directory as
   `cabinet-backup-YYYYMMDD-HHMMSS-prerestore.zip.age`, with photos and
   documents whenever the incoming archive replaces them, and verified by
   decrypting it in staging. If
   it fails, the restore doesn't start.
2. **Photos, documents.** The archive's files are unpacked into a hidden
   `.restore-new` folder inside each volume, after a free-space check.
   Nothing live is touched.
3. **Database.** The dump is unpacked into the private staging folder and
   its table of contents checked again. A marker row with a fresh random
   value is written to `app_settings` (`restore_marker`) and the same value
   to the journal (below). Then `pg_restore --schema=public --clean
   --if-exists --no-owner --single-transaction`, with the client matching
   the server and a 120-second lock timeout: it either commits whole or
   leaves the database as it was. One change is made just before it,
   outside that transaction: tables that exist in `public` here but not in
   the dump (added by a migration newer than the archive) are dropped,
   because they would block the restore and collide with the migration
   later; the journal names them first. `cabinet_auth` is never dropped.
   Afterwards any marker row the archive brought is deleted, and every
   stored secret this deployment can't use (plain text, or encrypted with
   another key) is cleared and named in the outcome ("Cleared: alert
   webhook").
4. **Migrations**, when the archive's revision is older than this build's:
   the collection chain only.
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
  (`restore_journal.json`) tells the next start where it was. Before the
  database step, the unpacked files are cleared ("Nothing was changed").
  During it, the marker row answers whether the database was replaced
  (v0.30.0): **this restore's value still there** means `pg_restore`'s
  transaction never committed, so nothing changed (or, if tables newer than
  the archive had already been dropped, the outcome names them and the
  safety backup); **no marker row, or one with any other value** (an archive
  can carry a row, never this restore's value) means the archive's database
  is in place, so its unusable secrets are cleared, the file swap is rolled
  forward, and startup migrates; **the database can't be reached** within a
  minute means the journal is kept and the backend stays in maintenance
  (health answers `restoring`) until a restart can decide, rather than serve
  an old database with new files. After the database step, a swap cut short
  is finished. If putting files back ever failed, a non-empty `.restore-old` is
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
[deployment.md](deployment.md#3-tls-and-an-authenticating-proxy-in-front).

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
- The MAC catches tampering as well as corruption, but only with your own
  key: an archive from a machine with another backup key can't be restored
  here. To move a collection between machines, give the new one your saved
  key (`BACKUP_KEY_FILE`).
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

The disaster-recovery path: it needs the host, Docker, and the running `db`
and `backend` containers, but not a working web app.

```bash
./scripts/restore.sh cabinet-backup-20260914-031500.zip.age
AGE_IDENTITY=key.txt ./scripts/restore.sh cabinet-backup-20260914-031500.zip.age
```

The script decrypts the archive into a private temporary folder (0700,
removed on exit, also after an interrupt), never beside the archive: with
the running backend's key (`python -m app.cli decrypt-archive`), or with a
key file on this host (`AGE_IDENTITY`, which needs `age` installed). It then
checks the MAC with the backend (`python -m app.cli verify-archive`, which
also refuses a zip holding any member the MAC doesn't cover, or one twice)
and the checksums before touching anything, and refuses a plain `.zip` or a
`backup.sh` directory from before v0.30.0. It is the break-glass path, so it
has no `RESTORE OLDER` step: it restores whichever genuine archive you give
it, and prints the date the archive was made.

**Destructive**: this replaces the current database contents (`pg_restore
--schema=public --clean`), all photo files, and all documents with the
backup's state. Sign-in data is kept: the script refuses, before changing
anything, a dump whose table of contents holds anything in `cabinet_auth`,
and restores only the collection's schema. The
stack must be running, and restoring an archive needs `unzip` and
`sha256sum` on the host. After a restore, the app reflects the backup
immediately, with no restart needed. The backend runs unprivileged while
`docker compose exec` enters as root, so the script gives the extracted
files to whoever owns the volume. Unlike the in-app restore, the script
takes no safety backup and doesn't pause the app: take a backup first if
the current state matters, and don't use the app while it runs.

A data-only archive restores the database and
leaves the photos and documents as they are; an archive from before v0.19.0,
which has no `documents.tar.gz`, leaves the documents as they are.

Restoring into a *fresh* deployment works the same way: bring the stack up
with your saved backup key (`BACKUP_KEY_FILE`), wait until `/api/health`
reports `schema.status: "ok"` (the backend creates the schema on startup),
then restore. `restore.sh` needs no sign-in, since it never touches
`cabinet_auth`, so it can run before or after the machine is claimed. The
in-app path needs an admin session, so claim the fresh instance with a
setup code first, then restore from Settings → Backups. Either order leaves
the new machine's own admin in place: an archive never carries sign-in data,
so restoring one never changes who is claimed. Without the backup key the
archives can't be opened.

### On a Swarm

`restore.sh` drives `docker compose`, so on a Swarm run its steps by hand
(the database step on the node running the `db` task, the photo and document
steps on the node running the `backend` task):

```bash
backend=$(docker ps -q -f name=cabinet_backend)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT     # private, removed afterwards
docker exec -i "$backend" python -m app.cli decrypt-archive \
  < cabinet-backup-20260914-031500.zip.age > "$tmp/backup.zip"
docker exec -i "$backend" python -m app.cli verify-archive - < "$tmp/backup.zip"
unzip -q "$tmp/backup.zip" -d "$tmp/restore"
cd "$tmp" && (cd restore && sha256sum -c SHA256SUMS)
db=$(docker ps -q -f name=cabinet_db)
# must print nothing: a dump holding sign-in data is not Cabinet's own
docker exec -i "$db" pg_restore --list < restore/db.dump | grep -v '^;' | grep -w cabinet_auth
docker exec -i "$db" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema=public --clean --if-exists' < restore/db.dump
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

The dump holds no sign-in data at all (see above). It does contain
price-source API credentials, and the alert webhook and heartbeat URLs,
**encrypted at rest** (see [security.md](security.md)); the encryption key
is *not* in the backup:
it lives in `.env` (`SECRET_KEY`) or on the private `backend_state` volume.
Restoring onto a host without the matching key works fine, from the app or
with the script; the affected sources and alerts show as not configured,
the in-app restore clears them and names them, and you re-enter them in
Settings. A secret found in plain text is never used, from any path: it is
cleared at startup, hourly, and after an in-app restore.

Back up `.env` separately and treat it as sensitive: it holds both the
database password and the encryption key.

## Notes

- Single-user means no write-concurrency concerns: any moment is a consistent
  moment to back up, as long as you aren't mid-upload.
- The dump format is version-tolerant; moving to a newer postgres image is
  supported (dump on old, restore on new).
- Restore is rehearsed: CI attaches a PDF to an item, downloads an in-app
  archive (checking it is an age file and that its dump holds no sign-in
  data), shows that a copy with one flipped byte is refused, deletes the
  item for good, restores the archive with `restore.sh`, and checks the
  item is back and the PDF matches byte for byte, on every push. It then rehearses the in-app route: back up, add a
  marker item, restore that backup through `/api/restore` (a wrong phrase is
  refused first), and check the marker is gone, the earlier items are
  still there, a `-prerestore` archive is listed, and health is back to
  `ok`. A Playwright test does the same from Settings. An untested backup is
  a hope, not a backup.
