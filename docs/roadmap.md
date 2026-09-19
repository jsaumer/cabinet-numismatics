# Cabinet — Features & Roadmap

Cabinet is a single-user, self-hosted numismatics collection manager. This
document lists the full intended feature set and sequences it into phases. The
guiding principle: reach a genuinely useful tool early (Phase 1–2), then deepen
cataloging, valuation, and insights. Open-sourcing is a possible endgame, so
phases that matter for that (docs, packaging, polish) are called out explicitly
rather than assumed.

**Status (September 2026): released as v0.21.1**, with versioned images
published to GHCR and running on a homelab Docker Swarm. Phases 0–5 are built, pricing-program M1–M5 are done — settings
backbone, the Numista and PCGS adapters, per-source value display with a
configurable blended-value strategy, scheduled auto-refresh for both
sources, and estimate provenance — in-app backup (Phase 5.6 B1 + B2) shipped
in v0.12.0, and the open-source readiness track (Phase 6) is complete apart
from application-level login, deliberately deferred in favour of
proxy-level auth.
A ✔ marks shipped items below. A second review on 19 September 2026 — with
v0.21.0 live and the real collection still to be entered — surveyed what
other coin-collection tools offer and re-planned everything unshipped into
**Phase 5.9**: entering the collection quickly first, then the money and the
paperwork, then v1.0.0 with authentication, in-app restore, and sharing.

**Target versions** on the unshipped items below assume each ships alone,
following how this project actually bumps versions — new capability = minor,
small fix/addition = patch. In practice several often land together in one
release rather than one each: M2 (Numista), M3 (PCGS), the live price-source
probe script, value differentiation/strategy, and scheduled refresh were all
separate chunks of work but shipped together as v0.10.0. Treat these as
illustrative sequencing, not a commitment.

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
- ✔ **[Core]** Grading depth: strike type (business, proof, specimen) with proof
  grades; designations (CAM/DCAM, PL/DMPL, RD/RB/BN, "+", star, CAC); "details"
  grades with the problem (cleaned, damaged…); PMG's EPQ and star designations
  and grades 1–3. See Phase 5.7 C1. **Target: v0.14.0.**
- ✔ **[Core]** Physical and type fields — diameter, thickness, edge, shape,
  mintage — and banknote fields: serial number, signatures, prefix/block,
  replacement/star note, issuing bank. Phase 5.7 C2. **Target: v0.14.0.**
- ✔ **[Core]** Acquisition and sale costs: fees, shipping, and tax in cost basis;
  commission and venue on sale, so gains are net. Phase 5.7 C3.
  **Target: v0.14.0.**
- ✔ **[Nice]** Certificate verification links to PCGS, NGC, and PMG lookups.
  Phase 5.7 C4. **Target: v0.14.0.**
- ✔ **[Core]** Fill in an item from the Numista catalogue by catalogue number or
  name search. Phase 5.7 C5. **Target: v0.15.0.**
- **[Core]** Fill in an item from its PCGS cert number (type, date, mint,
  grade, designation, variety), and a duplicate warning when an item with
  the same reference, year, and mint already exists. Phase 5.9.
  **Target: v0.22.0.**
- **[Core]** Add a run: pick a catalogue type, tick its issues, and get one
  item per date and mint. Phase 5.9. **Target: v0.23.0.**
- **[Nice]** Wish-list target price and priority, alerted when an estimate
  falls to the target; statuses beyond owned/sold/wishlist — watching,
  bidding, ordered, for sale, for swap — with auction fields (house, lot,
  date, max bid, result). Phase 5.9. **Target: v0.24.0.**
- **[Nice]** Grading submissions: service, submission number, tier, fees
  (into cost basis), dates, result, and old → new cert. Phase 5.9.
  **Target: v0.26.0.**
- **[Nice]** Nested storage locations (safe → box → row), printable 2×2
  inserts and slab/box labels with QR codes, and a "verified on" physical
  audit. Phase 5.9. **Target: v0.27.0.**
- **[Nice]** Variety references by scheme and number (FS, VAM, CONECA,
  Overton…) with links to NGC VarietyPlus and VAMworld. Phase 5.9.
  **Target: v0.28.0.**
- **[Nice]** Saved list views and a choice of list columns; print or export
  any view. Phase 5.9. **Target: v0.29.0.**

## 2. Photo management

- ✔ **[MVP]** Upload photos per item; store originals on the photo volume.
- ✔ **[MVP]** Obverse / reverse designation; mark a primary image (first
  upload becomes primary automatically).
- ✔ **[Core]** Automatic thumbnail generation and EXIF-orientation correction;
  uploads validated as real images (declared content-type is not trusted).
- ✔ **[Core]** Multiple photos per item (obverse, reverse, edge, other).
- ✔ **[Core]** Delete / reorder photos; change designation; primary promotion
  on delete.
- ✔ **[Nice]** In-browser crop / rotate / straighten.
- ✔ **[Nice]** Drag-and-drop and paste-from-clipboard upload.
- ✔ **[Nice]** Import a photo from a URL.
- ✔ **[Nice]** Lightbox / zoom for close inspection.
- ✔ **[Nice]** Webcam capture for direct photographing.

*(Those five were the "photo niceties" bundle — **shipped in v0.16.0**, with
the dashboard becoming the home page.)*

- ✔ **[Nice]** Documents: receipts, certificates of authenticity, invoices,
  and grading labels (PDFs included) attached to items — one document can be
  shared by several — on their own volume, served only through the API, with
  first-page thumbnails, and in backups. Phase 5.8. **Shipped in v0.19.0.**

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
- ✔ **[Core]** On-demand estimate from comparables with a confidence score —
  a per-item **sales log** (filled by hand from eBay sold listings and
  auction archives, or from Numista's auction records on its paid API plan)
  and a `comps` source taking the median of recent matching sales. No free
  sold-price API exists for individuals — see price-sources.md.
  **Shipped in v0.17.0.**
- ✔ **[Nice]** Pluggable price-source adapters: the registry carries melt,
  **Numista** (free key, coins + notes, prices by grade — pricing M2) and
  **PCGS** (free token, US coins, price guide + Auction Prices Realized —
  pricing M3), all sharing one contract — and comps (v0.17.0). eBay
  Marketplace Insights is closed to new applicants, so eBay sales are logged
  by hand into the sales log. See the Pricing
  program phase below.
- ✔ **[Nice]** Scheduled / periodic re-estimation: the same 12h loop refreshes
  stale melt estimates (window set by `REESTIMATE_DAYS`; manual values are
  never superseded), and — independently, per source, off by default —
  Numista (7/14/30-day cadence, with the projected monthly call count shown
  against its 2,000/month free tier) and PCGS (fixed weekly; its 1,000/day
  quota needs no such caveat) once switched on in Settings. Each source keeps
  its own data current regardless of which source is currently an item's
  overall-latest estimate, since `value_strategy` may prefer or average a
  source that isn't "winning" right now. On-demand refresh from the
  dashboard (melt) and per item (any source), with a success message and a
  "time since" label on the item page.
- ✔ **[Nice]** Currency conversion for multi-currency collections (daily ECB
  rates, 24h cache, stale fallback).
- ✔ **[Nice]** Value-over-time chart per item and per collection.
- ✔ **[Nice]** Configurable blended-value strategy: a `value_strategy`
  setting (latest / preferred source / average of sources) controls the
  single value shown in the items list, CSV/XLSX export, and dashboard
  totals — separate from the item page, which always shows every source's
  own latest value as a chip.
- **[Nice]** PCGS population and eBay sold-listings / Photograde links on
  the item page. Phase 5.9. **Target: v0.22.0** (links) and **v0.28.0**
  (population).
- **[Nice]** Stack view for bullion: fine ounces by metal, premium over spot
  at purchase, cost per ounce, break-even, and spot-price thresholds through
  the alert webhook. Phase 5.9, optional and last. **Target: v0.30.0.**

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
- **[Nice]** Registry-style sets: checklist slots generated from a catalogue
  type's issues or a year and mint range, matched automatically to owned
  items, with a completion percentage and a "needed to complete" list.
  Phase 5.9. **Target: v0.23.0.**
- **[Nice]** Tax lots and realized gains by year: several purchase and sale
  records per item, partial sales, holding period, basis including fees,
  FIFO or specific identification, and a Form 8949-style CSV. Phase 5.9.
  **Target: v0.26.0.**
- **[Nice]** Insurance schedule (the insurer's per-item fields, a flag above
  the scheduling threshold, appraisal records) and an estate packet (letter
  of instruction, dealer contacts, where everything is). Phase 5.9.
  **Target: v0.28.0.**

## 5. Platform, data & operations

Cross-cutting concerns that make the tool trustworthy and pleasant to run.

- ✔ **[MVP]** Containerized deployment via Docker Compose (backend, proxy, db).
- ✔ **[MVP]** Persistent storage for data and photos; config via `.env`.
- ✔ **[MVP]** Auto-generated API docs (OpenAPI / Swagger).
- ✔ **[Core]** Data import from CSV, round-tripping the export format with
  per-row error reporting.
- ✔ **[Core]** Backup / restore: one script for pg_dump + photo archive
  together, documented **and rehearsed** (see backup-restore.md).
- ✔ **[Nice]** Backup from inside the app: download the collection as one
  `.zip` from Settings, and scheduled backups with retention. The scripts
  stay as the disaster-recovery path. See Phase 5.6. **Shipped in v0.12.0**
  (B1 download + B2 scheduled/retention; B3 restore is blocked on the auth
  decision below, no target yet).
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
  or the OSS release. **Target: v1.0.0** — unlike everything else on this
  list, auth changes the security model of every endpoint rather than adding
  a capability, and this repo's README already treats 1.0 as the "HTTP API
  is now stable" marker; auth landing is the natural trigger for declaring
  that.
- ✔ **[Nice]** CI and published images: GitHub Actions runs ruff, pytest, a
  frontend typecheck, and a compose build/migrate/smoke test on every push and
  PR; a `v*` tag push additionally publishes the backend and proxy images to
  GHCR (from v0.10.2). This landed on GitHub rather than the homelab Forgejo
  originally planned.
- ✔ **[Nice]** Import from other tools, with a preview: the user's own
  Numista collection through the API, Numista's export file, OpenNumismat
  collections (schema 9–11, photos included), and any spreadsheet through a
  column mapping (which covers Colnect, uCoin, CoinSnap, and PCGS's registry,
  whose headers couldn't be confirmed). Re-imports are deduplicated by
  origin. **Shipped in v0.18.0.**
- ✔ **[Nice]** Audit/history of edits to an item (append-only, field-level
  diffs).
- ✔ **[Nice]** Dark mode / theming (CSS variables, header toggle, validated
  dark chart palette).
- ✔ **[Core]** Safer delete: a trash with restore — one item or a selection —
  keeping photos, documents, values, and history, emptied automatically
  after 30 days (adjustable, or never). Phase 5.8. **Shipped in v0.20.0.**
- ✔ **[Nice]** Alerts and metrics: a webhook (generic JSON, ntfy, Discord,
  Slack, Gotify) for failed backups, rejected or exhausted price-source keys,
  and failed refreshes, on change and on recovery; an Uptime Kuma heartbeat;
  a Prometheus `/api/metrics` endpoint. Phase 5.8. **Shipped in v0.21.0.**
- ✔ **[Core]** Hardening: a dashboard setup checklist (backups off, no alert
  webhook, no source key), Playwright smoke tests in CI, current
  screenshots, the three ~900-line frontend files split, a trimmed
  CLAUDE.md, and a Swarm-ready stack file in the repo. Phase 5.9.
  **Shipped in v0.21.1.**
- **[Nice]** Coin-show mode: an installable mobile web app (PWA) with
  quick-add from the phone camera and slab barcode/QR scanning (PCGS → cert
  and grade, NGC → cert) feeding cert-first entry, tolerant of a bad
  connection. Phase 5.9. **Target: v0.25.0.**
- **[Nice]** Portability: Excel export with thumbnails, and an
  OpenNumismat-compatible round-trip export with a photo archive. Phase
  5.9. **Target: v0.29.0.**

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
  ruff, the backend test suite (134 tests as of v0.13.0) on Python 3.10 and 3.14, a frontend typecheck, and a
  full compose build with migrations and an API smoke test.
- ✔ **[OSS]** Versioned releases and a changelog — `CHANGELOG.md`, version
  reported by `GET /api/health` and in the OpenAPI spec.
- ✔ **[OSS]** Database migrations (not just create-on-startup) for safe
  upgrades — Alembic since Phase 0, revisions `0001`–`0016`, applied by the
  backend on startup since v0.11.1.

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
- Health check. (CI was deferred at the time — it arrived later on GitHub
  Actions; see the Platform section.)
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
- Sold-listing comps integration as the stretch goal — deferred, then built
  for **v0.17.0** as a hand-filled sales log with an optional paid Numista
  feed, since no sold-price API is open to individuals.
*Exit: the collection has trackable, sourced value estimates.*

### Phase 4 — Insights & reporting ✔
- Dashboard and breakdowns (country, type, year, grade, tag).
- Gain/loss view — realized (sold items) and unrealized; Excel export;
  printable/insurance report (print-optimized HTML — the browser's
  Print → PDF replaces a server-side PDF library on purpose: lighter, and the
  user controls paper/margins).
- Basic charts.
*Exit: you can understand and report on the collection at a glance.*

### Phase 5 — Depth & niceties ✔
Pull from the **[Nice]** items as desired, roughly in value order:
- ✔ **5A — value depth:** scheduled re-estimation, currency conversion
  (daily ECB rates), value-over-time charts.
- ✔ **5B — catalog depth:** varieties/sub-types, sets/lots, custom fields,
  bulk edit. (Wishlist is covered by item status from Phase 2.)
- ✔ **5C — polish:** completeness checklists, dark mode, edit history.
- ✔ **Photo niceties:** in-browser crop/turn/straighten, a zoomable lightbox,
  drag-and-drop, clipboard paste, and URL import, and webcam capture.
  **Shipped in v0.16.0.**

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
  `source_cache` (revision `0009`, issues and prices 7d, stale-tolerant);
  enabled only when a key is configured; medium confidence
  (collector-swap-derived estimates, 0.60 — 0.45 when the exact grade bucket
  isn't priced and the nearest lower one stands in). `POST
  /api/items/{id}/estimate?source=numista`.
- **M3 — PCGS adapter.** ✔ US coins by PCGS cert number, or PCGS number +
  Sheldon grade. CoinFacts returns both numbers in one response: Auction
  Prices Realized win when present (median of up to ten recent lots, 0.75 —
  0.85 with five or more sales), price guide otherwise (0.60). Token from the
  PCGS public API program, 1,000 calls/day, cached 7 days. Coins only —
  PCGS Banknote responses carry no price fields.
  `POST /api/items/{id}/estimate?source=pcgs`.
- **M4 — Estimate provenance.** ✔ Each source's response summary is stored
  alongside the estimate (`price_estimates.details`, revision `0010`) so a
  value can be explained, not just asserted — melt's formula inputs and spot
  price, Numista's matched issue and per-grade prices, PCGS's auction lots
  and guide value, plus data age and a stale flag. The item page shows it
  per value-history row and filters that history by source; manual entries
  take an optional note. **Shipped in v0.11.0.**
- **M5 — Pricing reports.** ✔ A Pricing page with estimate coverage (items
  lacking estimates and why — source off, missing prerequisite, what the
  source said, fetch failed, or never tried), a stale-estimates view (one
  age threshold, 7/30/90/365 days, plus estimates built from expired source
  data), a per-source breakdown (including which source supplies each
  item's shown value, and where sources disagree most), and
  estimate-vs-reality accuracy (estimates standing on the sale date against
  realized prices). "Why" needs history the estimates table can't hold — a
  failure leaves no estimate — so every automatic attempt now records its
  outcome per item and source (`estimate_attempts`, revision `0011`), and
  each adapter's local checks became a `prerequisite()` the report can run
  without spending a request. **Shipped in v0.13.0** (moved behind in-app backup, which went first once real data started going into the live
  instance).

*Exit: every priceable item has a sourced, explainable, configurable
estimate — and you can see where pricing is thin.*

### Phase 5.6 — Backup from inside the app

B1 + B2 ✔ — **shipped in v0.12.0**, pulled ahead of pricing M5 once real data
started going into the live instance. B3 restore is blocked on the auth
decision in Phase 6/section 5, no target yet.

`scripts/backup.sh` needs a shell, the host, and Docker. That is the right
tool for disaster recovery and the wrong one for "I just entered forty items
and want a copy." Move the common case into the app; the scripts stay, and
stay the documented recovery path.

- ✔ **B1 — Download a backup.** `GET /api/backup.zip` streams one archive
  holding `db.dump`, `photos.tar.gz`, and a `manifest.json` — app version,
  Alembic revision, item/photo counts, created-at, and a SHA-256 per member.
  A button in Settings. The manifest is what makes an archive *checkable*
  rather than merely present, and it is what B3 validates against.
  `?photos=false` gives a small data-only archive for moving between machines.
- ✔ **B2 — Scheduled backups + retention.** Settings gains cadence (off /
  daily / weekly) and how many to keep. The destination is the `BACKUP_DIR`
  mount (`/data/backups`), set by the deployment rather than in Settings: an
  unauthenticated page choosing where the backend writes and prunes files
  was a worse idea than a fixed mount point. The same in-process scheduler that refreshes melt estimates runs
  it and prunes the oldest; Settings reports last run, size, and outcome.
  Pointing the destination at a NAS bind mount gets backups off the box with
  no new service — see the "no cut services" rule in CLAUDE.md.
- **B3 — Restore from an upload.** Upload an archive, validate the manifest
  (schema revision compatible, checksums intact), show what would change,
  then restore behind an explicit typed confirmation. **Blocked on a
  decision:** restore is destructive and the app has no auth, so this either
  waits for authentication or stays CLI-only. B1 and B2 do not depend on it.

Implementation notes:

- The backend image had no postgres client, so B1 added one. It carries only
  `pg_dump`/`pg_restore` for majors 14–18 and libpq, from the PostgreSQL apt
  repository, and dumps with the client matching the server: pg_dump refuses
  a newer server, and a *newer* pg_dump writes settings (`transaction_timeout`)
  an older server rejects on restore — found by the restore drill against
  Postgres 16. The full `postgresql-client` packages would have pulled in
  ~50 MB of perl. The
  alternative — dumping logically through SQLAlchemy to JSON — adds no
  dependency but produces an archive `restore.sh` and `pg_restore` can't
  read, which splits the format in two. One format is worth the megabytes.
- **An unauthenticated `/api/backup.zip` hands the whole collection to
  anyone who can reach the port.** That is acceptable behind the documented
  deployment (trusted LAN, or Traefik + Authentik) and not acceptable if the
  stack is ever exposed directly. Same caveat as the rest of the API, but
  this endpoint concentrates everything into one request.
- Archives are written to a temp file in the backup directory and then
  sent, never built in memory — photo volumes get large. nginx allows
  `/api/backup*` 30 minutes, since the download starts only once the archive
  is complete (which is also what lets a failed `pg_dump` return a clean
  error instead of a truncated file). `restore.sh` accepts these archives and
  checks `SHA256SUMS` before touching anything; CI rehearses it.

Deferred unless wanted: passphrase-encrypted archives, and push targets
(S3/WebDAV/SFTP). A mounted path covers the homelab case without new
dependencies.

*Exit: a backup is one click, happens on a schedule, and an archive can be
trusted before it is restored.*

### Phase 5.7 — Catalog depth II and faster data entry

**C1–C4 ✔ shipped in v0.14.0; C5 ✔ shipped in v0.15.0.** Added by the September 2026
feature review and placed ahead of the photo niceties. The live collection is
still empty, and the schema-complete-before-data-complete rule (see Notes on
sequencing) says fields are cheap to add now and tedious once hundreds of
items need revisiting.

- ✔ **C1 — Grading depth.** A strike type on each item (business, proof,
  specimen) with proof grades on the Sheldon scale (PR/PF-60 to 70);
  designations — CAM/DCAM, PL/DMPL, copper colour RD/RB/BN, "+" grades, star
  and CAC stickers; a "details" grade recording the problem (cleaned, damaged,
  environmental…); PMG's EPQ and star designations and its missing grades 1–3.
  The price adapters must respect them: PCGS keys proofs to their own numbers
  and takes a `PlusGrade` flag, and a proof must never be priced as a
  business strike.
- ✔ **C2 — Physical and type fields.** Diameter, thickness, edge, shape, and
  mintage for coins; serial number, signatures, prefix/block,
  replacement/star note, and issuing bank for notes. Searchable where it
  matters (serial numbers especially) and round-tripped by CSV import/export —
  today these end up in custom fields or notes.
- ✔ **C3 — Acquisition and sale costs.** Costs on the way in (buyer's premium,
  shipping, tax) count toward cost basis; costs on the way out (commission,
  listing fees) and the venue or buyer are recorded on sale. Unrealized and
  realized gain, the dashboard, and the insurance report use net figures —
  without this, gains read too optimistic. The accuracy report keeps the
  gross sold price, since the estimates it judges are market prices.
- ✔ **C4 — Certificate verification links.** A link to the grading service's
  own cert lookup (PCGS, NGC, PMG), built from the cert service and number
  already stored. PCGS opens the certificate itself; NGC's and PMG's lookups
  also ask for the grade, so those open the lookup page. No API involved.
- ✔ **C5 — Fill in an item from Numista.** Enter a Numista catalogue number, or
  search by name, and pre-fill country, denomination, years, composition,
  weight, and diameter on the item form. Uses the configured key and the same
  cache as pricing (catalogue data 7 days), and fills exactly the fields melt
  pricing needs. The biggest single time-saver when entering a real
  collection by hand. It also adds the type's other catalogue references and
  lists its issues, so choosing one sets year, mint mark, and mintage; only
  empty fields are filled.

*Exit: an item record can describe any coin or note accurately — proofs,
problem coins, and notes' own details included — gains are net of costs, and
entering a catalogued piece takes seconds.*

### Phase 5.8 — Operations and quality of life

From the same review. Each targets its own minor release after import
mappings (v0.18.0); like Phase 5's bundles, they can be pulled in any order.

- ✔ **Documents** (v0.19.0) — receipts, certificates of authenticity, and
  invoices attached to items, PDFs included, shareable between items. Served
  through the API rather than the public photo path, on a volume of their own,
  and included in backups.
- ✔ **Safer delete** (v0.20.0) — deleting an item moves it, with its photos,
  documents, estimates, and history, to a trash with restore; deleting from
  the trash, emptying it, or its automatic clear-out after the retention
  period is the only permanent step.
- ✔ **Alerts and metrics** (v0.21.0) — a webhook (n8n, ntfy, Discord…) for
  failed backups, a rejected or exhausted price-source key, and failed
  scheduled refreshes, sent when each starts failing and when it recovers; an
  hourly Uptime Kuma heartbeat; and a Prometheus `/api/metrics` endpoint with
  item counts, collection value, backup age, and refresh outcomes.
The rest of this phase — wish-list targets, checklist generation, realized
gains by year, storage locations and labels, saved views, and the mobile
web app — was re-planned into Phase 5.9 by the second review.

*Exit: the collection's paperwork lives with it, mistakes are recoverable,
and failures reach you instead of a log.*

### Phase 5.9 — Entering the real collection, then the money and the paperwork

Added by a second review on 19 September 2026. v0.21.0 was live and healthy,
and the collection it held had one item: the software was well ahead of the
data. The review surveyed desktop tools (OpenNumismat, CoinManage, Carlisle,
EzCoin, Coin Elite, Koillection), web and mobile tools (Numista, Colnect,
uCoin, CoinSnap, Coinoscope, the PCGS and NGC registries and apps, Heritage,
MyCollect), and what collectors track by hand (bullion stacks, tax lots,
grading submissions, insurance schedules, estate packets). What fits a
single-user, self-hosted tool is below, ordered so each release makes
entering and using a real collection easier than the last. Sizes are
relative to the pace so far: S about a day, M a few days, L a week.

- ✔ **Hardening** (v0.21.1, M) — a dashboard setup checklist that says what's
  still off (scheduled backups, the alert webhook, a price-source key);
  Playwright smoke tests in CI, since the frontend has none; screenshots
  retaken (the current ones predate the dashboard home page, documents,
  the trash, and alerts); `ItemDetail.tsx`, `ItemForm.tsx`, and `api.ts`
  split; CLAUDE.md trimmed; a Swarm-ready stack file in the repo.
- **Cert-first entry** (v0.22.0, M) — fill the item form from a PCGS cert
  number using the public API already used for pricing (type, date, mint,
  denomination, grade, designation, variety); a duplicate warning on add
  and import; eBay sold-listings and PCGS Photograde links on the item
  page. NGC has no public API, so an NGC cert gets a lookup link only.
- **Runs and registry sets** (v0.23.0, M–L) — "Add a run": pick a Numista
  type, tick its issues (already fetched for "Fill from Numista"), get one
  item per date and mint; checklists generated from a type's issues or a
  year and mint range, matched automatically to owned items, with a
  completion percentage and a "needed to complete" list.
- **Pipeline** (v0.24.0, M) — wish-list target price and priority, alerted
  through the existing webhook when an estimate falls to the target;
  statuses watching, bidding, ordered, for sale, and for swap; auction
  fields (house, lot, date, max bid, result); a duplicates-for-trade export.
  Swap *matching* needs a community and stays out.
- **Coin-show mode** (v0.25.0, L) — an installable PWA with quick-add from
  the camera and slab barcode/QR scanning: PCGS labels carry a 22-digit
  Interleaved 2 of 5 barcode (spec number, grade, cert) and a QR code, NGC
  labels a cert barcode; the scan feeds cert-first entry. Tolerant of a bad
  connection at a show.
- **Money** (v0.26.0, L) — tax lots: several purchase and sale records per
  item, partial sales, holding period, basis including grading fees, FIFO
  or specific identification; realized gains by year with a Form 8949-style
  CSV (US collectibles gains are taxed at up to 28%); grading submissions
  (service, submission number, tier, fees into basis, dates, result,
  old → new cert).
- **Physical** (v0.27.0, M) — nested locations (safe → box → row), printable
  2×2 flip inserts and slab/box labels with QR codes that open the item, a
  "verified on" physical audit, and a safe-deposit inventory print.
- **Paperwork** (v0.28.0, M) — an insurance schedule with the insurer's
  per-item fields, a flag above the scheduling threshold (collector
  policies schedule items from about $5,000), and appraisal records; an
  estate packet (letter of instruction, dealer contacts, where everything
  is); variety reference fields by scheme and number (FS, VAM, CONECA,
  Overton) with links to NGC VarietyPlus and VAMworld — no free dataset
  exists to embed; PCGS population on the item page.
- **Views and portability** (v0.29.0, M) — saved views with a choice of
  columns, print or export any view, Excel export with thumbnails, and an
  OpenNumismat-compatible round-trip export with a photo archive — the
  answer to collectors who went back to Excel after their software was
  abandoned.
- **Stack view** (v0.30.0, M, optional and last) — for bullion: fine ounces
  by metal, premium over spot at purchase, cost per ounce, break-even, and
  spot-price thresholds through the alert webhook.

Then **v1.0.0 — auth and sharing** (L): application login, or proxy
authentication with a documented metrics exemption; in-app restore (Phase
5.6 B3); read-only showcase links; the API declared stable.

Deliberately not planned, and why: image-based identification (paid or
hosted ML; Numista's image search is a paid tier), swap matching, a
marketplace, or social features (they need a community), a report designer
(saved views plus print cover it), multiple collections and multiple users
(tags and sets; single-user by design), cloud sync (backups go to a mount),
AI grading, and dealers, buyers, or loans as their own records.

*Exit: a real collection goes in quickly — by cert, by run, by scan — and
the tool answers the money and paperwork questions a collector actually
gets asked.*

### Phase 6 — Open-source release [OSS] ✔ (v0.9.0)
- ✔ MIT license, contributing guide, code of conduct, security policy, issue
  and PR templates, Dependabot.
- ✔ Hardened setup docs (`deployment.md`), CI on PRs, changelog + versioned
  release, demo seed data, screenshots.
- ✔ Migration story for upgrades (Alembic end to end).
- Application-level authentication remains **deliberately unbuilt**: proxy-level
  forward-auth (Traefik + Authentik) is the documented path, and app login is
  only required for direct public exposure. Revisit if that changes.
  **Target: v1.0.0** — see section 5's Authentication entry for why this one
  gets the major bump instead of a minor.
- ✔ The repository is public on GitHub (since v0.10.1); versioned images are
  published to GHCR from v0.10.2.
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
  bullion floor of most collections. Comps came last (v0.17.0).
- **Migrations are real.** Alembic since Phase 0; every schema change is a
  revision (`0001`–`0016`), never create-on-startup.
- **The September 2026 review reordered what comes next.** Catalog depth
  (Phase 5.7) went ahead of the photo niceties because the live collection
  was still empty — the same reasoning that front-loaded Phase 2's fields.
  That moved photo niceties to v0.16.0, sold-listing comps to v0.17.0, and
  import mappings to v0.18.0; Phase 5.8's additions follow from v0.19.0.
- **The second review (19 September 2026) put entry speed first.** With
  v0.21.0 live and one item in it, the six unshipped items and the new ones
  from the survey were ordered by how much each speeds up entering and
  using a real collection: hardening, cert-first entry, runs and sets, the
  pipeline, coin-show mode, then money, physical, paperwork, views, and an
  optional stack view, with authentication, restore, and sharing as v1.0.0.
- **External APIs get the same treatment:** keyless, cached in the database,
  stale-tolerant, and never trusted with collection data (spot prices via
  gold-api.com, exchange rates via frankfurter.dev).
- **[Nice] items are intentionally unordered within Phase 5** — pulled by
  preference, since this is a personal tool first. All four bundles are
  in.
