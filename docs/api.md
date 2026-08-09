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
| `DELETE` | `/api/items/{id}`         | Delete an item and its photos       |

**List query parameters** (all optional): `type`, `status`, `country`, `year`,
`year_min`/`year_max`, `tag`, `grade_min`/`grade_max` (grade rank 1–70),
`value_min`/`value_max` (latest estimate), `q` (substring match over
notes/series/country/denomination/cert numbers/catalog refs/tags), `limit`,
`offset`, `sort` (field name or `grade`, `-` prefix for descending). The list
response includes each item's primary photo/thumbnail keys and latest
estimated value.

Item payloads accept `tags` (list of names, get-or-create) and `catalog_refs`
(list of `{catalog, ref_code}`). CSV import consumes the export format;
derived columns are ignored and per-row failures are reported without
aborting the rest.

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

Estimates are append-only: each `POST .../estimates` adds a timestamped record
(`estimated_value`, `currency`, `source`, optional `confidence` 0–1), never
overwriting history. `POST .../estimate` runs the automatic adapters —
currently melt value (spot × weight × fineness × quantity, metal detected
from `composition`); it answers 422 with the missing prerequisite when an item
can't be melt-priced and 502 when no spot price is obtainable. See
[price-sources.md](price-sources.md).

## Stats

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| `GET`  | `/api/stats/collection`  | Totals in a display currency (`?currency=`)    |
| `GET`  | `/api/stats/breakdowns`  | Owned items grouped by country/type/decade/grade/tag + acquisitions by year |
| `GET`  | `/api/stats/gains`       | Per-item unrealized (owned) and realized (sold) gain/loss |

Counts by status/type, cost basis, estimated value (latest estimate per owned
item), unrealized gain (items with both price and estimate), and realized
gain (sold items). All three endpoints follow the same currency rule — no
conversion: rows in other currencies are excluded from money sums (and
reported in `excluded_other_currency` on `/collection`; breakdowns still
count such items).

The dashboard and the printable insurance report (`/report` in the UI —
export to PDF via the browser's print dialog) are built on these endpoints.

## Reference data

| Method | Path              | Purpose                                        |
|--------|-------------------|------------------------------------------------|
| `GET`  | `/api/grades`     | List grade scales and codes (`?scale=` filter) |
| `GET`  | `/api/tags`       | List tags with usage counts                    |

Grades are seeded by migration: `sheldon` for coins, `pmg` for notes. Catalog
references are managed inline on items rather than via a standalone endpoint.

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
