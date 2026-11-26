#!/usr/bin/env bash
# Back up Cabinet (database, photos, and documents) into one encrypted archive,
# the same kind Settings → Backups writes: cabinet-backup-<UTC stamp>.zip.age,
# encrypted with the backup key. Only ciphertext ever reaches this host.
# Usage: ./scripts/backup.sh [backup-root]     (default: ./backups)
#        ./scripts/backup.sh --data-only [backup-root]   (no photos or documents)
# Requires the compose stack to be running. On Windows, run from Git Bash.
# Opening an archive needs the backup key: keep a copy outside Cabinet
# (docker compose exec backend python -m app.cli backup-key show).
set -euo pipefail
cd "$(dirname "$0")/.."

FLAGS=()
if [ "${1:-}" = "--data-only" ]; then
  FLAGS+=(--data-only)
  shift
fi
DEST="${1:-backups}"
mkdir -p "$DEST"
# The suffix is set on its own: inside the name's command substitution, a
# test that fails (a full backup) made the assignment fail, and set -e then
# ended the script without a word. Full backups wrote nothing from v0.30.0
# to v0.37.4.
SUFFIX=""
if [ ${#FLAGS[@]} -gt 0 ]; then
  SUFFIX="-data"
fi
NAME="cabinet-backup-$(date -u +%Y%m%d-%H%M%S)$SUFFIX.zip.age"
PARTIAL="$DEST/$NAME.partial"
trap 'rm -f "$PARTIAL"' EXIT

# The backend dumps the collection (never the cabinet_auth sign-in schema),
# packs the files, and encrypts the lot; the archive is recorded like any other.
docker compose exec -T backend python -m app.cli write-archive --name "$NAME" "${FLAGS[@]}" \
  > "$PARTIAL"
mv "$PARTIAL" "$DEST/$NAME"

echo "Backup written to $DEST/$NAME"
ls -lh "$DEST/$NAME"
