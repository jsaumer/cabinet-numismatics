#!/usr/bin/env bash
# Drives a running Cabinet compose stack (proxy, backend, db) through sign-in,
# API tokens, the CRUD/backup/restore drills, and the metrics matrix. This is
# the shell that used to live inline in .github/workflows/ci.yml's "stack"
# job; it moved here so it can also run against the local stack before any
# push (docs/specs/SPEC_0300.md section 9, stage 7 of section 10).
#
# Usage: scripts/ci/stack-smoke.sh [race|bootstrap|smoke|outside-in|backup-restore|restore-drill|photos|share|trusted|sso|all]
#   (no argument, or "all", runs every phase in order)
#
# race must run before bootstrap, on a fresh, unclaimed stack (it skips
# itself with a message on one already claimed, so "all" still works
# against a stack that's already been signed into, such as the owner's main
# one). outside-in runs after bootstrap; it is independent of smoke,
# backup-restore, restore-drill, photos, share, and trusted. sso runs last:
# it needs the mock provider (docker-compose.ci.yml; it skips itself without
# one) and leaves the trusted-header mode on, so trusted fails after it
# until the stack is recreated without the TRUSTED_ASSERTION_* variables.
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
#   MOCK_IDP_URL       The mock provider as this shell reaches it (sso only;
#                       default http://localhost:8555)
#   MOCK_IDP_ISSUER    The mock provider as the backend reaches it, its issuer
#                       (sso only; default http://mock_idp:8555)
#   COMPOSE_FILE       The stack's compose files, for sso's recreate of the
#                       backend and proxy (CI: docker-compose.yaml:docker-compose.ci.yml)
#
# The `docker compose exec` calls below (a document's PDF, a photo, decrypting
# an archive) take no -p: they rely on COMPOSE_PROJECT_NAME (export it) to
# reach the right stack when BASE points at a throwaway project rather than
# the default "cabinet-numismatics" one docker compose infers from this
# directory's name.
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

# Run after a restore replaces the database: a fresh sign-in (its own cookie
# jar, so it doesn't disturb $COOKIES) and the bootstrap write token both
# still work, which proves neither the password hash nor the token survived
# by accident from before the restore, but by the restore itself keeping
# cabinet_auth untouched.
password_and_token_still_work() {
  echo "-- the password and the write token still work --"
  local jar
  jar="$(mktemp)"
  local status
  status=$(curl -s -o /dev/null -w '%{http_code}' -c "$jar" -H "Origin: $BASE" \
    -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}")
  rm -f "$jar"
  test "$status" = 200
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $WRITE_TOKEN" "$BASE/api/items")" = 200
}

# --- phases ------------------------------------------------------------------

# Two concurrent POST /api/auth/setup calls on a fresh, unclaimed stack must
# leave exactly one 201 and one 409: the setup race the gate is meant to
# close (docs/specs/SPEC_0300.md section 9). Meaningless once a stack is
# claimed, so it runs before bootstrap and skips itself on an already-claimed
# one rather than failing "all" on the main stack.
race() {
  echo "== race =="
  wait_for_health

  local required
  required=$(curl -fsS "$BASE/api/auth/state" | field setup_required)
  if [ "$required" != "True" ]; then
    echo "already claimed; race is only meaningful on a fresh stack, skipping"
    return 0
  fi
  : "${SETUP_CODE:?SETUP_CODE must be set to race a fresh stack}"

  # Both calls use CABINET_USER/CABINET_PASSWORD, so whichever wins is the
  # account bootstrap then signs in as: distinct usernames would leave
  # bootstrap not knowing which one to log in with.
  local out1 out2
  out1="$STATE_DIR/race-1.status"
  out2="$STATE_DIR/race-2.status"
  local body
  body="{\"code\":\"$SETUP_CODE\",\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}"
  curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/setup" \
    -H 'Content-Type: application/json' -d "$body" > "$out1" &
  local pid1=$!
  curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/setup" \
    -H 'Content-Type: application/json' -d "$body" > "$out2" &
  local pid2=$!
  wait "$pid1"
  wait "$pid2"
  local c1 c2
  c1="$(cat "$out1")"
  c2="$(cat "$out2")"
  rm -f "$out1" "$out2"
  echo "concurrent setup calls answered $c1 and $c2"
  if { [ "$c1" = 201 ] && [ "$c2" = 409 ]; } || { [ "$c1" = 409 ] && [ "$c2" = 201 ]; }; then
    echo "race passed: exactly one 201, one 409"
  else
    echo "race FAILED: wanted one 201 and one 409" >&2
    exit 1
  fi
}

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
assert isinstance(report["skipped_items"], list), report
'
  # metal= is evaluated in Python, not SQL (P11, v0.31.0): a known metal
  # answers, an unknown one is 422.
  apif "$BASE/api/items?metal=silver" > /dev/null
  test "$(status_of -H "Authorization: Bearer $WRITE_TOKEN" "$BASE/api/items?metal=tin")" = 422

  # a bullion item (P11, v0.31.0): no year, still counted, still in the stack
  bid=$(apif -X POST "$BASE/api/items" \
    -H 'Content-Type: application/json' \
    -d '{"type":"bullion","country":"CI Refinery","denomination":"1 oz silver bar","composition":"999 silver","weight_g":31.1035,"fineness":0.999}' \
    | field id)
  apif "$BASE/api/items/$bid" | "$PY" -c '
import json, sys
item = json.load(sys.stdin)
assert item["type"] == "bullion", item
assert item["year_label"] == "", item
'
  apif "$BASE/api/stats/collection" | "$PY" -c '
import json, sys
stats = json.load(sys.stdin)
assert stats["counts"]["bullion"] >= 1, stats
'
  apif "$BASE/api/stack" | "$PY" -c '
import json, sys
report = json.load(sys.stdin)
assert any(m["metal"] == "silver" and m["fine_oz"] > 0 for m in report["metals"]), report
'
  apif -X DELETE "$BASE/api/items/$bid" -o /dev/null
  apif "$BASE/api/trash" | grep -q "$bid"

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
  # attach a PDF (made by Pillow inside the backend image) as a document.
  # Scratch files live in STATE_DIR, never the repo root, so a run never
  # leaves stray files behind and separate CI steps (which share
  # STACK_SMOKE_STATE) see the same ones.
  receipt="$STATE_DIR/receipt.pdf"
  backup_age="$STATE_DIR/backup.zip.age"
  flipped_age="$STATE_DIR/flipped.zip.age"
  restored_pdf="$STATE_DIR/restored.pdf"
  docker compose exec -T backend python -c 'import io, sys; from PIL import Image; b = io.BytesIO(); Image.new("RGB", (200, 280), "white").save(b, "PDF"); sys.stdout.buffer.write(b.getvalue())' > "$receipt"
  doc=$(apif -X POST "$BASE/api/items/$id/documents" \
    -F kind=receipt -F file=@"$receipt" \
    | field id)

  # every archive is encrypted with the backup key (age); downloading one is
  # admin, fresh. sync before the very next read: on some Windows/Docker
  # Desktop setups, a file curl just wrote isn't reliably visible yet to a
  # process started a moment later inside the WSL2-backed daemon, and
  # decrypt-archive would see it as truncated or wrongly keyed.
  fresh -o "$backup_age" "$BASE/api/backup.zip"
  sync "$backup_age" 2>/dev/null || sync
  test "$(head -c 21 "$backup_age")" = "age-encryption.org/v1"
  # decrypt-archive and restore.sh need no token: they run on the host and in
  # the backend container, never through the API
  plain="$STATE_DIR/plain.zip"
  toc="$STATE_DIR/toc.txt"
  docker compose exec -T backend python -m app.cli decrypt-archive < "$backup_age" > "$plain"
  unzip -l "$plain" | grep -q documents.tar.gz
  unzip -p "$plain" db.dump | docker compose exec -T db pg_restore --list > "$toc"
  if grep -v '^;' "$toc" | grep -qw cabinet_auth; then
    echo "the dump holds sign-in data"
    exit 1
  fi
  rm -f "$plain" "$toc"

  # a flipped byte is refused before anything changes
  cp "$backup_age" "$flipped_age"
  printf '\x01' | dd of="$flipped_age" bs=1 seek=300 conv=notrunc status=none
  sync "$flipped_age" 2>/dev/null || sync
  if ./scripts/restore.sh "$flipped_age"; then
    echo "an altered archive was restored"
    exit 1
  fi
  rm -f "$flipped_age"

  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null
  if adminf "$BASE/api/documents/$doc/file" -o /dev/null; then
    echo "the document outlived its only item"
    exit 1
  fi
  ./scripts/restore.sh "$backup_age"
  apif "$BASE/api/items/$id" > /dev/null
  adminf "$BASE/api/documents/$doc/file" -o "$restored_pdf"
  cmp "$receipt" "$restored_pdf"
  echo "item $id and its document are back after restore"
  rm -f "$receipt" "$backup_age" "$restored_pdf"

  password_and_token_still_work

  adminf -X POST "$BASE/api/backups" | "$PY" -c '
import json, sys
run = json.load(sys.stdin)
print(run)
assert run["ok"]
'

  # deleting a stored archive (v0.30.1) needs a recent password, and is gone after
  gone=$(adminf -X POST "$BASE/api/backups" | field file)
  test "$(status_of -X DELETE "$BASE/api/backups/$gone")" = 401  # anonymous: refused
  fresh -X DELETE "$BASE/api/backups/$gone" | grep -q '"deleted"'
  test "$(fresh_status "$BASE/api/backups/$gone")" = 404
  echo "stored archive $gone deleted through the API"
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
  password_and_token_still_work
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

share() {
  load_tokens
  echo "== share =="
  local bogus_token="share_$(printf 'a%.0s' $(seq 1 43))"

  # Sharing starts off: the gate has no share rule then, so a stranger gets
  # the same 401 as on any other path (v0.32.0 stage 4), and making a link
  # answers 409 (the message says to switch sharing on first).
  test "$(status_of "$BASE/api/share/$bogus_token")" = 401
  test "$(status_of "$BASE/api/share/$bogus_token/items")" = 401
  test "$(fresh_status -X POST "$BASE/api/share-links" -H 'Content-Type: application/json' \
    -d '{"kind":"collection","name":"share smoke, off"}')" = 409

  # Switch it on (admin, fresh, like every settings change).
  fresh -X PUT "$BASE/api/settings" -H 'Content-Type: application/json' \
    -d '{"share_enabled": true}' -o /dev/null

  # An item carrying one of everything a share must never leak, plus a cert
  # and a photo whose EXIF names a camera and a place.
  id=$(apif -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Share check","denomination":"1 test","year":2026,"acquisition_price":"12.50","storage_location":"Box 1","serial_number":"A123456","custom_fields":{"note":"x"},"cert_service":"PCGS","cert_number":"12345678"}' \
    | field id)
  docker compose exec -T backend python -c 'import io, sys; from PIL import Image; e = Image.Exif(); e[0x0110] = "SmokeCam"; e[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}; b = io.BytesIO(); Image.new("RGB", (120, 90), "gray").save(b, "JPEG", exif=e.tobytes()); sys.stdout.buffer.write(b.getvalue())' > "$STATE_DIR/share-photo.jpg"
  photo=$(apif -X POST "$BASE/api/items/$id/photos" \
    -F "file=@-;filename=photo.jpg;type=image/jpeg" < "$STATE_DIR/share-photo.jpg")
  photo_id=$(printf '%s' "$photo" | field id)
  photo_thumb="/photos/$(printf '%s' "$photo" | field thumb_key)"

  # A collection link (fresh); the URL, and so the token, is shown once.
  created=$(fresh -X POST "$BASE/api/share-links" -H 'Content-Type: application/json' \
    -d '{"kind":"collection","name":"share smoke"}')
  link_id=$(printf '%s' "$created" | field id)
  token=$(printf '%s' "$created" | field url | sed 's#.*/s/##')
  test -n "$token"

  # Anonymous: the manifest, and the items page's allowlist.
  test "$(curl -fsS "$BASE/api/share/$token" | field kind)" = collection
  curl -fsS "$BASE/api/share/$token/items" | "$PY" -c '
import json, sys
body = json.load(sys.stdin)
item = body["items"][0]
forbidden = {
    "acquisition_price", "storage_location", "serial_number",
    "custom_fields", "documents", "cost_basis",
}
leaked = forbidden & item.keys()
assert not leaked, f"share item view leaked: {leaked}"
assert "cert_number" not in item, "cert_number shown with show_certs off"
assert item.get("cert_service") == "PCGS", "cert_service belongs to show_grades"
'
  # The cert number has a toggle of its own, off by default; changing a
  # link's options asks for the password again (fresh).
  fresh -X PATCH "$BASE/api/share-links/$link_id" -H 'Content-Type: application/json' \
    -d '{"show_certs": true}' -o /dev/null
  curl -fsS "$BASE/api/share/$token/items" | "$PY" -c '
import json, sys
item = json.load(sys.stdin)["items"][0]
assert item.get("cert_number") == "12345678", "cert_number missing with show_certs on"
'

  # The photo, through the share route (anonymous, with a CSP header), and
  # refused on nginx's /photos/ (session or token only, never a share).
  curl -s -D - -o /dev/null "$BASE/api/share/$token/photos/$photo_id/thumb" \
    | grep -qi '^content-security-policy:'
  test "$(status_of "$BASE/api/share/$token/photos/$photo_id/thumb")" = 200
  test "$(status_of "$BASE$photo_thumb")" = 401
  # No upload time on a shared photo (no Last-Modified, no ETag), and the
  # full image carries no EXIF: it was stripped when it was uploaded.
  photo_headers=$(curl -fsS -D - -o /dev/null "$BASE/api/share/$token/photos/$photo_id/full")
  if printf '%s' "$photo_headers" | grep -qiE '^(last-modified|etag):'; then
    echo "share: the photo response names its file time" >&2
    exit 1
  fi
  curl -fsS "$BASE/api/share/$token/photos/$photo_id/full" \
    | docker compose exec -T backend python -c 'import io, sys; from PIL import Image; d = sys.stdin.buffer.read(); i = Image.open(io.BytesIO(d)); assert not dict(i.getexif()) and b"SmokeCam" not in d, "photo metadata reached a share"'

  # A session cookie on the manifest route gets exactly the anonymous
  # answer: a share route ignores whatever credential rides along.
  test "$(status_of -b "$COOKIES" -H "Origin: $BASE" "$BASE/api/share/$token")" = 200

  # Revoke (fresh, 204): that link's manifest is 404 from then on.
  gone=$(fresh -X POST "$BASE/api/share-links" -H 'Content-Type: application/json' \
    -d '{"kind":"collection","name":"share smoke, revoked"}')
  gone_token=$(printf '%s' "$gone" | field url | sed 's#.*/s/##')
  test "$(status_of "$BASE/api/share/$gone_token")" = 200
  fresh -X DELETE "$BASE/api/share-links/$(printf '%s' "$gone" | field id)" -o /dev/null
  test "$(status_of "$BASE/api/share/$gone_token")" = 404

  # The throttle, last (it leaves this address waiting a few seconds). A
  # token that matches no link is 404 and counted; from the 21st failure on
  # the address waits, and a failed lookup inside the wait is 429 and not
  # counted. The live link is resolved first, so it always answers 200.
  got=404
  for _ in $(seq 1 25); do
    got=$(status_of "$BASE/api/share/$bogus_token")
    [ "$got" = 404 ] || break
  done
  test "$got" = 429
  test "$(status_of "$BASE/api/share/$token")" = 200
  test "$(status_of "$BASE/api/share/$token/items")" = 200
  test "$(status_of "$BASE/api/share/$token/photos/$photo_id/thumb")" = 200
  test "$(status_of "$BASE/api/share/$bogus_token")" = 429
  # Wait the wait out: the next failure is counted again (404), and the one
  # after it waits once more.
  retry=$(curl -s -D - -o /dev/null "$BASE/api/share/$bogus_token" \
    | tr -d '\r' | awk -F': ' 'tolower($1) == "retry-after" { print $2 }')
  test -n "$retry"
  sleep "$((retry + 1))"
  test "$(status_of "$BASE/api/share/$bogus_token")" = 404
  test "$(status_of "$BASE/api/share/$token")" = 200
  test "$(status_of "$BASE/api/share/$bogus_token")" = 429

  # Off again, and clean up what this phase made.
  fresh -X DELETE "$BASE/api/share-links/$link_id" -o /dev/null
  fresh -X PUT "$BASE/api/settings" -H 'Content-Type: application/json' \
    -d '{"share_enabled": false}' -o /dev/null
  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null
  echo "share checks passed"
}

outside_in() {
  load_tokens
  echo "== outside-in =="

  # Anonymous, one per class, before any principal is involved: public GET
  # /api/health is checked elsewhere (it answers 200); everything below is
  # either read, write, or admin, so it is 401.
  test "$(status_of "$BASE/api/openapi.json")" = 401
  test "$(status_of "$BASE/api/settings")" = 401
  test "$(status_of "$BASE/api/backups")" = 401
  test "$(status_of "$BASE/api/metrics")" = 401
  test "$(status_of "$BASE/api/items/1")" = 401

  # A document file is admin, session only: create an item and attach a
  # small PNG with the write token, then check the file itself anonymously.
  id=$(apif -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
    -d '{"type":"coin","country":"Outside-in","denomination":"1 test","year":2026}' | field id)
  doc_png="$STATE_DIR/outside-in-doc.png"
  docker compose exec -T backend python -c 'import io, sys; from PIL import Image; b = io.BytesIO(); Image.new("RGB", (60, 40), "white").save(b, "PNG"); sys.stdout.buffer.write(b.getvalue())' > "$doc_png"
  doc=$(apif -X POST "$BASE/api/items/$id/documents" \
    -F "file=@-;filename=doc.png;type=image/png" < "$doc_png" | field id)
  rm -f "$doc_png"
  test "$(status_of "$BASE/api/documents/$doc/file")" = 401

  # Each token's scope against one route per class: public GET /api/health,
  # read GET /api/items, write POST /api/items, admin GET /api/settings.
  # docs/api.md's table; the session gets 200 on all four.
  # A POST's status and body are captured together (status on its own last
  # line) and split in bash, never round-tripped through a file: curl and
  # python disagree about what a POSIX-looking path like $STATE_DIR/... means
  # on this Windows dev machine (curl is handed it as a bare argument and a
  # native launcher rewrites it; python sees it only as a substring of its
  # -c script and never rewrites it), so a file one writes the other can't
  # reliably reopen. Piping through stdin, like field() already does
  # everywhere else in this script, sidesteps the whole question.
  post_class_check() {
    local header="$1"
    curl -s -w '\n%{http_code}' -H "$header" -H 'Content-Type: application/json' -X POST \
      -d '{"type":"coin","country":"Class check","denomination":"1 test","year":2026}' \
      "$BASE/api/items"
  }
  check_class() {
    local label="$1" header="$2" want_health="$3" want_get="$4" want_post="$5" want_admin="$6"
    local got resp body new_id
    got=$(status_of -H "$header" "$BASE/api/health")
    [ "$got" = "$want_health" ] || { echo "$label GET /api/health: got $got, wanted $want_health" >&2; exit 1; }
    got=$(status_of -H "$header" "$BASE/api/items")
    [ "$got" = "$want_get" ] || { echo "$label GET /api/items: got $got, wanted $want_get" >&2; exit 1; }
    resp=$(post_class_check "$header")
    got=$(printf '%s\n' "$resp" | tail -n1)
    body=$(printf '%s\n' "$resp" | sed '$d')
    [ "$got" = "$want_post" ] || { echo "$label POST /api/items: got $got, wanted $want_post" >&2; exit 1; }
    if [ "$got" = 201 ]; then
      new_id=$(printf '%s' "$body" | field id)
      fresh -X DELETE "$BASE/api/items/$new_id?permanent=true" -o /dev/null
    fi
    got=$(status_of -H "$header" "$BASE/api/settings")
    [ "$got" = "$want_admin" ] || { echo "$label GET /api/settings: got $got, wanted $want_admin" >&2; exit 1; }
  }
  check_class read "Authorization: Bearer $READ_TOKEN" 200 200 403 403
  check_class write "Authorization: Bearer $WRITE_TOKEN" 200 200 201 403
  check_class metrics "Authorization: Bearer $METRICS_TOKEN" 200 403 403 403
  # The session cookie (no bearer header; Origin covers CSRF) gets all four.
  test "$(status_of -b "$COOKIES" -H "Origin: $BASE" "$BASE/api/health")" = 200
  test "$(status_of -b "$COOKIES" -H "Origin: $BASE" "$BASE/api/items")" = 200
  session_resp=$(curl -s -w '\n%{http_code}' -b "$COOKIES" -H "Origin: $BASE" \
    -H 'Content-Type: application/json' -X POST \
    -d '{"type":"coin","country":"Class check","denomination":"1 test","year":2026}' "$BASE/api/items")
  session_post=$(printf '%s\n' "$session_resp" | tail -n1)
  session_body=$(printf '%s\n' "$session_resp" | sed '$d')
  test "$session_post" = 201
  session_id=$(printf '%s' "$session_body" | field id)
  fresh -X DELETE "$BASE/api/items/$session_id?permanent=true" -o /dev/null
  test "$(status_of -b "$COOKIES" -H "Origin: $BASE" "$BASE/api/settings")" = 200

  fresh -X DELETE "$BASE/api/items/$id?permanent=true" -o /dev/null

  # A token minted then revoked is 401 everywhere, not 403: it no longer
  # exists as far as the gate is concerned.
  revoked=$(fresh -X POST "$BASE/api/auth/tokens" -H 'Content-Type: application/json' \
    -d '{"name":"ci-revoke-'"$$"'","scope":"read","days":1}')
  revoked_token=$(echo "$revoked" | field token)
  revoked_id=$(echo "$revoked" | field id)
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $revoked_token" "$BASE/api/items")" = 200
  fresh -X DELETE "$BASE/api/auth/tokens/$revoked_id" -o /dev/null
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $revoked_token" "$BASE/api/items")" = 401

  # Spoofed forwarded headers are overwritten by nginx before the backend
  # ever sees them: a failed login carrying a fake X-Forwarded-For/X-Real-IP
  # must not show up in the audit log under that address.
  curl -s -o /dev/null -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -H 'X-Forwarded-For: 203.0.113.99' -H 'X-Real-IP: 203.0.113.99' \
    -d "{\"username\":\"$CABINET_USER\",\"password\":\"not the password, spoof check\"}"
  adminf "$BASE/api/auth/audit?limit=5" | "$PY" -c '
import json, sys
rows = json.load(sys.stdin)
row = next(r for r in rows if r["action"] == "sign_in_failed")
assert row["address"] != "203.0.113.99", f"spoofed address reached the audit log: {row}"
print("failed sign-in recorded from", row["address"], "not the spoofed address")
'

  echo "outside-in checks passed"
}

trusted() {
  load_tokens
  echo "== trusted =="
  # The trusted-header mode (v0.33.0) against a stack with it OFF (CI's): the
  # routes answer 404, no gateway header ever reaches the backend, the
  # generated include blanks every name, and a callback's code and state
  # never reach an access log. The full header sign-in through real nginx
  # against a signed assertion is stage 5's: the mock provider hosts the
  # JWKS it needs.

  # (a) The sign-in page is told the mode isn't there.
  curl -fsS "$BASE/api/auth/state" | "$PY" -c '
import json, sys
state = json.load(sys.stdin)
assert state["methods"]["trusted_header"] is None, state
'

  # (b) The sign-in route is 404, anonymous and signed in alike.
  test "$(status_of -X POST "$BASE/api/auth/trusted")" = 404
  test "$(status_of -b "$COOKIES" -H "Origin: $BASE" -X POST "$BASE/api/auth/trusted")" = 404

  # (c) Every gateway header a client sends is blanked by nginx: a wrong
  # password carrying all of them answers exactly as one without, and none
  # of their values reaches the audit log.
  local plain spoofed
  plain=$(status_of -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$CABINET_USER\",\"password\":\"not the password, trusted check\"}")
  spoofed=$(status_of -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -H 'X-authentik-jwt: spoofed-marker-jwt' -H 'Remote-User: spoofed-marker-user' \
    -H 'X-Goog-IAP-JWT-Assertion: spoofed-marker-iap' \
    -H 'Cf-Access-Jwt-Assertion: spoofed-marker-cf' \
    -d "{\"username\":\"$CABINET_USER\",\"password\":\"not the password, trusted check\"}")
  test "$plain" = "$spoofed"
  adminf "$BASE/api/auth/audit?limit=20" | "$PY" -c '
import json, sys
rows = json.load(sys.stdin)
assert "spoofed-marker" not in json.dumps(rows), "a spoofed gateway header reached the audit log"
assert not any(r["action"] == "sso_sign_in_rejected" for r in rows), rows
print("spoofed gateway headers left no trace")
'

  # (d) The include nginx is running with blanks every name. (MSYS_NO_PATHCONV
  # keeps Git Bash on Windows from rewriting the container paths; no effect
  # elsewhere.)
  local include
  include=$(MSYS_NO_PATHCONV=1 docker compose exec -T proxy cat /etc/nginx/cabinet/cabinet-identity.conf)
  if printf '%s\n' "$include" | grep -q '\$http_'; then
    echo "the identity include passes a header through with the mode off" >&2
    exit 1
  fi
  for name in X-authentik-jwt Remote-User Cf-Access-Jwt-Assertion X-Pomerium-Jwt-Assertion \
    X-Goog-IAP-JWT-Assertion; do
    printf '%s\n' "$include" | grep -qx "proxy_set_header $name \"\";"
  done

  # (e) The start script, rendered inside the proxy container for each
  # supported assertion header, passes exactly that one; a header nginx sets
  # itself stops it.
  local rendered
  for name in X-authentik-jwt Cf-Access-Jwt-Assertion X-Pomerium-Jwt-Assertion \
    X-Goog-IAP-JWT-Assertion; do
    rendered=$(MSYS_NO_PATHCONV=1 docker compose exec -T -e TRUSTED_ASSERTION_HEADER="$name" proxy sh -c \
      'CABINET_NGINX_DIR=/tmp/cabinet-render /docker-entrypoint.d/40-cabinet-config.sh >/dev/null && cat /tmp/cabinet-render/cabinet-identity.conf && rm -rf /tmp/cabinet-render')
    test "$(printf '%s\n' "$rendered" | grep -c '\$http_')" = 1
    printf '%s\n' "$rendered" | grep -q "^proxy_set_header $name \$http_"
  done
  if MSYS_NO_PATHCONV=1 docker compose exec -T -e TRUSTED_ASSERTION_HEADER=Host proxy sh -c \
    'CABINET_NGINX_DIR=/tmp/cabinet-render /docker-entrypoint.d/40-cabinet-config.sh' >/dev/null 2>&1; then
    echo "the start script accepted TRUSTED_ASSERTION_HEADER=Host" >&2
    exit 1
  fi

  # (f) A callback's code and state never reach either access log.
  curl -s -o /dev/null "$BASE/api/auth/oidc/callback?code=smokecodeabc&state=smokestatedef"
  curl -s -o /dev/null "$BASE/api/auth/oidc/callback/?code=smokecodeabc"
  local logs
  logs=$(docker compose logs --no-log-prefix --tail 200 proxy backend 2>&1)
  printf '%s\n' "$logs" | grep -q 'oidc/callback?\[redacted\]'
  if printf '%s\n' "$logs" | grep -q 'smokecode\|smokestate'; then
    echo "a callback's code or state reached a log" >&2
    exit 1
  fi
  echo "trusted checks passed"
}

# --- single sign-on through the mock provider ----------------------------------

# A header's value from a `curl -D` dump (empty when it isn't there).
header_value() {
  tr -d '\r' < "$1" | grep -i "^$2:" | head -n1 | sed 's/^[^:]*: *//' || true
}

# Set what the mock's next token (or discovery document) does.
mock_control() {
  curl -fsS -X POST "$MOCK_IDP_URL/control" -H 'Content-Type: application/json' -d "$1" -o /dev/null
}

# One pass through the code flow with curl: Cabinet's start route, the mock's
# authorize page (auto-approved; sent to the mock's host-side address, since
# the authorize URL names the browser-facing one), then Cabinet's callback.
# Sets SSO_START (the start's status), SSO_AUTHORIZE, SSO_CALLBACK (the URL
# the mock sent back), SSO_FLOW (the flow cookie, read before the callback
# clears it), SSO_STATUS and SSO_LOCATION (the callback's answer); the
# callback's headers are left in $STATE_DIR/sso-callback.hdr.
sso_trip() {
  local jar="$1" intent="$2" next="$3"
  SSO_AUTHORIZE="" SSO_CALLBACK="" SSO_FLOW="" SSO_STATUS="" SSO_LOCATION=""
  SSO_START=$(curl -s -o /dev/null -D "$STATE_DIR/sso-start.hdr" -w '%{http_code}' \
    -b "$jar" -c "$jar" -H "Origin: $BASE" \
    "$BASE/api/auth/oidc/start?provider=$SSO_PROVIDER&intent=$intent&next=$next")
  [ "$SSO_START" = 302 ] || return 0
  SSO_AUTHORIZE=$(header_value "$STATE_DIR/sso-start.hdr" location)
  curl -s -o /dev/null -D "$STATE_DIR/sso-authorize.hdr" \
    "$MOCK_IDP_URL/authorize?${SSO_AUTHORIZE#*\?}&auto=1"
  SSO_CALLBACK=$(header_value "$STATE_DIR/sso-authorize.hdr" location)
  SSO_FLOW=$(awk '$6 == "cabinet_oidc" { print $7 }' "$jar")
  SSO_STATUS=$(curl -s -o /dev/null -D "$STATE_DIR/sso-callback.hdr" -w '%{http_code}' \
    -b "$jar" -c "$jar" "$SSO_CALLBACK")
  SSO_LOCATION=$(header_value "$STATE_DIR/sso-callback.hdr" location)
}

# A sign-in, in a new jar $1, that must land on $2.
sso_expect() {
  : > "$1"
  sso_trip "$1" login /collection
  if [ "$SSO_STATUS" != 303 ] || [ "$SSO_LOCATION" != "$2" ]; then
    echo "sso: wanted 303 to $2, got ${SSO_START}/${SSO_STATUS} to '$SSO_LOCATION'" >&2
    exit 1
  fi
}

me_of() { curl -fsS -b "$1" -c "$1" -H "Origin: $BASE" "$BASE/api/auth/me"; }
signin_config() { adminf "$BASE/api/auth/signin-config"; }
trusted_status() { curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/trusted" "$@"; }

sso() {
  load_tokens
  echo "== sso =="
  MOCK_IDP_URL="${MOCK_IDP_URL:-http://localhost:8555}"
  MOCK_IDP_ISSUER="${MOCK_IDP_ISSUER:-http://mock_idp:8555}"
  if ! curl -fsS -o /dev/null "$MOCK_IDP_URL/health" 2>/dev/null; then
    echo "no mock provider at $MOCK_IDP_URL (start the stack with docker-compose.ci.yml too); skipping sso"
    return 0
  fi
  # Single sign-on end to end against scripts/ci/mock_idp.py, then the
  # trusted-header mode through real nginx, which this phase leaves ON:
  # Playwright's sso.spec.ts follows it in CI and uses both the providers
  # configured here and the header mode. So `trusted` (which expects the
  # mode off) fails after this phase until the backend and proxy are
  # recreated without the TRUSTED_ASSERTION_* variables, which is what a
  # rerun of this phase does first. The `docker compose` calls below take
  # the stack's compose files from COMPOSE_FILE (docker compose reads it
  # itself), so export it as the stack was started.

  # Start clean: the mode off (a rerun finds it on; recreating the backend
  # also clears the single sign-on throttle an earlier run filled), and no
  # provider or header identity from an earlier run.
  if signin_config | "$PY" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["trusted_header"]["configured"] else 1)'; then
    env -u TRUSTED_ASSERTION_HEADER -u TRUSTED_ASSERTION_JWKS_URL \
      -u TRUSTED_ASSERTION_ISSUER -u TRUSTED_ASSERTION_AUDIENCE \
      docker compose up -d backend proxy
    wait_for_health
  fi
  mock_control '{"subject": "ci-user-1", "misbehave": null}'
  local stale
  for stale in $(signin_config | "$PY" -c '
import json, sys
c = json.load(sys.stdin)
for p in c["providers"]:
    if p["client_id"] in ("cabinet-ci", "cabinet-ci-github"):
        print("providers/%d" % p["id"])
for i in c["identities"]:
    if i["kind"] == "trusted_header":
        print("identities/%d" % i["id"])
' | tr -d '\r'); do
    fresh -X DELETE "$BASE/api/auth/$stale" -o /dev/null
  done

  # (1) Configure: a custom OpenID Connect provider at the mock (tried with
  # dry_run first) and a GitHub one. The GitHub preset's URLs are fixed to
  # github.com in the backend, so its exchange can't be round-tripped
  # against the mock from here: pytest's fake proves it (tests/test_oidc.py),
  # and the mock's GitHub mode waits for a way to reach it that needs no
  # backend change. Here the GitHub preset proves its configuration only.
  local oidc_body created
  oidc_body="{\"preset\":\"custom\",\"issuer\":\"$MOCK_IDP_ISSUER\",\"client_id\":\"cabinet-ci\",\"client_secret\":\"cabinet-ci-secret\",\"display_name\":\"CI provider\",\"enabled\":true"
  fresh -X POST "$BASE/api/auth/providers" -H 'Content-Type: application/json' \
    -d "$oidc_body,\"dry_run\":true}" | "$PY" -c '
import json, sys
r = json.load(sys.stdin)
assert r["ok"] is True and r["claims_supported_auth_time"] is True and r["prompt_login"] is True, r
'
  created=$(fresh -X POST "$BASE/api/auth/providers" -H 'Content-Type: application/json' \
    -d "$oidc_body}" -w '\n%{http_code}')
  test "$(printf '%s\n' "$created" | tail -n1)" = 201
  SSO_PROVIDER=$(printf '%s\n' "$created" | head -n1 | field id)
  created=$(fresh -X POST "$BASE/api/auth/providers" -H 'Content-Type: application/json' \
    -d '{"preset":"github","client_id":"cabinet-ci-github","client_secret":"cabinet-ci-github-secret","display_name":"GitHub","enabled":true}' \
    -w '\n%{http_code}')
  test "$(printf '%s\n' "$created" | tail -n1)" = 201
  printf '%s\n' "$created" | head -n1 | "$PY" -c '
import json, sys
p = json.load(sys.stdin)
assert p["kind"] == "oauth2_profile" and p["linked"] is False and p["enabled"] is True, p
'
  GITHUB_PROVIDER=$(printf '%s\n' "$created" | head -n1 | field id)
  test "$(fresh_status -X POST "$BASE/api/auth/providers" -H 'Content-Type: application/json' \
    -d '{"preset":"github","client_id":"cabinet-ci-github","display_name":"GitHub","dry_run":true}')" = 422
  curl -fsS "$BASE/api/auth/state" | "$PY" -c '
import json, sys
names = [p["name"] for p in json.load(sys.stdin)["methods"]["providers"]]
assert "CI provider" in names and "GitHub" in names, names
'

  local jar_anon="$STATE_DIR/sso-anon.txt" jar_sso="$STATE_DIR/sso-session.txt"
  local jar_x="$STATE_DIR/sso-x.txt" jar_header="$STATE_DIR/sso-header.txt"

  # (2) An identity nobody linked is refused, and audited with its subject.
  sso_expect "$jar_anon" "/login?error=unlinked"
  adminf "$BASE/api/auth/audit?limit=20" | "$PY" -c '
import json, sys
rows = [r for r in json.load(sys.stdin) if r["action"] == "sso_sign_in_rejected"]
assert rows, "no sso_sign_in_rejected row"
d = rows[0]["detail"]
assert d["reason"] == "unlinked" and d["subject"] == "ci-user-1", d
'

  # (3) Link it from the admin's own session (fresh): lands in Settings.
  confirm_now
  sso_trip "$COOKIES" link /settings/signin
  test "$SSO_START" = 302
  test "$SSO_STATUS" = 303
  test "$SSO_LOCATION" = "/settings/signin?linked=$SSO_PROVIDER"
  signin_config | "$PY" -c '
import json, sys
pid = int(sys.argv[1])
ids = [i for i in json.load(sys.stdin)["identities"] if i["kind"] == "provider"]
assert any(i["provider_id"] == pid and i["subject"] == "ci-user-1" for i in ids), ids
' "$SSO_PROVIDER"
  # A linked provider can't be repointed (R2-13).
  test "$(fresh_status -X PATCH "$BASE/api/auth/providers/$SSO_PROVIDER" \
    -H 'Content-Type: application/json' -d '{"client_id":"cabinet-ci-other"}')" = 409

  # (4) Sign in through it: a session and a browser cookie, never a device
  # cookie (CR-03); the failed-sign-ins notice is handed over once.
  sso_expect "$jar_sso" "/collection"
  local login_callback="$SSO_CALLBACK" login_flow="$SSO_FLOW" cookies
  test -n "$login_flow"
  cookies=$(tr -d '\r' < "$STATE_DIR/sso-callback.hdr" | grep -i '^set-cookie:' || true)
  printf '%s\n' "$cookies" | grep -q 'cabinet_session='
  printf '%s\n' "$cookies" | grep -q 'cabinet_browser='
  if printf '%s\n' "$cookies" | grep -q 'cabinet_device='; then
    echo "sso: a single sign-on set a device cookie" >&2
    exit 1
  fi
  me_of "$jar_sso" | "$PY" -c '
import json, sys
me = json.load(sys.stdin)
assert me["auth_method"] == "oidc" and me["provider_id"] == int(sys.argv[1]), me
assert me["confirm_methods"] == ["password", "provider"], me
assert isinstance(me["failed_since_previous"], int), me
assert me["confirmed_until"] is None, me
' "$SSO_PROVIDER"
  me_of "$jar_sso" | "$PY" -c '
import json, sys
assert json.load(sys.stdin)["failed_since_previous"] is None
'

  # (5) Every broken ID token lands on /login?error=token.
  local bad
  for bad in wrong_nonce wrong_aud extra_aud expired no_exp alg_none hs256 unknown_kid iss_mismatch; do
    mock_control "{\"misbehave\": \"$bad\"}"
    sso_expect "$jar_x" "/login?error=token"
    echo "refused as it should be: $bad"
  done
  # The same callback twice: its state is used up (CR-17).
  test "$(curl -s -o /dev/null -D "$STATE_DIR/sso-replay.hdr" -w '%{http_code}' \
    -H "Cookie: cabinet_oidc=$login_flow" "$login_callback")" = 303
  test "$(header_value "$STATE_DIR/sso-replay.hdr" location)" = "/login?error=state"
  # No flow cookie at all.
  curl -s -o /dev/null -D "$STATE_DIR/sso-nocookie.hdr" "$login_callback"
  header_value "$STATE_DIR/sso-nocookie.hdr" location | grep -q '^/login?error=[a-z_]*$'
  # The code and state reached neither log.
  local code state
  code=$(printf '%s' "$login_callback" | sed 's/.*[?&]code=\([^&]*\).*/\1/')
  state=$(printf '%s' "$login_callback" | sed 's/.*[?&]state=\([^&]*\).*/\1/')
  test -n "$code" && test -n "$state"
  if docker compose logs --no-log-prefix proxy backend 2>&1 | grep -qF -e "$code" -e "$state"; then
    echo "sso: a callback's code or state reached a log" >&2
    exit 1
  fi

  # (6) Confirm at the provider from the single sign-on session, which never
  # typed a password: prompt=login goes to the provider, and the window
  # opens. Then the same as someone else: refused, the window unchanged.
  sso_trip "$jar_sso" confirm /collection
  test "$SSO_START" = 302
  printf '%s' "$SSO_AUTHORIZE" | grep -q '[?&]prompt=login'
  test "$SSO_STATUS" = 303
  test "$SSO_LOCATION" = "/collection"
  local until
  until=$(me_of "$jar_sso" | field confirmed_until)
  test "$until" != None
  mock_control '{"subject": "someone-else"}'
  sso_trip "$jar_sso" confirm /collection
  mock_control '{"subject": "ci-user-1"}'
  test "$SSO_LOCATION" = "/collection?confirm_error=confirm_identity"
  test "$(me_of "$jar_sso" | field confirmed_until)" = "$until"

  # (7) Sign out there too: the logout answer names the mock's end-session
  # endpoint, which is then followed (on its host-side address).
  fresh -X PATCH "$BASE/api/auth/providers/$SSO_PROVIDER" -H 'Content-Type: application/json' \
    -d '{"logout_at_provider": true}' -o /dev/null
  local redirect
  redirect=$(curl -fsS -b "$jar_sso" -c "$jar_sso" -H "Origin: $BASE" -X POST "$BASE/api/auth/logout" \
    | field redirect)
  case "$redirect" in
    "$MOCK_IDP_ISSUER/end_session?client_id="*) ;;
    *) echo "sso: logout redirect was '$redirect'" >&2; exit 1 ;;
  esac
  curl -fsS -o /dev/null "$MOCK_IDP_URL/end_session?${redirect#*\?}"
  curl -fsS "$MOCK_IDP_URL/control" | "$PY" -c '
import json, sys
seen = json.load(sys.stdin)["end_session"]
assert seen["client_id"] == "cabinet-ci", seen
assert seen["post_logout_redirect_uri"] == sys.argv[1] + "/login", seen
' "$BASE"
  test "$(status_of -b "$jar_sso" -H "Origin: $BASE" "$BASE/api/auth/me")" = 401
  fresh -X PATCH "$BASE/api/auth/providers/$SSO_PROVIDER" -H 'Content-Type: application/json' \
    -d '{"logout_at_provider": false}' -o /dev/null

  # (8) Credentials the provider rejects: the sign-in fails and the alert
  # condition shows in Settings; the right secret clears it.
  fresh -X PATCH "$BASE/api/auth/providers/$SSO_PROVIDER" -H 'Content-Type: application/json' \
    -d '{"client_secret": "not the secret"}' -o /dev/null
  sso_expect "$jar_x" "/login?error=provider"
  signin_config | "$PY" -c '
import json, sys
p = [p for p in json.load(sys.stdin)["providers"] if p["id"] == int(sys.argv[1])][0]
assert p["credentials_failing"] is True, p
' "$SSO_PROVIDER"
  fresh -X PATCH "$BASE/api/auth/providers/$SSO_PROVIDER" -H 'Content-Type: application/json' \
    -d '{"client_secret": "cabinet-ci-secret"}' -o /dev/null
  sso_expect "$jar_sso" "/collection"
  signin_config | "$PY" -c '
import json, sys
p = [p for p in json.load(sys.stdin)["providers"] if p["id"] == int(sys.argv[1])][0]
assert p["credentials_failing"] is False, p
' "$SSO_PROVIDER"
  # A discovery document naming another issuer is refused. Last before the
  # recreate below, which forgets it: a failed discovery is remembered for
  # a minute.
  mock_control '{"misbehave": "wrong_issuer_discovery"}'
  fresh -X POST "$BASE/api/auth/providers" -H 'Content-Type: application/json' \
    -d "$oidc_body,\"dry_run\":true}" | "$PY" -c '
import json, sys
r = json.load(sys.stdin)
assert r["ok"] is False and r["error"] == "issuer", r
'

  # (9) The trusted-header mode, end to end through real nginx (stage 3 owed
  # it), the mock playing the gateway: its JWKS and its signed assertions.
  export TRUSTED_ASSERTION_HEADER=X-authentik-jwt
  export TRUSTED_ASSERTION_JWKS_URL="$MOCK_IDP_ISSUER/jwks"
  export TRUSTED_ASSERTION_ISSUER="$MOCK_IDP_ISSUER"
  export TRUSTED_ASSERTION_AUDIENCE=cabinet-gateway
  docker compose up -d backend proxy
  wait_for_health
  curl -fsS "$BASE/api/auth/state" | "$PY" -c '
import json, sys
assert json.load(sys.stdin)["methods"]["trusted_header"] == {"available": True}
'
  # The include nginx runs with passes exactly the one header.
  test "$(MSYS_NO_PATHCONV=1 docker compose exec -T proxy cat /etc/nginx/cabinet/cabinet-identity.conf \
    | grep -c '\$http_')" = 1
  MSYS_NO_PATHCONV=1 docker compose exec -T proxy nginx -T 2>/dev/null \
    | grep -q '^proxy_set_header X-authentik-jwt \$http_x_authentik_jwt;'

  local assertion
  assertion=$(curl -fsS "$MOCK_IDP_URL/mint")
  test "$(curl -s -X POST "$BASE/api/auth/trusted" | field code)" = assertion
  test "$(curl -s -X POST "$BASE/api/auth/trusted" -H "X-authentik-jwt: $assertion" | field code)" = unlinked
  test "$(fresh_status -X POST "$BASE/api/auth/identities/trusted_header" \
    -H "X-authentik-jwt: $assertion")" = 201
  : > "$jar_header"
  test "$(curl -s -o "$STATE_DIR/sso-trusted.json" -D "$STATE_DIR/sso-trusted.hdr" -w '%{http_code}' \
    -b "$jar_header" -c "$jar_header" -X POST "$BASE/api/auth/trusted" \
    -H "X-authentik-jwt: $assertion")" = 200
  test "$(field username < "$STATE_DIR/sso-trusted.json")" = "$CABINET_USER"
  cookies=$(tr -d '\r' < "$STATE_DIR/sso-trusted.hdr" | grep -i '^set-cookie:' || true)
  printf '%s\n' "$cookies" | grep -q 'cabinet_session='
  printf '%s\n' "$cookies" | grep -q 'cabinet_browser='
  if printf '%s\n' "$cookies" | grep -q 'cabinet_device='; then
    echo "sso: a header sign-in set a device cookie" >&2
    exit 1
  fi
  test "$(me_of "$jar_header" | field auth_method)" = trusted_header
  # Refused: the header twice (nginx joins them with ", "), another
  # audience, expired, HMAC-signed, a key the gateway never published.
  test "$(trusted_status -H "X-authentik-jwt: $assertion" -H "X-authentik-jwt: $assertion")" = 403
  local query
  for query in "aud=other" "exp=-1" "alg=HS256" "kid=ci-unknown"; do
    test "$(trusted_status -H "X-authentik-jwt: $(curl -fsS "$MOCK_IDP_URL/mint?$query")")" = 403
    echo "refused as it should be: $query"
  done
  # A JWKS URL in a request header is never used (CR-05).
  test "$(trusted_status -H "X-authentik-jwt: $assertion" \
    -H 'X-authentik-meta-jwks: http://elsewhere.invalid/jwks')" = 200

  # disable-sso from the container: no provider, no header mode, their
  # sessions ended, with no restart; Settings switches it all back on.
  MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m app.cli disable-sso
  curl -fsS "$BASE/api/auth/state" | "$PY" -c '
import json, sys
m = json.load(sys.stdin)["methods"]
assert m["trusted_header"] is None and m["providers"] == [], m
'
  test "$(trusted_status -H "X-authentik-jwt: $assertion")" = 404
  test "$(status_of -b "$jar_sso" -H "Origin: $BASE" "$BASE/api/auth/me")" = 401
  test "$(status_of -b "$jar_header" -H "Origin: $BASE" "$BASE/api/auth/me")" = 401
  fresh -X PUT "$BASE/api/auth/signin-config" -H 'Content-Type: application/json' \
    -d '{"trusted_header_enabled": true}' -o /dev/null
  local id
  for id in "$SSO_PROVIDER" "$GITHUB_PROVIDER"; do
    fresh -X PATCH "$BASE/api/auth/providers/$id" -H 'Content-Type: application/json' \
      -d '{"enabled": true}' -o /dev/null
  done
  curl -fsS "$BASE/api/auth/state" | "$PY" -c '
import json, sys
m = json.load(sys.stdin)["methods"]
assert m["trusted_header"] == {"available": True} and len(m["providers"]) == 2, m
'
  # (10) Nothing else is cleaned up: the providers, both identities, and the
  # header mode stay for Playwright.
  rm -f "$jar_anon" "$jar_sso" "$jar_x" "$jar_header" "$STATE_DIR"/sso-*.hdr "$STATE_DIR/sso-trusted.json"
  echo "sso checks passed (the trusted-header mode is left on)"
}

case "$phase" in
  race) race ;;
  bootstrap) bootstrap ;;
  smoke) smoke ;;
  outside-in) outside_in ;;
  backup-restore) backup_restore ;;
  restore-drill) restore_drill ;;
  photos) photos ;;
  share) share ;;
  trusted) trusted ;;
  sso) sso ;;
  all)
    race
    bootstrap
    smoke
    outside_in
    backup_restore
    restore_drill
    photos
    share
    trusted
    sso
    ;;
  *)
    echo "Usage: $0 [race|bootstrap|smoke|outside-in|backup-restore|restore-drill|photos|share|trusted|sso|all]" >&2
    exit 2
    ;;
esac
