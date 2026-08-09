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

| Method   | Path               | Purpose                            |
|----------|--------------------|------------------------------------|
| `GET`    | `/api/items`       | List items (filter/paginate)       |
| `POST`   | `/api/items`       | Create an item                     |
| `GET`    | `/api/items/{id}`  | Get one item with photos/estimates |
| `PATCH`  | `/api/items/{id}`  | Update fields on an item           |
| `DELETE` | `/api/items/{id}`  | Delete an item and its photos      |

**List query parameters** (all optional): `type`, `country`, `year`,
`grade`, `q` (free-text over notes/series), `limit`, `offset`,
`sort`.

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

| Method | Path                          | Purpose                               |
|--------|-------------------------------|---------------------------------------|
| `POST` | `/api/items/{id}/estimate`    | Produce a new price estimate          |
| `GET`  | `/api/items/{id}/estimates`   | List estimate history for an item     |

`POST .../estimate` looks up comparables, computes an estimate, and returns the
new `price_estimates` record. See [price-sources.md](price-sources.md) for how
estimates are produced.

## Reference data

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
