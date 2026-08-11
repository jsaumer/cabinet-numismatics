# Changelog

All notable changes to Cabinet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Database changes always ship as Alembic revisions; after upgrading, run:

```bash
docker compose up --build -d
docker compose exec backend alembic upgrade head
```

## [Unreleased]

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
