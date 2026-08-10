# Screenshots

These illustrate the README and the GitHub project page. They are not used by
the application.

## Capturing or refreshing them

1. Start a clean stack and load the demo collection, so no real holdings are
   shown:

   ```bash
   docker compose down -v && docker compose up --build -d
   docker compose exec backend alembic upgrade head
   python scripts/seed_demo.py
   ```

2. Set the browser window to **1280×800** and capture the viewport (not the
   full page) for consistent framing.

3. Save as PNG with these names, which the README expects:

   | File | Page | Notes |
   |------|------|-------|
   | `collection.png` | `/` | The list with the stats strip and a couple of filters set |
   | `dashboard.png` | `/dashboard` | Scrolled to show the hero value, tiles, and charts |
   | `item-detail.png` | `/items/<id>` | Pick an item with photos, a grade, and value history |
   | `dark-mode.png` | `/dashboard` | Same view with the theme toggle on |

4. Keep each file under ~400 KB (PNG, 8-bit palette is usually enough).

Upload a couple of real photos to one demo item before capturing
`item-detail.png` — the empty photo grid undersells the feature.
