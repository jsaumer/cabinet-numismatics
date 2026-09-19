# Cabinet

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics — Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name and OpenAPI title
are "Cabinet." **Public on GitHub under MIT, released as v0.21.0, and deployed on the owner's
homelab Docker Swarm from the published GHCR images** — treat it as
an open-source project: keep CONTRIBUTING/CHANGELOG/docs current, and bump the
version in `backend/pyproject.toml` (surfaced by `GET /api/health`) with the
changelog entry when releasing.

## Architecture (three services — keep it minimal)

- **backend** — FastAPI (Python). Serves the REST API under `/api/` and runs
  background tasks (thumbnails, price lookups, backups, alerts) in-process.
- **proxy** — nginx. Single entry point; serves the built frontend and photo
  files directly, proxies `/api/` to the backend.
- **db** — PostgreSQL.
- Frontend is React + Vite, built to static files that nginx serves.
- Photos are plain files on a shared volume (backend writes, nginx serves);
  documents on their own private volume, served only by the API; the
  database stores only file keys. No MinIO/S3, no Redis — deliberately cut
  as overkill for single-user.
- Single-user, so no auth in the app; authentication is deferred to a
  reverse proxy until v1.0.0.

## Repo layout

```
docker-compose.yaml      single-host stack (build + run)
deploy/docker-stack.yaml Swarm stack (pulled images)
.env.example / .env (gitignored)
README.md, CLAUDE.md (this file), CHANGELOG.md
docs/                    architecture, data-model, api, price-sources,
                         monitoring, roadmap, implementation-notes, claude-code
proxy/nginx.conf
backend/                 FastAPI app, Alembic migrations, pytest suite
frontend/                React + Vite app; e2e/ holds the Playwright tests
scripts/                 backup.sh, restore.sh, seed_demo.py
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
- Backend dev: `uvicorn app.main:app --reload` with `DATABASE_URL`,
  `PHOTO_DIR`, and `DOCUMENT_DIR` set, and `REQUIRE_DOCUMENT_MOUNT=false`.
- Tests: in `backend/` — `pip install -e .[dev]` once, then `pytest`. Tests do
  not require a running database (in-memory SQLite, every outbound call
  mocked). CI (`.github/workflows/ci.yml`) runs ruff + pytest on 3.10/3.14, a
  frontend typecheck, and a compose build/migrate/smoke job that drives the
  API with curl (smoke test, backup → restore drill) and the pages with
  Playwright (`frontend/e2e/`, `npm run e2e` against a running stack,
  `BASE_URL` for another host). When an endpoint's or a page's behaviour
  changes, update those too; pytest won't catch them.
- Demo data: `python scripts/seed_demo.py` against a running stack.
- Price sources: `docker compose exec backend python scripts/check_sources.py
  --list` (then `-s <source> -i <item-id>`) probes a live price API and dumps
  the raw response; `--fresh` bypasses the cache and spends quota.
- Lint/format: in `backend/` — `ruff check .` and `ruff format .`.
- Migrations: Alembic, run in `backend/` with `DATABASE_URL` set —
  `alembic upgrade head` to apply, `alembic revision --autogenerate -m "..."`
  to create. The backend also applies pending migrations itself on startup
  (`AUTO_MIGRATE`, default true; `app/services/schema.py`, under a Postgres
  advisory lock), so a deploy needs no manual step. Tests set
  `AUTO_MIGRATE=false` (conftest) and build the schema with `create_all` on
  SQLite. `/api/health` reports `schema` (current vs expected revision), shown
  in Settings → About.
- Screenshots: `docs/screenshots/README.md` has the exact headless command.

## Current status & next step

Released as v0.21.0: roadmap Phases 0–5.8 are complete, migrations
`0001`–`0016`. What each release added, and the rules it left behind, is in
@docs/implementation-notes.md — read the section for any area you touch. The
rules that bite most often:

- Every ORM select hides trashed items (`models.item._hide_trashed`) unless
  `.execution_options(include_deleted=True)`; anything counting through a
  link table, or deciding a document's last holder, handles the trash itself.
  `get_item_or_404` treats trashed as missing unless `include_deleted`.
- Every automatic estimate goes through `pricing.run_adapter` (it records
  `estimate_attempts`); each adapter's local checks live in its
  `prerequisite(db, item)`, never duplicated in the adapter.
  `EstimateResult.details` must be JSON-safe — never `Decimal`.
- Price sources are keyless where possible, cached in `source_cache` through
  `pricing.cached_fetch` (stale beats failed), and never sent collection
  data. `KeyRejected` / `QuotaExhausted` raise alerts and stop a scheduled
  refresh at the first one.
- Secrets (`app_settings.SECRET_KEYS` — API keys, the alert webhook and
  heartbeat URLs) are Fernet-encrypted, write-only, and never appear in logs,
  error text, or URLs.
- Document uploads are refused unless `DOCUMENT_DIR` is a mount; a Swarm
  needs the bind. Backups are refused inside `PHOTO_DIR`.
- Tests run on SQLite: one-second timestamps (backdate when order matters),
  `backup.dump_database` monkeypatched, alert delivery run inline. Import
  fixtures are synthetic (`tests/import_samples.py`); OpenNumismat's demo
  files are GPL — keep them out.

**Next: hardening** (v0.21.x — the dashboard setup checklist, Playwright
smoke tests, fresh screenshots, the frontend file splits, this file, the
Swarm stack file), **then cert-first entry** (v0.22.0). A second September
2026 review re-planned everything unshipped as roadmap Phase 5.9
(v0.22.0–v0.30.0, then v1.0.0).

Releases: pushing a `v*` tag runs CI's `publish` job, which pushes
`ghcr.io/jsaumer/cabinet-numismatics-{backend,proxy}` (version + `latest`;
nothing before v0.10.2 is published). The live homelab instance pins those
tags, so a release reaches it only once the tag's images exist; the backend
migrates on startup, so an upgrade there is just a tag bump.

## Notes for working in Claude Code (desktop app)

- Cabinet is developed with Claude Code in the Claude desktop app (Code tab),
  editing the working tree directly. There is no zip/flatten step here — that
  was specific to the earlier chat-based file delivery.
- Keep this file and `docs/` in sync with the code. If you correct the same
  thing twice across sessions, write it down here — or, if it's about one
  area, in docs/implementation-notes.md.
