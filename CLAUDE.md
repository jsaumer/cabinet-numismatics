# Cabinet

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics: Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name and OpenAPI title
are "Cabinet." **Public on GitHub under MIT, released as v0.27.0, and deployed on the owner's
homelab Docker Swarm from the published GHCR images**, so treat it as
an open-source project: keep CONTRIBUTING/CHANGELOG/docs current, and bump the
version in `backend/pyproject.toml` (surfaced by `GET /api/health`) with the
changelog entry when releasing.

## Architecture (three services; keep it minimal)

- **backend**: FastAPI (Python). Serves the REST API under `/api/` and runs
  background tasks (thumbnails, price lookups, backups, alerts) in-process.
- **proxy**: nginx. Single entry point; serves the built frontend and photo
  files directly, proxies `/api/` to the backend.
- **db**: PostgreSQL.
- Frontend is React + Vite, built to static files that nginx serves.
- Photos are plain files on a shared volume (backend writes, nginx serves);
  documents on their own private volume, served only by the API; the
  database stores only file keys. No MinIO/S3, no Redis: deliberately cut
  as overkill for single-user.
- No auth in the app yet: it runs on a trusted network or behind an
  authenticating reverse proxy. Login is planned (roadmap Phase 7, P8: local
  accounts with a first-run superuser, then OIDC single sign-on) and lands
  before v1.0.0; it stays one shared collection.

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
frontend/                React + Vite app; e2e/ holds the Playwright tests,
                         public/ the logo and favicon (see frontend/README.md)
scripts/                 backup.sh, restore.sh, seed_demo.py
```

## Conventions

- Proper git project with maintained documentation. When behaviour changes,
  update every affected document in the same commit, not only the changelog:
  `README.md` (features), `docs/api.md`, `docs/roadmap.md` (what shipped,
  what's next), `docs/implementation-notes.md`, `frontend/README.md`, and
  the topic doc it touches. Before cutting a release, reread those against
  the diff since the last tag; the owner expects the docs to match the
  build, and they drifted once (v0.24.x) when only the changelog was kept
  up. See @docs/roadmap.md for
  the feature list and phase plan, and @docs/architecture.md for service detail.
- Prefer single/minimal container images. Do not reintroduce cut services
  (Redis, object storage) without a clearly stated reason.
- Be concise and direct in explanations and in code comments.
- No em dashes anywhere: UI text, messages, docs, comments, commit messages.
  Write the sentence so it doesn't need one (comma, colon, period,
  parentheses). An empty value in a table or field shows an en dash.
- Config via environment variables in `.env`; never commit real secrets.
  `.env.example` is the committed template.

## Build & run

- Full stack: `docker compose up --build`, then nginx serves at
  http://localhost/, API docs at http://localhost/api/docs. The frontend is
  built inside the proxy image (multi-stage `frontend/Dockerfile`), so no host
  Node install is needed.
- Frontend dev: `npm run dev` in `frontend/` (the Vite dev server proxies
  `/api` to localhost:8000). Production build output is `frontend/dist`.
- Backend dev: `uvicorn app.main:app --reload` with `DATABASE_URL`,
  `PHOTO_DIR`, and `DOCUMENT_DIR` set, and `REQUIRE_DOCUMENT_MOUNT=false`.
- Tests: in `backend/`, `pip install -e .[dev]` once, then `pytest`. Tests do
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
- Lint/format: in `backend/`, `ruff check .` and `ruff format .`.
- Dependencies: the image installs `backend/requirements.txt` (hash-pinned);
  after editing `pyproject.toml`'s dependencies, regenerate it with the
  command in docs/security.md. `security.yml` audits it and scans both images.
- Migrations: Alembic, run in `backend/` with `DATABASE_URL` set:
  `alembic upgrade head` to apply, `alembic revision --autogenerate -m "..."`
  to create. The backend also applies pending migrations itself on startup
  (`AUTO_MIGRATE`, default true; `app/services/schema.py`, under a Postgres
  advisory lock), so a deploy needs no manual step. Tests set
  `AUTO_MIGRATE=false` (conftest) and build the schema with `create_all` on
  SQLite. `/api/health` reports `schema` (current vs expected revision), shown
  in Settings → About.
- Screenshots: `docs/screenshots/README.md` has the exact headless command.

## Current status & next step

Released as v0.27.0: roadmap Phases 0–5.8 are complete, migrations
`0001`–`0018`. What each release added, and the rules it left behind, is in
@docs/implementation-notes.md (read the section for any area you touch). The
rules that bite most often:

- Every ORM select hides trashed items (`models.item._hide_trashed`) unless
  `.execution_options(include_deleted=True)`; anything counting through a
  link table, or deciding a document's last holder, handles the trash itself.
  `get_item_or_404` treats trashed as missing unless `include_deleted`.
- Every automatic estimate goes through `pricing.run_adapter` (it records
  `estimate_attempts`); each adapter's local checks live in its
  `prerequisite(db, item)`, never duplicated in the adapter.
  `EstimateResult.details` must be JSON-safe, never `Decimal`.
- Price sources are keyless where possible, cached in `source_cache` through
  `pricing.cached_fetch` (stale beats failed), and never sent collection
  data. `KeyRejected` / `QuotaExhausted` raise alerts and stop a scheduled
  refresh at the first one.
- Secrets (`app_settings.SECRET_KEYS`: API keys, the alert webhook and
  heartbeat URLs) are Fernet-encrypted, write-only, and never appear in logs,
  error text, or URLs.
- Document uploads are refused unless `DOCUMENT_DIR` is a mount; a Swarm
  needs the bind. Backups are refused inside `PHOTO_DIR`.
- Every new `price_estimates` row goes through `pricing.add_estimate` (it
  notices a wish-list target). `serial_traits` and `population_as_of` are
  server-set, on every path that changes their inputs (`items._sync_derived`).
- Adding or retiring a dashboard widget touches both sides: the frontend
  `REGISTRY` in `frontend/src/dashboard/registry.tsx` and the backend
  `WIDGET_OPTIONS`/`DEFAULT_SIZES` in `backend/app/services/dashboard.py`
  have to agree, or the options form and the server's validation disagree
  too.
- In-app restore: only `maintenance.EXEMPT` (health, restore status) answers
  during one, and neither may touch the database; new loops use
  `maintenance.scheduled_task()`; `.restore-*` folders stay excluded from
  archives, listings, pruning, and nginx; the photo and document
  directories are mount points, never renamed or removed.
- Tests run on SQLite: one-second timestamps (backdate when order matters),
  `backup.dump_database` and `restore.restore_database` monkeypatched, alert
  delivery and the restore thread run inline. Import
  fixtures are synthetic (`tests/import_samples.py`); OpenNumismat's demo
  files are GPL, so keep them out.

Cert-first entry shipped in v0.22.0 (`pcgs.cert_facts` / `parse_grade`,
`services/duplicates.py` behind `GET /api/items/similar` and the importer's
lookalike note, `components/lookup.tsx`; no migration).
Runs and registry sets shipped in v0.23.0 (`services/checklists.py`,
`POST /api/items/run`, `POST /api/checklists/generate`, migration `0017`;
slot matches are computed on read, never stored).
v0.23.2 to v0.24.9 came from the owner's data-entry pass (the roadmap's
"From the data-entry pass" list): the text and look pass (no em dashes,
`api.money`, `components/icons.tsx` and `controls.tsx`, the bronze tokens
and Calibri-first `--font` in `styles.css`, dark by default, the logo in
`frontend/public/`, the Homepage tile in docs/monitoring.md), and the PCGS
fixes found with a real token (100 calls/day, `_country` / `_mint_mark`,
month-only lot dates, `APR_MAX_AGE`). The API call counter was planned and
**tabled** by the owner; don't build it unprompted.
Roadmap Phase 7 is the parity plan the owner chose on 20 September 2026 from
a survey of other tools. Its P1 and P3 to P6 shipped in v0.25.0 (migration
`0018`): the PCGS population on the item, wish-list target and priority with
a one-time webhook event, National Bank Note fields and the notes-by-signature
report, fancy serial traits (`services/serials.py`), and the die axis and
date as struck (`services/calendars.py`); see "Parity fields" in the
implementation notes.
P2, in-app restore, shipped in v0.26.0 (no migration): `services/restore.py`
and `maintenance.py`, `/api/restore/*`, `components/restore.tsx`; verify,
safety backup (`-prerestore`, outside `backup_keep`), typed `RESTORE`,
unpack, database in one transaction, then the file swap; outcome and journal
on the state volume; `RESTORE_ENABLED` / `RESTORE_MAX_GB`. Open until P8
makes it admin-only; see "In-app restore" in the implementation notes.
P10, a customisable dashboard, shipped in v0.27.0 (no migration):
`services/dashboard.py` and `routers/dashboard.py`, `dashboard_layout` in
`app_settings`, `/api/dashboard/layout` (`GET`/`PUT`/`DELETE`), and
`frontend/src/dashboard/`; the default layout reproduces the old fixed
page, reading is lenient and writing is strict, and the hand-written drag
listens on `window` rather than the handle; see "A customisable dashboard"
in the implementation notes.
**Next, in order:** P7 bullion stack figures, P8 authentication (decided: one admin first,
onboarded with a setup code from the backend log, always on, scoped API
tokens in the first cut, deny by default; then SSO for that admin; more
accounts and roles are optional; the design and permission table are in
docs/security.md), P9 a share view (blocked on P8; the whole feature is an
admin setting, off by default); labels, a phone app, and more accounts are
optional. Research and propose each before building, as always. v1.0.0
follows P8 and the checklist under "The road to v1.0.0". Before that, the
roadmap's Phase 5.9 was demoted
on 19 September 2026 from a release train to one next item plus unordered
**candidates** and **parked** items: the owner is entering 100–500 pieces by
hand (runs and singles, mostly held), so don't build ahead of that beyond
Phase 7: friction they report still comes first, and the pipeline statuses,
tax lots, submissions, and slab scanning stay parked.

Releases: pushing a `v*` tag runs CI's `publish` job, which pushes
`ghcr.io/jsaumer/cabinet-numismatics-{backend,proxy}` (version + `latest`;
nothing before v0.10.2 is published). The live homelab instance pins those
tags, so a release reaches it only once the tag's images exist; the backend
migrates on startup, so an upgrade there is just a tag bump.

## Notes for working in Claude Code (desktop app)

- Cabinet is developed with Claude Code in the Claude desktop app (Code tab),
  editing the working tree directly. There is no zip/flatten step here (that
  was specific to the earlier chat-based file delivery).
- Keep this file and `docs/` in sync with the code. If you correct the same
  thing twice across sessions, write it down here or, if it's about one
  area, in docs/implementation-notes.md.
