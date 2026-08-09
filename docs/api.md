# API

The service is titled **Cabinet API** in the OpenAPI spec.

The backend exposes a REST API under `/api/`. This document is a
human-readable summary; the authoritative, always-current spec is the
auto-generated OpenAPI documentation served at:

- Swagger UI: `http://localhost/api/docs`
- OpenAPI JSON: `http://localhost/api/openapi.json`

All request and response bodies are JSON unless noted (photo upload is
multipart). Since the app is single-user and self-hosted, endpoints are
described without an auth layer; add one before exposing the app publicly.

## Items

| Method   | Path                      | Purpose                             |
|----------|---------------------------|-------------------------------------|
| `GET`    | `/api/items`              | List items (filter/paginate)        |
| `POST`   | `/api/items`              | Create an item                      |
| `POST`   | `/api/items/import`       | Import items from CSV (multipart)   |
| `GET`    | `/api/items/export.csv`   | Export the collection as CSV        |
| `GET`    | `/api/items/export.xlsx`  | Export the collection as Excel      |
| `GET`    | `/api/items/{id}`         | Get one item with photos/estimates  |
| `PATCH`  | `/api/items/{id}`         | Update fields on an item            |
| `POST`   | `/api/items/{id}/clone`   | Duplicate an item (not its photos)  |
| `GET`    | `/api/items/{id}/history` | Edit history (created/updated diffs)|
| `POST`   | `/api/items/bulk`         | Bulk field updates + add/remove tags|
| `DELETE` | `/api/items/{id}`         | Delete an item and its photos       |

**List query parameters** (all optional): `type`, `status`, `country`, `year`,
`year_min`/`year_max`, `tag`, `set_id`, `grade_min`/`grade_max` (grade rank 1–70),
`value_min`/`value_max` (latest estimate), `q` (substring match over
notes/series/country/denomination/cert numbers/catalog refs/tags), `limit`,
`offset`, `sort` (field name or `grade`, `-` prefix for descending). The list
response includes each item's primary photo/thumbnail keys and latest
estimated value.

Item payloads accept `tags` (list of names, get-or-create) and `catalog_refs`
(list of `{catalog, ref_code}`). CSV import consumes the export format;
derived columns are ignored, rows whose `id` already exists are skipped (so
re-importing an export never duplicates the collection), and per-row failures
are reported without aborting the rest.

## Photos

| Method   | Path                              | Purpose                        |
|----------|-----------------------------------|--------------------------------|
| `GET`    | `/api/items/{id}/photos`          | List an item's photos          |
| `POST`   | `/api/items/{id}/photos`          | Upload a photo (multipart)     |
| `POST`   | `/api/items/{id}/photos/order`    | Reorder photos (full id list)  |
| `PATCH`  | `/api/photos/{photo_id}`          | Set angle / mark primary       |
| `DELETE` | `/api/photos/{photo_id}`          | Delete a photo                 |

Upload accepts a single image file plus optional `angle`. Files are validated
as real JPEG/PNG/WebP images (the declared content-type is not trusted), EXIF
orientation is corrected, and a JPEG thumbnail is generated alongside the
original. The first photo uploaded becomes the primary image. Responses
include the file keys; the files themselves are served by nginx at
`/photos/{file_key}` and `/photos/{thumb_key}`.

## Price estimates

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|------------------------------------------|
| `POST` | `/api/items/{id}/estimates`   | Record a manually researched value       |
| `GET`  | `/api/items/{id}/estimates`   | List estimate history for an item        |
| `POST` | `/api/items/{id}/estimate`    | Produce an automatic estimate            |
| `POST` | `/api/estimates/refresh-melt` | Re-run stale melt estimates now          |

Estimates are append-only: each `POST .../estimates` adds a timestamped record
(`estimated_value`, `currency`, `source`, optional `confidence` 0–1), never
overwriting history. `POST .../estimate` runs the automatic adapters —
currently melt value (spot × weight × fineness × quantity, metal detected
from `composition`); it answers 422 with the missing prerequisite when an item
can't be melt-priced and 502 when no spot price is obtainable. See
[price-sources.md](price-sources.md). An in-process scheduler re-runs stale
melt estimates every 12h (estimates older than `REESTIMATE_DAYS`, default 7;
`0` disables); a melt refresh never supersedes an item whose latest estimate
is manual.

## Stats

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| `GET`  | `/api/stats/collection`  | Totals in a display currency (`?currency=`)    |
| `GET`  | `/api/stats/breakdowns`  | Owned items grouped by country/type/decade/grade/tag + acquisitions by year |
| `GET`  | `/api/stats/gains`       | Per-item unrealized (owned) and realized (sold) gain/loss |
| `GET`  | `/api/stats/value-history` | Month-end collection value over time (`?months=`) |

Counts by status/type, cost basis, estimated value (latest estimate per owned
item), unrealized gain (items with both price and estimate), and realized
gain (sold items). All stats endpoints share one currency rule: amounts in
other currencies are **converted** into the display currency at cached daily
ECB rates (frankfurter.dev, 24h cache, stale fallback); amounts with no
obtainable rate are **excluded** and counted — never guessed
(`converted_other_currency` / `excluded_other_currency` on `/collection`).

The dashboard and the printable insurance report (`/report` in the UI —
export to PDF via the browser's print dialog) are built on these endpoints.

## Reference data

| Method   | Path                | Purpose                                        |
|----------|---------------------|------------------------------------------------|
| `GET`    | `/api/grades`       | List grade scales and codes (`?scale=` filter) |
| `GET`    | `/api/tags`         | List tags with usage counts                    |
| `GET`    | `/api/sets`         | List sets/lots with item counts                |
| `POST`   | `/api/sets`         | Create a set (409 on duplicate name)           |
| `PATCH`  | `/api/sets/{id}`    | Rename / edit a set                            |
| `DELETE` | `/api/sets/{id}`    | Delete a set (items are detached, not deleted) |

Grades are seeded by migration: `sheldon` for coins, `pmg` for notes. Catalog
references are managed inline on items rather than via a standalone endpoint.

## Settings

| Method | Path             | Purpose                                          |
|--------|------------------|--------------------------------------------------|
| `GET`  | `/api/settings`  | App settings + source status + cached market data|
| `PUT`  | `/api/settings`  | Partial update                                   |

Settings cover the app-wide display currency (used by all stats endpoints
unless `?currency=` overrides), the melt refresh cadence (DB override of the
`REESTIMATE_DAYS` env var; takes effect without restart), source toggles, and
source credentials (Numista API key, PCGS token). **Secrets are write-only and
encrypted at rest**: reads return only a configured flag and a last-4 hint,
never the value, and stored credentials are Fernet-encrypted before they reach
the database. See [security.md](security.md).

## Checklists (completeness tracking)

| Method   | Path                                    | Purpose                     |
|----------|-----------------------------------------|-----------------------------|
| `GET`    | `/api/checklists`                       | List with filled/total      |
| `POST`   | `/api/checklists`                       | Create with a slot list     |
| `GET`    | `/api/checklists/{id}`                  | Detail with slots           |
| `PATCH`  | `/api/checklists/{id}/slots/{slot_id}`  | Check/uncheck or link item  |
| `DELETE` | `/api/checklists/{id}`                  | Delete a checklist          |

## Health

| Method | Path           | Purpose                             |
|--------|----------------|-------------------------------------|
| `GET`  | `/api/health`  | Liveness/readiness probe            |

## Conventions

- **Timestamps** are ISO 8601 UTC (`timestamptz`).
- **Money** fields carry an explicit ISO 4217 `currency` alongside the amount.
- **IDs** are UUIDs for items/photos/estimates; reference tables use integers.
- **Errors** follow a consistent JSON shape: `{ "detail": "..." }`, matching
  FastAPI defaults, with appropriate HTTP status codes.
