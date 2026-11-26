#!/usr/bin/env bash
# Restore a Cabinet backup: an encrypted archive (cabinet-backup-....zip.age)
# from Settings → Backups or scripts/backup.sh.
# DESTRUCTIVE: replaces the current database contents, all photo files, and
# all attached documents. A data-only archive (no photos.tar.gz) restores the
# database and leaves the files as they are.
# Usage: ./scripts/restore.sh <archive.zip.age>
#   e.g. ./scripts/restore.sh backups/cabinet-backup-20260914-031500.zip.age
#
# The archive is decrypted with the backup key into a private temporary folder
# (removed on exit, including after an interrupt), never beside the archive,
# and its MAC is checked before anything is touched. The key is the running
# backend's, or a key file on this host: AGE_IDENTITY=key.txt (needs `age`).
# Unencrypted archives from before v0.30.0 can't be restored by any path.
#
# The database step is the backend's own (python -m app.cli restore-database),
# so an archive from an older release is migrated to this build's schema, and
# the script ends by restarting the backend and the proxy. The stack has to
# be running.
#
# Unlike the in-app restore, this script puts back the archive's share links
# and sharing switch, not the live ones (v0.32.0; see docs/backup-restore.md),
# so it ends by saying to check Settings, Sharing. The archive's photos may
# carry metadata (EXIF, GPS) from before v0.32.0; the script has the backend
# remove it once they are back.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: restore.sh <archive.zip.age>}"
# .env is docker compose's to read, never this shell's: the script needs
# nothing from it now that the backend restores the database, and a value
# with a space or a Windows line ending in it used to stop the script here.

if [ ! -f "$SRC" ]; then
  echo "$SRC is not a file. Directory backups from before v0.30.0 can't be restored." >&2
  exit 1
fi
if [ "$(head -c 21 "$SRC")" != "age-encryption.org/v1" ]; then
  echo "$SRC is not an encrypted Cabinet archive. Unencrypted archives from before" \
    "v0.30.0 can't be restored: take a new backup instead." >&2
  exit 1
fi

TMP=$(mktemp -d)
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 130' INT TERM
PLAIN="$TMP/archive.zip"
( umask 077; : > "$PLAIN" )

# Container paths live inside sh -c strings so Git Bash (MSYS) on Windows
# doesn't rewrite them into host paths.
if [ -n "${AGE_IDENTITY:-}" ]; then
  age --decrypt --identity "$AGE_IDENTITY" "$SRC" > "$PLAIN"
else
  docker compose exec -T backend python -m app.cli decrypt-archive < "$SRC" > "$PLAIN" \
    || { echo "$SRC can't be opened with the backend's backup key: nothing restored" >&2; exit 1; }
fi
# The MAC: made with this deployment's backup key, nothing altered.
docker compose exec -T backend python -m app.cli verify-archive - < "$PLAIN" \
  || { echo "$SRC was not verified: nothing restored" >&2; exit 1; }

# verify-archive refuses a zip holding anything but the members the MAC covers,
# each once. unzip reads names its own way, so check what it sees too: a
# doubled name must never let it restore bytes other than those verified.
if [ -n "$(unzip -Z1 "$PLAIN" | sort | uniq -d)" ]; then
  echo "$SRC holds a member twice: nothing restored" >&2
  exit 1
fi
DIR="$TMP/archive"
mkdir "$DIR"
unzip -o -q "$PLAIN" -d "$DIR"
(cd "$DIR" && sha256sum -c --quiet SHA256SUMS) \
  || { echo "Checksum mismatch in $SRC: nothing restored" >&2; exit 1; }
echo "Archive verified"
[ -f "$DIR/db.dump" ] || { echo "No db.dump in $SRC" >&2; exit 1; }

# The backend replaces the database, the same way the in-app restore does:
# tables the archive predates are dropped first, the dump goes in as one
# transaction (pg_restore --schema=public, so sign-in data in cabinet_auth is
# never touched, and a dump that holds any is refused before anything
# changes), and the migrations then bring it to this build's schema. Without
# that last step an archive from an older release left a database the
# running backend could not read.
docker compose exec -T backend python -m app.cli restore-database < "$DIR/db.dump" \
  || { echo "The database step failed; the message above says what state it is in." \
       "Photos and documents were not touched." >&2; exit 1; }

if [ -f "$DIR/photos.tar.gz" ]; then
  # Without the photo marker, the share view cleans each photo as it serves
  # it, so the archive's photos are never sent as they are, even before the
  # pass below has rewritten them.
  docker compose exec -T backend python -c 'from app.services import photos; photos.remove_marker()'
  docker compose exec -T backend sh -c 'find /data/photos -mindepth 1 -delete'
  docker compose exec -T backend sh -c 'tar xzf - -C /data/photos' < "$DIR/photos.tar.gz"
  # exec runs as root, but the backend doesn't: give the files to whoever owns the volume
  docker compose exec -T backend sh -c 'chown -R "$(stat -c %u:%g /data/photos)" /data/photos'
  # Re-encode every photo, thumbnails included, without its metadata (as the
  # backend's user); it writes the marker again when every one is done.
  echo "Removing metadata from the restored photos"
  docker compose exec -T backend python -m app.cli strip-photo-metadata \
    || echo "Some photos kept their metadata; run this again:" \
      "docker compose exec backend python -m app.cli strip-photo-metadata" >&2
else
  echo "Data-only archive: photos left unchanged"
fi

if [ -f "$DIR/documents.tar.gz" ]; then
  docker compose exec -T backend sh -c 'mkdir -p /data/documents && find /data/documents -mindepth 1 -delete'
  docker compose exec -T backend sh -c 'tar xzf - -C /data/documents' < "$DIR/documents.tar.gz"
  # exec runs as root, but the backend doesn't: give the files to whoever owns the volume
  docker compose exec -T backend sh -c 'chown -R "$(stat -c %u:%g /data/documents)" /data/documents'
else
  echo "No documents.tar.gz: documents left unchanged"
fi

# The running backend still holds what it knew about the old database (the
# sharing switch, cached figures, open connections), so start it afresh and
# wait for it; the proxy follows, since it looks the backend's address up
# only when it starts.
echo "Restarting the backend"
docker compose restart backend > /dev/null
ready=""
for _ in $(seq 1 60); do
  if docker compose exec -T backend python -c \
    'import sys, urllib.request; sys.exit(0 if urllib.request.urlopen("http://localhost:8000/api/health", timeout=3).status == 200 else 1)' \
    > /dev/null 2>&1; then
    ready=yes
    break
  fi
  sleep 2
done
docker compose restart proxy > /dev/null
if [ -z "$ready" ]; then
  echo "The backend did not answer within two minutes of restarting:" \
    "check 'docker compose logs backend'." >&2
  exit 1
fi

echo "Restored from $SRC"
echo "The archive's share links and sharing switch are now live, not the ones this" \
  "Cabinet had before: check Settings, Sharing."
