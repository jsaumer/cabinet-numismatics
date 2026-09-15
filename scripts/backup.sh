#!/usr/bin/env bash
# Back up the Cabinet database and photos together, into one timestamped dir.
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
docker compose exec -T db pg_dump -U "${DB_USER:?set in .env}" -Fc "${DB_NAME:?set in .env}" \
  > "$DIR/db.dump"
docker compose exec -T backend sh -c 'tar czf - -C /data/photos .' > "$DIR/photos.tar.gz"

echo "Backup written to $DIR"
ls -lh "$DIR"
