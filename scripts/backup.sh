#!/usr/bin/env bash
# Back up the Cabinet database, photos, and documents together, into one
# timestamped dir.
# Usage: ./scripts/backup.sh [backup-root]     (default: ./backups)
# Requires the compose stack to be running. On Windows, run from Git Bash.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a

STAMP=$(date +%Y%m%d-%H%M%S)
DIR="${1:-backups}/$STAMP"
mkdir -p "$DIR"

# Container paths live inside sh -c strings so Git Bash (MSYS) on Windows
# doesn't rewrite them into host paths.
# Sign-in data (the cabinet_auth schema, v0.30.0) is never backed up.
docker compose exec -T db pg_dump -U "${DB_USER:?set in .env}" -Fc \
  --exclude-schema=cabinet_auth "${DB_NAME:?set in .env}" > "$DIR/db.dump"
docker compose exec -T backend sh -c 'tar czf - -C /data/photos .' > "$DIR/photos.tar.gz"
# Attached documents (v0.19.0+); an older backend has no /data/documents.
if docker compose exec -T backend sh -c '[ -d /data/documents ]'; then
  docker compose exec -T backend sh -c 'tar czf - -C /data/documents .' > "$DIR/documents.tar.gz"
fi

echo "Backup written to $DIR"
ls -lh "$DIR"
