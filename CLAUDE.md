# Cabinet

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics: Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name and OpenAPI title
are "Cabinet." **Public on GitHub under MIT, released as v0.33.1, and deployed on the owner's
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
- Photos are plain files on a shared volume (backend writes, nginx serves
  after asking the backend, `auth_request`, from v0.30.0);
  documents on their own private volume, served only by the API; the
  database stores only file keys. No MinIO/S3, no Redis: deliberately cut
  as overkill for single-user.
- Sign-in (roadmap Phase 7, P8 A1: one admin, database-backed sessions,
  scoped API tokens, deny by default) **shipped in v0.30.0**. Every route
  needs a session or a token; setup asks for a one-time code on first
  start. v0.31.0 shipped bars and rounds (P11); v0.32.0 shipped the share
  view (P9); v0.33.0 shipped single sign-on (P8 A2: OpenID Connect, GitHub,
  and a trusted-header mode). Every design decision was
  settled on 20 and 21 September 2026: see "Accounts and permissions" in
  docs/security.md, and don't re-open them. It stays one shared collection.
  The build contract, `docs/specs/SPEC_0300.md`, was approved by the owner
  on 21 September 2026 and built stage by stage (section 10 has the
  stages); that day the owner also cut forwarded-header trust
  (`TRUSTED_PROXIES`), pinned networks, and the `/api/docs` page from the
  design.

## Repo layout

```
docker-compose.yaml      single-host stack (build + run)
deploy/docker-stack.yaml Swarm stack (pulled images)
.env.example / .env (gitignored)
README.md, CLAUDE.md (this file), CHANGELOG.md
docs/                    architecture, data-model, api, price-sources,
                         monitoring, roadmap, implementation-notes, claude-code;
                         specs/ holds build contracts; review briefs and reviews stay local (gitignored) from v0.33.0
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
  http://localhost/ (no API docs page; the schema is `/api/openapi.json`).
  `PUBLIC_ORIGINS` is required (backend and proxy stop without it); nginx
  answers only its Host names and 444s the rest. The frontend is
  built inside the proxy image (multi-stage `frontend/Dockerfile`), so no host
  Node install is needed.
- Frontend dev: `npm run dev` in `frontend/` (the Vite dev server proxies
  `/api` to localhost:8000). Production build output is `frontend/dist`.
- Backend dev: `uvicorn app.main:app --reload` with `DATABASE_URL`,
  `PHOTO_DIR`, and `DOCUMENT_DIR` set, `REQUIRE_DOCUMENT_MOUNT=false`, and
  `PUBLIC_ORIGINS=http://localhost:5173` with `AUTH_INSECURE_HTTP=true`.
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
- Migrations: Alembic, two chains, run in `backend/` with `DATABASE_URL`
  set. The collection (`alembic/`, schema `public`): `alembic upgrade head`
  to apply, `alembic revision --autogenerate -m "..."` to create. Sign-in
  data (`alembic_auth/`, schema `cabinet_auth`, v0.30.0): the same with
  `-c alembic_auth.ini`. The backend also applies both itself on startup,
  collection first, in one transaction (`AUTO_MIGRATE`, default true;
  `app/services/schema.py`, under a Postgres advisory lock), so a deploy
  needs no manual step. Tests set `AUTO_MIGRATE=false` (conftest) and build
  both schemas with `create_all` on SQLite (`cabinet_auth` mapped away by
  `schema_translate_map`). `/api/health` reports `schema` and `auth_schema`
  (current vs expected revision), shown in Settings → About.
- Screenshots: `docs/screenshots/README.md` has the exact headless command.

## Current status & next step

Released as v0.33.1: roadmap Phase 7 is complete, migrations
`0001`–`0022` and `a0001`–`a0002`. v0.27.1 fixed two bugs found entering real pieces: a year is
now optional (an ND checkbox with an optional attributed year), and a
same-year Numista variety with no prices no longer blocks the one that has
them. v0.29.0 added note details (width/height, printer, watermark,
demonetisation) and reworked the item page into a hero plus grouped facts,
with ten more dashboard widgets from the "group C" survey. What each release added, and the rules it left behind, is in
@docs/implementation-notes.md (read the section for any area you touch). The
rules that bite most often:

- Sign-in data lives in the `cabinet_auth` schema (v0.30.0, `AuthBase`, its
  own chain in `alembic_auth/`): never dumped, never restored, no foreign
  key to or from `public`. Every archive is age-encrypted with the backup
  key (`services/archive_keys.py`) and MAC-signed; nothing unencrypted is
  ever written to `BACKUP_DIR` (write through `backup.encrypt_stream`, decrypt
  only via `backup.decrypt_to_staging` into `/data/staging`), plain `.zip`
  archives are never restored, the MAC is checked before anything in an
  archive is read, and an archive older than the newest in
  `cabinet_auth.backup_ledger` needs `RESTORE OLDER`. The key never crosses
  the API. Tests use conftest's `fake_age`.
- **Every API route declares its permission** (v0.30.0):
  `@permission("public" | "read" | "write" | "admin", metrics_ok=, fresh=)`
  directly above `def`, below the router decorator (`app/auth/permissions.py`);
  an undeclared route is refused, and `tests/test_gate.py` compares every
  route with the appendix of SPEC_0300 and runs the anonymous, token-scope,
  fresh, and CSRF matrices over the OpenAPI document. A new route needs a
  class that matches the spec table (or a spec change first). The gate
  (`app/auth/gate.py`) refuses any `%` in a path, lets anonymous callers
  reach only four routes, and fails CSRF closed for every cookie request.
  Tests: `client` is the signed-in admin inside its recent-password window;
  `anon_client`, `stale_client`, `token_client(scope)`, and
  `unclaimed_client` cover the rest.
- The credential services are `app/auth/` (v0.30.0), used through
  `accounts`; a password is only ever checked by `accounts._check_password`
  (throttles, the reserved slot, then Argon2, then the failure bookkeeping).
  Only hashes of secrets are stored, and no password, setup code, or token
  secret reaches a log, an exception, an audit row, or argv. Time comes from
  `app.auth.common` so tests can freeze it; tests never touch `/data`.
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
- `item.year` can be `None`: an undated piece is `year_nd` true, with an
  optional attributed year. Guard `None` anywhere that does arithmetic on
  it, and print `year_label` (`"1922"`, `"ND"`, `"ND (1922)"`), never `year`
  itself.
- Adding or retiring a dashboard widget touches both sides: the frontend
  `REGISTRY` in `frontend/src/dashboard/registry.tsx` and the backend
  `WIDGET_OPTIONS`/`DEFAULT_SIZES` in `backend/app/services/dashboard.py`
  have to agree, or the options form and the server's validation disagree
  too.
- The bullion stack (`services/stack.py`) never calls out from the item save
  path: `spot_at_purchase` only ever arrives typed in or from the backfill.
  Purchase-day spot comes only from the CC0 fawazahmed0 currency-api, never
  LBMA (its terms need a licence for valuation use).
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
safety backup (`-prerestore`, outside the retention), typed `RESTORE`,
unpack, database in one transaction, then the file swap; outcome and journal
on the state volume; `RESTORE_ENABLED` / `RESTORE_MAX_GB`. Admin-only and
password-confirmed from P8 A1 (v0.30.0); see "In-app restore" in the
implementation notes.
P10, a customisable dashboard, shipped in v0.27.0 (no migration):
`services/dashboard.py` and `routers/dashboard.py`, `dashboard_layout` in
`app_settings`, `/api/dashboard/layout` (`GET`/`PUT`/`DELETE`), and
`frontend/src/dashboard/`; the default layout reproduces the old fixed
page, reading is lenient and writing is strict, and the hand-written drag
listens on `window` rather than the handle; see "A customisable dashboard"
in the implementation notes.
P7, bullion stack figures, shipped in v0.28.0 (migration `0020`):
`services/stack.py` and `routers/stack.py`, `/api/stack` and
`/api/stack/backfill`, `/api/reference/historic-spot`, `spot_at_purchase`
and server-set `spot_at_purchase_source` on the item, `spot_alerts` /
`spot_alert_state` in settings, and the `stack` dashboard widget;
purchase-day spot comes only from the CC0 fawazahmed0 currency-api (never
LBMA, whose terms need a licence for valuation), cached ten years and
refusing today; a typed value is never overwritten by the hourly backfill;
see "Bullion stack figures" in the implementation notes.
Note details, the item page, and P10's "group C" widgets shipped in v0.29.0
(migration `0021`): `items.width_mm`/`height_mm`/`printer`/`watermark`/
`demonetized_on`, `services/insights.py` behind four `/api/stats/*`
endpoints, `components/item-hero.tsx` and `item-facts.tsx`, and ten
dashboard widget types; see "Note details, the item page, more widgets" in
the implementation notes.
P8 A1, sign-in and encrypted backups, shipped in v0.30.0
(migration `a0001`, the `cabinet_auth` schema and chain): one admin claimed
with a setup code, sessions, scoped API tokens, and a deny-by-default gate
(details in the rules below); see "Authentication and encrypted backups" in
the implementation notes and `docs/specs/SPEC_0300.md`.
P11, bars and rounds, shipped in v0.31.0 (SPEC_0310, staged 22 September
2026 as PR 22, branch `p11-bullion`): a third item type, `bullion` ("Bar or
round"), no migration. The rules that bite: `pricing.detect_metal` and
`pricing.parse_fineness` are the one detector and one parser a composition's
metal and fineness are ever read by, mirrored (never duplicated) in the
frontend's `detectMetal`; the year-or-ND rule and fancy serial traits don't
apply to bullion; nothing on the item save path ever makes a network call,
so a new bullion piece's melt estimate comes from the cached spot price
only; and Numista's bars and rounds are read by `object_type` (id 36, or
the name Bars/Rounds/Ingots/Bullion), never by a word in the title. See
"Bars and rounds" in the implementation notes.
P9, the share and showcase view, shipped in v0.32.0 (`docs/specs/SPEC_0320.md`,
built 23 September 2026 as PR 25 on `p9-share`; migration `0022`,
`share_links`): a read-only link to the collection, a set, or a checklist,
opened without signing in, the whole feature an admin setting off by
default. The rules that bite: `share` is a permission class of its own, and
the gate lets a `GET`/`HEAD` under its `/api/share/` prefix through before
any credential is looked up, so a session or a token on the request changes
nothing; what a piece shows is an allowlist (`services/share.py`'s
`FIELDS`/`GRADE_FIELDS` plus the six `show_*` toggles) pinned by a test,
never a cost, gain, storage location, document, serial number, or custom
field; while sharing is off the gate has no share rule at all (an anonymous
caller gets 401 like any unlisted path, from the in-memory switch
`share.enabled()`, no database read), and while on every failure (a
malformed, unknown, or revoked token, a target gone) is the same one `404`,
with the link resolved before the throttle is consulted, so a live link is
never 429'd and failed lookups live in a throttle map of their own; a public
route never makes a network call (values convert at cached rates only);
every stored photo is re-encoded without metadata (`photos.clean_bytes`,
the one-time `strip_existing` pass over originals and thumbnails, marker
`photos_clean`, and until that marker exists the share photo route cleans
each file on the fly); an in-app restore keeps the live `share_links` and
`share_enabled` over the archive's (a restore stopped mid-way leaves
`pending_sharing.json` on the state volume, applied after migrations); and the token is hashed (never stored plain) and redacted from
both logs (the backend's `uvicorn.access` filter and nginx's own
`access_log` rewrite the path to `[token]`). The security review that set
those rules is kept outside the repository (reviews are local from
v0.33.0; SPEC_0320 summarises its findings). An authenticating
reverse proxy kept in front must
exempt `/s/`, `/api/share/`, and `/robots.txt` from its own check, or it
blocks the app's own share links; see "Share and showcase view" in the
implementation notes and
[deployment.md](docs/deployment.md#sharing-and-the-forward-auth-exemption).
P8 A2, single sign-on, shipped in v0.33.0 (`docs/specs/SPEC_0330.md`,
reviewed twice before any code, as A1 and P9 were): OpenID Connect against
any provider, a GitHub button (GitHub has no ID token, so its identity
comes from a profile-endpoint call instead), and a trusted-header mode
verifying a gateway's **signed** assertion, never a shared secret. The
rules that bite: provider rows and the sign-in configuration live in
`cabinet_auth` and are read from the database on every use, never cached,
so a container command takes effect on the next request with no restart;
the provider's callback passes the gate with no credential lookup at all
and is bound instead to the one-use state in an encrypted, short-lived flow
cookie, and no other route may join that anonymous list without the same
binding; a session's `identity_id` is set so revoking a provider or an
identity ends exactly the sessions that came through it, before the row is
deleted, in one transaction; the trusted-header mode's header name is
checked against two identical blocklists (the backend and the proxy's start
script) so it can never be set to a header nginx or the gate already uses;
`GET /api/auth/state` never reads or verifies the header itself, only
whether the mode is configured, so a slow or wrong JWKS host can't stall
the sign-in page for everyone; and the keys for a signed assertion come
only from `TRUSTED_ASSERTION_JWKS_URL`, never from a header the gateway
also sends. **Cabinet builds no second factor of its own**: the identity
provider's own multi-factor check is the second factor, and the local
password is a deliberately one-factor recovery credential the container can
always reset. **The exposure advisory in `docs/deployment.md` is a hard
recommendation, not a formality**: Cabinet is for private networks, never
the internet, whatever sign-in method or gateway sits in front, and the
same paragraph is copied verbatim into security.md, README.md, SECURITY.md,
and `.env.example`. Review briefs and reviews stay local (gitignored), as
they have since v0.33.0's spec was reviewed.
**Next, in order:** the road to v1.0.0's remaining items: v0.33.0
validated on the owner's Swarm (docs/live-validation.md: Authentik,
Google, and GitHub sign-in, the trusted-header mode, an OpenVAS scan;
nothing destructive against the live instance), a CI check against a
breaking OpenAPI change, "Add a run" and the Numista banknote mapping
confirmed against a live account, and a README and quick-start pass, then
v1.0.0 itself; labels, a phone app, and more accounts are optional. Research
and propose each before building, as always. Before that, the roadmap's Phase 5.9
was demoted
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
