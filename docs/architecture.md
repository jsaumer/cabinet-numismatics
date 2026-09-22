# Architecture

## Overview

Cabinet is a single-user, self-hosted numismatics web application. All
components run as containers managed by a single `docker-compose.yaml`
(`deploy/docker-stack.yaml` is the same stack for a Docker Swarm, from the
published images). The stack is deliberately small (three services) because
a single-user collection manager has modest performance needs.

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

     photos: shared volume (backend writes, nginx serves)
     documents, backups, key file: backend-only volumes
```

## Services

### proxy (nginx, built image)
The single public entry point. Its image is built from the multi-stage
`frontend/Dockerfile` (Node build stage → nginx stage with the static files
baked in), so `docker compose up --build` needs no host Node install. It serves
the frontend and photo files directly, and proxies `/api/` to the backend. The
built frontend includes what is in `frontend/public`, so the logo and icons
are served at `/logo.svg`, `/logo-512.png`, `/favicon.ico`, and
`/apple-touch-icon.png`. `client_max_body_size` is 25 MB for photo and
document uploads, and 1 GB under `/api/imports` (an OpenNumismat file carries
its photos); `/api/backup*` and `/api/imports` get a 30-minute read timeout.
`/api/restore` has a location of its own: 20 GB bodies (an uploaded archive
carries every photo and document), request buffering off so the backend
streams the upload straight to the backup volume, and 60-minute read and
send timeouts. Any dot-name under `/photos/` answers 404: a restore's
working folders sit inside the photo volume for a moment.
It sets the security headers on every response and a Content-Security-Policy
on the app (see [security.md](security.md)). Config lives in
`proxy/nginx.conf`, baked into the image. The photo volume is mounted
read-only, and it is the only data volume the proxy sees.

### backend (built image)
FastAPI application exposing the REST API under `/api/`. It also runs
background work (thumbnail generation, price lookups, scheduled backups,
alerts and the heartbeat, see [monitoring.md](monitoring.md)) in-process,
since the job volume for a single user is low: thumbnails and on-demand
estimates run inside the request, and two loops in the process handle the
rest (every 12 hours, the scheduled price refreshes; every hour, the backup
schedule, the trash clear-out, and the heartbeat). On startup it ensures the
photo directory exists and, unless `AUTO_MIGRATE=false`, waits up to 60
seconds for postgres and applies pending migrations before serving. Before
that it finishes, or clears up after, an in-app restore the last process
didn't complete.

While an in-app restore runs the backend is in **maintenance mode**
(`services/maintenance.py`, in memory): every request but `GET /api/health`
and `GET /api/restore/status` answers 503, the two loops skip their work,
and health answers `db: "restoring"` without touching the database. See
[backup-restore.md](backup-restore.md#restore-from-inside-the-app).

The container's entrypoint starts as root only to hand the data directories
to an unprivileged user (`PUID`:`PGID`, default `1000`:`1000`), then drops to
that user with `setpriv`; see [security.md](security.md). It mounts four
volumes: `photo_data` (`/data/photos`), `document_data` (`/data/documents`),
`backup_data` (`/data/backups`), and `backend_state` (`/data/state`: the
generated encryption key when `SECRET_KEY` is unset, plus the last restore's
outcome, `restore_last.json`, and `restore_journal.json` while one runs).
Run one replica: the loops, and a restore's state, live in the process.

### db (postgres)
Primary relational store (`postgres:16-alpine`) for items, photo and document
metadata, price estimates, settings, and the market-data caches; see
[data-model.md](data-model.md). Data persists in the `db_data` volume. Under
Compose a healthcheck gates the backend so it waits for the database to be
ready; on a Swarm, which has no `depends_on`, the backend's own wait covers
it.

## Photo storage

Photos are stored as plain files on the `photo_data` volume rather than in an
object store, which is simpler to run and back up for a single user. The
backend writes originals and generated thumbnails into `PHOTO_DIR`; nginx
serves them read-only under `/photos/`. The database stores only the
relative file keys.

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
1. Client POSTs to `/api/items/{id}/estimates/auto?source=` (`melt` by default, or
   `numista`, `pcgs`, `comps`).
2. Backend checks the source is switched on and the item has what it needs
   (weight and fineness for melt, a catalog reference and grade for Numista,
   a cert or PCGS number for PCGS, logged sales for comps).
3. Backend fetches through the database cache (spot prices, `source_cache`),
   computes an estimate + confidence, and writes a `price_estimates` row with
   a `details` summary of what the source returned (provenance). The outcome,
   success or not, is recorded in `estimate_attempts`.
4. Client refetches the item to see the new estimate.

## Configuration

Deployment configuration is via environment variables, loaded from `.env`
(gitignored). Start from `.env.example`. Everything else (display currency,
price-source keys, refresh cadence, backup schedule, alerts) is set in the
app's Settings page and stored in the database.

| Variable          | Purpose                                              |
|-------------------|------------------------------------------------------|
| `DB_USER`         | Postgres username                                    |
| `DB_PASSWORD`     | Postgres password                                    |
| `DB_NAME`         | Postgres database name                               |
| `REESTIMATE_DAYS` | Default melt re-estimation window in days (default `7`, `0` disables; Settings overrides) |
| `AUTO_MIGRATE`    | Apply pending migrations on backend startup (default `true`) |
| `BACKUP_DIR`      | Where in-app backup archives are written (compose: `/data/backups`) |
| `SECRET_KEY`      | Fernet key(s) encrypting stored secrets (API credentials, the alert webhook and heartbeat URLs); comma-separated to rotate |
| `DOCUMENT_DIR`    | Where attached documents are stored (compose: `/data/documents`, its own volume) |
| `REQUIRE_DOCUMENT_MOUNT` | Refuse document uploads unless `DOCUMENT_DIR` is a mounted volume (default `true`; `false` for local development) |
| `PUID` / `PGID`   | The unprivileged user the backend runs as, and that owns its files (default `1000`:`1000`) |
| `IMPORT_DIR`      | Where uploaded import files wait between preview and import (default: a temp folder; kept a day) |
| `RESTORE_ENABLED` | In-app restore (default `true`); `false` makes every restore endpoint answer 404 and hides it in Settings |
| `RESTORE_MAX_GB`  | Largest archive that may be uploaded for a restore, in GB (default `20`, which is also what nginx allows) |
| `TAG`             | Image tag Compose names its builds with and the Swarm stack pulls (default `latest`; e.g. `0.29.1`) |

`docker-compose.yaml` builds the backend's `DATABASE_URL` from the `DB_*`
values and fixes the container paths itself: `PHOTO_DIR=/data/photos`,
`BACKUP_DIR=/data/backups`, `DOCUMENT_DIR=/data/documents`, and
`SECRET_KEY_FILE=/data/state/secret.key` on the private `backend_state`
volume, used when `SECRET_KEY` is unset. Change where data lives by changing
the mounts, not these. See [security.md](security.md) for key management and
rotation.

## Development

- **Backend:** run FastAPI with `uvicorn app.main:app --reload`, with
  `DATABASE_URL` pointed at a local or containerized postgres, `PHOTO_DIR`
  and `DOCUMENT_DIR` set to local directories, and `REQUIRE_DOCUMENT_MOUNT=false`.
- **Frontend:** `npm run dev` runs the Vite dev server, which proxies `/api`
  to localhost:8000. `npm run build` emits static files to `frontend/dist`
  (only needed for local inspection: the container build does this itself).
- **Full stack:** `docker compose up --build` brings everything up with nginx
  as the entry point at http://localhost/; the frontend is built inside the
  proxy image.

## Deployment notes

- Single-host deployment is the design target; [deployment.md](deployment.md)
  covers it, and the Swarm stack. For remote access, place the stack behind
  an existing reverse proxy or tunnel that terminates TLS (the nginx config
  is baked into the proxy image, so terminating TLS there means building
  your own image with a cert and a `443` server block).
- Back up from Settings → Backups (download, or scheduled archives into
  `BACKUP_DIR`), or with `./scripts/backup.sh` from the host (database dump,
  photo archive, and document archive together either way). Restore from
  Settings → Backups too, or with `./scripts/restore.sh` when the app won't
  start; see [backup-restore.md](backup-restore.md).
- There is no application-level auth yet: Cabinet is for a trusted
  network, or behind an authenticating reverse proxy with TLS (for example
  Traefik + Authentik forward-auth). Application login is the next thing
  built (roadmap Phase 7, P8: v0.30.0 one admin and API tokens, v0.31.0
  single sign-on), and it has to work both behind such a proxy and directly
  exposed. See [security.md](security.md).
- The stack can be reduced to two services by letting FastAPI serve the static
  frontend itself and dropping nginx; nginx is kept for efficient static/photo
  serving and as a clean place to terminate TLS later.
