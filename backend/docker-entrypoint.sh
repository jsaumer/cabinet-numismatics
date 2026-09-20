#!/bin/sh
# Run the backend as an unprivileged user.
#
# The container starts as root only long enough to make sure that user can
# write the data directories — volumes created by earlier releases, and bind
# mounts, are owned by root — then drops to it for good with setpriv. PUID and
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
  for dir in "${PHOTO_DIR:-/data/photos}" "${key_file%/*}" \
             "${BACKUP_DIR:-/data/backups}" "${DOCUMENT_DIR:-/data/documents}"; do
    mkdir -p "$dir" 2>/dev/null || true
    # Only when the owner differs: a one-time hand-over, not a walk of the
    # whole photo volume on every start.
    if [ "$(stat -c %u "$dir" 2>/dev/null)" != "$uid" ]; then
      chown -R "$uid:$gid" "$dir" 2>/dev/null || true
    fi
    if ! setpriv --reuid="$uid" --regid="$gid" --clear-groups test -w "$dir"; then
      echo "WARNING:  $dir is not writable by $uid:$gid" >&2
      writable=0
    fi
  done
  if [ "$writable" = "1" ]; then
    exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
  fi
  echo "WARNING:  staying root — fix the ownership above (or set PUID/PGID) to run unprivileged" >&2
fi

exec "$@"
