# Architecture

## Overview

Cabinet is a single-user, self-hosted numismatics web application. All components run
as containers managed by a single `docker-compose.yaml`. The stack is
deliberately small — three services — because a single-user collection manager
has modest performance needs.

```
                    ┌─────────────┐
     HTTP :80  ───► │    proxy    │  (nginx)
                    │  UI + /photos│
                    └──────┬──────┘
                           │ /api
                    ┌──────▼──────┐
                    │   backend   │  (FastAPI + background tasks)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     db      │  (postgres)
                    └─────────────┘

     photos: shared volume — backend writes, nginx serves
```

## Services

### proxy (nginx, built image)
The single public entry point. Its image is built from the multi-stage
`frontend/Dockerfile` (Node build stage → nginx stage with the static files
baked in), so `docker compose up --build` needs no host Node install. It serves
the frontend and photo files directly, and proxies `/api/` to the backend. Sets
`client_max_body_size` high enough for photo uploads. Config lives in
`proxy/nginx.conf`, baked into the image.

### backend (built image)
FastAPI application exposing the REST API under `/api/`. It also runs
background work (thumbnail generation, price lookups, scheduled backups) in-process — either
synchronously or via FastAPI background tasks — since the job volume for a
single user is low. On startup it ensures the photo directory exists.

### db (postgres)
Primary relational store for items, photo metadata, and price estimates. Data
persists in the `db_data` volume. A healthcheck gates the backend so it waits
for the database to be ready.

## Photo storage

Photos are stored as plain files on the `photo_data` volume rather than in an
object store — simpler to run and back up for a single user. The backend
writes originals and generated thumbnails into `PHOTO_DIR`; nginx serves them
read-only under `/photos/`. The database stores only the relative file keys.

## Document storage

Attached documents (receipts, certificates, invoices) are files too, on a
separate `document_data` volume at `DOCUMENT_DIR` that nginx never sees:
receipts carry names and addresses, so they're served only through the API,
with headers set from the type detected at upload. The backend refuses
uploads unless `DOCUMENT_DIR` is a mounted volume, so a deployment missing the
mount can't quietly keep documents inside the container.

## Data flow

**Adding an item with photos**
1. Client POSTs item data to `/api/items`.
2. Backend validates and writes a row to postgres.
3. Client uploads photos to `/api/items/{id}/photos`.
4. Backend validates the image, corrects EXIF orientation, and writes the
   original plus a generated thumbnail to the photo volume.
5. Backend records photo metadata (file keys) in postgres.
6. nginx serves the files directly at `/photos/{key}`.

**Requesting a price estimate**
1. Client POSTs to `/api/items/{id}/estimate`.
2. Backend looks up comparables by catalog reference + grade.
3. Backend computes an estimate + confidence and writes a `price_estimates`
   row, with a `details` summary of what the source returned (provenance).
4. Client refetches the item to see the new estimate.

## Configuration

All configuration is via environment variables, loaded from `.env`
(gitignored). Start from `.env.example`.

| Variable          | Purpose                                              |
|-------------------|------------------------------------------------------|
| `DB_USER`         | Postgres username                                    |
| `DB_PASSWORD`     | Postgres password                                    |
| `DB_NAME`         | Postgres database name                               |
| `REESTIMATE_DAYS` | Default melt re-estimation window (Settings overrides)|
| `AUTO_MIGRATE`    | Apply pending migrations on backend startup (default `true`) |
| `BACKUP_DIR`      | Where in-app backup archives are written (compose: `/data/backups`) |
| `SECRET_KEY`      | Fernet key(s) encrypting stored API credentials; comma-separated to rotate |
| `DOCUMENT_DIR`    | Where attached documents are stored (compose: `/data/documents`, its own volume) |
| `REQUIRE_DOCUMENT_MOUNT` | Refuse document uploads unless `DOCUMENT_DIR` is a mounted volume (default `true`; `false` for local development) |
| `IMPORT_DIR`      | Where uploaded import files wait between preview and import (default: a temp folder; kept a day) |

The backend derives `DATABASE_URL` from these in `docker-compose.yaml`,
`PHOTO_DIR` points at the mounted photo volume, and `SECRET_KEY_FILE` points
at the private `backend_state` volume used when `SECRET_KEY` is unset. See
[security.md](security.md) for key management and rotation.

## Development

- **Backend:** run FastAPI with `uvicorn app.main:app --reload`, with
  `DATABASE_URL` pointed at a local or containerized postgres, `PHOTO_DIR`
  and `DOCUMENT_DIR` set to local directories, and `REQUIRE_DOCUMENT_MOUNT=false`.
- **Frontend:** `npm run dev` runs the Vite dev server, which proxies `/api`
  to localhost:8000. `npm run build` emits static files to `frontend/dist`
  (only needed for local inspection — the container build does this itself).
- **Full stack:** `docker compose up --build` brings everything up with nginx
  as the entry point at http://localhost/; the frontend is built inside the
  proxy image.

## Deployment notes

- Single-host deployment is the design target. For remote access, terminate
  TLS at the nginx proxy (add a cert and a `443` server block) or place the
  stack behind an existing reverse proxy / tunnel.
- Back up from Settings → Backups (download, or scheduled archives into
  `BACKUP_DIR`), or with `./scripts/backup.sh` from the host — database dump
  and photo archive together either way; see
  [backup-restore.md](backup-restore.md).
- There is no application-level auth by design; put the stack behind an
  authenticating proxy with TLS before exposing it beyond a trusted network.
  See [security.md](security.md).
- The stack can be reduced to two services by letting FastAPI serve the static
  frontend itself and dropping nginx; nginx is kept for efficient static/photo
  serving and as a clean place to terminate TLS later.
