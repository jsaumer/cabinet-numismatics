# Cabinet

<!-- Maintainer note: this file is the persistent brief Claude Code reads at the
start of every session. Keep it under ~200 lines and specific. When the design
changes, update this file and the docs it points to in the same commit. -->

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics — Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name and OpenAPI title
are "Cabinet." Endgame is a polished personal tool that may later be
open-sourced.

## Architecture (three services — keep it minimal)

- **backend** — FastAPI (Python). Serves the REST API under `/api/` and runs
  background tasks (thumbnails, price lookups) in-process. Ensures the photo
  directory exists on startup.
- **proxy** — nginx. Single entry point; serves the built frontend and photo
  files directly, proxies `/api/` to the backend.
- **db** — PostgreSQL.
- Frontend is React + Vite, built to static files that nginx serves.
- Photos are plain files on a shared volume (backend writes, nginx serves); the
  database stores only file keys. No MinIO/S3, no Redis — deliberately cut as
  overkill for single-user.
- Single-user, so no auth in the MVP; authentication is deferred until just
  before any networked/public exposure.

## Repo layout

```
docker-compose.yaml
.env.example / .env (gitignored)
.gitignore
README.md
CLAUDE.md                (this file)
docs/                    architecture, data-model, api, price-sources,
                         roadmap, claude-code
proxy/nginx.conf
backend/                 FastAPI app (Phase 0 onward)
frontend/                React + Vite app (Phase 0 onward)
```

## Conventions

- Proper git project with maintained documentation. When the design changes,
  update the affected `docs/` files in the same commit. See @docs/roadmap.md for
  the feature list and phase plan, and @docs/architecture.md for service detail.
- Prefer single/minimal container images. Do not reintroduce cut services
  (Redis, object storage) without a clearly stated reason.
- Be concise and direct in explanations and in code comments.
- Config via environment variables in `.env`; never commit real secrets.
  `.env.example` is the committed template.

## Build & run

- Full stack: `docker compose up --build` — nginx serves at http://localhost/,
  API docs at http://localhost/api/docs. The frontend is built inside the proxy
  image (multi-stage `frontend/Dockerfile`), so no host Node install is needed.
- Frontend dev: `npm run dev` in `frontend/` — the Vite dev server proxies
  `/api` to localhost:8000. Production build output is `frontend/dist`.
- Backend dev: `uvicorn app.main:app --reload` with `DATABASE_URL` and
  `PHOTO_DIR` set.

<!-- Fill in exact test/lint/migration commands as they are established in
Phase 0 so future sessions can run them without asking. -->

- Tests: in `backend/` — `pip install -e .[dev]` once, then `pytest`. Tests do
  not require a running database.
- Lint/format: in `backend/` — `ruff check .` and `ruff format .`.
- Migrations: Alembic, run in `backend/` with `DATABASE_URL` set —
  `alembic upgrade head` to apply, `alembic revision --autogenerate -m "..."`
  to create. Inside the compose stack:
  `docker compose exec backend alembic upgrade head`. The baseline revision
  (`0001`) is empty; the first real tables arrive with Phase 1 models.

## Current status & next step

Phase 3 (valuation) is complete: melt-value adapter (spot × weight × fineness
× quantity via gold-api.com, 12h cache in `spot_prices`, stale fallback) at
`POST /api/items/{id}/estimate`, optional confidence on manual estimates,
and `GET /api/stats/collection` totals in a declared display currency
(mismatched currencies excluded + counted, never mixed — full conversion is
Phase 5). Money convention: prices/estimates are per row (the lot), not per
piece. Sold-comps integration was deferred as a stretch goal. Migrations
through `0004`. Phases 0–2 done earlier (see git history; backup/restore in
scripts/, rehearsed). **Next: Phase 4 — insights & reporting** — dashboard
breakdowns, realized + unrealized gain/loss views, Excel export,
printable/insurance report, basic charts. See docs/roadmap.md.

## Notes for working in Claude Code (desktop app)

- Cabinet is developed with Claude Code in the Claude desktop app (Code tab),
  editing the working tree directly. There is no zip/flatten step here — that
  was specific to the earlier chat-based file delivery.
- Keep this file and `docs/` in sync with the code. If you correct the same
  thing twice across sessions, write it down here.
