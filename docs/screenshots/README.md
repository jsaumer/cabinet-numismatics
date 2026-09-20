# Screenshots

These illustrate the README. They are not used by the application. Every
page is captured twice, dark first because dark is Cabinet's default:

| Files | Page |
|-------|------|
| `dashboard-dark.png`, `dashboard-light.png` | `/` |
| `collection-dark.png`, `collection-light.png` | `/collection` |
| `item-detail-dark.png`, `item-detail-light.png` | `/items/<id>` |
| `settings-dark.png`, `settings-light.png` | `/settings` |

The Settings pair is captured straight off the demo seed with no
price-source keys configured, so both Numista and PCGS show "(not
configured)" and no `secret_hint`. If you ever capture it with a key
actually saved, double-check the image doesn't show the masked hint before
committing it; a fake, obviously-non-functional key (e.g.
`demo-key-not-real`) is the safe way to show that state.

## Regenerating them

Captured headlessly by `capture.cjs`, so the result doesn't depend on your
desktop theme, OS font rendering, or window chrome. Start a clean stack
with demo data:

```bash
docker compose down -v && docker compose up --build -d
python scripts/seed_demo.py
```

The captures run in the Playwright image, joined to the compose network so
the proxy is reachable as `proxy`. `frontend/node_modules` must hold
`@playwright/test` (`npm ci` in `frontend/`, or the same image running it).
The image has no Calibri, so the command installs Carlito, its
metric-compatible twin, which Cabinet's font stack names second:

```bash
shoot() {
  MSYS_NO_PATHCONV=1 docker run --rm --network cabinet-numismatics_default \
    -v "$PWD/frontend:/app" -v "$PWD/docs/screenshots:/out" \
    mcr.microsoft.com/playwright:v1.63.0-noble sh -c \
    "apt-get update -qq && apt-get install -y -qq fonts-crosextra-carlito >/dev/null && node /out/capture.cjs $*"
}
```

Capture Settings first, while nothing is configured:

```bash
shoot settings
```

Then satisfy the dashboard's setup checklist so it doesn't crowd out the
value hero, with daily backups plus one run, a placeholder webhook, and the
fake key (never a real one), and capture the rest:

```bash
curl -fsS -X PUT http://localhost/api/settings -H 'Content-Type: application/json' \
  -d '{"backup_schedule":"daily","alert_webhook_url":"https://ntfy.example/cabinet","numista_api_key":"demo-key-not-real"}'
curl -fsS -X POST http://localhost/api/backups

ITEM=$(curl -s 'http://localhost/api/items?limit=100' \
  | python3 -c 'import json,sys; print(next(i["id"] for i in json.load(sys.stdin)["items"] if i["grade"] and i["latest_value"]))')
shoot rest "$ITEM"
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
