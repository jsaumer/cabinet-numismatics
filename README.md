# Cabinet

**Numismatics — Coin & Paper Money Collection Manager**

A self-hosted, single-user web application for cataloging a coin and paper
money collection, managing photos of each item, and retrieving estimated
market prices.

## Features

- **Collection management** — catalog coins and notes with full detail:
  identity, variety, Sheldon/PMG grading, certification, composition and
  weight, provenance, storage location, sets/lots, custom fields, and
  owned/sold/wishlist status. Search, filter (including grade and value
  ranges), tag, clone, bulk edit, per-item edit history, completeness
  checklists, CSV import/export.
- **Photo management** — upload photos per item with angle designation, a
  primary image, drag-free reordering, automatic thumbnails, and EXIF
  orientation correction.
- **Value tracking** — record timestamped value estimates per item (with
  optional confidence), kept as append-only history; one-click and scheduled
  melt-value estimates from live spot prices; multi-currency totals converted
  at daily ECB rates; value-over-time charts; cost basis and
  realized/unrealized gains.
- **Dark mode** — full light/dark theming with a header toggle.
- **Insights & reporting** — dashboard with collection value, breakdowns by
  country/decade/grade/tag, realized and unrealized gain/loss, charts;
  Excel/CSV export; printable insurance report (browser Print → PDF).
- **Backup/restore** — one script captures the database and photos together;
  see [docs/backup-restore.md](docs/backup-restore.md).

## Architecture

The application runs as three containers orchestrated with Docker Compose:

| Service    | Image             | Purpose                                   |
|------------|-------------------|-------------------------------------------|
| `proxy`    | nginx             | Entry point; serves the UI and photos,    |
|            |                   | proxies the API                           |
| `backend`  | (built) FastAPI   | REST API + in-process background tasks     |
| `db`       | postgres          | Relational data store                     |

Photos are stored on a shared volume: the backend writes them, nginx serves
them directly. See [docs/architecture.md](docs/architecture.md) for detail.

## Quick start

```bash
git clone <your-repo-url> cabinet-numismatics
cd cabinet-numismatics
cp .env.example .env        # then edit secrets in .env
docker compose up --build
docker compose exec backend alembic upgrade head
```

No host Node or Python install is needed — the frontend is built inside the
proxy image. Once running, the app is available at http://localhost/ and the
API docs (auto-generated OpenAPI) at http://localhost/api/docs.

## Configuration

All configuration is via environment variables in `.env`. Start from
`.env.example`; never commit the real `.env` (it is gitignored). See
[docs/architecture.md](docs/architecture.md#configuration) for the full list.

## Documentation

- [Architecture](docs/architecture.md) — services, data flow, configuration
- [Data model](docs/data-model.md) — database schema and relationships
- [API](docs/api.md) — REST endpoints (mirrors the OpenAPI spec)
- [Price sources](docs/price-sources.md) — where estimates come from and caveats
- [Roadmap](docs/roadmap.md) — full feature list and phased plan
- [Developing with Claude Code](docs/claude-code.md) — how the project is built from Phase 0 on

## Development

The backend serves the API and runs background tasks from a single image. The
frontend is a Vite SPA built to static files that nginx serves. See
[docs/architecture.md](docs/architecture.md#development) for local workflows.

From Phase 0 onward the project is built with Claude Code, which reads the
repo-root `CLAUDE.md` for persistent context. See
[docs/claude-code.md](docs/claude-code.md).

## License

TBD.
