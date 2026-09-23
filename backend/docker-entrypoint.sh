#!/bin/sh
# Run the backend as an unprivileged user.
#
# The container starts as root only long enough to make sure that user can
# write the data directories (volumes created by earlier releases, and bind
# mounts, are owned by root), then drops to it for good with setpriv. PUID and
# PGID pick the user (default 1000:1000), so files on a bind mount or a NAS
# belong to whoever you expect.
#
# If the directories can't be handed over (an NFS export with root squash, a
# read-only parent), the backend stays root and says so rather than failing
# to start: a working app beats a purer one. Started with `user:` already
# set, the script does nothing.
set -e

if [ "$(id -u)" = "0" ]; then
  uid="${PUID:-1000}"
  gid="${PGID:-1000}"
  key_file="${SECRET_KEY_FILE:-/data/state/secret.key}"
  writable=1
  staging="${STAGING_DIR:-/data/staging}"
  # Secret files (the backup key, the setup code) are the operator's and are
  # never changed: if one sits inside a folder handed over below, its owner
  # and mode are put back afterwards.
  secret_modes=""
  for secret in "${BACKUP_KEY_FILE:-}" "${SETUP_CODE_FILE:-}"; do
    if [ -n "$secret" ] && [ -f "$secret" ]; then
      secret_modes="$secret_modes$(stat -c '%u:%g %a' "$secret") $secret
"
    fi
  done
  for dir in "${PHOTO_DIR:-/data/photos}" "${key_file%/*}" \
             "${BACKUP_DIR:-/data/backups}" "${DOCUMENT_DIR:-/data/documents}" "$staging" \
             /run/cabinet; do
    mkdir -p "$dir" 2>/dev/null || true
    # Only when the owner differs: a one-time hand-over, not a walk of the
    # whole photo volume on every start.
    if [ "$(stat -c %u "$dir" 2>/dev/null)" != "$uid" ]; then
      chown -R "$uid:$gid" "$dir" 2>/dev/null || true
    fi
    # A folder whose top level was already yours can still hold entries made
    # as root by releases before v0.23.1. One level is cheap to list, and a
    # restore can't move a folder it doesn't own.
    find "$dir" -mindepth 1 -maxdepth 1 ! -user "$uid" \
      -exec chown -R "$uid:$gid" {} + 2>/dev/null || true
    if ! setpriv --reuid="$uid" --regid="$gid" --clear-groups test -w "$dir"; then
      echo "WARNING:  $dir is not writable by $uid:$gid" >&2
      writable=0
    fi
  done
  # An archive's database is unpacked here in plain form: the app's user only.
  chmod 700 "$staging" 2>/dev/null || true
  printf '%s' "$secret_modes" | while read -r owner mode secret; do
    [ -n "$secret" ] || continue
    chown "$owner" "$secret" 2>/dev/null || true
    chmod "$mode" "$secret" 2>/dev/null || true
  done
  if [ "$writable" = "1" ]; then
    exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
  fi
  echo "WARNING:  staying root. Fix the ownership above (or set PUID/PGID) to run unprivileged" >&2
fi

exec "$@"
