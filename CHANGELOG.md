# Changelog

All notable changes to Cabinet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Database changes always ship as Alembic revisions. From 0.11.1 the backend
applies them itself on startup; for earlier releases, run
`docker compose exec backend alembic upgrade head` after upgrading.

## [Unreleased]

### Added
- **Sales log and comps estimates** (sold-listing comparables). Each item has
  a sales log of what pieces like it actually sold for — date, where (with a
  link and lot), the grade as sold, price, whether buyer's premium is
  included, and any fees on top. A new **comps** price source estimates the
  median of recent logged sales (the last three years, or older ones when
  fewer than three are that recent), converted into the display currency,
  with confidence from the number of sales and how far apart they are. The
  sales behind each estimate show in its value-history details, and a sale
  can be left out without deleting it. Comps works everywhere a source does:
  the value strategy (preferred or averaged), the item list's source column,
  and the Pricing reports. The item page also lists free places to look up
  sold prices.
- **Numista auction sales** (Settings → Price sources, off by default): a
  button on the sales log that copies the auction results Numista records
  for the item's year and mint into the log. **This needs Numista's paid API
  plan** — a free key gets "Permission denied", which Cabinet explains
  rather than reporting a bad key. Runs only when clicked; a repeat the same
  day is served from cache.
- `scripts/check_sources.py` probes `comps` and `numista-sales` too.
- API: `GET/POST /api/items/{id}/comparables`,
  `PATCH/DELETE /api/comparables/{id}`, `POST /api/items/{id}/comparables/numista`;
  `?source=comps` on `POST /api/items/{id}/estimate`; item details include
  `comparables`. Migration `0013` adds the `comparables` table.

### Changed
- Numista catalogue data (a type, its issues, and searches) is cached for 7
  days instead of 30 — the longest Numista's API licence allows.

## [0.16.0] — 2026-09-18

### Added
- **Photo tools on the item page** (the roadmap's "photo niceties" bundle):
  - **Lightbox**: click a photo to view it full size; click or scroll to zoom
    where you point, move the pointer to pan, ←/→ to step through, Esc to
    close.
  - **Edit**: crop, turn 90°, and straighten (±15°, scaled so no empty
    corners appear) in the browser at full resolution, then replace the photo
    or save the edit as a new photo.
  - **Drag and drop** image files onto the Photos card, or **paste** an image
    anywhere on the item page.
  - **Import from URL**: the backend fetches the image, following up to three
    redirects and stopping at 25 MB, and refuses private and local network
    addresses.
  - **Webcam**: take photos straight into the item from a webcam or a phone's
    camera (needs HTTPS or localhost).
  API: `POST /api/items/{id}/photos/url` and `PUT /api/photos/{id}/image`.

### Changed
- **The dashboard is the home page**, first in the menu; the collection list
  moved to `/collection`. Old links still work: `/dashboard` and `/` with list
  filters redirect to the new addresses.
- Photo upload errors show on the Photos card instead of replacing the whole
  item page.

## [0.15.0] — 2026-09-15

### Added
- **Fill an item in from the Numista catalogue.** The item form's new
  **Fill from Numista** card takes a Numista number (`N#1493`, or just
  `1493`) or a name search, and fills the fields that are still empty:
  country, denomination, series, composition, fineness (read from the
  composition for precious metals), weight, diameter, thickness, edge, and
  shape for coins; country, denomination, and issuing bank for notes; the
  year when the type has only one. It adds the Numista number and the type's
  other catalogue references (KM, Pick…) as catalog refs, and lists the
  type's issues so picking one sets the year, mint mark, and mintage.
  API: `GET /api/numista/search?q=&category=` and
  `GET /api/numista/types/{id}`.
- Lookups need only a Numista API key, not Numista pricing switched on.
  They use the same cache and quota as pricing: a search or a type costs one
  request, cached for 30 days, and a type's issues share their cache entry
  with Numista estimates.

## [0.14.0] — 2026-09-15

### Added
- **Grading depth.** A strike type on every item (business, proof, specimen):
  a proof or specimen on the Sheldon scale reads PR-/SP- with the same grade
  number. Plus grades, the NGC/PMG star, designations (PL, DMPL, CAM, DCAM,
  UCAM, RD, RB, BN, FB, FBL, FH, FS, FT, and PMG's EPQ), CAC stickers, and
  "details" grades recording the problem (cleaned, damaged…). Items carry a
  `grade_label` that reads like the holder — `PR-69 DCAM ★`, `MS-64+ RD`,
  `VF-20 Details (Cleaned)` — shown in the list, item page, and report. PMG's
  grades 1–3 are now on the scale.
- **Coin physical fields** — diameter, thickness, edge, shape, mintage — and
  **banknote fields**: serial number, prefix/block, signatures, issuer, and a
  replacement/star-note flag. Serial numbers, prefixes, and issuers are
  searchable.
- **Fees in gains.** `acquisition_fees` (buyer's premium, shipping, tax) count
  toward cost basis; `sold_fees` and `sold_to` record the sale. Items expose
  `cost_basis` and `sale_proceeds`.
- **Certificate verification links** on the item page: PCGS opens the
  certificate directly; NGC and PMG open their lookup pages.
- A **strike filter** on the list (`?strike=`), and all new fields in CSV/XLSX
  export and CSV import. Import also reads grades written the way holders
  write them: `PR-65`/`PF-65`/`SP-65` set the strike, and a trailing `+` sets
  the plus grade.

### Changed
- **Cost basis, unrealized and realized gain are net of fees** everywhere —
  dashboard, gains tables, breakdowns, and the insurance report's Cost column.
  The accuracy report still compares estimates with the gross sold price,
  since estimates are market prices.
- **Numista no longer prices proofs, specimens, or details grades** — its
  prices are for problem-free circulation strikes. **PCGS** passes the plus
  grade through, labels proofs PR-, and prices a details-graded coin only by
  its cert number.

### Fixed
- CSV import no longer loses the rows it had already imported when a later
  row fails validation.

### Upgrade notes
- Revision `0012` adds the new item columns and PMG grades 1–3; the backend
  applies it on startup.

## [0.13.0] — 2026-09-14

### Added
- **Pricing reports** — a new **Pricing** page (also linked from the
  dashboard's "based on X of Y owned items" line) with four reports:
  - **Coverage**: per automatic source, how many owned items are priced,
    can't be priced, failed, or haven't been tried — and for each item that
    needs attention, why: the source is off, a prerequisite is missing (no
    catalog ref, no grade, no weight…), what the source itself said, or the
    fetch error.
  - **Stale estimates**: each item's latest estimate per source older than
    7/30/90/365 days (manual entries included), plus any built from source
    data already past its cache window, marking which ones feed the shown
    value.
  - **By source**: items priced, total, average confidence, and median age
    per source; how many items' shown value each supplies under the current
    value strategy; and the items where sources disagree most.
  - **Accuracy against sales**: for sold items, the estimates standing on
    the sale date against the realized price — median error, bias, and how
    many landed within 20%, for the shown value and for each source.
  API: `GET /api/pricing/coverage`, `/stale?days=`, `/sources`, `/accuracy`.

### Changed
- Every automatic pricing attempt — from the item page or the scheduled
  refresh — now records its outcome per item and source (revision `0011`,
  `estimate_attempts`), so a failed fetch or an upstream "can't price this"
  is visible later instead of vanishing with the error message. Applied
  automatically on startup.

## [0.12.0] — 2026-09-14

### Added
- **Backups from inside the app** (Settings → Backups). **Download backup**
  builds one `.zip` holding the database dump, the photos, a
  `manifest.json` (app version, schema revision, counts, SHA-256 per member),
  and a `SHA256SUMS` file; **Data only** leaves the photos out. **Scheduled
  backups** write archives daily or weekly into a backup directory, keep the
  newest N, retry a failed run within the hour, and show the last outcome.
  **Back up now** writes one on demand, and stored archives are listed for
  download. API: `GET /api/backup.zip`, `GET`/`POST /api/backups`,
  `GET /api/backups/{name}`; settings `backup_schedule`, `backup_keep`,
  `backup_include_photos`.
- `scripts/restore.sh` restores an in-app archive directly: it verifies the
  checksums first, and a data-only archive restores the database without
  touching photos.
- CI rehearses a restore on every push: download an archive, delete an item,
  restore, and check the item is back.

### Changed
- The backend image carries `pg_dump` and `pg_restore` for PostgreSQL 14–18
  and dumps with the one matching the server's major version, so archives
  restore with the server's own `pg_restore`.
- nginx gives `/api/backup*` up to 30 minutes to respond, since an archive is
  built before the download starts.

### Upgrade notes
- `docker-compose.yaml` adds a `backup_data` volume mounted at `/data/backups`
  (`BACKUP_DIR`). **On a Swarm or custom stack, mount a directory there** —
  ideally NAS storage — or scheduled archives live inside the container and
  disappear with it. It must not be inside the photo directory; the backend
  refuses that, because nginx serves photos publicly.
- The backup endpoints are unauthenticated, like the rest of the API, and one
  request returns the whole collection. Keep Cabinet behind an
  authenticating proxy (see docs/deployment.md).

## [0.11.1] — 2026-09-14

No manual migration step from this release on: the backend applies pending
migrations itself when it starts (set `AUTO_MIGRATE=false` to opt out).

### Added
- **Settings → About** shows the running version (linked to its release) and
  the database schema: current revision, and whether it's up to date, waiting
  on a migration, or ahead of this build. `GET /api/health` reports the same
  under a new `schema` field.

### Changed
- **The backend applies database migrations itself on startup**, before it
  serves anything — upgrading is now just deploying the new image, with no
  separate `alembic upgrade head`. All pending migrations run in one
  transaction under a Postgres advisory lock; a failure rolls back and stops
  startup instead of leaving new code running on an old schema. On Swarm,
  where there's no startup ordering, the backend waits up to 60 seconds for
  Postgres first. Set `AUTO_MIGRATE=false` to keep running migrations by hand.
  Going back to an older image still doesn't undo a migration.

### Fixed
- The backend's own INFO logs never reached the container log — uvicorn only
  configures its own loggers — so scheduled price refreshes ran silently. The
  `app` and `alembic` loggers now log at INFO, which also shows migrations
  applied at startup.

## [0.11.0] — 2026-09-14

After upgrading, run `alembic upgrade head` (revision `0010`).

### Added
- **Estimate provenance** (pricing program M4). Automatic estimates now keep
  what produced them in a new `price_estimates.details` column (revision
  `0010`) instead of just a value and a terse source string: melt records the
  weight, fineness (and whether it came from the field or the composition
  text) and spot price; Numista the matched issue, the grade wanted versus
  priced, and the full per-grade price list; PCGS the lookup, the auction lots
  behind the median, the price-guide value, and the CoinFacts link. Each also
  records when the upstream data was fetched and whether a stale cached copy
  was served because a refresh failed. On the item page, a "details" toggle
  under each value-history row shows it.
- Value history on the item page can be filtered by source; the chart then
  plots one source at a time instead of zig-zagging between them.
- Manual values take an optional note (up to 500 characters), kept and shown
  the same way.

### Changed
- On-demand and scheduled estimates now build their rows through one helper
  (`pricing.estimate_row`); the scheduled melt refresh had been dropping
  `sample_size`. `pricing.cached_response` became `cached_fetch`, which also
  returns when the payload was fetched.

## [0.10.2] — 2026-08-12

### Added
- **Published images.** Tagged releases now build and push
  `ghcr.io/jsaumer/cabinet-numismatics-backend` and `...-proxy` to GHCR
  (`.github/workflows/ci.yml`, `publish` job), tagged with both the release
  version and `latest`. `docker-compose.yaml` gained matching `image:`
  entries alongside its existing `build:` blocks — local dev keeps building
  from source with `docker compose up --build`, while `docker stack deploy`
  (which cannot build at all) now has something to pull. Documented in
  `docs/deployment.md` §7, including the two Compose keys (`depends_on`,
  `restart`) that Swarm doesn't honor and what that actually means in
  practice for this stack.

### Changed
- `nginx.conf` is now baked into the proxy image at build time instead of
  bind-mounted from the host — a bind mount can't be relied on to exist
  across every node in a multi-host deployment. The proxy image's build
  context moved from `frontend/` to the repo root so its Dockerfile can
  reach `proxy/nginx.conf`; a new root `.dockerignore` keeps that context
  from also picking up `backend/`, `.git`, and other irrelevant content.

## [0.10.1] — 2026-08-11

### Added
- A `SOURCE` column on the collection list, next to `VALUE` — the blended
  value shown there was giving no indication of which price source (or
  "average") it came from. Backed by a real schema change: `GET /api/items`
  entries now carry `latest_value_source`, resolved by the same
  `pricing.resolve_display_value` used for the value itself, not guessed
  separately on the frontend.

### Fixed
- The item page's per-source value chips could wrap mid-pill (value on one
  line, the "time since" label pushed to a second) once a source's key or
  timestamp made a chip too wide for its grid cell. Chips now lay out in a
  wrapping flex row spanning the full card width, each pinned to a single
  line.

## [0.10.0] — 2026-08-11

### Added
- **Numista price adapter** (pricing program M2) — coins *and* notes priced by
  their `numista` catalog reference and grade. `POST /api/items/{id}/estimate`
  takes a `?source=` parameter (`melt`, the default, or `numista`), and the
  item page shows a button per configured source. Requires a free Numista API
  key in Settings; the source stays off until you switch it on.
- New `source_cache` table (revision `0009`) caching upstream price-source
  responses — Numista catalogue data for 30 days, prices for 7 — so repeated
  estimates don't burn the free tier's 2,000 requests a month. A stale entry
  is preferred to a failed request, matching how spot prices and exchange
  rates behave.

- **PCGS price adapter** (pricing program M3) — US coins priced by PCGS cert
  number, or by `pcgs` catalog reference + Sheldon grade, via
  `?source=pcgs`. CoinFacts returns both numbers in one request: realized
  auction prices win when PCGS has any (median of up to the ten most recent
  lots, confidence 0.85 with five or more sales, 0.75 below), and the price
  guide is the fallback at 0.60. Coins only — PCGS Banknote responses carry
  no price fields. Requires a token from pcgs.com/publicapi.

- `backend/scripts/check_sources.py` — runs one price adapter against one real
  item and prints the upstream calls, the raw payload, and the parsed
  estimate, without saving anything. The unit tests prove the parsing; this
  checks the contract. Ships in the backend image, so
  `docker compose exec backend python scripts/check_sources.py --list` works.
  Long string fields in a payload (e.g. PCGS's `CoinFactsNotes` essays) are
  now trimmed like long lists already were.

- **Per-source value display and a configurable value strategy.** With more
  than one price source configured, they don't agree — the item page now
  shows each source's own latest value as a chip instead of collapsing to
  whichever is newest. A new `value_strategy` setting (Settings → General)
  controls the single blended number used everywhere else (items list,
  CSV/XLSX export, dashboard totals): latest estimate (default, unchanged
  behavior), a preferred source (falling back to latest if that source
  hasn't priced the item yet), or an average across melt/Numista/PCGS
  (currency-converted; manual entries excluded from the average for now).

- **Scheduled auto-refresh for Numista and PCGS, and item-level freshness.**
  The existing 12h melt-refresh loop now also refreshes each owned item's own
  Numista and/or PCGS estimate independently of whichever source currently
  wins the item — needed since `value_strategy` can be "preferred source" or
  "average," where a non-winning source still needs its own data current.
  Both are off by default: Numista offers 7/14/30-day cadences (Settings
  shows the real projected monthly call count against the free tier's
  2,000/month, since Numista costs 2 calls per estimate against PCGS's 1),
  PCGS is a simple weekly on/off (its 1,000 calls/day quota comfortably
  covers weekly refresh at any realistic collection size). `GET /api/settings`
  now reports `numista_priceable_items`/`pcgs_priceable_items` to drive that
  math. The item page's per-source value chips now show a relative
  "time since" next to each value, and manual per-item refresh buttons now
  show a success message, not just silence on success / an error on failure.
  The blended value shown in the items list/export/dashboard has no single
  "since" timestamp when averaging sources, so this freshness label is
  deliberately scoped to the item detail page only.

### Changed
- Price adapters now share one contract: `NotApplicable` for a missing
  prerequisite (422) and `SourceUnavailable` for an upstream failure (502).
  `SpotUnavailable` is a subclass, so melt behavior is unchanged. Response
  caching is shared too (`pricing.cached_response`).

## [0.9.1] — 2026-08-10

No user-facing changes: no schema change (still revision `0008`), no API
change, and identical application behavior. This release exists mainly
because the test suite could not be run from a fresh checkout of 0.9.0.

### Fixed
- `pytest` failed on a clean clone with nine collection errors
  (`ModuleNotFoundError: No module named 'tests'`). The suite needs the
  project root on `sys.path`; that only happened by accident under legacy
  editable installs, which add the whole directory, while modern setuptools
  exposes just the configured `app*` packages. Fixed with
  `pythonpath = ["."]` in the pytest config.
- Committed `frontend/package-lock.json`. Without it, CI's Node setup had no
  lock file to cache from, and every build floated to the newest matching
  dependency versions. CI and the container build now use `npm ci`.

### Changed
- Base images updated: backend to Python 3.14, frontend build to Node 26,
  proxy to nginx 1.31. The CI matrix now covers Python 3.10 (the supported
  floor) and 3.14 (what the container runs).
- GitHub Actions updated: `checkout` v7, `setup-node` v7, `setup-python` v7.
- Frontend toolchain updated: Vite 8, `@vitejs/plugin-react` 6, TypeScript 7.
  Vite 8 and the plugin must move together — their peer ranges don't overlap
  across the boundary. TypeScript 7 also requires `src/vite-env.d.ts`, which
  supplies the type declarations for `import './styles.css'`.

### Added
- `frontend/src/vite-env.d.ts` referencing Vite's client types.

## [0.9.0] — 2026-08-09

First public release. Pre-1.0 signals that the HTTP API may still change; the
data model and migration path are considered stable.

### Cataloging
- Coins and notes with country, denomination, year, mint mark, series,
  variety, composition, weight, fineness, quantity, and notes.
- Sheldon and PMG grading scales, seeded by migration; certification tracking
  (service + cert number).
- Provenance (acquisition date, price, source), storage location, and
  `owned` / `sold` / `wishlist` status with sold date and realized price.
- Tags, catalog references (Krause / Numista / Red Book), sets and lots, and
  up to 20 custom fields per item.
- Search across notes, series, variety, cert numbers, catalog refs, and tags;
  combined filters for type, status, country, year range, grade range,
  latest-value range, tag, and set; filters and paging persist in the URL.
- Clone an item, bulk-edit a selection, and per-item append-only edit history
  with field-level diffs.
- Completeness checklists for target sets, with progress tracking.

### Photos
- Multiple photos per item with angle designation, a primary image, and
  reordering; multi-file upload and a direct camera input on mobile.
- Uploads are validated as real JPEG/PNG/WebP by decoding them; EXIF
  orientation is corrected and thumbnails are generated automatically.

### Valuation
- Manual estimates with source and optional confidence, stored append-only.
- Melt-value estimates (spot × weight × fineness × quantity) with the metal
  detected from composition; spot prices cached 12h with stale fallback.
- Scheduled re-estimation of stale melt values; a melt refresh never
  supersedes a manual value.
- Multi-currency totals converted at cached daily ECB rates; amounts with no
  obtainable rate are excluded and counted rather than guessed.
- Collection and per-item value-over-time charts.

### Insights and reporting
- Dashboard with collection value, cost basis, realized and unrealized
  gain/loss, breakdowns by country, type, decade, grade and tag, and
  acquisitions by year.
- CSV and Excel export honoring the current filters; CSV import round-trips
  the export format with per-row error reporting and id-based deduplication.
- Print-optimized insurance report (browser Print → PDF).

### Platform
- Three-service Docker Compose stack (nginx proxy, FastAPI backend,
  postgres); the frontend builds inside the proxy image, so no host Node or
  Python is required.
- Alembic migrations end to end (revisions `0001`–`0008`).
- Settings page for display currency, melt cadence, and price-source
  credentials. Credentials are **encrypted at rest** (Fernet, with key
  rotation via `SECRET_KEY`) and are write-only through the API.
- Backup and restore in one script pair covering the database and photos
  together, with a rehearsed restore drill.
- Dark mode, responsive layout, and auto-generated OpenAPI docs.
- `GET /api/health` reports status, database reachability, and version.

### Known gaps
- No application-level authentication — deploy behind an authenticating
  reverse proxy. See [docs/security.md](docs/security.md).
- Sold-listing comparables are not integrated (eBay's Marketplace Insights
  API is closed to new applicants); record those values manually.
- Numista and PCGS adapters are planned; their credentials can be configured
  in Settings already.
- Photo lightbox, drag-and-drop upload, URL import, and in-browser editing
  are not built yet.

[Unreleased]: https://github.com/jsaumer/cabinet-numismatics/compare/v0.9.1...HEAD
[0.9.1]: https://github.com/jsaumer/cabinet-numismatics/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/jsaumer/cabinet-numismatics/releases/tag/v0.9.0
