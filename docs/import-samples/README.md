# Import samples

Synthetic files in the formats Cabinet imports (v0.18.0), for trying the
Import page (Collection → Import → *A file from another tool*) without data
of your own. None of it is anyone's real collection: the files are generated
from each format's published layout by `backend/tests/import_samples.py`,
which the tests use too. Regenerate them with:

```bash
cd backend && python -m tests.import_samples ../docs/import-samples
```

| File | Format | What it exercises |
|---|---|---|
| `opennumismat-1.10.db` | OpenNumismat, schema 10 | purchase and sale on the coins table, JPEG photos, statuses owned / sold / wish / lost at auction, a banknote, a record without a year |
| `opennumismat-1.11.db` | OpenNumismat, schema 11 | the `prices` table OpenNumismat 1.11 introduced, WebP photos, a purchase in EUR |
| `numista-export.csv`, `.xlsx` | numista.com collection export | column names from a real export; an AH-dated coin, an undated one, a banknote with a serial |
| `hand-kept-sheet.csv` | a spreadsheet | "$1,250.00" prices, month-first dates, grades written as MS63 and BU, a row with no year |
| `colnect-style.csv` | a spreadsheet | lines above the header row. Colnect's real column names vary by language and couldn't be confirmed, so this only illustrates the layout |

Import them into a test instance (the local `docker compose` stack), not the
collection you care about, because the items are fictional.
