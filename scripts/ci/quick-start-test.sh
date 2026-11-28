#!/usr/bin/env bash
# Walks the README's quick start the way a newcomer would, so a change that
# breaks a first run fails here instead of in someone's living room:
#
#   1. deploy/docker-compose.yaml in an empty folder with nothing set but
#      DB_PASSWORD, then the setup code read from the log, the instance
#      claimed at http://localhost, the backup key printed, and the two host
#      scripts run from a `scripts` folder beside the file;
#   2. an address Cabinet wasn't told to expect gets the plain "not at this
#      address" page (421), never the app and never an empty reply;
#   3. the same stack moved to a LAN name over plain http: the name works,
#      sign-in works, and the old address gets the page;
#   4. an https address: the backend stops with a message naming the one
#      setting to change, then starts with it changed and sets Secure cookies;
#   5. .env.example, copied unchanged, beside the repository's own
#      docker-compose.yaml.
#
# Nothing is built: the images named by TAG are used as they are (CI builds
# them from the commit under test first; with TAG unset and no local image,
# Compose pulls the published `latest`). Each stack is its own throwaway
# project in its own temporary folder, torn down at the end; pass
# KEEP_STACKS=1 to leave them up for a look.
#
# Usage: scripts/ci/quick-start-test.sh
#
# Environment:
#   QUICK_START_PORT   Port to publish (default 80, which is what the README's
#                      first run uses; another port also sets PUBLIC_ORIGINS
#                      to match, since the two have to agree)
#   TAG                Image tag (default latest)
#   KEEP_STACKS        Set to 1 to skip the teardown

set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=$PWD

PORT="${QUICK_START_PORT:-80}"
PASSWORD="correct horse battery"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cabinet-quick-start.XXXXXX")"
FIRST="$WORK/cabinet"          # the pull-and-run file, as the README has it
EXAMPLE="$WORK/from-source"    # .env.example beside the repository's file
mkdir -p "$FIRST" "$EXAMPLE"

# The CI stack job exports COMPOSE_FILE for its own stack; each stack here is
# the one file in its own folder.
unset COMPOSE_FILE COMPOSE_PROJECT_NAME

if python3 -c '' >/dev/null 2>&1; then PY=python3; else PY=python; fi

first() { (cd "$FIRST" && docker compose -p cabinet-quick-start "$@"); }
example() { (cd "$EXAMPLE" && docker compose -p cabinet-quick-example "$@"); }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "== quick start test FAILED; backend log follows =="
    first logs --tail 40 backend 2>/dev/null || true
    example logs --tail 40 backend 2>/dev/null || true
  fi
  if [ "${KEEP_STACKS:-0}" != "1" ]; then
    first down -v >/dev/null 2>&1 || true
    example down -v >/dev/null 2>&1 || true
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf -- "$WORK"; fi
  else
    echo "left running; folders under $WORK"
  fi
  exit "$status"
}
trap cleanup EXIT

# wait_for <url> [curl options]: health answers within 90 seconds.
wait_for() {
  local url=$1; shift
  for i in $(seq 1 90); do
    if curl -fsS "$@" "$url" >/dev/null 2>&1; then
      echo "   answering after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "   never answered: $url" >&2
  return 1
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# Output is written to a file and the file searched, never piped into
# `grep -q`: grep leaves at the first match, the writer dies of SIGPIPE, and
# under `pipefail` a match then reads as a failure.
backend_log() {  # backend_log <first|example>: that stack's backend log, as a file
  "$1" logs backend > "$WORK/backend.log" 2>&1 || true
  echo "$WORK/backend.log"
}
body_of() {  # body_of <curl args...>: the response body, as a file
  curl -s -o "$WORK/body" "$@" || true
  echo "$WORK/body"
}
# never <what> <command...>: fails when the command succeeds. (A bare
# `! command` is exempt from `set -e`, so it would assert nothing.)
never() {
  local what=$1; shift
  if "$@" >/dev/null 2>&1; then
    echo "   unexpected: $what" >&2
    exit 1
  fi
}

if [ "$PORT" = "80" ]; then HERE="http://localhost"; else HERE="http://localhost:$PORT"; fi

# --- 1. the pull-and-run file, nothing set but the database password ---------
echo "== 1. deploy/docker-compose.yaml in an empty folder =="
cp "$REPO/deploy/docker-compose.yaml" "$FIRST/"
echo "DB_PASSWORD=$(openssl rand -hex 16)" > "$FIRST/.env"
if [ "$PORT" != "80" ]; then
  # Off port 80 the address changes, so it has to be said (the README's
  # "on a server" lines); on 80 this file holds the password and nothing else.
  printf 'CABINET_PORT=%s\nPUBLIC_ORIGINS=%s\n' "$PORT" "$HERE" >> "$FIRST/.env"
fi
first up -d
wait_for "$HERE/api/health"
grep -q '"setup_required":true' "$(body_of "$HERE/api/auth/state")"
test "$(status_of "$HERE/")" = 200

# The README's own line for the setup code.
code_line="$(grep "setup code" "$(backend_log first)" | tail -1)"
code="${code_line##*setup code: }"
code="${code%%[[:space:]]*}"
test "${#code}" -ge 32
claim() {  # claim <origin> [curl options]
  local origin=$1; shift
  curl -s -o /dev/null -w '%{http_code}' "$@" -c "$WORK/jar" \
    -H "Origin: $origin" -H 'Content-Type: application/json' \
    -X POST "$origin/api/auth/setup" \
    -d "{\"code\":\"$code\",\"username\":\"owner\",\"password\":\"$PASSWORD\"}"
}
test "$(claim "$HERE")" = 201
grep -q '"schema"' "$(body_of -b "$WORK/jar" -H "Origin: $HERE" "$HERE/api/health")"
echo "   claimed at $HERE with the code from the log"

# The README's third step: the backup key comes from the container, since
# the browser never shows it.
first exec -T backend python -m app.cli backup-key show > "$WORK/key.out" 2>&1
grep -q '^AGE-SECRET-KEY-1' "$WORK/key.out"
rm -f "$WORK/key.out"
# And its host scripts, in a `scripts` folder beside the one file: a backup,
# then that archive restored. (They run plain `docker compose` from the
# folder, so the project this test started the stack under is named here.)
mkdir "$FIRST/scripts"
cp "$REPO/scripts/backup.sh" "$REPO/scripts/restore.sh" "$FIRST/scripts/"
chmod +x "$FIRST/scripts/backup.sh" "$FIRST/scripts/restore.sh"
beside() { (cd "$FIRST" && COMPOSE_PROJECT_NAME=cabinet-quick-start "$@"); }
beside ./scripts/backup.sh > "$WORK/backup.out" 2>&1
archive="$(cd "$FIRST" && ls backups/cabinet-backup-*.zip.age)"
never "a restore by the archive's bare name" beside ./scripts/restore.sh "${archive#backups/}"
beside ./scripts/restore.sh "$archive" > "$WORK/restore.out" 2>&1
grep -q '^Restored from' "$WORK/restore.out"
wait_for "$HERE/api/health"
echo "   the backup key printed; backup.sh and restore.sh ran from beside the file"

# --- 2. an address it wasn't told to expect ----------------------------------
echo "== 2. a wrong address gets a page that says so =="
wrong() { curl -s -H 'Host: 192.168.1.50' "$@"; }
test "$(wrong -o /dev/null -w '%{http_code}' "$HERE/")" = 421
grep -q 'PUBLIC_ORIGINS' "$(body_of -H 'Host: 192.168.1.50' "$HERE/")"
# Nothing of the app is reachable under it: no API, no photo, no sign-in.
test "$(wrong -o /dev/null -w '%{http_code}' "$HERE/api/health")" = 421
test "$(wrong -o /dev/null -w '%{http_code}' -X POST "$HERE/api/auth/login")" = 421
test "$(wrong -o /dev/null -w '%{http_code}' "$HERE/photos/x.jpg")" = 421
wrong -D "$WORK/wrong.headers" -o "$WORK/wrong.html" "$HERE/"
never "a cookie set on the wrong-address page" grep -qi '^set-cookie' "$WORK/wrong.headers"
never "the Host echoed in the page" grep -q '192.168.1.50' "$WORK/wrong.html"
echo "   421 with the two settings named, nothing proxied"

# --- 3. a LAN name over plain http ------------------------------------------
echo "== 3. the same stack at a LAN name, plain http =="
LAN_HOST="nas.home.arpa"
if [ "$PORT" = "80" ]; then LAN="http://$LAN_HOST"; else LAN="http://$LAN_HOST:$PORT"; fi
grep -v '^PUBLIC_ORIGINS=' "$FIRST/.env" > "$FIRST/.env.next" && mv "$FIRST/.env.next" "$FIRST/.env"
echo "PUBLIC_ORIGINS=$LAN" >> "$FIRST/.env"
first up -d
resolve=(--resolve "$LAN_HOST:$PORT:127.0.0.1")
wait_for "$LAN/api/health" "${resolve[@]}"
login() {  # login <origin> [curl options]: prints the response headers
  local origin=$1; shift
  curl -s -D - -o /dev/null "$@" -H "Origin: $origin" -H 'Content-Type: application/json' \
    -X POST "$origin/api/auth/login" \
    -d "{\"username\":\"owner\",\"password\":\"$PASSWORD\"}"
}
login "$LAN" "${resolve[@]}" > "$WORK/lan.headers"
grep -q '^HTTP/1.1 200' "$WORK/lan.headers"
grep -i '^set-cookie: cabinet_session=' "$WORK/lan.headers" > "$WORK/lan.cookie"
never "a Secure cookie over plain http" grep -qi 'secure' "$WORK/lan.cookie"
# The address it used to answer is now the wrong one.
test "$(status_of "$HERE/")" = 421
echo "   signed in at $LAN; $HERE now gets the page"

# --- 4. an https address ------------------------------------------------------
echo "== 4. an https address =="
HTTPS_HOST="cabinet.home.arpa"
grep -v '^PUBLIC_ORIGINS=' "$FIRST/.env" > "$FIRST/.env.next" && mv "$FIRST/.env.next" "$FIRST/.env"
echo "PUBLIC_ORIGINS=https://$HTTPS_HOST" >> "$FIRST/.env"
first up -d
# The plain-http cookie setting is still at its default, so the backend
# refuses to start and says which setting to change.
refused=0
for i in $(seq 1 45); do
  if grep -q 'AUTH_INSECURE_HTTP=false' "$(backend_log first)"; then refused=1; break; fi
  sleep 1
done
test "$refused" = 1
echo "   refused to start, naming AUTH_INSECURE_HTTP=false"
echo "AUTH_INSECURE_HTTP=false" >> "$FIRST/.env"
first up -d
# No reverse proxy here: the proxy is asked by name, as one would ask it.
wait_for "$HERE/api/health" -H "Host: $HTTPS_HOST"
curl -s -D "$WORK/https.headers" -o /dev/null -H "Host: $HTTPS_HOST" \
  -H "Origin: https://$HTTPS_HOST" -H 'Content-Type: application/json' \
  -X POST "$HERE/api/auth/login" \
  -d "{\"username\":\"owner\",\"password\":\"$PASSWORD\"}"
grep -q '^HTTP/1.1 200' "$WORK/https.headers"
grep -i '^set-cookie: __Host-cabinet_session=' "$WORK/https.headers" > "$WORK/https.cookie"
grep -qi 'secure' "$WORK/https.cookie"
echo "   started with it changed; the session cookie is Secure"
first down -v >/dev/null 2>&1

# --- 5. .env.example, unchanged, with the repository's own Compose file ------
echo "== 5. .env.example beside docker-compose.yaml =="
cp "$REPO/docker-compose.yaml" "$EXAMPLE/"
cp "$REPO/.env.example" "$EXAMPLE/.env"
if [ "$PORT" != "80" ]; then
  # The shell wins over .env, so the copied file itself stays unchanged.
  export CABINET_PORT="$PORT" PUBLIC_ORIGINS="$HERE,http://proxy"
fi
example up -d --no-build
wait_for "$HERE/api/health"
grep -q '"setup_required":true' "$(body_of "$HERE/api/auth/state")"
grep -q "setup code" "$(backend_log example)"
echo "   up and waiting to be claimed"

echo "quick start test passed"
