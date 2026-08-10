# Screenshots

These illustrate the README. They are not used by the application.

| File | Page | Theme |
|------|------|-------|
| `collection.png` | `/` | light |
| `dashboard.png` | `/dashboard` | light |
| `item-detail.png` | `/items/<id>` | light |
| `dark-mode.png` | `/dashboard` | dark |

## Regenerating them

Captured headlessly so the result doesn't depend on your desktop theme, OS
font rendering, or window chrome. Start a clean stack with demo data:

```bash
docker compose down -v && docker compose up --build -d
docker compose exec backend alembic upgrade head
python scripts/seed_demo.py
```

Then capture at a fixed 1280×800 with Playwright, joining the compose network
so the proxy is reachable as `proxy`:

```bash
ITEM=$(curl -s 'http://localhost/api/items?limit=100' \
  | python3 -c 'import json,sys; print(next(i["id"] for i in json.load(sys.stdin)["items"] if i["grade"] and i["latest_value"]))')

docker run --rm --network cabinet-numismatics_default \
  -v "$PWD/docs/screenshots:/out" \
  mcr.microsoft.com/playwright:v1.49.0-jammy sh -c "
    P='npx -y playwright@1.49.0 screenshot --viewport-size=1280,800 --wait-for-timeout=4000'
    \$P --color-scheme=light http://proxy/                 /out/collection.png
    \$P --color-scheme=light http://proxy/dashboard        /out/dashboard.png
    \$P --color-scheme=light http://proxy/items/$ITEM      /out/item-detail.png
    \$P --color-scheme=dark  http://proxy/dashboard        /out/dark-mode.png
  "
```

Pin the `playwright@` version to match the image tag — `npx` otherwise
installs the newest release, which then can't find the image's browsers.

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
