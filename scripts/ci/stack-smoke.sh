#!/usr/bin/env bash
# Drives a running Cabinet compose stack (proxy, backend, db) through sign-in,
# API tokens, the CRUD/backup/restore drills, and the metrics matrix. This is
# the shell that used to live inline in .github/workflows/ci.yml's "stack"
# job; it moved here so it can also run against the local stack before any
# push (docs/specs/SPEC_0300.md section 9, stage 7 of section 10).
#
# Usage: scripts/ci/stack-smoke.sh [bootstrap|smoke|backup-restore|restore-drill|photos|all]
#   (no argument, or "all", runs every phase in order)
#
# Run from the repository root, with the stack already up
# (docker compose up -d) and PUBLIC_ORIGINS/ALLOWED_HOSTS/AUTH_INSECURE_HTTP
# exported to match the running stack's .env.
#
# Environment:
#   BASE               Where the proxy answers (default http://localhost)
#   SETUP_CODE         The setup code, required only to claim an unclaimed stack
#   CABINET_USER       Admin username (default owner)
#   CABINET_PASSWORD   Admin password (default "correct horse battery")
#   STACK_SMOKE_STATE  Where the cookie jar and minted tokens are kept between
#                       phases, so bootstrap/smoke/backup-restore/restore-drill
#                       can run as separate steps (default a temp folder)
#
# Idempotent: bootstrap mints tokens named with the current timestamp and PID,
# so running the whole script twice against the same claimed stack is safe.

set -euo pipefail
cd "$(dirname "$0")/../.."

BASE="${BASE:-http://localhost}"
SETUP_CODE="${SETUP_CODE:-}"
CABINET_USER="${CABINET_USER:-owner}"
CABINET_PASSWORD="${CABINET_PASSWORD:-correct horse battery}"

STATE_DIR="${STACK_SMOKE_STATE:-${TMPDIR:-/tmp}/cabinet-stack-smoke}"
mkdir -p "$STATE_DIR"
COOKIES="$STATE_DIR/cookies.txt"
TOKENS_FILE="$STATE_DIR/tokens.env"
[ -f "$COOKIES" ] || : > "$COOKIES"

# python3 is a non-functional Windows Store stub on some dev machines; pick
# whichever interpreter actually runs. CI (ubuntu) has a real python3.
if python3 -c '' >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

# --- small helpers ---------------------------------------------------------

field() { "$PY" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

# Bearer, write-scoped token. Reads (any GET) and writes go through this;
# it covers everything but the admin-only routes (section 3 of the spec).
api() { curl -sS -H "Authorization: Bearer $WRITE_TOKEN" "$@"; }
apif() { curl -fsS -H "Authorization: Bearer $WRITE_TOKEN" "$@"; }

# The admin session's cookie, with the Origin the CSRF check needs since
# curl sends no Sec-Fetch-Site header (section 4). Persists across phases.
admin() { curl -sS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"; }
adminf() { curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"; }

confirm_now() {
  adminf -X POST "$BASE/api/auth/confirm" -H 'Content-Type: application/json' \
    -d "{\"password\":\"$CABINET_PASSWORD\"}" -o /dev/null
}

# A "fresh" route (section 5's recent-password window): confirm, then call.
# Confirming is cheap, so every fresh call just re-confirms first.
fresh() { confirm_now; adminf "$@"; }
fresh_status() {
  confirm_now
  curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$@"
}

load_tokens() {
  if [ -z "${WRITE_TOKEN:-}" ]; then
    if [ ! -f "$TOKENS_FILE" ]; then
      echo "No bootstrap state in $STATE_DIR; run '$0 bootstrap' first." >&2
      exit 1
    fi
    # shellcheck disable=SC1090
    . "$TOKENS_FILE"
  fi
}

mint_token() {
  local name="$1" scope="$2" days="$3"
  fresh -X POST "$BASE/api/auth/tokens" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$name\",\"scope\":\"$scope\",\"days\":$days}" | field token
}

wait_for_health() {
  for i in $(seq 1 60); do
    if curl -fsS "$BASE/api/health" | grep -q '"status":"ok"'; then
      echo "healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "backend never became healthy"
  command -v docker >/dev/null 2>&1 && docker compose logs
  exit 1
}

# --- phases ------------------------------------------------------------------

bootstrap() {
  echo "== bootstrap =="
  : > "$COOKIES"
  rm -f "$TOKENS_FILE"

  wait_for_health

  local required
  required=$(curl -fsS "$BASE/api/auth/state" | field setup_required)
  if [ "$required" = "True" ]; then
    : "${SETUP_CODE:?SETUP_CODE must be set to claim an unclaimed stack}"
    admin -X POST "$BASE/api/auth/setup" -H 'Content-Type: application/json' \
      -d "{\"code\":\"$SETUP_CODE\",\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}" \
      -o /dev/null -w 'claimed as %{http_code}\n'
  else
    admin -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
      -d "{\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}" \
      -o /dev/null -w 'signed in as %{http_code}\n'
  fi

  local stamp
  stamp="$(date +%s)-$$"
  WRITE_TOKEN=$(mint_token "ci-write-$stamp" write 1)
  READ_TOKEN=$(mint_token "ci-read-$stamp" read 1)
  METRICS_TOKEN=$(mint_token "ci-metrics-$stamp" metrics null)

  {
    echo "WRITE_TOKEN=$WRITE_TOKEN"
    echo "READ_TOKEN=$READ_TOKEN"
    echo "METRICS_TOKEN=$METRICS_TOKEN"
  } > "$TOKENS_FILE"
  chmod 600 "$TOKENS_FILE"

  # Confirms the schema migrated itself on startup; anonymous health gives
  # only {"status":"ok"}, so this needs a signed-in call for the full body.
  apif "$BASE/api/health" | "$PY" -c '
import json, sys
schema = json.load(sys.stdin)["schema"]
print(schema)
assert schema["status"] == "ok", schema
'
  echo "bootstrap done: write/read/metrics tokens minted"
}

smoke() {
  load_tokens
  echo "== smoke =="
  # no interactive docs page; the schema stays. Anonymous gets 401 (the gate
  # refuses an unlisted path before routing even runs); a signed-in caller
  # reaches FastAPI, which has no such route, so 404 proves it's really gone.
  test "$(status_of "$BASE/api/docs")" = 401
  test "$(curl -s -o /dev/null -w '%{http_code}' -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$BASE/api/docs")" = 404
  # GET /api/openapi.json is session-only; a token gets 403
  adminf "$BASE/api/openapi.json" > /dev/null
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $WRITE_TOKEN" "$BASE/api/openapi.json")" = 403
  # nginx answers only its own Host names: anything else gets no
  # response at all (444 closes the connection; curl exits 52)
  set +e
  curl -s -o /dev/null -H 'Host: elsewhere.example' "$BASE/"
  rc=$?
  set -e
  test "$rc" = 52
  # sign-in and setup take at most 8 KiB, refused by nginx itself
  test "$(head -c 9216 /dev/zero | curl -s -o /dev/null -w '%{http_code}' \
    -X POST --data-binary @- "$BASE/api/auth/login")" = 413

  # create -> read -> trash -> restore -> delete for good, end to end
  id=$(apif -X POST "$BASE/api/items" \
    -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"CI","denomination":"1 test","year":2026}' \
    | field id)
  apif "$BASE/api/items/$id" > /dev/null
  apif -X DELETE "$BASE/api/items/$id" -o /dev/null
  apif "$BASE/api/trash" | grep -q "$id"
  apif -X POST "$BASE/api/items/$id/restore" -o /dev/null
  # deleting for good is admin, fresh: a write token can't do it
  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null
  if apif "$BASE/api/items/$id" -o /dev/null; then
    echo "the item survived a permanent delete"
    exit 1
  fi

  adminf "$BASE/api/settings" > /dev/null
  apif "$BASE/api/dashboard/layout" | "$PY" -c '
import json, sys
layout = json.load(sys.stdin)
assert layout["is_default"] is True, layout
assert len(layout["widgets"]) == 11, layout
'
  apif "$BASE/api/stack" | "$PY" -c '
import json, sys
report = json.load(sys.stdin)
assert isinstance(report["metals"], list), report
assert report["history_start"] == "2024-03-02", report
'

  # metrics: anonymous 401, a read token 403, a metrics token 404 while off,
  # then 200 once an admin session turns it on. Explicitly turned off first,
  # since a previous run against the same claimed stack may have left it on.
  fresh -X PUT "$BASE/api/settings" -H 'Content-Type: application/json' \
    -d '{"metrics_enabled": false}' -o /dev/null
  test "$(status_of "$BASE/api/metrics")" = 401
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $READ_TOKEN" "$BASE/api/metrics")" = 403
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $METRICS_TOKEN" "$BASE/api/metrics")" = 404
  fresh -X PUT "$BASE/api/settings" -H 'Content-Type: application/json' \
    -d '{"metrics_enabled": true}' -o /dev/null
  curl -fsS -H "Authorization: Bearer $METRICS_TOKEN" "$BASE/api/metrics" > "$STATE_DIR/metrics.txt"
  grep -q '^cabinet_schema_up_to_date 1.0' "$STATE_DIR/metrics.txt"
  # the gauge agrees with the trash itself (0 on a fresh stack; a local one
  # may hold what earlier runs left there)
  trashed=$(apif "$BASE/api/trash" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["items"]))')
  grep -q "^cabinet_items_in_trash ${trashed}.0" "$STATE_DIR/metrics.txt"

  # no webhook saved: the test alert says so rather than failing
  adminf -X POST "$BASE/api/alerts/test" | grep -q '"ok":false'
  echo "smoke test passed"
}

backup_restore() {
  load_tokens
  echo "== backup-restore =="
  id=$(apif -X POST "$BASE/api/items" \
    -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Backup drill","denomination":"1 test","year":2026}' \
    | field id)
  # attach a PDF (made by Pillow inside the backend image) as a document
  docker compose exec -T backend python -c 'import io, sys; from PIL import Image; b = io.BytesIO(); Image.new("RGB", (200, 280), "white").save(b, "PDF"); sys.stdout.buffer.write(b.getvalue())' > receipt.pdf
  doc=$(apif -X POST "$BASE/api/items/$id/documents" \
    -F kind=receipt -F file=@receipt.pdf \
    | field id)

  # every archive is encrypted with the backup key (age); downloading one is
  # admin, fresh
  fresh -o backup.zip.age "$BASE/api/backup.zip"
  test "$(head -c 21 backup.zip.age)" = "age-encryption.org/v1"
  # decrypt-archive and restore.sh need no token: they run on the host and in
  # the backend container, never through the API
  docker compose exec -T backend python -m app.cli decrypt-archive < backup.zip.age > plain.zip
  unzip -l plain.zip | grep -q documents.tar.gz
  unzip -p plain.zip db.dump | docker compose exec -T db pg_restore --list > toc.txt
  if grep -v '^;' toc.txt | grep -qw cabinet_auth; then
    echo "the dump holds sign-in data"
    exit 1
  fi
  rm plain.zip toc.txt

  # a flipped byte is refused before anything changes
  cp backup.zip.age flipped.zip.age
  printf '\x01' | dd of=flipped.zip.age bs=1 seek=300 conv=notrunc status=none
  if ./scripts/restore.sh flipped.zip.age; then
    echo "an altered archive was restored"
    exit 1
  fi

  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null
  if adminf "$BASE/api/documents/$doc/file" -o /dev/null; then
    echo "the document outlived its only item"
    exit 1
  fi
  ./scripts/restore.sh backup.zip.age
  apif "$BASE/api/items/$id" > /dev/null
  adminf "$BASE/api/documents/$doc/file" -o restored.pdf
  cmp receipt.pdf restored.pdf
  echo "item $id and its document are back after restore"

  adminf -X POST "$BASE/api/backups" | "$PY" -c '
import json, sys
run = json.load(sys.stdin)
print(run)
assert run["ok"]
'
}

restore_drill() {
  load_tokens
  echo "== restore-drill =="
  drill_items() { apif "$BASE/api/items?country=Backup%20drill" | field total; }
  before=$(drill_items)
  test "$before" -ge 1

  keep=$(apif -X POST "$BASE/api/items" \
    -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Restore drill","denomination":"1 kept","year":2026}' \
    | field id)
  name=$(adminf -X POST "$BASE/api/backups" | field file)
  marker=$(apif -X POST "$BASE/api/items" \
    -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Restore drill","denomination":"1 marker","year":2026}' \
    | field id)

  rid=$(fresh -X POST "$BASE/api/restore/inspect?name=$name" | field restore_id)
  # a wrong phrase is refused, and nothing starts
  test "$(fresh_status -X POST "$BASE/api/restore/$rid/run" \
    -H 'Content-Type: application/json' -d '{"confirm":"yes"}')" = 422
  fresh -X POST "$BASE/api/restore/$rid/run" \
    -H 'Content-Type: application/json' -d '{"confirm":"RESTORE"}' -o /dev/null

  # the status poll must use the same cookie jar/session that started the
  # restore: it is the only one holding the grant while maintenance is on
  state=running
  for _ in $(seq 1 150); do # five minutes
    state=$(admin "$BASE/api/restore/status" | field state)
    [ "$state" = running ] || break
    sleep 2
  done
  admin "$BASE/api/restore/status"
  test "$state" = done

  if apif "$BASE/api/items/$marker" -o /dev/null; then
    echo "the marker item outlived the restore"
    exit 1
  fi
  apif "$BASE/api/items/$keep" > /dev/null
  test "$(drill_items)" = "$before"
  adminf "$BASE/api/backups" | grep -q -- '-prerestore.zip.age'
  apif "$BASE/api/health" | grep -q '"db":"ok"'
  echo "in-app restore drill passed"
}

# --- entry point -------------------------------------------------------------

phase="${1:-all}"
photos() {
  load_tokens
  echo "== photos =="
  # nginx asks the backend (auth_request) before serving anything under
  # /photos/: a session or a read or write token, nobody else.
  id=$(apif -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Photo check","denomination":"1 test","year":2026}' | field id)
  docker compose exec -T backend python -c 'import io, sys; from PIL import Image; b = io.BytesIO(); Image.new("RGB", (120, 90), "gray").save(b, "PNG"); sys.stdout.buffer.write(b.getvalue())' > "$STATE_DIR/photo.png"
  # on stdin: a Windows curl can't read a Git Bash /tmp path
  thumb=/photos/$(apif -X POST "$BASE/api/items/$id/photos" \
    -F "file=@-;filename=photo.png;type=image/png" < "$STATE_DIR/photo.png" | field thumb_key)
  missing="${thumb%/*}/00000000-0000-0000-0000-000000000000.jpg"
  expect() { local want=$1; shift; local got; got=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' "$@"); \
    [ "$got" = "$want" ] || { echo "photos: got $got, wanted $want for: $*" >&2; exit 1; }; }
  expect 401 "$BASE$thumb"
  expect 200 -b "$COOKIES" "$BASE$thumb"
  expect 200 -H "Authorization: Bearer $READ_TOKEN" "$BASE$thumb"
  expect 200 -H "Authorization: Bearer $WRITE_TOKEN" "$BASE$thumb"
  expect 403 -H "Authorization: Bearer $METRICS_TOKEN" "$BASE$thumb"
  expect 403 -b "$COOKIES" -H 'Sec-Fetch-Site: cross-site' "$BASE$thumb"
  expect 200 -b "$COOKIES" -H 'Sec-Fetch-Site: none' "$BASE$thumb"
  # the check comes before the file: a missing photo tells a stranger nothing
  expect 401 "$BASE$missing"
  expect 404 -b "$COOKIES" "$BASE$missing"
  # hidden names, dot segments, and encoded paths
  expect 404 "$BASE/photos/.restore-new/x.jpg"
  expect 401 "$BASE/photos/x/..$thumb"
  expect 401 "$BASE/api/..$thumb"
  expect 401 "$BASE${thumb/_thumb/%5fthumb}"
  expect 404 "$BASE/_auth/photo"
  curl -s -D - -o /dev/null -b "$COOKIES" "$BASE$thumb" | grep -qi '^cache-control: private, no-store'
  # the app itself and its logo are not behind the check
  expect 200 "$BASE/"
  expect 200 "$BASE/logo-512.png"
  # the backend stopped: 503 with a retry, not a broken image forever
  docker compose stop backend > /dev/null
  expect 503 -b "$COOKIES" "$BASE$thumb"
  curl -s -D - -o /dev/null -b "$COOKIES" "$BASE$thumb" | grep -qi '^retry-after: 5'
  docker compose start backend > /dev/null
  wait_for_health
  expect 200 -b "$COOKIES" "$BASE$thumb"
  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null
  echo "photo checks passed"
}

case "$phase" in
  bootstrap) bootstrap ;;
  smoke) smoke ;;
  backup-restore) backup_restore ;;
  restore-drill) restore_drill ;;
  photos) photos ;;
  all)
    bootstrap
    smoke
    backup_restore
    restore_drill
    photos
    ;;
  *)
    echo "Usage: $0 [bootstrap|smoke|backup-restore|restore-drill|photos|all]" >&2
    exit 2
    ;;
esac
