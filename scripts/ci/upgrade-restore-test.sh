#!/usr/bin/env bash
# Proves two things an owner does to a real instance, against a published
# release rather than a rewritten fixture:
#
#   1. Upgrade: a claimed instance on an older release, holding a piece with
#      a tag, a catalog reference, a photo, and a document, plus an API
#      token, is switched to the images built from this commit. The password
#      and the token still work, both migration chains reach head, and the
#      piece, its photo, and its document are as they were.
#   2. Restore: the archive that older release wrote is then restored inside
#      the upgraded app (Settings -> Backups does the same calls). The piece
#      deleted since comes back with its files, a piece added since is gone,
#      the restored database is migrated to head, a share link made since
#      still opens, and the password and the token still work.
#
# Usage: scripts/ci/upgrade-restore-test.sh [FROM_TAG]
#
# FROM_TAG is the published release to start from, as its image tag
# (default `latest`, which is always the newest stable release: on a
# release's own pull request that is the previous one). It has to be 0.30.0
# or later: sign-in and encrypted archives start there, and
# scripts/ci/upgrade-test.sh covers the step from v0.29.1.
#
# Always talks to a throwaway compose project, never the default one, and
# pulls FROM_TAG fresh, since a local build may hold the `latest` tag. The
# build under test gets a tag of its own (BUILD_TAG) for the same reason.
# docker compose reads the database settings from a .env beside
# docker-compose.yaml, so one must exist (CI writes a throwaway one); the
# script never reads or writes it.
#
# Leaves the stack running when it finishes or fails; tear it down with
#   docker compose -p "$COMPOSE_PROJECT_NAME" down -v
#
# Environment:
#   COMPOSE_PROJECT_NAME  Throwaway project (default cabinet-upgrade-restore)
#   CABINET_PORT          Port the proxy publishes (default 8083)
#   BUILD_TAG             Tag for the images built here (default under-test)
#   SETUP_CODE            32+ hex characters, used to claim the old release
#   CABINET_USER / CABINET_PASSWORD   The admin created on the old release

set -euo pipefail
cd "$(dirname "$0")/../.."

FROM_TAG="${1:-${FROM_TAG:-latest}}"
BUILD_TAG="${BUILD_TAG:-under-test}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cabinet-upgrade-restore}"
export CABINET_PORT="${CABINET_PORT:-8083}"
export PUBLIC_ORIGINS="http://localhost:${CABINET_PORT}"
export ALLOWED_HOSTS="localhost"
export AUTH_INSECURE_HTTP=true
export SETUP_CODE="${SETUP_CODE:-5f8a2c9e1b7d4063a9e2f5c8b1d7e4a0}"
# The CI stack job exports COMPOSE_FILE for its own stack; this one is the
# repository's docker-compose.yaml alone.
unset COMPOSE_FILE

BASE="http://localhost:${CABINET_PORT}"
CABINET_USER="${CABINET_USER:-owner}"
CABINET_PASSWORD="${CABINET_PASSWORD:-correct horse battery}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cabinet-upgrade-restore.XXXXXX")"
COOKIES="$WORK/jar"
trap 'if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf -- "$WORK"; fi' EXIT

if python3 -c '' >/dev/null 2>&1; then PY=python3; else PY=python; fi
field() { "$PY" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
compose() { docker compose -p "$COMPOSE_PROJECT_NAME" "$@"; }

admin() { curl -sS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"; }
adminf() { curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"; }
# A route that wants a recent password: confirm, then call.
fresh() {
  adminf -X POST "$BASE/api/auth/confirm" -H 'Content-Type: application/json' \
    -d "{\"password\":\"$CABINET_PASSWORD\"}" -o /dev/null
  adminf "$@"
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# The same for the admin's session: an API call by cookie needs the Origin.
admin_status() { status_of -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"; }
fail() { echo "upgrade-restore: $*" >&2; exit 1; }

wait_for_health() {
  for i in $(seq 1 90); do
    if curl -fsS "$BASE/api/health" 2>/dev/null | grep -q '"status":"ok"'; then
      echo "healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "backend never became healthy"
  compose logs --tail 80 backend
  exit 1
}
running_version() {
  compose exec -T backend python -c \
    'from importlib.metadata import version; print(version("cabinet-backend"))'
}
sign_in() {
  local status
  status=$(curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" -c "$COOKIES" \
    -H "Origin: $BASE" -H 'Content-Type: application/json' \
    -X POST "$BASE/api/auth/login" \
    -d "{\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}")
  [ "$status" = 200 ] || fail "sign-in answered $status"
}
schemas_at_head() {
  adminf "$BASE/api/health" | "$PY" -c '
import json, sys
body = json.load(sys.stdin)
for key in ("schema", "auth_schema"):
    assert body[key]["status"] == "ok", f"{key} is not at head: {body[key]}"
print("version", body["version"], "schema", body["schema"]["current"],
      "auth_schema", body["auth_schema"]["current"])
'
}
# piece_is_whole <id>: the piece, its tag, its reference in the one stored
# form, its photo through nginx, and its document byte for byte.
piece_is_whole() {
  adminf "$BASE/api/items/$1" | "$PY" -c '
import json, sys
item = json.load(sys.stdin)
assert item["denomination"] == "1 kept", item["denomination"]
assert item["tags"] == ["upgrade"], item["tags"]
refs = [(r["catalog"], r["ref_code"]) for r in item["catalog_refs"]]
assert refs == [("numista", "N#1234")], refs
assert len(item["photos"]) == 1, item["photos"]
'
  [ "$(status_of -b "$COOKIES" "$BASE/photos/$thumb_key")" = 200 ] \
    || fail "the photo's thumbnail is not served"
  adminf "$BASE/api/documents/$document_id/file" -o "$WORK/document.back"
  cmp -s "$WORK/file.png" "$WORK/document.back" || fail "the document's bytes changed"
}
token_works() {
  [ "$(status_of -H "Authorization: Bearer $TOKEN" "$BASE/api/items")" = 200 ] \
    || fail "the API token made on $from_version no longer works"
}

echo "== project $COMPOSE_PROJECT_NAME, port $CABINET_PORT, from tag $FROM_TAG =="

# --- the older release -------------------------------------------------------
echo "== starting the published $FROM_TAG images =="
TAG="$FROM_TAG" compose pull --quiet backend proxy
TAG="$FROM_TAG" compose up -d --no-build
wait_for_health
from_version="$(running_version)"
echo "running $from_version"

echo "== claiming it, and entering a piece with everything attached =="
[ "$(curl -fsS "$BASE/api/auth/state" | field setup_required)" = True ] \
  || fail "$FROM_TAG did not ask for setup"
adminf -X POST "$BASE/api/auth/setup" -H 'Content-Type: application/json' \
  -d "{\"code\":\"$SETUP_CODE\",\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}" \
  -o /dev/null
kept=$(adminf -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
  -d '{"type":"coin","country":"Upgrade test","denomination":"1 kept","year":1921,
       "tags":["upgrade"],"catalog_refs":[{"catalog":"numista","ref_code":"1234"}]}' | field id)
# One small PNG, used as the photo and as the document. Made by the backend's
# own Pillow, and sent on stdin (a Windows curl can't read a Git Bash path).
compose exec -T backend python -c 'import io, sys; from PIL import Image; b = io.BytesIO(); Image.new("RGB", (120, 90), "gray").save(b, "PNG"); sys.stdout.buffer.write(b.getvalue())' > "$WORK/file.png"
thumb_key=$(adminf -X POST "$BASE/api/items/$kept/photos" \
  -F "file=@-;filename=photo.png;type=image/png" < "$WORK/file.png" | field thumb_key)
document_id=$(adminf -X POST "$BASE/api/items/$kept/documents" \
  -F "file=@-;filename=receipt.png;type=image/png" < "$WORK/file.png" | field id)
TOKEN=$(fresh -X POST "$BASE/api/auth/tokens" -H 'Content-Type: application/json' \
  -d '{"name":"upgrade-restore","scope":"read","days":1}' | field token)
token_works

echo "== a full backup, written by $from_version =="
archive=$(adminf -X POST "$BASE/api/backups" | field file)
echo "archive $archive"

# --- the build under test ----------------------------------------------------
echo "== switching to the images built from this commit =="
TAG="$BUILD_TAG" compose up --build -d
wait_for_health
echo "running $(running_version)"

echo "== after the upgrade =="
sign_in
schemas_at_head
piece_is_whole "$kept"
token_works
adminf "$BASE/api/backups" | grep -q "\"$archive\"" \
  || fail "the archive $from_version wrote is not listed"
echo "password, token, piece, photo, and document all survived"

echo "== changing things, so the restore has something to undo =="
marker=$(adminf -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
  -d '{"type":"coin","country":"Upgrade test","denomination":"1 marker","year":2026}' | field id)
# Deleting for good takes the photo and the document's files with it.
fresh -X DELETE "$BASE/api/items/$kept?permanent=true" -o /dev/null
[ "$(admin_status "$BASE/api/items/$kept")" = 404 ] || fail "the piece was not deleted"
# A share link made after the archive: a restore keeps the live links, also
# over an archive from before there were any.
fresh -X PUT "$BASE/api/settings" -H 'Content-Type: application/json' \
  -d '{"share_enabled": true}' -o /dev/null
share_token=$(fresh -X POST "$BASE/api/share-links" -H 'Content-Type: application/json' \
  -d '{"kind":"collection","name":"upgrade-restore"}' | field url | sed 's#.*/s/##')
[ "$(status_of "$BASE/api/share/$share_token")" = 200 ] || fail "the share link does not open"

echo "== restoring the $from_version archive inside the app =="
inspected=$(fresh -X POST "$BASE/api/restore/inspect?name=$archive")
restore_id=$(printf '%s' "$inspected" | field restore_id)
phrase=$(printf '%s' "$inspected" | field confirm_phrase)
fresh -X POST "$BASE/api/restore/$restore_id/run" -H 'Content-Type: application/json' \
  -d "{\"confirm\":\"$phrase\"}" -o /dev/null
# Only the session that started the restore may read its status meanwhile.
state=running
for _ in $(seq 1 150); do # five minutes
  state=$(admin "$BASE/api/restore/status" | field state)
  [ "$state" = running ] || break
  sleep 2
done
admin "$BASE/api/restore/status"; echo
[ "$state" = done ] || fail "the restore ended as $state"

echo "== after the restore =="
wait_for_health
sign_in
schemas_at_head
piece_is_whole "$kept"
[ "$(admin_status "$BASE/api/items/$marker")" = 404 ] \
  || fail "a piece added after the archive outlived the restore"
token_works
[ "$(status_of "$BASE/api/share/$share_token")" = 200 ] \
  || fail "the share link made before the restore no longer opens"
adminf "$BASE/api/backups" | grep -q -- '-prerestore.zip.age' \
  || fail "no safety backup was written before the restore"

echo "upgrade and restore test passed: $from_version -> this commit, and its archive restored"
