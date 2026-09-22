#!/usr/bin/env bash
# Proves a database from v0.29.1 (the last release with no sign-in) upgrades
# cleanly to the images built from this commit: both migration chains reach
# head and existing data survives. docs/specs/SPEC_0300.md section 9,
# "Upgrade test".
#
# Usage: scripts/ci/upgrade-test.sh
# Run from anywhere; always operates from the repository root. Always talks
# to a throwaway compose project (COMPOSE_PROJECT_NAME below), never the
# main "cabinet-numismatics" one: it passes -p explicitly to every command
# so it can't collide with a stack already running under the default
# project name. The script itself never reads or writes .env, but docker
# compose does: the database settings (DB_USER, DB_PASSWORD, DB_NAME) come
# from a .env beside docker-compose.yaml, so one must exist (CI writes a
# throwaway one first). The v0.30.0 settings are exported into this shell
# only (docker compose prefers shell values over .env), so a real .env is
# never changed.
#
# Leaves the throwaway stack running when it finishes (or fails) so its
# state can be inspected; tear it down yourself when you're done:
#   docker compose -p "$COMPOSE_PROJECT_NAME" down -v
#
# Environment:
#   COMPOSE_PROJECT_NAME  Throwaway compose project name (default cabinet-upgrade)
#   CABINET_PORT          Port the proxy publishes (default 8082)
#   SETUP_CODE            32+ hex characters, used to claim the upgraded
#                          stack (default a fixed value shared with CI)
#   CABINET_USER           Admin username to claim with (default owner)
#   CABINET_PASSWORD       Admin password to claim with (default "correct horse battery")

set -euo pipefail
cd "$(dirname "$0")/../.."

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cabinet-upgrade}"
export CABINET_PORT="${CABINET_PORT:-8082}"
export PUBLIC_ORIGINS="http://localhost:${CABINET_PORT}"
export ALLOWED_HOSTS="localhost"
export AUTH_INSECURE_HTTP=true
export SETUP_CODE="${SETUP_CODE:-5f8a2c9e1b7d4063a9e2f5c8b1d7e4a0}"

BASE="http://localhost:${CABINET_PORT}"
CABINET_USER="${CABINET_USER:-owner}"
CABINET_PASSWORD="${CABINET_PASSWORD:-correct horse battery}"

if python3 -c '' >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
field() { "$PY" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

wait_for_health() {
  for i in $(seq 1 60); do
    if curl -fsS "$BASE/api/health" >/dev/null 2>&1; then
      echo "healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "backend never became healthy"
  docker compose -p "$COMPOSE_PROJECT_NAME" logs
  exit 1
}

echo "== project $COMPOSE_PROJECT_NAME, port $CABINET_PORT =="

echo "== starting v0.29.1 from GHCR (no sign-in in that release) =="
TAG=0.29.1 docker compose -p "$COMPOSE_PROJECT_NAME" up -d
wait_for_health
old_health=$(curl -fsS "$BASE/api/health")
echo "v0.29.1 health: $old_health"
echo "$old_health" | grep -q '"status":"ok"'
if echo "$old_health" | grep -q '"setup_required"\|reauth_required'; then
  echo "v0.29.1 answered something sign-in shaped; it should be fully open" >&2
  exit 1
fi

echo "== creating an item anonymously (v0.29.1 has no auth) =="
id=$(curl -fsS -X POST "$BASE/api/items" -H 'Content-Type: application/json' \
  -d '{"type":"coin","country":"Upgrade test","denomination":"1 test","year":2026}' | field id)
echo "item $id created on v0.29.1"

echo "== switching to the images built from this commit =="
docker compose -p "$COMPOSE_PROJECT_NAME" up --build -d
wait_for_health

echo "== claiming the upgraded stack =="
required=$(curl -fsS "$BASE/api/auth/state" | field setup_required)
if [ "$required" != "True" ]; then
  echo "the upgraded stack did not ask for setup; expected setup_required: true" >&2
  exit 1
fi
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT
curl -fsS -c "$COOKIES" -b "$COOKIES" -X POST "$BASE/api/auth/setup" \
  -H 'Content-Type: application/json' -H "Origin: $BASE" \
  -d "{\"code\":\"$SETUP_CODE\",\"username\":\"$CABINET_USER\",\"password\":\"$CABINET_PASSWORD\"}" \
  -o /dev/null -w 'claimed as %{http_code}\n'

echo "== checking both schemas reached head, and the item survived =="
health=$(curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$BASE/api/health")
echo "$health" | "$PY" -c '
import json, sys
body = json.load(sys.stdin)
schema = body["schema"]
auth_schema = body["auth_schema"]
print("schema:", schema)
print("auth_schema:", auth_schema)
assert schema["status"] == "ok", f"collection schema not at head: {schema}"
assert auth_schema["status"] == "ok", f"auth schema not at head: {auth_schema}"
'
curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: $BASE" "$BASE/api/items/$id" \
  | grep -q "\"id\":\"$id\""

echo "upgrade test passed: v0.29.1 database migrated to this commit's schema, item $id intact"
