# Screenshots

These illustrate the README. They are not used by the application. Every
page is captured twice, dark first because dark is Cabinet's default:

| Files | Page |
|-------|------|
| `signin-dark.png`, `signin-light.png` | `/login`, signed out |
| `dashboard-dark.png`, `dashboard-light.png` | `/` |
| `collection-dark.png`, `collection-light.png` | `/collection` |
| `item-detail-dark.png`, `item-detail-light.png` | `/items/<id>` |
| `settings-general-dark.png`, `settings-general-light.png` | `/settings/general` |

Settings is routed into sections (v0.30.2); General is the one shown
(the Backups section on a default Compose stack carries the red
"cannot tell where your backup key is stored" notice, which is true there
and misleading in a screenshot). Check every shot for a token secret, a
setup code, or a real API key before committing it.

## Regenerating them

Captured headlessly by `capture.cjs`, so the result doesn't depend on your
desktop theme, OS font rendering, or window chrome. Cabinet needs a sign-in
(v0.30.0), and the whole point of a clean set of screenshots is a clean,
throwaway stack, so do this on its own compose project and port, never the
one you use for day-to-day manual testing: `down -v` on a project you're
using elsewhere would erase it. `-p cabinet-shots` below is that throwaway
project name; pick a port nothing else on your machine is using.

`http://localhost` (bare, no port) is in `PUBLIC_ORIGINS` alongside the
published `http://localhost:8090` because `capture.cjs` reaches the stack
that way too, on the compose network's own port 80, not 8090: see the note
in `capture.cjs` about why (in short, `localhost` is the one hostname
Chromium always treats as a secure context, which the published port isn't
part of).

```bash
export PUBLIC_ORIGINS=http://localhost:8090,http://localhost,http://proxy
export ALLOWED_HOSTS=localhost,proxy
export AUTH_INSECURE_HTTP=true
export SETUP_CODE=$(python -c 'import secrets; print(secrets.token_hex(16))')
export CABINET_PORT=8090
docker compose -p cabinet-shots up --build -d
```

Claim the fresh stack and mint a write-scoped token with
`scripts/ci/stack-smoke.sh` (see [CONTRIBUTING.md](../../CONTRIBUTING.md)
for what its phases do); it keeps the session cookie jar and the token
together in one state folder, which the rest of these steps reuse:

```bash
BASE=http://localhost:8090 STACK_SMOKE_STATE=/tmp/cabinet-shots-smoke \
  scripts/ci/stack-smoke.sh bootstrap
. /tmp/cabinet-shots-smoke/tokens.env
COOKIES=/tmp/cabinet-shots-smoke/cookies.txt
```

Seed the demo collection. `scripts/seed_demo.py` needs only the standard
library, so any working Python 3 does (on Windows, `python3` is often a
non-functional Microsoft Store stub; use `python` if `python3 --version`
doesn't print a real version). Running it inside the backend container
works just as well if you'd rather not rely on a host interpreter:

```bash
python scripts/seed_demo.py --base-url http://localhost:8090 --token "$WRITE_TOKEN"
# or: docker compose -p cabinet-shots exec -T -e CABINET_TOKEN="$WRITE_TOKEN" backend \
#       python - --base-url http://localhost:8000 < scripts/seed_demo.py
```

The captures run in the Playwright image, joined to the throwaway project's
own compose network (`cabinet-shots_default`, not the main stack's) so the
proxy is reachable as `proxy`. `frontend/node_modules` must hold
`@playwright/test` (`npm ci` in `frontend/`, or the same image running it).
The image has no Calibri, so the command installs Carlito, its
metric-compatible twin, which Cabinet's font stack names second. `capture.cjs`
signs in through the sign-in form itself (`CABINET_USER`/`CABINET_PASSWORD`,
defaults `owner` / `correct horse battery`, matching the account
`stack-smoke.sh bootstrap` just claimed), so the shots need no session
handed to them:

```bash
shoot() {
  MSYS_NO_PATHCONV=1 docker run --rm --network cabinet-shots_default \
    -v "$PWD/frontend:/app" -v "$PWD/docs/screenshots:/out" \
    -e CABINET_USER=owner -e CABINET_PASSWORD='correct horse battery' \
    mcr.microsoft.com/playwright:v1.63.0-noble sh -c \
    "apt-get update -qq && apt-get install -y -qq fonts-crosextra-carlito >/dev/null && node /out/capture.cjs $*"
}
```

Capture the sign-in page (nothing to configure first, since it's shown
signed out):

```bash
shoot signin
```

Then satisfy the dashboard's setup checklist so it doesn't crowd out the
value hero, with daily backups plus one run, a placeholder webhook, the fake
key (never a real one), and the "I have saved my backup key" tick. Most of
this changes settings, so it goes through the signed-in session, with the
password confirmed first, the same as the app itself does for any
`PUT /api/settings` (see "Recent password" in
[docs/api.md](../api.md#sign-in-and-permissions)); the key-saved tick is
admin but not a fresh route, so it needs no confirm, just the cookie jar and
`Origin`:

```bash
curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: http://localhost:8090" \
  -X POST http://localhost:8090/api/auth/confirm -H 'Content-Type: application/json' \
  -d '{"password":"correct horse battery"}'
curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: http://localhost:8090" \
  -X PUT http://localhost:8090/api/settings -H 'Content-Type: application/json' \
  -d '{"backup_schedule":"daily","alert_webhook_url":"https://ntfy.example/cabinet","numista_api_key":"demo-key-not-real"}'
curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: http://localhost:8090" \
  -X POST http://localhost:8090/api/backups
curl -fsS -b "$COOKIES" -c "$COOKIES" -H "Origin: http://localhost:8090" \
  -X POST http://localhost:8090/api/backups/key/saved

ITEM=$(curl -fsS -b "$COOKIES" -H "Origin: http://localhost:8090" \
  'http://localhost:8090/api/items?limit=100' \
  | python -c 'import json,sys; print(next(i["id"] for i in json.load(sys.stdin)["items"] if i["grade"] and i["latest_value"]))')
shoot settings
shoot rest "$ITEM"
```

Tear the throwaway project down once you have what you need:

```bash
docker compose -p cabinet-shots down -v
```

Keep the image tag at the `@playwright/test` version in
`frontend/package.json`, so the browser tests and the screenshots use one
browser build. `MSYS_NO_PATHCONV=1` matters if you're running this from Git
Bash on Windows: without it, MSYS rewrites the container-side paths as if
they were Windows paths too, silently breaking the bind mounts.

## Notes

- Cabinet keeps the chosen theme in `localStorage` and defaults to dark, so
  `capture.cjs` sets that key for each pass; a browser's colour-scheme
  preference has no effect.
- The demo items have no photos, so the item page shows an empty photo
  section. Upload two images to that item before capturing if you want the
  photo grid represented.
- The value-over-time chart needs estimates recorded on different days;
  freshly seeded demo data is all one day, so that card shows its
  single-data-point message.
- Never point any of this at your main development stack. `bootstrap`'s
  claim step only works once per stack anyway (a claimed stack signs in
  instead), but the settings and backup calls above are real writes, and
  they belong on the throwaway project, not one you rely on.
