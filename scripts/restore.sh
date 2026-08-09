#!/usr/bin/env bash
# Restore a Cabinet backup created by backup.sh.
# DESTRUCTIVE: replaces the current database contents and all photo files.
# Usage: ./scripts/restore.sh <backup-dir>      e.g. ./scripts/restore.sh backups/20260809-120000
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="${1:?usage: restore.sh <backup-dir>}"
[ -f "$DIR/db.dump" ] || { echo "No db.dump in $DIR" >&2; exit 1; }
[ -f "$DIR/photos.tar.gz" ] || { echo "No photos.tar.gz in $DIR" >&2; exit 1; }
set -a; [ -f .env ] && . ./.env; set +a

# Container paths live inside sh -c strings so Git Bash (MSYS) on Windows
# doesn't rewrite them into host paths.
docker compose exec -T db pg_restore -U "${DB_USER:?set in .env}" -d "${DB_NAME:?set in .env}" \
  --clean --if-exists < "$DIR/db.dump"
docker compose exec -T backend sh -c 'find /data/photos -mindepth 1 -delete'
docker compose exec -T backend sh -c 'tar xzf - -C /data/photos' < "$DIR/photos.tar.gz"

echo "Restored from $DIR"
