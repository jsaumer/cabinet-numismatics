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
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: restore.sh <archive.zip.age>}"
set -a; [ -f .env ] && . ./.env; set +a

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

# In-app archives are dumped with the client matching the server's major
# version, so the db image's own pg_restore reads them.
# Sign-in data (the cabinet_auth schema, v0.30.0) is never restored. Cabinet's
# own dumps leave it out, so a dump that holds any is refused before anything
# changes, and only the collection's schema is restored either way.
LISTING=$(docker compose exec -T db pg_restore --list < "$DIR/db.dump")
if printf '%s\n' "$LISTING" | grep -v '^;' | grep -qw cabinet_auth; then
  echo "$SRC contains sign-in data, which Cabinet never restores. It was not made" \
    "by Cabinet's own backup: nothing restored" >&2
  exit 1
fi
docker compose exec -T db pg_restore -U "${DB_USER:?set in .env}" -d "${DB_NAME:?set in .env}" \
  --schema=public --clean --if-exists < "$DIR/db.dump"

if [ -f "$DIR/photos.tar.gz" ]; then
  docker compose exec -T backend sh -c 'find /data/photos -mindepth 1 -delete'
  docker compose exec -T backend sh -c 'tar xzf - -C /data/photos' < "$DIR/photos.tar.gz"
  # exec runs as root, but the backend doesn't: give the files to whoever owns the volume
  docker compose exec -T backend sh -c 'chown -R "$(stat -c %u:%g /data/photos)" /data/photos'
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

echo "Restored from $SRC"
