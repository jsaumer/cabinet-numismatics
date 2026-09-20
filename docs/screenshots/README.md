# Screenshots

These illustrate the README. They are not used by the application.

| File | Page | Theme |
|------|------|-------|
| `collection.png` | `/collection` | light |
| `dashboard.png` | `/` | light |
| `item-detail.png` | `/items/<id>` | light |
| `settings.png` | `/settings` | light |
| `dark-mode.png` | `/` | dark |

`settings.png` is captured straight off the demo seed with no price-source
keys configured, so both Numista and PCGS show "(not configured)" and no
`secret_hint`. If you ever capture it with a key actually saved, double-check
the image doesn't show the masked hint before committing it; a fake,
obviously-non-functional key (e.g. `demo-key-not-real`) is the safe way to
show that state.

## Regenerating them

Captured headlessly so the result doesn't depend on your desktop theme, OS
font rendering, or window chrome. Start a clean stack with demo data:

```bash
docker compose down -v && docker compose up --build -d
docker compose exec backend alembic upgrade head
python scripts/seed_demo.py
```

Capture `settings.png` first, while nothing is configured. Then satisfy the
dashboard's setup checklist so it doesn't crowd out the value hero in the two
dashboard shots, with daily backups plus one run, a placeholder webhook, and
the fake key (never a real one):

```bash
curl -fsS -X PUT http://localhost/api/settings -H 'Content-Type: application/json' \
  -d '{"backup_schedule":"daily","alert_webhook_url":"https://ntfy.example/cabinet","numista_api_key":"demo-key-not-real"}'
curl -fsS -X POST http://localhost/api/backups
```

Then capture at a fixed 1280×800 with Playwright, joining the compose network
so the proxy is reachable as `proxy`:

```bash
ITEM=$(curl -s 'http://localhost/api/items?limit=100' \
  | python3 -c 'import json,sys; print(next(i["id"] for i in json.load(sys.stdin)["items"] if i["grade"] and i["latest_value"]))')

MSYS_NO_PATHCONV=1 docker run --rm --network cabinet-numismatics_default \
  -v "$PWD/docs/screenshots:/out" \
  mcr.microsoft.com/playwright:v1.63.0-noble sh -c "
    P='npx -y playwright@1.63.0 screenshot --viewport-size=1280,800 --wait-for-timeout=4000'
    \$P --color-scheme=light http://proxy/collection       /out/collection.png
    \$P --color-scheme=light http://proxy/                 /out/dashboard.png
    \$P --color-scheme=light http://proxy/items/$ITEM      /out/item-detail.png
    \$P --color-scheme=light http://proxy/settings         /out/settings.png
    \$P --color-scheme=dark  http://proxy/                 /out/dark-mode.png
  "
```

Pin the `playwright@` version to match the image tag (and keep it at the
`@playwright/test` version in `frontend/package.json`, so the browser tests and
the screenshots use one browser build), because `npx` otherwise
installs the newest release, which then can't find the image's browsers.
`MSYS_NO_PATHCONV=1` matters if you're running this from Git Bash on
Windows: without it, MSYS rewrites the container-side `/out` path as if it
were a Windows path too, silently breaking the bind mount. The container
reports every capture as successful, but nothing lands on the host.

## Notes

- Playwright's `--color-scheme` is what makes the light/dark pair reliable.
  Chromium's command line has no equivalent flag, so plain headless Chrome
  silently inherits the host's theme and both captures come out identical.
- The demo items have no photos, so `item-detail.png` shows an empty photo
  section. Upload two images to that item before capturing if you want the
  photo grid represented.
- The value-over-time chart needs estimates recorded on different days;
  freshly seeded demo data is all one day, so that card shows its
  single-data-point message.
