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

Nothing yet.

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

[Unreleased]: https://github.com/jsaumer/cabinet-numismatics/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/jsaumer/cabinet-numismatics/releases/tag/v0.9.0
