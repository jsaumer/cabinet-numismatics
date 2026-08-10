# Cabinet

**Numismatics — Coin & Paper Money Collection Manager**

[![CI](https://github.com/jsaumer/cabinet-numismatics/actions/workflows/ci.yml/badge.svg)](https://github.com/jsaumer/cabinet-numismatics/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-0.9.0-informational)

A self-hosted, single-user web application for cataloging a coin and paper
money collection, managing photos of each item, and tracking estimated market
value over time. Runs as a small Docker Compose stack; no external accounts
or API keys required.

**Status: v0.9.0 — feature-complete and in daily use.** Pre-1.0 signals that
the HTTP API may still change; the data model and migration path are stable.
Deliberately open: a photo-niceties bundle (lightbox, drag-and-drop upload),
sold-listing comparables, and the Numista/PCGS price adapters (their
credentials are already configurable). See the
[roadmap](docs/roadmap.md) and [changelog](CHANGELOG.md).

> **Deploying it?** Cabinet has no built-in login by design — put it behind an
> authenticating reverse proxy. See [docs/deployment.md](docs/deployment.md).

## Features

### Cataloging
- Coins and notes with full numismatic detail: country, denomination, year,
  mint mark, series, variety/sub-type, composition, weight, fineness,
  quantity, and free-text notes — plus up to 20 custom fields per item.
- **Grading** on seeded Sheldon (coins) and PMG (notes) scales, with
  certification tracking (service + cert number) for slabbed pieces.
- **Provenance & location**: acquisition date, price, source (dealer, show,
  auction, inheritance), and storage location (album, slab box, safe).
- **Lifecycle**: `owned` / `sold` / `wishlist` status with sold date and
  realized price; sets/lots for pieces held or sold together; catalog
  references (Krause, Numista, Red Book…); free-form tags.
- **Working at scale**: search across notes/series/variety/certs/refs/tags,
  combined filters (type, status, country, year ranges, grade ranges,
  latest-value ranges, tag, set), sortable columns, clone-item, bulk edit,
  per-item edit history, and completeness checklists for target sets (e.g. a
  date/mint run) with progress tracking.
- List filters and paging persist in the URL, so back-navigation keeps your
  place.

### Photos
- Multiple photos per item with angle designation (obverse/reverse/edge/
  other), a primary image, and reordering.
- Uploads are validated as real JPEG/PNG/WebP images, EXIF orientation is
  corrected, and thumbnails are generated automatically. Files live on a
  plain Docker volume served directly by nginx — no object store.

### Valuation
- **Manual estimates**: record researched values (dealer quote, auction
  result, price guide) with source and optional confidence — kept as
  append-only history, never overwritten.
- **Melt value**: one-click and scheduled automatic estimates for
  precious-metal items (spot price × weight × fineness × quantity), using
  free keyless spot data with a 12-hour cache. A melt refresh never
  supersedes a manual value.
- **Multi-currency**: totals are shown in one display currency; other
  currencies convert at cached daily ECB rates, and anything unconvertible
  is excluded and counted — never silently mixed.
- **Value over time**: month-end collection value and per-item estimate
  charts.

### Insights & reporting
- Dashboard: hero collection value, cost basis, unrealized and realized
  gain/loss, breakdowns by country/decade/grade/tag, acquisitions by year,
  and top-movers tables.
- Export to CSV or Excel; CSV import round-trips the export format (including
  grades, tags, refs, sets, and custom fields) with per-row error reporting.
- Printable insurance report with photos, certs, provenance, and totals —
  export to PDF via the browser's print dialog.

### Platform
- Three-container Compose stack; responsive UI for phone/tablet; full
  **dark mode** with a header toggle; auto-generated OpenAPI docs.
- **Backup/restore**: one script captures the database dump and photo archive
  together, with a rehearsed restore path — see
  [docs/backup-restore.md](docs/backup-restore.md).
- **Configurable pricing**: a Settings page for display currency, melt
  cadence, and price-source credentials — stored **encrypted at rest** and
  never readable back through the API
  (see [docs/security.md](docs/security.md)).

## Architecture

| Service    | Image             | Purpose                                    |
|------------|-------------------|--------------------------------------------|
| `proxy`    | nginx (built)     | Entry point; serves the UI (built into the image) and photos, proxies `/api/` |
| `backend`  | FastAPI (built)   | REST API + in-process background tasks (thumbnails, scheduled melt refresh) |
| `db`       | postgres          | Relational store; schema managed by Alembic migrations |

Backend: Python / FastAPI / SQLAlchemy 2 / Alembic / Pillow. Frontend:
React + Vite + TypeScript, hand-rolled SVG charts (no chart library). Photos
are plain files on a shared volume — the backend writes, nginx serves. See
[docs/architecture.md](docs/architecture.md) for detail.

## Quick start

```bash
git clone <your-repo-url> cabinet-numismatics
cd cabinet-numismatics
cp .env.example .env        # then edit secrets in .env
docker compose up --build
docker compose exec backend alembic upgrade head
```

No host Node or Python install is needed — the frontend is built inside the
proxy image. Once running: the app is at http://localhost/, API docs at
http://localhost/api/docs. After pulling a new version, re-run the two
commands above (rebuild, then migrate).

**Want something to look at first?** Load a small demo collection — 13 items
across several countries, decades, and grades, with value history:

```bash
python scripts/seed_demo.py
```

It uses only the standard library and refuses to run if you already have
items. To start clean afterwards: `docker compose down -v`.

## Configuration

All configuration is via environment variables in `.env` (gitignored; start
from `.env.example`).

| Variable          | Purpose                                              |
|-------------------|------------------------------------------------------|
| `DB_USER`         | Postgres username                                    |
| `DB_PASSWORD`     | Postgres password                                    |
| `DB_NAME`         | Postgres database name                               |
| `REESTIMATE_DAYS` | Optional: default melt re-estimation window in days (Settings overrides it; `0` disables the scheduler) |
| `SECRET_KEY`      | Recommended: Fernet key encrypting stored price-source API credentials. Auto-generated onto a private volume if unset. Comma-separated to rotate. See [docs/security.md](docs/security.md) |

External data sources (both free, keyless, and only contacted when needed,
with cached fallbacks): gold-api.com for metal spot prices and
frankfurter.dev for daily ECB exchange rates. No collection data ever leaves
the machine.

## Backup & restore

```bash
./scripts/backup.sh                     # → backups/<timestamp>/{db.dump, photos.tar.gz}
./scripts/restore.sh backups/<timestamp>
```

Run from Git Bash on Windows. Copy backups off the machine — see
[docs/backup-restore.md](docs/backup-restore.md).

## Documentation

- [Deployment](docs/deployment.md) — durable install: secrets, reverse proxy + auth, backups, upgrades
- [Architecture](docs/architecture.md) — services, data flow, configuration
- [Data model](docs/data-model.md) — database schema and relationships
- [API](docs/api.md) — REST endpoints (mirrors the OpenAPI spec)
- [Price sources](docs/price-sources.md) — where estimates come from and caveats
- [Backup & restore](docs/backup-restore.md) — what a backup contains and how to drill it
- [Security](docs/security.md) — secrets at rest, key management, exposure guidance
- [Roadmap](docs/roadmap.md) — full feature list, what's done, what remains
- [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)
- [Developing with Claude Code](docs/claude-code.md) — how the project is built from Phase 0 on

## Development

- **Full stack:** `docker compose up --build` (the container build is also
  the frontend typecheck).
- **Backend:** in `backend/` — `pip install -e .[dev]` once, then `pytest`
  (no database needed), `ruff check .` / `ruff format .`, and
  `alembic upgrade head` with `DATABASE_URL` set.
- **Frontend:** in `frontend/` — `npm run dev` proxies `/api` to
  localhost:8000.

CI runs ruff, the backend test suite on Python 3.10 and 3.12, a frontend
typecheck, and a full compose build with migrations and an API smoke test on
every pull request.

From Phase 0 onward the project is built with Claude Code, which reads the
repo-root `CLAUDE.md` for persistent context. See
[docs/claude-code.md](docs/claude-code.md).

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, conventions, and what's in scope. Cabinet stays deliberately small;
[docs/roadmap.md](docs/roadmap.md) records what was cut and why. Security
issues should be reported privately per [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Jayson Saumer.

Value estimates produced by Cabinet are guidance, not appraisals. For
insurance or sale, get a professional appraisal or grading-service valuation.
