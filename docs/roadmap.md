# Cabinet — Features & Roadmap

Cabinet is a single-user, self-hosted numismatics collection manager. This
document lists the full intended feature set and sequences it into phases. The
guiding principle: reach a genuinely useful tool early (Phase 1–2), then deepen
cataloging, valuation, and insights. Open-sourcing is a possible endgame, so
phases that matter for that (docs, packaging, polish) are called out explicitly
rather than assumed.

Legend: **[MVP]** core to a usable tool · **[Core]** expected of a polished
tool · **[Nice]** valuable but deferrable · **[OSS]** matters mainly if
released publicly.

---

## 1. Cataloging

The heart of the app: describing what you own, accurately and flexibly.

- **[MVP]** Add / edit / delete items (coins and notes).
- **[MVP]** Core fields: type, country, denomination, year, mint mark, series,
  quantity, acquisition date, acquisition price + currency, free-text notes.
- **[MVP]** List view with sorting and basic filtering (type, country, year).
- **[MVP]** Item detail view.
- **[Core]** Item status: `owned` / `sold` / `wishlist`, with sold date and
  realized price on sold items. Enables *realized* gain/loss reporting in
  Phase 4 and subsumes the separate wishlist feature.
- **[Core]** Composition & weight: metal, weight (g), fineness as structured
  fields — prerequisite for melt-value estimation in Phase 3.
- **[Core]** Grading: attach a grade from a recognized scale (Sheldon for
  coins; PMG / PCGS-style for notes), stored against a reference table.
- **[Core]** Certification tracking: grading service + cert number for slabbed
  pieces (distinct from the grade; verifiable and insurance-relevant).
- **[Core]** Acquisition source: where a piece came from (dealer, show,
  auction, inheritance) — provenance in one field.
- **[Core]** Catalog references: link items to Krause / Numista / Red Book
  numbers for identification and price matching.
- **[Core]** Full-text search across notes, series, and identifiers.
- **[Core]** Advanced / combined filters (grade ranges, value ranges, tags).
- **[Core]** Tags / custom labels for arbitrary grouping (type sets, wishlists,
  "for sale").
- **[Core]** Duplicate / clone an item to speed up entering similar pieces.
- **[Nice]** Varieties & sub-types (e.g. die varieties, overdates) as
  structured data rather than notes.
- **[Nice]** Lots & sets: group items sold or held together, with set-level
  metadata.
- **[Nice]** Storage/location tracking (which album, slab, box, safe).
- **[Nice]** Custom user-defined fields.
- **[Nice]** Bulk edit across multiple items.

## 2. Photo management

- **[MVP]** Upload photos per item; store originals on the photo volume.
- **[MVP]** Obverse / reverse designation; mark a primary image.
- **[Core]** Automatic thumbnail generation and EXIF-orientation correction.
- **[Core]** Multiple photos per item (obverse, reverse, edge, detail, slab).
- **[Core]** Delete / reorder photos; change designation.
- **[Nice]** In-browser crop / rotate / straighten.
- **[Nice]** Drag-and-drop and paste-from-clipboard upload.
- **[Nice]** Import a photo from a URL.
- **[Nice]** Lightbox / zoom for close inspection.
- **[Nice]** Webcam capture for direct photographing.

## 3. Market price / valuation

See `price-sources.md` for the sourcing detail and caveats. Value estimates are
guidance, not appraisals.

- **[MVP]** Manual value entry: record a value you researched, with source and
  date, stored as a timestamped estimate.
- **[Core]** Melt value: spot price × weight × fineness for precious-metal
  items. Deterministic, high-confidence, ToS-clean — the *first* automatic
  source, not the last.
- **[Core]** Estimate history retained per item (append-only), so value can be
  tracked over time.
- **[Core]** Collection total value (sum of latest estimates), with cost basis
  vs. estimated value. Requires an explicit multi-currency answer *before*
  building: simple daily-rate conversion, or a declared single display
  currency — a total that silently mixes currencies is wrong.
- **[Core]** On-demand estimate: look up comparables by catalog ref + grade and
  record an estimate with a confidence score.
- **[Nice]** Pluggable price-source adapters (sold-listing comps, price
  guides), each toggleable and rate-limited.
- **[Nice]** Scheduled / periodic re-estimation of the whole collection.
- **[Nice]** Currency conversion for multi-currency collections.
- **[Nice]** Value-over-time chart per item and per collection.

## 4. Stats, reports & insights

- **[Core]** Dashboard: counts, total cost basis, total estimated value, and
  top-level breakdowns.
- **[Core]** Breakdowns by country, type, year/decade, grade, and tag.
- **[Core]** Cost-basis vs. estimated-value comparison (unrealized gain/loss).
- **[Core]** Export the collection to CSV / Excel.
- **[Nice]** Printable / PDF collection report.
- **[Nice]** Charts: composition, value distribution, acquisitions over time.
- **[Nice]** Completeness tracking against a target set (e.g. a date/mint run).
- **[Nice]** Insurance report (itemized values, photos, totals).

## 5. Platform, data & operations

Cross-cutting concerns that make the tool trustworthy and pleasant to run.

- **[MVP]** Containerized deployment via Docker Compose (backend, proxy, db).
- **[MVP]** Persistent storage for data and photos; config via `.env`.
- **[MVP]** Auto-generated API docs (OpenAPI / Swagger).
- **[Core]** Data import: bring in an existing collection from CSV.
- **[Core]** Backup / restore: a simple, documented way to dump and restore the
  database and photos together.
- **[Core]** Responsive UI that works on phone and tablet, not just desktop.
- **[Core]** Data validation and sensible error messages.
- **[Nice]** Authentication. For homelab deployment behind an authenticating
  reverse proxy (e.g. Traefik + Authentik forward-auth), no application code is
  needed — that is the intended path for private networked use. Application-
  level login only becomes necessary for direct public exposure or the OSS
  release.
- **[Nice]** CI (ruff + pytest + image build) once the repo is pushed to the
  homelab Forgejo; promote to required for the OSS release.
- **[Nice]** Import mappings for common formats (OpenNumismat, Colnect, generic
  spreadsheets).
- **[Nice]** Audit/history of edits to an item.
- **[Nice]** Dark mode / theming.

## 6. Open-source readiness [OSS]

Only relevant if Cabinet is released publicly, but cheap to keep in mind.

- **[OSS]** LICENSE chosen and applied.
- **[OSS]** CONTRIBUTING guide, issue/PR templates, code of conduct.
- **[OSS]** Setup docs good enough for a stranger to self-host in one sitting.
- **[OSS]** Seed/demo data and screenshots.
- **[OSS]** Automated tests and CI on pull requests.
- **[OSS]** Versioned releases and a changelog.
- **[OSS]** Database migrations (not just create-on-startup) for safe upgrades.

---

## Phased roadmap

Each phase ends at a state that is usable on its own, so the tool is never
"half-built and unusable" between milestones.

### Phase 0 — Foundations
Scaffolding so features have somewhere to live. From this phase on, Cabinet is
built with Claude Code (see `claude-code.md`); commit the repo-root `CLAUDE.md`
early so every session starts with full context.
- Backend app skeleton (FastAPI), database models, migrations baseline.
- Establish and record the test, lint, and migration commands in `CLAUDE.md`.
- Frontend app skeleton (React + Vite) wired to the API.
- Compose stack running end to end with the nginx proxy.
- Health check. (CI was deferred — see the Platform section; it arrives with
  the Forgejo push.)
*Exit: `docker compose up` serves an empty but working app.* ✔ Done.

### Phase 1 — Usable catalog (MVP)
The point at which you can actually start entering your collection.
- Item CRUD with core fields; list + detail views.
- Basic sorting and filtering.
- Photo upload with obverse/reverse and a primary image.
- Manual value entry.
- CSV export.
*Exit: you can catalog real items with photos and see them back.* ✔ Done.

### Phase 2 — Polished catalog (Core cataloging + photos)
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

### Phase 3 — Valuation
Easiest-first ordering: melt value is deterministic and ToS-clean; sold-listing
comps are the hardest integration, so they come last, not first.
- Melt-value adapter (spot price × weight × fineness) as the first automatic
  source; allow optional user-set confidence on manual entries.
- Collection total value + cost basis vs. estimate — with the multi-currency
  decision made explicitly (simple conversion or declared display currency).
- Adapter interface for further sources; confidence scoring.
- Sold-listing comps integration as the stretch goal (subject to terms of
  service).
*Exit: the collection has trackable, sourced value estimates.*

### Phase 4 — Insights & reporting
- Dashboard and breakdowns (country, type, year, grade, tag).
- Gain/loss view — realized (sold items) and unrealized; Excel export;
  printable/insurance PDF report.
- Basic charts.
*Exit: you can understand and report on the collection at a glance.*

### Phase 5 — Depth & niceties
Pull from the **[Nice]** items as desired, roughly in value order:
- Varieties/sub-types, sets/lots, custom fields, bulk edit. (Wishlist is
  covered by item status in Phase 2.)
- In-browser image editing, lightbox, clipboard/URL upload, webcam.
- Scheduled re-estimation, full currency conversion, value-over-time charts.
- Completeness tracking, dark mode, edit history.

### Phase 6 — Open-source release [OSS]
Only if/when you decide to publish.
- Authentication, license, contributing docs, seed data, screenshots.
- Hardened setup docs, CI on PRs, versioned releases + changelog.
- Migration story for upgrades.
*Exit: a stranger can find, trust, deploy, and contribute to Cabinet.*

---

## Notes on sequencing

- **Auth is deliberately late — and mostly external.** For homelab deployment,
  an authenticating reverse proxy (Traefik + Authentik forward-auth) covers
  private networked use with zero application code. App-level login is only a
  prerequisite for direct public exposure or the OSS release, so it sits there.
- **Schema-complete before data-complete.** Phase 2 front-loads every field
  the collection will need (status, composition, certification, provenance)
  because adding columns is cheap before the full collection is entered and
  tedious after.
- **Valuation before insights.** Reports about value are only meaningful once
  estimates exist, so Phase 3 precedes Phase 4.
- **Easiest price source first.** Melt value ships before sold-listing comps:
  it is deterministic, needs no external agreement, and covers the bullion
  floor of most collections.
- **Migrations are already real.** Alembic has been in place since Phase 0
  (baseline `0001`, Phase 1 tables in `0002`) — every schema change from here
  is a revision, never create-on-startup.
- **[Nice] items are intentionally unordered within Phase 5** — pull whichever
  scratch your own itch first, since this is a personal tool first.
