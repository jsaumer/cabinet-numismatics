# Cabinet — Features & Roadmap

Cabinet is a single-user, self-hosted numismatics collection manager. This
document lists the full intended feature set and sequences it into phases. The
guiding principle: reach a genuinely useful tool early (Phase 1–2), then deepen
cataloging, valuation, and insights. Open-sourcing is a possible endgame, so
phases that matter for that (docs, packaging, polish) are called out explicitly
rather than assumed.

**Status (August 2026): released as v0.9.1.** Phases 0–5 are built (Phase 5
minus the photo-niceties bundle), pricing-program M1 is done, and the
open-source readiness track (Phase 6) is complete apart from application-level
login, deliberately deferred in favour of proxy-level auth.
A ✔ marks shipped items below. What remains, all optional: the photo-niceties
bundle, the sold-listing comps price source, the PCGS adapter and the pricing
program's remaining milestones (M3–M5), and import mappings for other
collection tools.

Legend: **[MVP]** core to a usable tool · **[Core]** expected of a polished
tool · **[Nice]** valuable but deferrable · **[OSS]** matters mainly if
released publicly · **✔** shipped.

---

## 1. Cataloging

The heart of the app: describing what you own, accurately and flexibly.

- ✔ **[MVP]** Add / edit / delete items (coins and notes).
- ✔ **[MVP]** Core fields: type, country, denomination, year, mint mark,
  series, quantity, acquisition date, acquisition price + currency, free-text
  notes.
- ✔ **[MVP]** List view with sorting and basic filtering (type, country, year).
- ✔ **[MVP]** Item detail view.
- ✔ **[Core]** Item status: `owned` / `sold` / `wishlist`, with sold date and
  realized price on sold items. Enables *realized* gain/loss reporting and
  subsumes the separate wishlist feature.
- ✔ **[Core]** Composition & weight: metal, weight (g), fineness as structured
  fields — the melt-value prerequisite.
- ✔ **[Core]** Grading: Sheldon (coins) and PMG (notes) scales, seeded into a
  reference table by migration.
- ✔ **[Core]** Certification tracking: grading service + cert number for
  slabbed pieces (distinct from the grade; verifiable and insurance-relevant).
- ✔ **[Core]** Acquisition source: where a piece came from (dealer, show,
  auction, inheritance) — provenance in one field.
- ✔ **[Core]** Catalog references: link items to Krause / Numista / Red Book
  numbers for identification and price matching.
- ✔ **[Core]** Search across notes, series, variety, cert numbers, catalog
  refs, and tags.
- ✔ **[Core]** Advanced / combined filters (grade ranges, latest-value ranges,
  year ranges, tags, sets, status).
- ✔ **[Core]** Tags / custom labels for arbitrary grouping.
- ✔ **[Core]** Duplicate / clone an item to speed up entering similar pieces.
- ✔ **[Nice]** Varieties & sub-types (die varieties, overdates) as a
  structured, searchable field.
- ✔ **[Nice]** Lots & sets: group items held or sold together; deleting a set
  detaches items rather than deleting them.
- ✔ **[Nice]** Storage/location tracking (which album, slab, box, safe).
- ✔ **[Nice]** Custom user-defined fields (up to 20 per item, validated).
- ✔ **[Nice]** Bulk edit across selected items (fields + add/remove tags).

## 2. Photo management

- ✔ **[MVP]** Upload photos per item; store originals on the photo volume.
- ✔ **[MVP]** Obverse / reverse designation; mark a primary image (first
  upload becomes primary automatically).
- ✔ **[Core]** Automatic thumbnail generation and EXIF-orientation correction;
  uploads validated as real images (declared content-type is not trusted).
- ✔ **[Core]** Multiple photos per item (obverse, reverse, edge, other).
- ✔ **[Core]** Delete / reorder photos; change designation; primary promotion
  on delete.
- **[Nice]** In-browser crop / rotate / straighten.
- **[Nice]** Drag-and-drop and paste-from-clipboard upload.
- **[Nice]** Import a photo from a URL.
- **[Nice]** Lightbox / zoom for close inspection.
- **[Nice]** Webcam capture for direct photographing.

*(The unshipped [Nice] items above are the remaining "photo niceties"
bundle.)*

## 3. Market price / valuation

See `price-sources.md` for the sourcing detail and caveats. Value estimates are
guidance, not appraisals.

- ✔ **[MVP]** Manual value entry: record a value you researched, with source,
  date, and optional confidence, stored as a timestamped estimate.
- ✔ **[Core]** Melt value: spot price × weight × fineness × quantity for
  precious-metal items. Deterministic, high-confidence, ToS-clean — the
  *first* automatic source, not the last. Metal detected from composition;
  fineness falls back to a percentage in the composition text.
- ✔ **[Core]** Estimate history retained per item (append-only), so value can
  be tracked over time.
- ✔ **[Core]** Collection total value with cost basis vs. estimate. The
  multi-currency answer: convert at cached daily ECB rates; exclude and count
  anything unconvertible — never silently mix currencies.
- **[Core]** On-demand estimate from comparables by catalog ref + grade with
  a confidence score — *the sold-listings integration; not yet built
  (deferred stretch goal; the adapter registry it plugs into exists).*
- ◐ **[Nice]** Pluggable price-source adapters: the registry and adapter
  interface carry melt and **Numista** (free key, coins + notes, prices by
  grade — shipped with pricing M2); **PCGS Public API** (free, US price guide
  + Auction Prices Realized) is researched and next. eBay Marketplace
  Insights is closed to new applicants, so eBay comps stay a manual-entry
  path. See the Pricing program phase below.
- ✔ **[Nice]** Scheduled / periodic re-estimation: stale melt estimates
  refresh every 12h (window set by `REESTIMATE_DAYS`; manual values are never
  superseded); on-demand refresh from the dashboard.
- ✔ **[Nice]** Currency conversion for multi-currency collections (daily ECB
  rates, 24h cache, stale fallback).
- ✔ **[Nice]** Value-over-time chart per item and per collection.

## 4. Stats, reports & insights

- ✔ **[Core]** Dashboard: counts, total cost basis, total estimated value,
  and top-level breakdowns.
- ✔ **[Core]** Breakdowns by country, type, decade, grade, and tag, plus
  acquisitions by year.
- ✔ **[Core]** Cost-basis vs. estimated-value comparison — unrealized (owned)
  *and* realized (sold) gain/loss, per item and in total.
- ✔ **[Core]** Export the collection to CSV and Excel.
- ✔ **[Nice]** Printable collection report — print-optimized HTML; the
  browser's Print → PDF replaces a server-side PDF library on purpose
  (lighter, and the user controls paper/margins).
- ✔ **[Nice]** Charts: value by country/tag, items by decade/grade,
  acquisitions over time, value over time.
- ✔ **[Nice]** Completeness tracking against a target set (checklists with
  progress, e.g. a date/mint run).
- ✔ **[Nice]** Insurance report (itemized values, photos, certs, totals,
  disclaimer).

## 5. Platform, data & operations

Cross-cutting concerns that make the tool trustworthy and pleasant to run.

- ✔ **[MVP]** Containerized deployment via Docker Compose (backend, proxy, db).
- ✔ **[MVP]** Persistent storage for data and photos; config via `.env`.
- ✔ **[MVP]** Auto-generated API docs (OpenAPI / Swagger).
- ✔ **[Core]** Data import from CSV, round-tripping the export format with
  per-row error reporting.
- ✔ **[Core]** Backup / restore: one script for pg_dump + photo archive
  together, documented **and rehearsed** (see backup-restore.md).
- ✔ **[Core]** Responsive UI that works on phone and tablet, not just desktop.
- ✔ **[Core]** Data validation and sensible error messages (real image
  validation, enum/range checks, actionable estimate errors).
- ✔ **[Core]** Secrets handled to standard: price-source credentials are
  Fernet-encrypted at rest with env-supplied keys and rotation support, and
  are write-only through the API. See `security.md`.
- **[Nice]** Authentication. For homelab deployment behind an authenticating
  reverse proxy (e.g. Traefik + Authentik forward-auth), no application code
  is needed — that is the intended path for private networked use.
  Application-level login only becomes necessary for direct public exposure
  or the OSS release.
- **[Nice]** CI (ruff + pytest + image build) once the repo is pushed to the
  homelab Forgejo; promote to required for the OSS release.
- **[Nice]** Import mappings for common formats (OpenNumismat, Colnect,
  generic spreadsheets).
- ✔ **[Nice]** Audit/history of edits to an item (append-only, field-level
  diffs).
- ✔ **[Nice]** Dark mode / theming (CSS variables, header toggle, validated
  dark chart palette).

## 6. Open-source readiness [OSS]

Only relevant if Cabinet is released publicly, but cheap to keep in mind.

- ✔ **[OSS]** LICENSE chosen and applied — MIT.
- ✔ **[OSS]** CONTRIBUTING guide, issue/PR templates, code of conduct,
  security policy.
- ✔ **[OSS]** Setup docs good enough for a stranger to self-host in one
  sitting — README quick start plus `deployment.md` (secrets, reverse proxy +
  auth, storage, scheduled backups, upgrades).
- ✔ **[OSS]** Seed/demo data and screenshots — `scripts/seed_demo.py` seeds a
  13-item demo collection; screenshots are captured headlessly at a fixed
  viewport, with the exact command recorded in `docs/screenshots/README.md`
  so they can be regenerated rather than re-staged by hand.
- ✔ **[OSS]** Automated tests and CI on pull requests — GitHub Actions runs
  ruff, 81 backend tests on Python 3.10 and 3.14, a frontend typecheck, and a
  full compose build with migrations and an API smoke test.
- ✔ **[OSS]** Versioned releases and a changelog — `CHANGELOG.md`, version
  reported by `GET /api/health` and in the OpenAPI spec.
- ✔ **[OSS]** Database migrations (not just create-on-startup) for safe
  upgrades — Alembic since Phase 0, revisions `0001`–`0008`.

---

## Phased roadmap

Each phase ends at a state that is usable on its own, so the tool is never
"half-built and unusable" between milestones.

### Phase 0 — Foundations ✔
Scaffolding so features have somewhere to live. From this phase on, Cabinet is
built with Claude Code (see `claude-code.md`); commit the repo-root `CLAUDE.md`
early so every session starts with full context.
- Backend app skeleton (FastAPI), database models, migrations baseline.
- Establish and record the test, lint, and migration commands in `CLAUDE.md`.
- Frontend app skeleton (React + Vite) wired to the API.
- Compose stack running end to end with the nginx proxy.
- Health check. (CI was deferred — see the Platform section; it arrives with
  the Forgejo push.)
*Exit: `docker compose up` serves an empty but working app.*

### Phase 1 — Usable catalog (MVP) ✔
The point at which you can actually start entering your collection.
- Item CRUD with core fields; list + detail views.
- Basic sorting and filtering.
- Photo upload with obverse/reverse and a primary image.
- Manual value entry.
- CSV export.
*Exit: you can catalog real items with photos and see them back.*

### Phase 2 — Polished catalog ✔
Schema-completing phase: add the fields that are cheap now and expensive after
the whole collection is entered.
- New item fields: status (owned/sold/wishlist + sold date/price), composition
  + weight + fineness, certification (service + cert number), acquisition
  source, storage/location.
- Grading and catalog-reference reference tables + UI (seed Sheldon/PMG scales
  via data migration).
- Full-text search and advanced filters; list filter/sort state persisted in
  the URL.
- Tags, clone-item.
- Thumbnails + EXIF correction (Pillow — also validate that uploads are real
  images, not just a trusted content-type); multiple photos; reorder/designate.
- CSV import + backup/restore that is documented **and rehearsed** — one script
  for pg_dump + photo volume together, with a tested restore drill.
- Responsive UI pass.
*Exit: pleasant day-to-day cataloging; safe to trust with the whole collection.*

### Phase 3 — Valuation ✔
Easiest-first ordering: melt value is deterministic and ToS-clean; sold-listing
comps are the hardest integration, so they come last, not first.
- Melt-value adapter (spot price × weight × fineness) as the first automatic
  source; optional user-set confidence on manual entries.
- Collection total value + cost basis vs. estimate — with the multi-currency
  decision made explicitly (a declared display currency at Phase 3; upgraded
  to daily-rate conversion in Phase 5A).
- Adapter interface for further sources; confidence scoring.
- Sold-listing comps integration as the stretch goal — **deferred**; still
  the natural next valuation feature (subject to terms of service).
*Exit: the collection has trackable, sourced value estimates.*

### Phase 4 — Insights & reporting ✔
- Dashboard and breakdowns (country, type, year, grade, tag).
- Gain/loss view — realized (sold items) and unrealized; Excel export;
  printable/insurance report (print-optimized HTML — the browser's
  Print → PDF replaces a server-side PDF library on purpose: lighter, and the
  user controls paper/margins).
- Basic charts.
*Exit: you can understand and report on the collection at a glance.*

### Phase 5 — Depth & niceties (3 of 4 bundles ✔)
Pull from the **[Nice]** items as desired, roughly in value order:
- ✔ **5A — value depth:** scheduled re-estimation, currency conversion
  (daily ECB rates), value-over-time charts.
- ✔ **5B — catalog depth:** varieties/sub-types, sets/lots, custom fields,
  bulk edit. (Wishlist is covered by item status from Phase 2.)
- ✔ **5C — polish:** completeness checklists, dark mode, edit history.
- **Photo niceties — not pulled yet:** in-browser image editing, lightbox,
  clipboard/drag-drop/URL upload, webcam capture.

### Phase 5.5 — Pricing program: settings, sources, reports
Fully enable configurable price estimation: a settings surface, the two
researched external sources, estimate provenance, and pricing-quality
reports. Staged so each milestone is independently useful.

- **M1 — Settings backbone + page.** ✔ `app_settings` table and
  `GET/PUT /api/settings` (secrets encrypted at rest, write-only, masked on
  read — see `security.md`); a `/settings`
  page with General (app-wide display currency, melt refresh cadence, melt
  on/off), Price sources (Numista API key + toggle, PCGS token + toggle —
  configurable ahead of their adapters), and Cached data (current spot
  prices and exchange rates with fetch times). Display currency and
  re-estimation cadence move from env/hardcoded into DB settings with env
  fallback.
- **M2 — Numista adapter.** ✔ Coins *and* notes priced by `numista` catalog
  ref + grade (free key, 2,000 req/month); upstream responses cached in
  `source_cache` (revision `0009`, issues 30d / prices 7d, stale-tolerant);
  enabled only when a key is configured; medium confidence
  (collector-swap-derived estimates, 0.60 — 0.45 when the exact grade bucket
  isn't priced and the nearest lower one stands in). `POST
  /api/items/{id}/estimate?source=numista`.
- **M3 — PCGS adapter.** US coins by PCGS number/cert: price-guide values
  (medium confidence) and Auction Prices Realized (high confidence — real
  sales); OAuth token from the PCGS public API program, 1,000 calls/day.
- **M4 — Estimate provenance.** Store each source's response summary
  alongside the estimate (`price_estimates.details`) so a value can be
  explained, not just asserted; filter value history by source.
- **M5 — Pricing reports.** Estimate coverage (items lacking estimates and
  why — no ref, source unconfigured, fetch failed), stale-estimates view,
  per-source breakdown, and estimate-vs-reality accuracy (last estimate
  against realized price on sold items).

*Exit: every priceable item has a sourced, explainable, configurable
estimate — and you can see where pricing is thin.*

### Phase 6 — Open-source release [OSS] ✔ (v0.9.0)
- ✔ MIT license, contributing guide, code of conduct, security policy, issue
  and PR templates, Dependabot.
- ✔ Hardened setup docs (`deployment.md`), CI on PRs, changelog + versioned
  release, demo seed data, screenshots.
- ✔ Migration story for upgrades (Alembic end to end).
- Application-level authentication remains **deliberately unbuilt**: proxy-level
  forward-auth (Traefik + Authentik) is the documented path, and app login is
  only required for direct public exposure. Revisit if that changes.
- The repository itself is still private — publishing is a separate decision.
*Exit: a stranger can find, trust, deploy, and contribute to Cabinet.*

---

## Notes on sequencing

- **Auth is deliberately late — and mostly external.** For homelab deployment,
  an authenticating reverse proxy (Traefik + Authentik forward-auth) covers
  private networked use with zero application code. App-level login is only a
  prerequisite for direct public exposure or the OSS release, so it sits there.
- **Schema-complete before data-complete.** Phase 2 front-loaded every field
  the collection would need (status, composition, certification, provenance)
  because adding columns is cheap before the full collection is entered and
  tedious after.
- **Valuation before insights.** Reports about value are only meaningful once
  estimates exist, so Phase 3 preceded Phase 4.
- **Easiest price source first.** Melt value shipped before sold-listing
  comps: it is deterministic, needs no external agreement, and covers the
  bullion floor of most collections. Comps remain the open valuation item.
- **Migrations are real.** Alembic since Phase 0; every schema change is a
  revision (`0001`–`0007`), never create-on-startup.
- **External APIs get the same treatment:** keyless, cached in the database,
  stale-tolerant, and never trusted with collection data (spot prices via
  gold-api.com, exchange rates via frankfurter.dev).
- **[Nice] items are intentionally unordered within Phase 5** — pulled by
  preference, since this is a personal tool first. Three of four bundles are
  in; photo niceties await an itch.
