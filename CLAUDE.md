# Cabinet

Cabinet is a single-user, self-hosted web application for managing a coin and
paper money collection. Subtitle: "Numismatics: Coin & Paper Money Collection
Manager." Repo name is `cabinet-numismatics`; UI/display name is "Cabinet";
the OpenAPI title is "Cabinet API." **Public on GitHub under MIT, released as v0.41.0, and deployed on the owner's
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
docker-compose.yaml      single-host stack, built from source (reads .env)
deploy/docker-compose.yaml  the same from the published images: one file,
                         nothing beside it (the README's quick start)
deploy/docker-stack.yaml Swarm stack (pulled images)
.env.example / .env (gitignored)
README.md, CLAUDE.md (this file), CHANGELOG.md
docs/                    features, architecture, data-model, api, price-sources,
                         deployment, security, backup-restore, monitoring,
                         live-validation, roadmap, implementation-notes,
                         claude-code; specs/ holds build contracts;
                         screenshots/ and import-samples/ hold generated
                         assets; review briefs and reviews stay local
                         (gitignored) from v0.33.0
proxy/nginx.conf
backend/                 FastAPI app, Alembic migrations, pytest suite
frontend/                React + Vite app; e2e/ holds the Playwright tests,
                         public/ the logo and favicon (see frontend/README.md)
scripts/                 backup.sh, restore.sh, seed_demo.py
```

## Conventions

- Proper git project with maintained documentation. When behavior changes,
  update every affected document in the same commit, not only the changelog:
  `docs/features.md` (the full feature list, and its comparison table
  when a row changes), `README.md` (the short version: a bullet only when
  the feature is worth one), `docs/api.md`, `docs/roadmap.md` (what shipped,
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
- American spelling in everything a person reads: UI text, messages, docs,
  the changelog, commit messages, and new comments (color, catalog,
  customizable, demonetized, canceled, gray, license). Switched over in
  v0.35.1. Identifiers and data stay as they are: `catalogue_fields`,
  `routers/catalogue.py`, Numista's `catalogue` field, and the spreadsheet
  import's "catalogue" header alias, so renaming those is never part of a
  spelling fix.
- Config via environment variables in `.env`; never commit real secrets.
  `.env.example` is the committed template.

## Build & run

- Full stack: `docker compose up --build`, then nginx serves at
  http://localhost/ (no API docs page; the schema is `/api/openapi.json`).
  `PUBLIC_ORIGINS` is required (backend and proxy stop without it); nginx
  answers only its Host names, and any other gets one static page saying so
  (421, v0.41.0; never the app). The three Compose files pass the same
  settings (a test compares them), and `scripts/ci/quick-start-test.sh`
  walks the README's first run in CI. The frontend is
  built inside the proxy image (multi-stage `frontend/Dockerfile`), so no host
  Node install is needed.
- Frontend dev: `npm run dev` in `frontend/` (the Vite dev server proxies
  `/api` to localhost:8000). Production build output is `frontend/dist`.
- Backend dev: `uvicorn app.main:app --reload` with `DATABASE_URL`,
  `PHOTO_DIR`, and `DOCUMENT_DIR` set, `REQUIRE_DOCUMENT_MOUNT=false`, and
  `PUBLIC_ORIGINS=http://localhost:5173` with `AUTH_INSECURE_HTTP=true`.
- Tests: in `backend/`, `pip install -e .[dev]` once, then `pytest`. Tests do
  not require a running database (in-memory SQLite, every outbound call
  mocked). CI (`.github/workflows/ci.yml`) runs ruff + pytest on 3.10/3.15, a
  frontend typecheck, the smoke script against the stack on a native arm64
  runner (v0.40.0), an upgrade job (from v0.29.1, and from the newest
  release and v0.30.0 with the old release's own archive restored in the
  app: `scripts/ci/upgrade-restore-test.sh`), and a compose build/migrate/smoke job that drives the
  API with curl (smoke test, backup → restore drill) and the pages with
  Playwright (`frontend/e2e/`, `npm run e2e` against a running stack,
  `BASE_URL` for another host). When an endpoint's or a page's behavior
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

Released as v0.41.0: roadmap Phase 7 is complete, migrations
`0001`–`0024` and `a0001`–`a0002`. v0.27.1 fixed two bugs found entering real pieces: a year is
now optional (an ND checkbox with an optional attributed year), and a
same-year Numista variety with no prices no longer blocks the one that has
them. v0.29.0 added note details (width/height, printer, watermark,
demonetization) and reworked the item page into a hero plus grouped facts,
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
- Reading an item never validates it: `ItemOut` is built from `ItemBase`'s
  fields without their rules (`schemas._ItemRead`), so no stored row can
  500 a list page. Rules belong on input models only, every input is
  bounded by its column (SQLite won't catch a missing bound; see
  `tests/test_hardening.py`), a currency input is `schemas.Currency`, and
  `pricing.melt_on_save` never adds a melt value above a typed-in one or
  another source's. See "Review fixes" in the implementation notes.
- An outbound fetch that failed is not retried for two minutes (rates and
  spot prices; stale stands in), a free-text export cell goes through
  `items._csv_safe`, history rows come from `items._changed`, and
  `restore.sh` restores the database only through
  `python -m app.cli restore-database`, never `pg_restore` itself. See
  "Review fixes, second batch" in the implementation notes.
- **The API contract** (v0.38.0): `docs/openapi.json` is the last release's
  schema, and `backend/tests/api_contract.py` (run by
  `tests/test_api_contract.py`) fails the suite on a removed path,
  operation, parameter, field, or listed value, a changed type, or a newly
  required input. An addition needs nothing. A breaking change that is
  meant (before 1.0 only) is `python -m tests.api_contract update
  --allow-breaking` in `backend/` plus a changelog entry with the old and
  new forms; from 1.0.0 the tool refuses without a new major version. Every
  release PR runs `python -m tests.api_contract update`, since a test
  fails while the committed schema names another version.
- **The item answer carries `latest_estimates`** (v0.39.0), the newest per
  source; a list that grows by itself gets its own paged route
  (`{items, total, limit, offset}`), never a place on the item. The API's
  `source_key` is `sources.key_of` (`manual` for every typed-in value);
  `pricing.source_key` keeps typed sources apart for the blend.
- **1.0's promise is wider than the schema**: "What else is promised" in
  docs/api.md (statuses, error bodies, environment variables, container
  commands, archives, exports, upgrades, share links, metrics). Read it
  before changing any of those; the contract check sees almost none of it.
- **The web interface carries its release** (after v0.41.0):
  `frontend/vite.config.ts` bakes in the version from
  `backend/pyproject.toml`, `src/version.ts` is its one reader, and a
  notice shows on every page when `/api/health` reports another. The
  version still lives in one file. The web app manifest
  (`public/manifest.webmanifest`) has no service worker behind it, on
  purpose. See "Small items before 1.0" in the implementation notes.
- A share link shows no value from `share.PRIVATE_SOURCES` (Numista and
  PCGS: both licenses keep their data from third parties), and every page
  carries PCGS's credit once anything from PCGS is held
  (`services/credits.py`, the agreement's own sentence, at least 10-point
  type). docs/data-sources.md is what users are told about each service's
  terms and must change with the code.
- A tag is one per name whatever the capitals (`services/tags.py`, the
  unique index on `lower(name)`), and a Numista reference is stored as
  `N#<digits>` (`services/refs.py`; `schemas.CatalogRefIn` refuses anything
  else, `CatalogRefOut` has no rules). A typed-in estimate's `source` can't
  be a price source's name (`schemas.RESERVED_SOURCES`), and a LIKE filter
  escapes what was typed (`items._like`).
- `item.year` can be `None`: an undated piece is `year_nd` true, with an
  optional attributed year. Guard `None` anywhere that does arithmetic on
  it, and print `year_label` (`"1922"`, `"ND"`, `"ND (1922)"`), never `year`
  itself.
- A proof or mint set (`mint_set`, v0.37.0, SPEC_0370) is one item for the
  whole set: it needs a year and is never ND, takes no grade on the form,
  has no Numista or PCGS price, and its metal counts in the stack only when
  `count_in_stack` is ticked. `stack.counts(item)` is the one answer to
  that (the stack, `needs_spot`, the gauge); melt and `fine_oz` never ask
  it. A type is described once on the frontend (`components/item-types.tsx`,
  `TYPE_INFO`), and a set's title (year, issuer else country, set name) is
  built in five places that must agree: `Item.label`, `_name_key`, the list
  row, the item hero, and `shareItemLabel` (plus the report).
- Adding or retiring a dashboard widget touches both sides: the frontend
  `REGISTRY` in `frontend/src/dashboard/registry.tsx` and the backend
  `WIDGET_OPTIONS`/`DEFAULT_SIZES` in `backend/app/services/dashboard.py`
  have to agree, or the options form and the server's validation disagree
  too.
- The bullion stack (`services/stack.py`) never calls out from the item save
  path: `spot_at_purchase` only ever arrives typed in or from the backfill.
  Purchase-day spot comes only from the CC0 fawazahmed0 currency-api, never
  LBMA (its terms need a license for valuation use).
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
P10, a customizable dashboard, shipped in v0.27.0 (no migration):
`services/dashboard.py` and `routers/dashboard.py`, `dashboard_layout` in
`app_settings`, `/api/dashboard/layout` (`GET`/`PUT`/`DELETE`), and
`frontend/src/dashboard/`; the default layout reproduces the old fixed
page, reading is lenient and writing is strict, and the hand-written drag
listens on `window` rather than the handle; see "A customizable dashboard"
in the implementation notes.
P7, bullion stack figures, shipped in v0.28.0 (migration `0020`):
`services/stack.py` and `routers/stack.py`, `/api/stack` and
`/api/stack/backfill`, `/api/reference/historic-spot`, `spot_at_purchase`
and server-set `spot_at_purchase_source` on the item, `spot_alerts` /
`spot_alert_state` in settings, and the `stack` dashboard widget;
purchase-day spot comes only from the CC0 fawazahmed0 currency-api (never
LBMA, whose terms need a license for valuation), cached ten years and
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
v0.33.0; SPEC_0320 summarizes its findings). An authenticating
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
**v0.34.0 (14 October 2026)** shipped the workbench layout: a sidebar shell, the collection as a list with the selected piece in an inspector, facts edited in place, and a lookup-first quick add at `/items/add`; see "The workbench layout" in the implementation notes. v0.34.1 put the dashboard first in the sidebar and made the list's Piece, Grade, and Value headings sort it (`sort=name` mirrors the row title). v0.35.0 added four color themes (Bronze, Silver, Album, Ledger) chosen in Settings → General and saved through `/api/appearance`; a theme lives in five places that must agree, see "Color themes" in the implementation notes. v0.35.2 made the logo and tab icon follow the theme (files written by `scripts/theme_icons.py`). v0.36.0 gave the demo collection public domain photos from Wikimedia Commons (`scripts/seed_demo.py`, `--no-photos` to skip) and a URL import that names itself (`photos.REMOTE_USER_AGENT`). v0.37.0 added proof and mint sets as a fourth item type (SPEC_0370, migration `0023`; Numista's export imports each set as one, by its "From set" title) and carried Numista's 2026 terms (no Numista value on a share link, sales records on the free plan); see "Proof and mint sets" and "Numista's 2026 terms" in the implementation notes. v0.37.1 fixed the Numista export import's denomination (the title's, without the nickname) and read both of its reference columns. v0.37.2 moved the backend image (and CI's top Python) to 3.15. v0.37.3 fixed five bugs a full review (9 November 2026) reproduced on a running stack: a bulk type change that made the list page a 500, a melt value burying a typed-in one, a stale dashboard, 500s for values with no room in their column, and lower-case currencies; see "Review fixes" in the implementation notes. v0.37.4 raised `opentelemetry-api` in the lockfile past a denial-of-service advisory the weekly audit flagged, and carried the condensed README with `docs/features.md` (the full feature list and a comparison with OpenNumismat, CoinManage, and Numista). v0.37.5 was the review's second batch (26 November 2026): `scripts/backup.sh` had written no full backup since v0.30.0, `scripts/restore.sh` now restores through the backend and migrates, four 500s became answers, failed rate and spot fetches back off, and exports, the URL photo import, the sign-in limit, and the generated key were hardened; see "Review fixes, second batch" in the implementation notes. v0.38.0 (26 November 2026) added the API contract check (`docs/openapi.json`, `backend/tests/api_contract.py`) and tightened four inputs before 1.0 (migration `0024`): a typed-in estimate's source, `%` and `_` in a search, one tag per name whatever the capitals, and one form for a Numista reference; see "The API contract check and the last input rules" in the implementation notes. v0.39.0 (26 November 2026) settled four contract decisions before 1.0: the item answer carries `latest_estimates` with the history and edit log as paged routes (breaking), `docs/api.md` gained the wider promise and what today's fields will keep meaning, a share link hides PCGS values, every page shows PCGS's credit once its data is held (`GET /api/reference/data-credits`), and `docs/data-sources.md` tells users each service's terms; see "Four contract decisions" in the implementation notes. v0.40.0 (26 November 2026) was packaging only: both images for arm64 as well as amd64 (one composite action, `.github/actions/build-images`), a native arm64 CI job, every action pinned by commit, labels, provenance and an SBOM on each image, and `1`/`1.0` tags from 1.0.0; see "Images for arm64, and the release's supply chain" in the implementation notes. v0.41.0 (26 November 2026) was the first run: `deploy/docker-compose.yaml` (the published images, one file, the README's quick start), a static 421 page for a wrong Host where nginx returned 444, plain http on a trusted LAN documented as a supported way to start, `docs/https-private-network.md`, and `scripts/ci/quick-start-test.sh` in CI; see "The first run" in the implementation notes.
**Next, in order:** the road to v1.0.0's remaining items ("Add a run" and
the Numista banknote mapping confirmed against a live account, and a README
and quick-start pass), then v1.0.0 itself; the CI check against a breaking
OpenAPI change and the last input rules shipped in v0.38.0 (see "The API
contract check and the last input rules" in the implementation notes), and
the four contract decisions after them shipped in v0.39.0 ("Four
contract decisions"), with two questions left for the owner to send: to
Numista about catalog facts on a share link, and to PCGS about whether a
private collection is a use its agreement covers; labels, a phone app, and more accounts are
optional. Research and propose each before building, as always. Before
that, the roadmap's Phase 5.9 was demoted
on 19 September 2026 from a release train to one next item plus unordered
**candidates** and **parked** items: the owner is entering 100–500 pieces by
hand (runs and singles, mostly held), so don't build ahead of that beyond
Phase 7: friction they report still comes first, and the pipeline statuses,
tax lots, submissions, and slab scanning stay parked.

Releases: pushing a `v*` tag runs CI's `publish` job, which pushes
`ghcr.io/jsaumer/cabinet-numismatics-{backend,proxy}` (version, plus
`latest` on a stable tag only; nothing before v0.10.2 is published). A
release candidate is tagged `v1.0.0-rc.1` with pyproject at `1.0.0rc1`;
the job refuses a tag that doesn't match pyproject's version. From v0.40.0
the images are built for amd64 and arm64 with labels, provenance, and an
SBOM (`.github/actions/build-images`; `images.yml` runs the same build
without pushing when a pull request touches a Dockerfile, a lockfile, or
`proxy/`), every action in a workflow is pinned by commit hash (a test
fails otherwise), and from 1.0.0 a stable tag also moves `1` and `1.0`.
The release
PR also rewrites `docs/openapi.json` (`python -m tests.api_contract update`
in `backend/`; a test fails until it names the new version). The live homelab instance pins those
tags, so a release reaches it only once the tag's images exist; the backend
migrates on startup, so an upgrade there is just a tag bump.
**The GitHub Releases list is curated** (the owner's decision, 18 October
2026): one page per milestone, 15 from v0.9.0 to v0.36.0, each carrying
the notes of the versions folded into it; the other 45 releases and their
tags were deleted (their GHCR images stay). From here to 1.0 a minor gets
a release page; a patch is still tagged, so its images build, but gets no
page of its own: add its notes to its minor's page under a `## vX.Y.Z`
heading. CHANGELOG.md keeps every version.

## Notes for working in Claude Code (desktop app)

- Cabinet is developed with Claude Code in the Claude desktop app (Code tab),
  editing the working tree directly. There is no zip/flatten step here (that
  was specific to the earlier chat-based file delivery).
- Keep this file and `docs/` in sync with the code. If you correct the same
  thing twice across sessions, write it down here or, if it's about one
  area, in docs/implementation-notes.md.
