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

| Method   | Path                      | Purpose                            |
|----------|---------------------------|------------------------------------|
| `GET`    | `/api/items`              | List items (filter/paginate)       |
| `POST`   | `/api/items`              | Create an item                     |
| `GET`    | `/api/items/export.csv`   | Export the collection as CSV       |
| `GET`    | `/api/items/{id}`         | Get one item with photos/estimates |
| `PATCH`  | `/api/items/{id}`         | Update fields on an item           |
| `DELETE` | `/api/items/{id}`         | Delete an item and its photos      |

**List query parameters** (all optional): `type`, `country`, `year`, `q`
(substring match over notes/series/country/denomination), `limit`, `offset`,
`sort` (field name, `-` prefix for descending; e.g. `-year`). A `grade` filter
arrives with grading in Phase 2. The list response includes each item's
primary photo key and latest estimated value.

## Photos

| Method   | Path                              | Purpose                     |
|----------|-----------------------------------|-----------------------------|
| `GET`    | `/api/items/{id}/photos`          | List an item's photos       |
| `POST`   | `/api/items/{id}/photos`          | Upload a photo (multipart)  |
| `PATCH`  | `/api/photos/{photo_id}`          | Set angle / mark primary    |
| `DELETE` | `/api/photos/{photo_id}`          | Delete a photo              |

Upload accepts a single image file plus optional `angle`. The backend writes
the original to the photo volume and generates a thumbnail. Responses include
the file keys; the files themselves are served by nginx at
`/photos/{file_key}` and `/photos/{thumb_key}`.

## Price estimates

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|------------------------------------------|
| `POST` | `/api/items/{id}/estimates`   | Record a manually researched value       |
| `GET`  | `/api/items/{id}/estimates`   | List estimate history for an item        |
| `POST` | `/api/items/{id}/estimate`    | Produce an automatic estimate *(Phase 3)*|

Estimates are append-only: each `POST .../estimates` adds a timestamped record
(`estimated_value`, `currency`, `source`), never overwriting history. The
automatic `POST .../estimate` lookup — comparables by catalog ref + grade, with
a confidence score — arrives in Phase 3; see
[price-sources.md](price-sources.md).

## Reference data

*(Phase 2 — not yet implemented.)*

| Method | Path              | Purpose                          |
|--------|-------------------|----------------------------------|
| `GET`  | `/api/grades`     | List grade scales and codes      |
| `GET`  | `/api/catalogs`   | List known catalogs              |

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
