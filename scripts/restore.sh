#!/usr/bin/env bash
# Restore a Cabinet backup: a directory written by backup.sh, or a .zip archive
# from Settings → Backups (downloaded or scheduled).
# DESTRUCTIVE: replaces the current database contents, all photo files, and
# all attached documents. A data-only archive (no photos.tar.gz) restores the
# database and leaves the files as they are; an archive from before v0.19.0
# (no documents.tar.gz) leaves the documents as they are.
# Usage: ./scripts/restore.sh <backup-dir | archive.zip>
#   e.g. ./scripts/restore.sh backups/20260809-120000
#        ./scripts/restore.sh cabinet-backup-20260914-031500.zip
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: restore.sh <backup-dir | archive.zip>}"
set -a; [ -f .env ] && . ./.env; set +a

if [ -f "$SRC" ] && [[ "$SRC" == *.zip ]]; then
  DIR=$(mktemp -d)
  trap 'rm -rf "$DIR"' EXIT
  unzip -q "$SRC" -d "$DIR"
  [ -f "$DIR/SHA256SUMS" ] || { echo "$SRC is not a Cabinet backup archive" >&2; exit 1; }
  (cd "$DIR" && sha256sum -c --quiet SHA256SUMS) \
    || { echo "Checksum mismatch in $SRC: nothing restored" >&2; exit 1; }
  echo "Archive checksums OK"
else
  DIR="$SRC"
  [ -f "$DIR/photos.tar.gz" ] || { echo "No photos.tar.gz in $DIR" >&2; exit 1; }
fi
[ -f "$DIR/db.dump" ] || { echo "No db.dump in $SRC" >&2; exit 1; }

# Container paths live inside sh -c strings so Git Bash (MSYS) on Windows
# doesn't rewrite them into host paths.
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
