# Implementation notes, by release

What each release added and the non-obvious rules it left behind — the
things a change in that area has to respect. Moved here from `CLAUDE.md`
in v0.21.x so that file stays short; `CLAUDE.md` keeps the rules that bite
most often and points here for the rest. Newest last.

## Phases 0–5 (through v0.9.x)

Phases 0–4 complete (see git history). Phase 5: three of four bundles done —
value depth (currency conversion via frankfurter.dev daily rates, value-over-
time charts, scheduled + on-demand melt refresh, `REESTIMATE_DAYS` env),
catalog depth (sets/lots, variety, custom_fields JSON, bulk edit), polish
(dark mode via CSS variables + toggle, append-only item edit history,
completeness checklists). Migrations through `0007`. Stats currency rule:
convert at cached daily rates, exclude + count what can't convert. Money is
per row (the lot). Backup/restore in scripts/, rehearsed.

## Pricing M1–M3 and scheduled refresh (v0.10.0)

Pricing program (roadmap Phase 5.5) M1: `app_settings` table (migration
`0008`), `GET/PUT /api/settings` (secrets Fernet-encrypted at rest via
`services/crypto.py` + `SECRET_KEY`, write-only, masked; see
docs/security.md), `/settings` page (display currency, melt cadence +
toggle, Numista/PCGS credentials ahead of their adapters, cached market
data). Display currency and melt cadence are DB-backed with env fallback.

M2 and M3: `services/numista.py` prices coins and notes by `numista` catalog
ref + grade, `services/pcgs.py` prices US coins by PCGS cert (or `pcgs` ref
+ Sheldon grade), preferring realized auction prices over the price guide.
Both are selected with `POST /api/items/{id}/estimate?source=`, resolved
through `pricing.get_adapter`, and share `NotApplicable` (422) /
`SourceUnavailable` (502) plus `pricing.cached_response` over the
`source_cache` table (migration `0009`).

Value differentiation + strategy: the item page shows every configured
source's own latest value as a chip (with a "time since" label), never
blending them; a `value_strategy` setting (latest / preferred source /
average, Settings → General) controls the single blended number used
everywhere else — items list (with a `SOURCE` column showing which source or
"average" produced it), CSV/XLSX export, dashboard totals — via one shared
`pricing.resolve_display_value`. Scheduled refresh covers Numista (7/14/30-
day cadence with projected monthly-call-count shown against its 2,000/month
quota) and PCGS (fixed weekly; generous 1,000/day quota) in addition to melt,
off by default, each kept fresh independent of whichever source currently
wins an item — necessary since `value_strategy` may prefer or average a
source that isn't "latest." Manual per-item refresh shows a success message.

## Estimate provenance, M4 (v0.11.0)

`price_estimates.details` (migration `0010`) holds what each adapter's
`EstimateResult.details` recorded — JSON-safe values only, never `Decimal` —
built into rows by `pricing.estimate_row` on every path, with
`pricing.freshness` supplying `data_as_of`/`stale` from `cached_fetch`'s
fetch time; manual entries take an optional `note`. The item page renders it
per value-history row and filters that history by source.

## In-app backup, B1 + B2 (v0.12.0)

`services/backup.py` writes one zip — `db.dump` (pg_dump custom format, the
same file `scripts/backup.sh` makes), `photos.tar.gz`, `manifest.json`,
`SHA256SUMS` — for `GET /api/backup.zip` and for scheduled/on-demand archives
in `BACKUP_DIR` (`/data/backups`, the `backup_data` volume; refused inside
`PHOTO_DIR` because nginx serves that). An hourly in-process loop runs
`backup.run_scheduled` against the `backup_schedule`/`backup_keep` settings
and records `backup_last_run`. The backend image copies only `pg_dump`/
`pg_restore` for majors 14–18 + libpq from the PGDG repo (multi-stage; the
full client packages pull ~50 MB of perl) into
`/usr/local/lib/pgclient/<major>`, and `backup.pg_tool` picks the server's
major — pg_dump 18 against a 16 server writes `SET transaction_timeout`,
which 16 rejects on restore. Tests monkeypatch `backup.dump_database` —
SQLite has no pg_dump; CI's stack job rehearses download → restore.sh on
real Postgres. B3 (in-app restore) stays blocked on auth.

## Pricing reports, M5 (v0.13.0)

`services/pricing_reports.py` behind `GET /api/pricing/{coverage, stale,
sources, accuracy}` and a `/pricing` page. Every automatic estimate goes
through `pricing.run_adapter`, which records the outcome in
`estimate_attempts` (one row per item + source, migration `0011`; a failure
is committed before it propagates) — so coverage can report fetch failures
and upstream "can't price" answers that leave no estimate. Each adapter's
local checks live in a `prerequisite(db, item)` (`pricing.get_prerequisite`)
that the adapter calls first and coverage calls without spending a request;
keep reason messages there, not duplicated in the adapter. Reports group
estimates as melt / numista / pcgs / manual (any other source text).
`Item.label` is the shared short display label. Tests on SQLite: timestamps
have one-second resolution, so backdate estimates when order matters.

## Catalog depth, C1–C4 (v0.14.0)

Migration `0012`: `items.strike` (business/proof/specimen — a Sheldon grade
row is reused and `Item.grade_code` prints PR-/SP- plus "+"), `grade_plus`,
`grade_star`, `designations` (JSON list validated against
`schemas.DESIGNATIONS`), `grade_details`, `cac_sticker`; coin
`diameter_mm`/`thickness_mm`/`edge`/`shape`/`mintage`; note
`serial_number`/`prefix_block`/`signatures`/`issuer`/`replacement_note`;
`acquisition_fees`, `sold_fees`, `sold_to`. `Item.grade_label`,
`Item.cost_basis`, and `Item.sale_proceeds` are properties exposed on
`ItemOut`; every gain uses cost_basis/sale_proceeds, while the accuracy
report keeps gross `sold_price`. Numista refuses non-business strikes and
details grades; PCGS sends `PlusGrade` and prices details grades by cert
only. PMG grades 1–3 were inserted with WHERE NOT EXISTS because `0003`
seeds from the same list. CSV import commits per row.

## Fill from the Numista catalogue, C5 (v0.15.0)

`numista.search_types` / `numista.catalogue_type` behind
`GET /api/numista/{search,types/{id}}` (`routers/catalogue.py`), cached via
the same `_cached`/`source_cache` as pricing (type `type:<id>`, search
`search:<category>:<q>`, issues share `issues:<id>` with estimates).
`catalogue_fields` maps a type onto item-schema keys, trimmed to schema
limits, category-aware (notes get `issuer`, never diameter); fineness is
parsed from composition text only for precious metals. The item form's
"Fill from Numista" card fills empty fields only.

## Photo niceties (v0.16.0)

`components/photos.tsx` holds the lightbox, the canvas editor (90° turns,
±15° straighten with a cover-scale so no corners show, crop box in fractions
of the turned frame, exported at full resolution), and the webcam modal; the
item page adds drop, paste, and URL import. Backend:
`POST /api/items/{id}/photos/url` (`photos.fetch_remote_image` — http(s),
public addresses only at every redirect hop, 3 redirects, 25 MB) and
`PUT /api/photos/{id}/image`, which saves under a fresh file stem so cached
images aren't reused. The dashboard is the home page (`/`); the list is
`/collection`, and `/?filters` and `/dashboard` redirect.

## Sold-listing comps (v0.17.0)

Migration `0013`. Research found no free sold-price API for individuals
(eBay's is closed, auction houses forbid automation, Numista's
`sales_records` is paid-plan only), so each item has a sales log
(`comparables`, `routers/comparables.py`) and `services/comps.py` is a
fourth adapter (`comps`, keyless, on by default) — median of included,
grade-bucket-matching sales from the last 3 years (older if fewer than 3),
converted at daily rates. `numista.fetch_sales` feeds Numista's auction
records into the log behind `numista_sales_enabled` (off; a 403 there means
no paid plan, raised as `NotApplicable(PAID_PLAN)`), on click only, cached a
day. Numista catalogue caching dropped to 7 days (licence §8.3).
PriceCharting/Greysheet were researched and not planned.

## Import from other tools (v0.18.0–v0.18.2)

Migration `0014`: `items.import_source` + `import_key`, unique together;
clone skips them. `services/import_formats.py` reads each source into
`importing.Candidate`s — `cabinet` (Cabinet's own CSV/XLSX export, detected
by its columns, rows validated by `items._row_to_payload` into
`Candidate.ready`, keyed by the exported id; added in v0.18.1 after v0.18.0
read it as a plain spreadsheet), `spreadsheet` (field → column mapping,
`suggest_mapping` — headers normalized with underscores as spaces — header
row found past preambles), `numista_file` (by header name), `opennumismat`
(SQLite; schema ≤10 keeps buy/sell on `coins`, 11 moved them to `prices`;
photos read lazily via `BlobReader`), and `numista_account`
(`numista.fetch_collection`: OAuth client-credentials with the stored key,
collection cached 1h, `type_fields` per type — fields plus `catalog_refs`;
titles split by `importing.split_title`, which handles both `X "Name"` and
`X - Name`, fixed in v0.18.2) — and `services/importing.py` resolves grades
(`parse_grade`; Numista buckets → the band's lowest grade), validates
through `ItemCreate`, previews, and imports one commit per item via
`items._build_item`. Files are staged under `IMPORT_DIR` (temp, 1 GB, a
day) so preview and run read the same upload; `/api/imports/numista/*`
routes are registered before `/{upload_id}/*`. Test fixtures are synthetic
(`tests/import_samples.py`, also written to `docs/import-samples/`) —
OpenNumismat's own demo files are GPL, keep them out.

## Documents (v0.19.0)

Migration `0015`: `documents` + `item_documents`, many-to-many;
`services/documents.py`, `routers/documents.py`. Files live on their own
`document_data` volume at `DOCUMENT_DIR` (the user chose a new volume over
the state volume or Postgres), never `PHOTO_DIR`; uploads are refused (503)
unless it's a mount point (`/proc/self/mountinfo`;
`REQUIRE_DOCUMENT_MOUNT=false` in tests/dev) — a Swarm needs a new bind.
Type from bytes: `%PDF-` + PDFium open (pypdfium2, page-one JPEG thumbnail;
password-protected kept without one) or Pillow JPEG/PNG/WebP; HEIC refused.
Served by the API with `nosniff` and CSP `default-src 'none'` (+`sandbox`
for images only — `sandbox` blanks Chrome's PDF viewer); no bundled pdf.js.
Unlinking from the last item, or purging that item, deletes the file.
Backups add `documents.tar.gz` (follows the photos flag),
`backup.sh`/`restore.sh` handle it, CI's drill restores a PDF byte for byte.

## The trash (v0.20.0)

Migration `0016`, `items.deleted_at`. `models.item._hide_trashed` is a
`do_orm_execute` listener adding `with_loader_criteria(Item, deleted_at IS
NULL)` to every ORM select unless `.execution_options(include_deleted=True)`
— so new queries hide trashed items for free, but anything counting through
a link table (tag counts) or deciding a document's last holder
(`trash.links`, counted on `item_documents`) must handle trashed items
itself. `get_item_or_404` treats trashed as missing unless `include_deleted`
(only GET, restore, and delete use it), so every other item endpoint is
read-only by default. `services/trash.py` moves, restores, purges (the old
hard delete), and `purge_expired` runs in the hourly loop
(`trash_retention_days`, 0 = never, default 30). `DELETE /api/items/{id}`
trashes; `?permanent=true` purges. Imports and Cabinet-export dedupe look
into the trash. CI's stack job drives the API with curl (smoke test, backup
→ restore drill) — when an endpoint's behaviour changes, update those steps
too; pytest won't catch them (the trash broke the drill's `DELETE`).

## Alerts and metrics (v0.21.0)

No migration; state lives in `app_settings`. `services/alerts.py` keeps
each condition in `CONDITIONS` (backup, `<source>_key`/`_quota`,
`refresh_<source>`) in the `alert_state` setting, and `fail`/`recover` send
the webhook only on a change, on a background thread (`_spawn`; tests run it
inline). `KeyRejected` / `QuotaExhausted` (subclasses of `SourceUnavailable`)
are raised by the Numista and PCGS request helpers; `pricing.cached_fetch`
reports them — even when stale cache covers — and any successful fetch
recovers them, and `refresh_source_estimates` stops at the first one. The
loops' work lives in `services/scheduled.py` (`refresh` records
`refresh_last_run` and the refresh alerts; `hourly` = backup, trash,
heartbeat). `services/metrics.py` renders `/api/metrics` via
`prometheus_client` from DB queries plus the dashboard's own
`collection_stats`, cached 60s; delivery/heartbeat outcomes are in memory.
Webhook and heartbeat URLs are secrets (`SECRET_KEYS`); error details never
repeat a URL (`alerts._describe`). See docs/monitoring.md.

## Hardening (v0.21.x)

The frontend API client is `src/api/` (`types/*` by area, `client.ts`,
`calls.ts`, `index.ts` re-exporting everything, so imports stay
`from "../api"`). The item page is `pages/ItemDetail.tsx` plus
`components/photo-gallery.tsx`, `components/value-history.tsx`, and
`components/provenance.tsx` (which also owns `timeSince`, `sourceKey`, and
`latestBySource`); the item form is `pages/ItemForm.tsx` plus
`pages/item-form/model.ts` (form state, `toPayload`, `fromItem`, the
designation/problem lists) and `pages/item-form/NumistaFill.tsx`.
`components/setup.tsx` is the dashboard's setup checklist, hidden for 30
days through `localStorage` and back on any new problem. Playwright smoke
tests in `frontend/e2e/` run in CI's stack job against the compose stack;
`deploy/docker-stack.yaml` is the Swarm stack file.

## Cert-first entry (v0.22.0)

`pcgs.cert_facts` reuses the pricing lookup's cache key (`certfacts:<cert>`,
`retrieveAllData=true`), so a fill and the estimate that follows cost one
request; `pcgs.cert_fields` maps the CoinFacts model (fields confirmed from
the API's swagger: PCGSNo, Year, Denomination, MintMark, SeriesName,
MetalContent, Weight, Diameter, Edge, Mintage, Grade, Designation, the
varieties, Population, PopHigher, CoinFactsLink) onto item-schema keys, and
`pcgs.parse_grade` turns `Grade` + `Designation` into a Sheldon rank, strike,
plus flag, and Cabinet's designation codes; the frontend picks the grade row
by rank from `/api/grades?scale=sheldon`. `services/duplicates.find_similar`
is shared by `GET /api/items/similar` and the importer's `_note_similar`;
matches are case- and space-insensitive, trash included, cert matches
first. Catalogue references are shared rows, so a reference match goes
through `item_catalog_refs`. The item page's outbound links live in
`components/lookup.tsx`; they're URLs only.

## Runs and registry sets (v0.23.0)

Migration `0017`: `checklists.match_catalog`/`match_ref`/`match_country`/
`match_denomination` and `checklist_slots.year`/`mint_mark`.
`services/checklists.owned_by_issue` indexes owned (status `owned`,
untrashed via the ORM listener) items of one kind — by catalogue reference
through `item_catalog_refs`, or by country + denomination — keyed by
(year, normalized mint mark). `slot_views` computes each slot's match **on
read**; nothing about a match is stored, `ChecklistSlot.filled` stays the
hand tick, and the API's `filled` is tick-or-match. The same index marks
`owned` issues in `GET /api/numista/types/{id}` and lets `POST
/api/items/run` skip them. A run builds each `ItemCreate` from
`numista.catalogue_type`'s fields (less `year`/`mintage`) + the issue + the
shared fields, through `_build_item`, in one transaction. Mint marks match
as written (`P` ≠ blank). `POST /api/checklists/generate` and
`POST /api/items/run` are declared before the `/{id}` routes.

## Releases

Pushing a `v*` tag runs CI's `publish` job, which pushes
`ghcr.io/jsaumer/cabinet-numismatics-{backend,proxy}` (version + `latest`;
nothing before v0.10.2 is published). The live homelab instance pins those
tags, so a release reaches it only once the tag's images exist; from v0.11.1
the backend migrates on startup, so an upgrade there is just a tag bump.
