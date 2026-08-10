# Cabinet

<!-- Maintainer note: this file is the persistent brief Claude Code reads at the
start of every session. Keep it under ~200 lines and specific. When the design
changes, update this file and the docs it points to in the same commit. -->

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics — Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name and OpenAPI title
are "Cabinet." **On GitHub (private for now) under MIT, released as v0.9.1** — treat it as
an open-source project: keep CONTRIBUTING/CHANGELOG/docs current, and bump the
version in `backend/pyproject.toml` (surfaced by `GET /api/health`) with the
changelog entry when releasing.

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
  not require a running database. CI (GitHub Actions, `.github/workflows/ci.yml`)
  runs ruff + pytest on 3.10/3.12, a frontend typecheck, and a compose
  build/migrate/smoke job on every PR.
- Demo data: `python scripts/seed_demo.py` against a running stack.
- Lint/format: in `backend/` — `ruff check .` and `ruff format .`.
- Migrations: Alembic, run in `backend/` with `DATABASE_URL` set —
  `alembic upgrade head` to apply, `alembic revision --autogenerate -m "..."`
  to create. Inside the compose stack:
  `docker compose exec backend alembic upgrade head`. The baseline revision
  (`0001`) is empty; the first real tables arrive with Phase 1 models.

## Current status & next step

Phases 0–4 complete (see git history). Phase 5: three of four bundles done —
value depth (currency conversion via frankfurter.dev daily rates, value-over-
time charts, scheduled + on-demand melt refresh, REESTIMATE_DAYS env),
catalog depth (sets/lots, variety, custom_fields JSON, bulk edit), polish
(dark mode via CSS variables + toggle, append-only item edit history,
completeness checklists). Migrations through `0007`. Stats currency rule:
convert at cached daily rates, exclude + count what can't convert. Money is
per row (the lot). Backup/restore in scripts/, rehearsed. Pricing program (roadmap Phase 5.5) M1 is done: `app_settings` table
(migration `0008`), `GET/PUT /api/settings` (secrets Fernet-encrypted at rest
via `services/crypto.py` + `SECRET_KEY`, write-only, masked; see
docs/security.md),
`/settings` page (display currency, melt cadence + toggle, Numista/PCGS
credentials ahead of their adapters, cached market data). Display currency
and melt cadence are DB-backed with env fallback. **Next: pricing M2 —
Numista adapter** (coins + notes by numista ref + grade), then M3 PCGS, M4
estimate provenance, M5 pricing reports. Also open: photo-niceties bundle,
Phase 6 / homelab deployment (Traefik + Authentik, CI). See docs/roadmap.md.

## Notes for working in Claude Code (desktop app)

- Cabinet is developed with Claude Code in the Claude desktop app (Code tab),
  editing the working tree directly. There is no zip/flatten step here — that
  was specific to the earlier chat-based file delivery.
- Keep this file and `docs/` in sync with the code. If you correct the same
  thing twice across sessions, write it down here.
