<img src="frontend/public/logo.svg" alt="" width="96" align="right">

# Cabinet

**Numismatics: Coin & Paper Money Collection Manager**

[![CI](https://github.com/jsaumer/cabinet-numismatics/actions/workflows/ci.yml/badge.svg)](https://github.com/jsaumer/cabinet-numismatics/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-0.33.4-informational)

A self-hosted, single-user web application for cataloging a coin and paper
money collection, managing photos of each item, and tracking estimated market
value over time. Runs as a small Docker Compose stack; no external accounts
or API keys required.

**Status: v0.33.4 released.** 1.0 will mean a stable HTTP API; until then
the API may still change. See the [roadmap](docs/roadmap.md) for what's
built and what's next, and the [changelog](CHANGELOG.md) for release detail.

> **Deploying it?**

<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->
Cabinet is designed for private networks (a home LAN, a homelab, or a VPN
you control), not the open internet. Do not expose it directly to the
internet, even behind TLS, single sign-on, or an authenticating gateway;
reach it from outside through your own network's remote access instead,
such as a VPN (WireGuard, Tailscale, or your router's own) or an
identity-aware tunnel that terminates before Cabinet. Cabinet has one
admin account and, by design, a password sign-in path with a single
factor, so that a provider outage or a lost phone can never lock you out;
exposing any self-hosted service that holds personal records invites
automated credential guessing and vulnerability scanning within hours of
the port opening. The project cannot see or control how Cabinet is
deployed and takes no responsibility for an exposed instance. If you
deploy it this way regardless, at minimum use TLS, single sign-on with
multi-factor authentication enforced at the provider, an authenticating
gateway in front, the alert webhook switched on, and a password no human
has memorised.
<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->

If you turn sharing on, exempt `/s/`, `/api/share/`, and `/robots.txt`
from any gateway kept in front, or a forward-auth proxy blocks your own
share links too. See [docs/deployment.md](docs/deployment.md).

## Screenshots

Shown with the bundled demo collection (`python scripts/seed_demo.py`).

Dark is the default; the header toggle switches to light and remembers it.

| Dark | Light |
|---|---|
| [![Sign in, dark](docs/screenshots/signin-dark.png)](docs/screenshots/signin-dark.png) | [![Sign in, light](docs/screenshots/signin-light.png)](docs/screenshots/signin-light.png) |
| [![Dashboard, dark](docs/screenshots/dashboard-dark.png)](docs/screenshots/dashboard-dark.png) | [![Dashboard, light](docs/screenshots/dashboard-light.png)](docs/screenshots/dashboard-light.png) |
| [![Collection list, dark](docs/screenshots/collection-dark.png)](docs/screenshots/collection-dark.png) | [![Collection list, light](docs/screenshots/collection-light.png)](docs/screenshots/collection-light.png) |
| [![Item detail, dark](docs/screenshots/item-detail-dark.png)](docs/screenshots/item-detail-dark.png) | [![Item detail, light](docs/screenshots/item-detail-light.png)](docs/screenshots/item-detail-light.png) |
| [![Settings, dark](docs/screenshots/settings-general-dark.png)](docs/screenshots/settings-general-dark.png) | [![Settings, light](docs/screenshots/settings-general-light.png)](docs/screenshots/settings-general-light.png) |

## Features

### Cataloging
- Coins and notes with full numismatic detail: country, denomination, year
  (or ND, with an optional attributed year, for an undated piece), mint
  mark, series, variety/sub-type, strike (business, proof, specimen),
  composition, weight, fineness, diameter, thickness, edge, shape, die axis,
  mintage, quantity, and free-text notes (banknotes add serial number,
  prefix/block, signatures, issuer, and replacement notes), plus up to 20
  custom fields per item.
- **Bars and rounds**: a third item type alongside coins and notes, with no
  year required. A Metal select (gold, silver, platinum, palladium) fills
  the composition and defaults the fineness to .999; weight can be entered
  in grams or troy ounces; the product name is suggested from weight,
  metal, and shape until you type your own. Filled in from Numista's
  bullion catalogue too.
- **Dates as struck**: a coin dated in another calendar (Islamic, Persian,
  Thai Buddhist, Hebrew, Japanese eras, Vikram Samvat, Saka, Minguo, Chula
  Sakarat, Rattanakosin, Ethiopian) keeps the year as written, and the
  Gregorian year is worked out for you unless you type one.
- **Paper money depth**: National Bank Note charter number, bank city and
  state, and plate position; Pick and Friedberg catalogue references with a
  web-search link; and fancy serial numbers (solid, ladder, radar, repeater,
  binary, low and high numbers, dates, star notes, and more) badged on the
  item and in the list, with a filter for any of them.
- **Note details**: width and height for anything not round (coins keep
  diameter), printer, watermark, and a demonetisation date for coins and
  notes alike, filled in from Numista along with everything else.
- **Grading** on seeded Sheldon (coins) and PMG (notes) scales, with proof
  and specimen strikes, plus grades, stars, designations (CAM/DCAM, PL/DMPL,
  RD/RB/BN, EPQ…), CAC stickers, and details grades, shown the way the holder
  reads, e.g. `PR-69 DCAM ★`. Certification tracking (service + cert number)
  links to the grading service's verification. A PCGS coin keeps its
  population (graded at this grade, and higher) with the date it was read.
- **Provenance & location**: acquisition date, price and fees, source
  (dealer, show, auction, inheritance), and storage location (album, slab
  box, safe).
- **Lifecycle**: `owned` / `sold` / `wishlist` status with sold date and
  realized price; sets/lots for pieces held or sold together; catalog
  references (Krause, Numista, Red Book…); free-form tags.
- **Wish list**: a target price and a priority per piece, the gap between
  the newest estimate and the target, a "target reached" filter, and one
  webhook message when an estimate first reaches the target.
- **Working at scale**: search across notes/series/variety/certs/refs/tags,
  combined filters (type, status, country, year ranges, grade ranges,
  latest-value ranges, tag, set, fancy serials, targets reached), sortable
  columns, clone-item, bulk edit, per-item edit history, and completeness
  checklists for target sets (e.g. a date/mint run), written by hand or
  generated, with progress tracking.
- List filters and paging persist in the URL, so back-navigation keeps your
  place.
- **The item page leads with the piece**: a large primary photo beside the
  title, grade, certification, and value, then the rest of what's known
  grouped into titled facts (identity, grade and certification, physical,
  acquisition) that only show fields with something in them, with a
  "Show empty fields" toggle for the full sheet.
- **Fill from Numista**: enter a Numista number or search by name, and the
  item form fills in country, denomination, composition, fineness, weight,
  dimensions, catalogue references, and the issue's year, mint, and mintage.
  Needs a free Numista API key in Settings.
- **Fill from a PCGS cert number**: a slabbed coin's type, date, mint,
  denomination, grade, designations, variety, PCGS number, and population
  come from the cert lookup (needs a free PCGS API token). Only empty fields
  are filled.
- **Duplicate warning** while entering anything already here: by cert,
  catalogue reference, or country, denomination, year, and mint. The trash
  is checked too, and the importer notes lookalikes in its preview.
- **Add a run**: pick a type on Numista, tick the dates and mints you have,
  and get one item each, with the shared fields typed once. Issues you
  already own are marked and skipped.
- **Generated checklists**: slots come from a Numista type's issues or a
  year and mint range, and fill themselves from the owned items that match,
  with a completion percentage and a "needed to complete" list. A slot can
  still be ticked by hand.

### Photos
- Multiple photos per item with angle designation (obverse/reverse/edge/
  other), a primary image, and reordering.
- Uploads are validated as real JPEG/PNG/WebP images, EXIF orientation is
  corrected, and thumbnails are generated automatically. Every stored photo
  is re-encoded with its EXIF, XMP, and IPTC metadata stripped (the colour
  profile is kept), so nothing but the image itself, no camera, location,
  or timestamp data, ever leaves the app, shared or not. Files live on a
  plain Docker volume served directly by nginx, with no object store.
- Add photos by file picker, drag and drop, pasting an image, a URL, or a
  webcam or phone camera; view them full size in a zoomable lightbox; and
  crop, turn, or straighten them in the browser.
- Attach documents, such as receipts, invoices, certificates of
  authenticity, and grading labels (PDF or image), with a first-page
  thumbnail; share one lot's invoice across every coin in it. Kept off the
  public photo path and included in backups.

### Valuation
- **Manual estimates**: record researched values (dealer quote, auction
  result, price guide) with source and optional confidence, kept as
  append-only history, never overwritten (a value typed in by mistake can be
  deleted; what a source said is kept).
- **Pluggable price sources**: melt value (spot price × weight × fineness ×
  quantity, keyless; metal detection skips named alloys like nickel silver
  and surface coatings like plating, and fineness parsing reads the
  percentage attached to the detected metal), Numista (coins, notes, and
  bars/rounds, priced by catalog ref + grade), and PCGS (US coins, by cert
  number or catalog ref + grade, preferring auction prices realized in the
  last five years over the price guide; the same answer keeps the coin's
  population current). One-click and scheduled refresh for all three, with
  Numista and PCGS off by default, Numista's cadence (7/14/30 days) shown
  against its 2,000/month quota, and PCGS weekly within its 100 calls a day.
- **Sold comparables**: log what pieces like yours actually sold for (eBay
  sold listings, auction archives, dealer sales) and get a comps estimate:
  the median of recent sales in your currency, with confidence from how many
  there are and how much they agree. Numista's auction records can fill the
  log automatically on Numista's paid API plan.
- **Value differentiation**: the item page shows every configured source's
  own latest value side by side (never blended), each with a "time since"
  label. A `value_strategy` setting picks the single blended number shown
  in the items list, export, and dashboard totals: latest estimate,
  a preferred source, or an average, with a `SOURCE` column on the list
  showing which one produced it.
- **Multi-currency**: totals are shown in one display currency; other
  currencies convert at cached daily ECB rates, and anything unconvertible
  is excluded and counted, never silently mixed.
- **Value over time**: month-end collection value and per-item estimate
  charts.
- **Pricing reports**: a Pricing page showing which items lack estimates and
  why (source off, missing catalog ref or grade, what the source said, a
  failed fetch), which estimates are stale, how the sources compare and
  disagree, and how estimates held up against actual sale prices.
- **Bullion stack**: a Stack page with fine troy ounces, melt value, cost per
  ounce (also the break-even spot price), gain or loss, and the premium paid
  over spot at purchase, by metal and per item, scopeable by tag, listing
  what it leaves out and why (no weight, no fineness). Purchase-day spot is
  looked up automatically for purchases from 2 March 2024 and can be typed
  in for older ones; spot-price threshold alerts fire through the existing
  webhook.

### Insights & reporting
- Customisable dashboard (the home page): 32 widgets (value, breakdowns by
  country/decade/grade/tag/metal or one tag/set, acquisitions by year,
  top-movers tables, owned notes by series and signature pair, wish list,
  fancy serials, checklists, the bullion stack, pricing coverage, operations
  status, and a "group C" of showcase widgets: most valuable, piece of the
  day, oldest and newest pieces, on this day, a photo mosaic, certified
  share, value spread, population highlights, and data health) added,
  removed, resized, retitled, and arranged by drag or keyboard, saved on the
  server so it follows the collection; the default layout is today's fixed
  page (the group C widgets are opt-in), and a setup checklist widget says
  what is still off (scheduled backups, the alert webhook, a price-source
  key).
- Export to CSV or Excel; CSV import round-trips the export format (including
  grades, tags, refs, sets, and custom fields) with per-row error reporting.
- Deleting is recoverable: items go to a trash with their photos, documents,
  values, and history, and restore exactly as they were; the trash empties
  itself after 30 days (adjustable).
- Import from other tools, with a preview first: your Numista collection
  (straight from your account), Numista's export file, OpenNumismat
  collections with their photos, or any spreadsheet with its columns matched
  to Cabinet's fields. Re-importing skips what's already here.
- Printable insurance report with photos, certs, provenance, and totals,
  exported to PDF via the browser's print dialog.

### Platform
- Three-container Compose stack, also published as versioned images on GHCR
  with a [Swarm stack file](deploy/docker-stack.yaml); an OpenAPI schema at
  `/api/openapi.json`. The backend applies its own migrations on startup.
- Responsive UI for phone/tablet, **dark by default** with a light theme on
  the header toggle. System fonts and inline SVG icons only: the page loads
  nothing from outside the app.
- **Backups from the app**: download the collection as one encrypted,
  tamper-evident archive (database + photos + documents + manifest, `.zip.age`,
  encrypted with a backup key you keep a copy of) from Settings, or schedule
  daily or weekly archives with retention by age (7 days to a year, or
  forever) into a directory you can point at a NAS, and delete any archive
  from the same page. Nothing unencrypted ever lands there.
- **Restore from the app**: pick a stored archive or upload one in
  Settings. It is decrypted in private staging, its MAC checked, compared
  with what is there now (an older archive needs `RESTORE OLDER`), and restored
  only after an automatic safety backup and a typed confirmation; a failure
  before the database is replaced changes nothing. `RESTORE_ENABLED=false`
  switches it off. `scripts/restore.sh` remains for when the app won't
  start, and CI rehearses both routes on every push (see
  [docs/backup-restore.md](docs/backup-restore.md)).
- **Configurable pricing**: a Settings page for display currency, the
  blended-value strategy, per-source refresh cadence, and price-source
  credentials, stored **encrypted at rest** and never readable back
  through the API (see [docs/security.md](docs/security.md)).
- **Alerts and metrics**: a webhook (n8n, ntfy, Discord, Slack, Gotify) when
  a backup fails, a price source rejects its key or runs out of quota, or a
  refresh fails, and when it recovers, and when a wish-list target is
  reached; an Uptime Kuma heartbeat;
  Prometheus metrics; and a recipe for a [Homepage](https://gethomepage.dev)
  tile. See [docs/monitoring.md](docs/monitoring.md).
- **Sign-in**: one admin, claimed with a one-time setup code on first start,
  database-backed sessions, and scoped API tokens (`read`, `write`,
  `metrics`) for scripts and dashboards. Every route is denied by default;
  sensitive actions (backups, exports, restore, settings, tokens) ask for
  the password again. Photos go through the same check as the API. No
  interactive API docs page; the OpenAPI schema stays at
  `/api/openapi.json` for a signed-in session. See
  [docs/security.md](docs/security.md).
- **Single sign-on**: sign in as the same admin through an OpenID Connect
  provider (Authentik, Keycloak, Authelia, Entra ID, Google, and more), a
  GitHub button, or a gateway's signed assertion (a trusted-header mode for
  Authentik, Cloudflare Access, Pomerium, or Google IAP), one button per
  configured provider. The identity provider's own multi-factor check is
  the second factor; the local password stays as a one-factor recovery
  credential the container can always reset. See
  [docs/deployment.md](docs/deployment.md) for provider setup and
  [docs/security.md](docs/security.md) for the model.
- **Share and showcase view**: a read-only link to the collection, a set, or
  a checklist, opened without signing in. Off by default; while off, no
  link can be made and every link answers not found. Each link chooses what
  it shows (photos, grades, tags, notes, the estimated value, and the cert
  number, each its own toggle); never a cost, gain, storage location,
  document, serial number, or custom field. Shared photos carry no
  metadata, the same as every stored photo. The token is shown once and
  stored only as its hash, with a Regenerate for a lost link and a Revoke
  that kills it at once. See [docs/security.md](docs/security.md).
- **Hardened by default**: the backend container drops to an unprivileged
  user (`PUID`/`PGID`), the image installs a hash-pinned lockfile, nginx
  sets a Content-Security-Policy and the usual security headers, and a
  security workflow runs pip-audit, npm audit, and Trivy image scans on
  every change and weekly.

## Architecture

| Service    | Image             | Purpose                                    |
|------------|-------------------|--------------------------------------------|
| `proxy`    | nginx (built)     | Entry point; serves the UI (built into the image) and photos, proxies `/api/` |
| `backend`  | FastAPI (built)   | REST API + in-process background tasks (thumbnails, scheduled price refreshes and backups, trash clear-out, alerts and heartbeat) |
| `db`       | postgres          | Relational store; schema managed by Alembic migrations |

Backend: Python / FastAPI / SQLAlchemy 2 / Alembic / Pillow. Frontend:
React + Vite + TypeScript, hand-rolled SVG charts (no chart library). Photos
are plain files on a shared volume: the backend writes, nginx serves.
Documents sit on a private volume of their own and are served only by the
API. See [docs/architecture.md](docs/architecture.md) for detail.

## Quick start

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env        # then edit secrets in .env
docker compose up --build
```

No host Node or Python install is needed: the frontend is built inside the
proxy image. `PUBLIC_ORIGINS` in `.env` is required (the sample suits the
local stack; see [deployment.md](docs/deployment.md)). The backend creates
and updates the database schema itself on startup. Once running, open
http://localhost/: **nothing but the setup page is served until you claim
it**. Enter the setup code from `docker compose logs backend` (or the
`SETUP_CODE` you set) and choose a username and password; that account is
the only one. The OpenAPI schema is at http://localhost/api/openapi.json,
for a signed-in browser. After pulling a new version, run
`docker compose up --build` again; Settings → About shows the version and
whether the schema is current. To run the published images instead of
building, see [docs/deployment.md](docs/deployment.md).

**Want something to look at first?** Load a small demo collection (16 items
across several countries, decades, and grades, with value history). Mint a
write-scoped API token first (Settings → Account → API tokens, or
`POST /api/auth/tokens`):

```bash
python scripts/seed_demo.py --token cabinet_...
# or: CABINET_TOKEN=cabinet_... python scripts/seed_demo.py
```

It uses only the standard library and refuses to run if you already have
items. To start clean afterwards: `docker compose down -v`.

## Configuration

All configuration is via environment variables in `.env` (gitignored; start
from `.env.example`).

| Variable          | Purpose                                              |
|-------------------|------------------------------------------------------|
| `PUBLIC_ORIGINS`  | Required: the exact address(es) browsers use to reach Cabinet, comma-separated (`https://cabinet.example.com`). The backend and the proxy both refuse to start without it |
| `ALLOWED_HOSTS`   | Optional: extra Host names nginx answers besides those of `PUBLIC_ORIGINS` (an internal name such as `cabinet_proxy`). Any other Host gets no response |
| `AUTH_INSECURE_HTTP` | Optional, default `false`: sign-in cookies without `Secure`, for a plain-http local stack. Refused beside an `https` origin |
| `SETUP_CODE` / `SETUP_CODE_FILE` | Optional: the one-time code for creating the admin, at least 32 characters. `SETUP_CODE_FILE` names a file holding it (a Docker secret) and wins. Unset, one is generated and logged. Ignored once the admin exists |
| `BACKUP_KEY_FILE` | Optional: a file of [age](https://age-encryption.org) identities that encrypt every backup archive, typically a Docker secret. Unset, one is generated onto the state volume. Save a copy outside Cabinet either way: see [docs/backup-restore.md](docs/backup-restore.md#the-backup-key) |
| `BACKUP_KEY`      | Optional, not with `BACKUP_KEY_FILE`: the same key as a variable (the line `python -m app.cli backup-key new` prints), for a secret manager that sets variables |
| `CABINET_PORT`    | Optional, default `80`: the port the proxy publishes |
| `DB_USER`         | Postgres username                                    |
| `DB_PASSWORD`     | Postgres password                                    |
| `DB_NAME`         | Postgres database name                               |
| `REESTIMATE_DAYS` | Optional: default melt re-estimation window in days (Settings overrides it; `0` disables the scheduler) |
| `AUTO_MIGRATE`    | Optional, default `true`: apply database migrations when the backend starts. Set `false` to run `alembic upgrade head` yourself |
| `BACKUP_DIR`      | Set by `docker-compose.yaml` to `/data/backups` (the `backup_data` volume): where scheduled and on-demand backups are written |
| `SECRET_KEY`      | Recommended: Fernet key encrypting stored secrets (price-source credentials, the alert webhook and heartbeat URLs). Auto-generated onto a private volume if unset. Comma-separated to rotate. See [docs/security.md](docs/security.md) |
| `DOCUMENT_DIR`    | Set by `docker-compose.yaml` to `/data/documents` (the `document_data` volume): where attached documents are stored |
| `REQUIRE_DOCUMENT_MOUNT` | Optional, default `true`: refuse document uploads unless `DOCUMENT_DIR` is a mounted volume. `false` for local development |
| `PUID` / `PGID`   | Optional, default `1000`:`1000`: the unprivileged user the backend runs as, and that owns its files |
| `IMPORT_DIR`      | Optional: where uploaded import files wait between preview and import (default: a temp folder; kept a day) |
| `RESTORE_ENABLED` | Optional, default `true`: restore from Settings → Backups. `false` switches it off (the endpoints answer 404; `scripts/restore.sh` is then the only way) |
| `RESTORE_MAX_GB`  | Optional, default `20`: the largest archive that may be uploaded for a restore, in GB (nginx allows 20) |
| `TRUSTED_ASSERTION_HEADER` | Optional: the header carrying a gateway's signed JWT for the trusted-header mode (e.g. `X-authentik-jwt`), set on both the backend and the proxy. All four `TRUSTED_ASSERTION_*` variables or none |
| `TRUSTED_ASSERTION_JWKS_URL` | Optional: where the gateway's public keys are; `https://` required unless `AUTH_INSECURE_HTTP` |
| `TRUSTED_ASSERTION_ISSUER` | Optional: the `iss` the gateway's assertion must carry |
| `TRUSTED_ASSERTION_AUDIENCE` | Optional: the `aud` the gateway's assertion must carry; never empty |
| `SSO_CA_FILE`     | Optional: extra CA certificates trusted for a single sign-on provider or trusted-header gateway behind a local certificate authority |
| `TAG`             | Optional, default `latest`: the image tag Compose names its builds with and the Swarm stack pulls, e.g. `0.33.4` |

External data sources (both free, keyless, and only contacted when needed,
with cached fallbacks): gold-api.com for metal spot prices and
frankfurter.dev for daily ECB exchange rates. Numista and PCGS are optional
and contacted only once you save a key and switch them on. No collection
data ever leaves the machine: a lookup sends a catalogue or cert number,
nothing else.

## Backup & restore

Settings → Backups downloads an archive or schedules them, and restores one
(a safety backup is taken first). Every archive is encrypted with a backup
key you keep a copy of outside Cabinet (`python -m app.cli backup-key
show`); without it, nobody can open one. From the host, and when the app
won't start:

```bash
./scripts/backup.sh                     # → backups/cabinet-backup-<UTC stamp>.zip.age
./scripts/restore.sh cabinet-backup-20260914-031500.zip.age
```

Run from Git Bash on Windows. Copy backups off the machine. See
[docs/backup-restore.md](docs/backup-restore.md).

## Documentation

- [Deployment](docs/deployment.md): a durable install (secrets, TLS, single sign-on, an optional gateway, backups, upgrades); read the [exposure section](docs/deployment.md#2-exposure-cabinet-is-for-private-networks) first
- [Swarm stack file](deploy/docker-stack.yaml): `docker stack deploy` with the published images
- [Architecture](docs/architecture.md): services, data flow, configuration
- [Data model](docs/data-model.md): database schema and relationships
- [API](docs/api.md): REST endpoints (mirrors the OpenAPI spec)
- [Price sources](docs/price-sources.md): where estimates come from and caveats
- [Backup & restore](docs/backup-restore.md): what a backup contains and how to drill it
- [Monitoring](docs/monitoring.md): alert webhooks, the heartbeat, and Prometheus metrics
- [Security](docs/security.md): secrets at rest, key management, exposure guidance
- [Live validation](docs/live-validation.md): checking a release against real sign-in providers and a vulnerability scanner, non-destructively
- [Roadmap](docs/roadmap.md): full feature list, what's done, what remains
- [Implementation notes](docs/implementation-notes.md): what each release added and the rules it left behind
- [Backend](backend/README.md) and [frontend](frontend/README.md): layout and commands for each half
- [Screenshots](docs/screenshots/README.md): how the images above are retaken
- [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)
- [Developing with Claude Code](docs/claude-code.md): how the project is built from Phase 0 on

## Development

- **Full stack:** `docker compose up --build` (the container build is also
  the frontend typecheck).
- **Backend:** in `backend/`, `pip install -e .[dev]` once, then `pytest`
  (no database needed), `ruff check .` / `ruff format .`, and
  `alembic upgrade head` with `DATABASE_URL` set.
- **Frontend:** in `frontend/`, `npm run dev` proxies `/api` to
  localhost:8000; `npm run build` typechecks and builds; `npm run e2e` runs
  the Playwright smoke tests against a running stack. See
  [frontend/README.md](frontend/README.md).

CI runs ruff and the backend test suite on Python 3.10 and 3.14, a frontend
typecheck and build, and a full compose stack job on every push and pull
request: the schema migrating itself, an API smoke test, a backup → restore
drill (with `restore.sh`, then from inside the app), and Playwright tests of
the pages. A `v*` tag also publishes both
images to GHCR. A separate security workflow audits dependencies and scans
both images.

From Phase 0 onward the project is built with Claude Code, which reads the
repo-root `CLAUDE.md` for persistent context. See
[docs/claude-code.md](docs/claude-code.md).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, conventions, and what's in scope. Cabinet stays deliberately small;
[docs/roadmap.md](docs/roadmap.md) records what was cut and why. Security
issues should be reported privately per [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Jayson Saumer.

Value estimates produced by Cabinet are guidance, not appraisals. For
insurance or sale, get a professional appraisal or grading-service valuation.
