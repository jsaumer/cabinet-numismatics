# Implementation notes, by release

What each release added and the non-obvious rules it left behind: the
things a change in that area has to respect. Moved here from `CLAUDE.md`
in v0.21.x so that file stays short; `CLAUDE.md` keeps the rules that bite
most often and points here for the rest. Newest last.

## Phases 0–5 (through v0.9.x)

Phases 0–4 complete (see git history). Phase 5: three of four bundles done:
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
Both are selected with `POST /api/items/{id}/estimates/auto?source=` (it was
`.../estimate` until v0.30.0), resolved
through `pricing.get_adapter`, and share `NotApplicable` (422) /
`SourceUnavailable` (502) plus `pricing.cached_response` over the
`source_cache` table (migration `0009`).

Value differentiation + strategy: the item page shows every configured
source's own latest value as a chip (with a "time since" label), never
blending them; a `value_strategy` setting (latest / preferred source /
average, Settings → General) controls the single blended number used
everywhere else: items list (with a `SOURCE` column showing which source or
"average" produced it), CSV/XLSX export, dashboard totals, all via one shared
`pricing.resolve_display_value`. Scheduled refresh covers Numista (7/14/30-
day cadence with projected monthly-call-count shown against its 2,000/month
quota) and PCGS (fixed weekly; 1,000/day when built, 100/day by default since) in
addition to melt,
off by default, each kept fresh independent of whichever source currently
wins an item, necessary since `value_strategy` may prefer or average a
source that isn't "latest." Manual per-item refresh shows a success message.

## Estimate provenance, M4 (v0.11.0)

`price_estimates.details` (migration `0010`) holds what each adapter's
`EstimateResult.details` recorded (JSON-safe values only, never `Decimal`),
built into rows by `pricing.estimate_row` on every path, with
`pricing.freshness` supplying `data_as_of`/`stale` from `cached_fetch`'s
fetch time; manual entries take an optional `note`. The item page renders it
per value-history row and filters that history by source.

## In-app backup, B1 + B2 (v0.12.0)

`services/backup.py` writes one zip of `db.dump` (pg_dump custom format, the
same file `scripts/backup.sh` makes), `photos.tar.gz`, `manifest.json`, and
`SHA256SUMS` for `GET /api/backup.zip` and for scheduled/on-demand archives
in `BACKUP_DIR` (`/data/backups`, the `backup_data` volume; refused inside
`PHOTO_DIR` because nginx serves that). An hourly in-process loop runs
`backup.run_scheduled` against the `backup_schedule`/`backup_keep` settings
and records `backup_last_run`. The backend image copies only `pg_dump`/
`pg_restore` for majors 14–18 + libpq from the PGDG repo (multi-stage; the
full client packages pull ~50 MB of perl) into
`/usr/local/lib/pgclient/<major>`, and `backup.pg_tool` picks the server's
major: pg_dump 18 against a 16 server writes `SET transaction_timeout`,
which 16 rejects on restore. Tests monkeypatch `backup.dump_database`
(SQLite has no pg_dump); CI's stack job rehearses download → restore.sh on
real Postgres. B3 (in-app restore) was blocked on auth until the owner unblocked it; it is
roadmap Phase 7, P2.

## Pricing reports, M5 (v0.13.0)

`services/pricing_reports.py` behind `GET /api/pricing/{coverage, stale,
sources, accuracy}` and a `/pricing` page. Every automatic estimate goes
through `pricing.run_adapter`, which records the outcome in
`estimate_attempts` (one row per item + source, migration `0011`; a failure
is committed before it propagates), so coverage can report fetch failures
and upstream "can't price" answers that leave no estimate. Each adapter's
local checks live in a `prerequisite(db, item)` (`pricing.get_prerequisite`)
that the adapter calls first and coverage calls without spending a request;
keep reason messages there, not duplicated in the adapter. Reports group
estimates as melt / numista / pcgs / manual (any other source text).
`Item.label` is the shared short display label. Tests on SQLite: timestamps
have one-second resolution, so backdate estimates when order matters.

## Catalog depth, C1–C4 (v0.14.0)

Migration `0012`: `items.strike` (business/proof/specimen; a Sheldon grade
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
`POST /api/items/{id}/photos/url` (`photos.fetch_remote_image`: http(s),
public addresses only at every redirect hop, 3 redirects, 25 MB) and
`PUT /api/photos/{id}/image`, which saves under a fresh file stem so cached
images aren't reused. The dashboard is the home page (`/`); the list is
`/collection`, and `/?filters` and `/dashboard` redirect.

## Sold-listing comps (v0.17.0)

Migration `0013`. Research found no free sold-price API for individuals
(eBay's is closed, auction houses forbid automation, Numista's
`sales_records` is paid-plan only), so each item has a sales log
(`comparables`, `routers/comparables.py`) and `services/comps.py` is a
fourth adapter (`comps`, keyless, on by default): median of included,
grade-bucket-matching sales from the last 3 years (older if fewer than 3),
converted at daily rates. `numista.fetch_sales` feeds Numista's auction
records into the log behind `numista_sales_enabled` (off; a 403 there means
no paid plan, raised as `NotApplicable(PAID_PLAN)`), on click only, cached a
day. Numista catalogue caching dropped to 7 days (licence §8.3's limit for
catalogue metadata; §8.4, personal projects, is what permits the cache).
PriceCharting/Greysheet were researched and not planned.

## Import from other tools (v0.18.0–v0.18.2)

Migration `0014`: `items.import_source` + `import_key`, unique together;
clone skips them. `services/import_formats.py` reads each source into
`importing.Candidate`s: `cabinet` (Cabinet's own CSV/XLSX export, detected
by its columns, rows validated by `items._row_to_payload` into
`Candidate.ready`, keyed by the exported id; added in v0.18.1 after v0.18.0
read it as a plain spreadsheet), `spreadsheet` (field → column mapping,
`suggest_mapping` normalizing headers with underscores as spaces, header
row found past preambles), `numista_file` (by header name), `opennumismat`
(SQLite; schema ≤10 keeps buy/sell on `coins`, 11 moved them to `prices`;
photos read lazily via `BlobReader`), and `numista_account`
(`numista.fetch_collection`: OAuth client-credentials with the stored key,
collection cached 1h, `type_fields` per type giving fields plus `catalog_refs`;
titles split by `importing.split_title`, which handles both `X "Name"` and
`X - Name`, fixed in v0.18.2). `services/importing.py` resolves grades
(`parse_grade`; Numista buckets → the band's lowest grade), validates
through `ItemCreate`, previews, and imports one commit per item via
`items._build_item`. Files are staged under `IMPORT_DIR` (temp, 1 GB, a
day) so preview and run read the same upload; `/api/imports/numista/*`
routes are registered before `/{upload_id}/*`. Test fixtures are synthetic
(`tests/import_samples.py`, also written to `docs/import-samples/`):
OpenNumismat's own demo files are GPL, keep them out.

## Documents (v0.19.0)

Migration `0015`: `documents` + `item_documents`, many-to-many;
`services/documents.py`, `routers/documents.py`. Files live on their own
`document_data` volume at `DOCUMENT_DIR` (the user chose a new volume over
the state volume or Postgres), never `PHOTO_DIR`; uploads are refused (503)
unless it's a mount point (`/proc/self/mountinfo`;
`REQUIRE_DOCUMENT_MOUNT=false` in tests/dev), so a Swarm needs a new bind.
Type from bytes: `%PDF-` + PDFium open (pypdfium2, page-one JPEG thumbnail;
password-protected kept without one) or Pillow JPEG/PNG/WebP; HEIC refused.
Served by the API with `nosniff` and CSP `default-src 'none'` (+`sandbox`
for images only: `sandbox` blanks Chrome's PDF viewer); no bundled pdf.js.
Unlinking from the last item, or purging that item, deletes the file.
Backups add `documents.tar.gz` (follows the photos flag),
`backup.sh`/`restore.sh` handle it, CI's drill restores a PDF byte for byte.

## The trash (v0.20.0)

Migration `0016`, `items.deleted_at`. `models.item._hide_trashed` is a
`do_orm_execute` listener adding `with_loader_criteria(Item, deleted_at IS
NULL)` to every ORM select unless `.execution_options(include_deleted=True)`,
so new queries hide trashed items for free, but anything counting through
a link table (tag counts) or deciding a document's last holder
(`trash.links`, counted on `item_documents`) must handle trashed items
itself. `get_item_or_404` treats trashed as missing unless `include_deleted`
(only GET, restore, and delete use it), so every other item endpoint is
read-only by default. `services/trash.py` moves, restores, purges (the old
hard delete), and `purge_expired` runs in the hourly loop
(`trash_retention_days`, 0 = never, default 30). `DELETE /api/items/{id}`
trashes; `?permanent=true` purges. Imports and Cabinet-export dedupe look
into the trash. CI's stack job drives the API with curl (smoke test, backup
→ restore drill). When an endpoint's behaviour changes, update those steps
too; pytest won't catch them (the trash broke the drill's `DELETE`).

## Alerts and metrics (v0.21.0)

No migration; state lives in `app_settings`. `services/alerts.py` keeps
each condition in `CONDITIONS` (backup, `<source>_key`/`_quota`,
`refresh_<source>`) in the `alert_state` setting, and `fail`/`recover` send
the webhook only on a change, on a background thread (`_spawn`; tests run it
inline). `KeyRejected` / `QuotaExhausted` (subclasses of `SourceUnavailable`)
are raised by the Numista and PCGS request helpers; `pricing.cached_fetch`
reports them, even when stale cache covers, and any successful fetch
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
`components/setup.tsx` is the dashboard's setup checklist; "Don't show this
again" dismisses it for good in that browser (`localStorage`
`cabinet.setup.dismissed`; from v0.22.0, replacing a 30-day snooze). Playwright smoke
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
untrashed via the ORM listener) items of one kind (by catalogue reference
through `item_catalog_refs`, or by country + denomination) keyed by
(year, normalized mint mark). `slot_views` computes each slot's match **on
read**; nothing about a match is stored, `ChecklistSlot.filled` stays the
hand tick, and the API's `filled` is tick-or-match. The same index marks
`owned` issues in `GET /api/numista/types/{id}` and lets `POST
/api/items/run` skip them. A run builds each `ItemCreate` from
`numista.catalogue_type`'s fields (less `year`/`mintage`) + the issue + the
shared fields, through `_build_item`, in one transaction. Mint marks match
as written (`P` ≠ blank). `POST /api/checklists/generate` and
`POST /api/items/run` are declared before the `/{id}` routes.

## Security hardening (v0.23.1)

`backend/docker-entrypoint.sh` starts as root, chowns each data directory
whose top-level owner isn't `PUID` (a one-time hand-over, never a walk on
every start), and `exec setpriv`s to `PUID:PGID`; if a directory still isn't
writable it logs that and stays root. `docker compose exec` still enters as
root, which is why `restore.sh` chowns what it extracts to the volume's
owner. The image installs `requirements.txt` with `--require-hashes`, then
the project with `--no-deps`, then uninstalls pip (Trivy flags the msgpack
and setuptools pip bundles), so there is no pip in the running container.
`proxy/nginx.conf`: an `add_header` inside a `location` replaces the
server-level ones, so `location /` repeats them alongside its CSP (from
v0.30.0 by including `cabinet-headers.conf`); `/api/` gets no CSP from nginx
(documents set their own). New inline scripts, external fonts, or iframes will trip
the CSP, and the e2e header test visits the main pages to catch that.

## Interface polish (v0.24.0)

`api.money` formats through `Intl.NumberFormat` (currency style, the
browser's locale, formatters cached per code) and falls back to
`12.50 XYZ` for a code the browser rejects; tests that look for an amount
look for `$12.50`. Icons are inline SVG in `components/icons.tsx` (the CSP
allows nothing external, and emoji differ by system); settings is drawn as
sliders because a gear that small reads as a sun. `components/controls.tsx`
has `FileButton` (the real input stays inside the label, visually hidden
but focusable, so keyboard and Playwright's `setInputFiles` still work) and
`Menu`. The palette is the `:root` tokens in `styles.css` (bronze `--accent`,
warm surfaces, `--font`: a Calibri-first system stack with
`font-size-adjust`, since the CSP's `font-src` is `'self'`; the serif titles
of v0.24.0 lasted one release). The theme defaults to dark
(`components/theme.ts`, and `data-theme="dark"` on `<html>` so there's no
light flash before the script runs); only `localStorage` overrides it, so
screenshots set that key (`docs/screenshots/capture.cjs`). No em dashes anywhere; see CLAUDE.md.

## PCGS fill normalisation (v0.24.5)

Confirmed against the live API with a real cert: `parse_grade` and
`cert_fields` read PCGS's answer correctly. `pcgs._country` and
`pcgs._mint_mark` then bring it into line with hand entry and the Numista
fill ("United States"; "P" only where it is on the coin), because matching
everywhere is by the text as written. The same cert showed the live
`AuctionList` dating lots `MM-YYYY`; `pcgs_estimate` counts only lots inside
`APR_MAX_AGE` (five years), falls back to the guide, then to old lots
(`basis` `apr` / `guide` / `apr_old`), and keeps uncounted lots in
`details.older_lots`. Test fixtures date their lots relative to today so
they don't age out.

## Parity fields (v0.25.0)

Roadmap Phase 7's P1 and P3 to P6 in one release. Migration `0018`: fourteen
nullable columns on `items` (population, `target_price`/`priority`, the
National Bank Note fields, `serial_traits`, `die_axis`, the date as struck).

- **Two fields are server-set**, never accepted from a client (they are on
  `ItemOut`, not `ItemBase`/`ItemUpdate`): `serial_traits` and
  `population_as_of`. `_build_item` sets both (so create, the run, and every
  import path do), and `items._sync_derived` keeps them in step after an
  update **and a bulk edit**: traits when `serial_number` or
  `replacement_note` changed, the date when either population figure changed
  (cleared when both are). Clone re-stamps the date. A PCGS estimate sets all
  three population fields from the response it already has, dated by the
  response's fetch time (`pricing._as_utc(fetched_at)`), and leaves the item
  alone when PCGS reports none. Any new path that writes a serial number or
  a population has to do the same.
- **Traits** come from `services/serials.traits` (digits only, leading zeros
  kept, four digits at least; `TRAITS` is also the order and the reference
  endpoint's labels). A solid is only `solid`; `super_radar` and
  `super_repeater` replace `radar` and `repeater`. They are stored
  comma-wrapped (`,radar,binary,`, or NULL) so `serial_trait=` is a
  `LIKE '%,radar,%'` that can't match inside `super_radar`; `ItemOut` splits
  the string into the API's list. An unknown `serial_trait` is a 422, since
  the value goes into a LIKE pattern. Migration `0018` backfills with a
  **frozen copy** of the function: never import the service into a
  migration, and don't edit that copy when the rules change (rows are
  recomputed the next time their serial is saved; a rule change that must
  reach existing rows needs a new data migration).
- **`pricing.add_estimate(db, item, row)` is the one way a `price_estimates`
  row is added** (the manual endpoint, `POST .../estimates/auto`, and both
  scheduled refreshes), because it is where a wish-list target is noticed.
  Don't `db.add` an estimate anywhere else. It looks up the previous newest
  estimate before adding the row, and the caller commits.
- **`alerts.event` is not `fail`/`recover`.** An event is delivered once
  through the same formats (`status` `event`, its own title, the key as
  `alert`) if a webhook is saved, and never touches `alert_state`, so it has
  no recovery, no Settings row, and no metric. The target event fires on the
  crossing: status `wishlist`, a `target_price`, the new estimate in the
  item's currency at or under it, and the estimate before it over it, in
  another currency, or missing.
- **The gap uses the newest estimate, not the shown value.**
  `Item.target_gap`/`target_reached`, the list's `target_reached=true`
  (`_latest_value_subquery` for value and for currency), and the alert all
  take the newest `price_estimates` row, whatever `value_strategy` says, and
  only when its currency equals the item's; nothing is converted. Keep the
  three in agreement.
- **Target and priority survive a status change** (the owner's decision).
  The form only hides them off the wishlist; `toPayload` still sends them,
  so a coin bought later keeps what it was wanted at.
- **The year and the date as struck.** On create, `ItemCreate`'s
  before-validator fills a missing `year` from `calendars.to_gregorian`; a
  given year stands. On update, `_apply_struck_date` checks the era rule
  against the item as it will be, leaves `year` alone when the `PATCH`
  doesn't name it, and converts only on an explicit `year: null` beside a
  struck calendar and year. `japanese` needs an era, and an era without it
  is a 422. Bulk edit skips this check. The form fills Year from
  `/api/reference/convert-date` only when Year is empty or still holds the
  form's own earlier conversion (`autoYear`); a typed year is never
  overwritten.
- **Calendar labels are parsed.** The item page takes a calendar's short
  name from the parentheses that end its label (`Islamic (AH)` gives
  `AH 1335 (1917)`; `Republic of China (Minguo)` gives `Minguo`), and uses
  the era's label for `japanese`. A new entry in `calendars.CALENDARS` needs
  a label ending in `(short name)`, or the whole label is shown.
- **Nulls-last sorts are portable.** `priority` and `target_price`
  (`NULLS_LAST`) order by `column IS NULL` first, then the column, which
  puts empty rows last in both directions on SQLite and Postgres alike;
  `NULLS LAST` is not used because SQLite's support depends on its version.
- `q` also matches `charter_number` and `bank_city` (`issuer` already did).
  `friedberg` and `pick` are only suggestions in the form's datalist and
  link builders in `components/lookup.tsx`; the catalogue stays free text.
  `GET /api/stats/notes-by-signature` groups in Python over the ORM select,
  so the trash is hidden for free.
- The export gained twelve columns (not `serial_traits` or
  `population_as_of`, which the import recomputes); an older export still
  imports. `components/serial-traits.tsx` fetches the trait labels once per
  session. The seed has a National Bank Note, a repeater serial, an AH-dated
  coin, and a wishlist target to show them.

## v0.25.1

`components/lookup.tsx` matches a catalogue by several names, because the
Numista fill writes Pick as `p: P#109` (so `p` and `pick`, `fr`/`f` and
`friedberg`), and searches for the bare number. `HBars` sizes its label
column from the longest label (`--hbar-label`, in `ch`) and left-aligns it:
a fixed right-aligned gutter made short-label charts look centred.

## In-app restore (v0.26.0)

No migration. `services/restore.py`, `services/maintenance.py`,
`routers/restore.py`, `components/restore.tsx`; the procedure is in
docs/backup-restore.md. What a change here has to respect:

- **Order.** Safety backup, unpack into `.restore-new` inside each volume
  (touches nothing live), database, migrations, then the file swap
  (`_Swap`, renames only) in `finishing`, after the database committed. The
  status `step` follows that order, so `photos`/`documents` mean unpacking.
  Anything that can fail cheaply belongs before the database step, where
  the error can still end "Nothing was changed." (`NOTHING_CHANGED`).
- **`restore.restore_database(dump_path)` is the monkeypatch point** (SQLite
  has no pg_restore), like `backup.dump_database`. It drops tables the dump
  doesn't hold before `pg_restore --single-transaction` (`--clean` only
  drops what the dump knows, and a newer table's foreign keys block it);
  that is the one change outside the transaction, so a failure after it
  raises `PartialDatabase`, whose message names the tables and the safety
  backup instead of claiming nothing changed.
- **Maintenance** (`MaintenanceMiddleware`, plain ASGI so streamed responses
  pass through): everything answers 503 except `maintenance.EXEMPT`,
  `GET /api/health` and `GET /api/restore/status`. Anything added to that
  list must not touch the database. `/api/restore*` requests aren't counted
  as in flight, or `drain()` (30 s) would wait on the request that started
  the restore. The scheduled loops wrap their work in
  `maintenance.scheduled_task()`; a new loop must too, and `restore.start`
  refuses while one holds it.
- **`/api/health` must not touch the database during a restore**
  (`db: "restoring"`): pg_restore holds exclusive locks, and a hung health
  check gets the container killed mid-restore on a Swarm.
- **Never rename or remove `PHOTO_DIR` or `DOCUMENT_DIR`**: they are mount
  points. The swap moves their top-level entries, skipping `.restore-*` and
  `.nfs*`.
- **`backup.RESTORE_PREFIX` (`.restore-`) names stay excluded everywhere**:
  the tar filter in `backup.write_archive`, `_safe_target` on the way in,
  `stored_backups`/`prune` (which match `NAME_RE` on files only, so
  `.restore-staging` is never listed or pruned as an archive), and nginx's
  dot-name 404 under `/photos/`. A new walk over either volume, or a new
  listing of `BACKUP_DIR`, has to skip them as well.
- **Tar members** go through `_safe_target` at inspect (422) and again in
  `_extract`, which is written by hand: plain files and folders only, no
  modes or ownership. Don't replace it with `extractall`.
- **The ending order in `_finish`**: write `restore_last.json`, maintenance
  off, then set the final state, then release the locks, so whoever sees
  `done` or `failed` can already read the outcome and call the API.
- **Outcome and journal are files on the state volume** (beside
  `SECRET_KEY_FILE`), never the database, which is what was replaced. The
  journal's `phase` is `preparing` or `swapping`; `recover()` runs on
  startup before migrations and rolls a `swapping` restore forward
  (`_Swap.apply` is repeatable, the `MOVED_OUT` marker says which half is
  done) or clears `.restore-new`. A non-empty `.restore-old` only survives
  a failed put-back, may hold the only copy, and makes the next restore
  refuse; never delete it automatically.
- **Pre-restore archives** (`backup.write_prerestore`): verified after
  writing, not recorded as `backup_last_run` (that database is about to go),
  outside `backup_keep` in `prune`, newest `PRERESTORE_KEEP` (3) kept, and
  the archive being restored is never pruned (`protect`). They match
  `NAME_RE`, so they are listed (`prerestore: true`), downloadable,
  restorable, and counted by the backup metrics.
- **`backup._run_lock` is held for the whole restore**, with restore's own
  lock, so no backup starts meanwhile; `write_prerestore` expects the caller
  to hold it. Busy (another restore, a backup, a scheduled task) is 409.
- **Uploads** are parsed with `python_multipart` straight into
  `BACKUP_DIR/.restore-staging/<id>.zip`; FastAPI's `UploadFile` would spool
  20 GB through the container's temp folder. `_pending` (restore ids) is in
  memory; `DELETE` only ever unlinks a staged upload.
- **After a restore** the engine is disposed and `metrics.reset_cache()` /
  `alerts.reset_memory()` run; any new in-memory cache of database state
  needs the same. Settings, `backup_last_run` and `alert_state` included,
  are whatever the archive held.
- **Tests** (`tests/test_restore.py`) run the thread inline (`restore._spawn`
  patched), record rather than run `restore_database`, and stub
  `dispose_engine` (disposing the StaticPool engine drops the in-memory
  database) and `migrate`; conftest points `SECRET_KEY_FILE` at a temp state
  folder and calls `restore.reset_memory()`. Real Postgres is covered by
  CI's in-app drill (after the restore.sh drill) and the Playwright restore
  test, which is last in `smoke.spec.ts` on purpose.
- **Not covered**: NFS volumes, and an archive from a genuinely older
  release (the older-revision path ran against a rewritten manifest). The
  manifest isn't in `SHA256SUMS`, so verification catches corruption only.
- nginx: `location /api/restore` (20g, `proxy_request_buffering off`, 60m)
  sits before `location /api/`; `RESTORE_MAX_GB` above 20 needs it raised.

## v0.26.1

The first real NFS restore failed in the swap: renaming a DIRECTORY into
another parent needs write permission on the directory itself, and item
folders made before v0.23.1 were root-owned inside a volume whose top level
already belonged to `PUID` (so the entrypoint's owner check never recursed).
`restore.check_movable` now walks the target folders at inspect and again at
the start of a run, before the safety backup and the database; the
entrypoint also chowns first-level entries not owned by `PUID` (one `find
-maxdepth 1`, still never a walk of the whole volume on every start). Local
gotcha met while proving it: rebuilding only the backend leaves nginx
holding the old container's address (502 until the proxy restarts); a Swarm
service VIP doesn't have that problem.

## A customisable dashboard (v0.27.0)

Roadmap Phase 7, P10. `backend/app/services/dashboard.py` and
`routers/dashboard.py`; `frontend/src/dashboard/` (`registry.tsx`,
`widgets/*.tsx`, `data.ts`, `edit.tsx`, `WidgetFrame.tsx`,
`options.ts`); `pages/Dashboard.tsx` is now the shell. No migration: the
layout sits under the generic `dashboard_layout` key in `app_settings` (see
docs/data-model.md), read and written only by `/api/dashboard/layout`.
What a later change has to respect:

- **Adding a widget type needs three things in step**: a `REGISTRY` entry in
  `registry.tsx` (name, description, group, default size, default options,
  the options-form fields, the `Component`), a matching entry in the
  backend's `WIDGET_OPTIONS` and `DEFAULT_SIZES` (`services/dashboard.py`),
  and a row in the widget table in docs/api.md. The backend is the source of
  truth for what is valid; the frontend registry has to describe exactly
  that, or a value the form can produce would fail `PUT` validation, or a
  value the backend accepts would have no field to set it.
- **Retiring a widget type** means removing it from both `WIDGET_OPTIONS`
  and `REGISTRY`. Nothing else is needed: `normalize_for_read` drops an
  unknown type from a stored layout silently, and the frontend's grid
  already skips a widget whose type isn't in `REGISTRY` (`Dashboard.tsx`,
  "a widget this build retired"). Existing saved layouts keep working; the
  retired type just stops appearing in them.
- **Changing an option** (adding a choice, narrowing a range, changing a
  default) is a `WIDGET_OPTIONS` edit plus the matching `registry.tsx` field
  and `docs/api.md` row. A stored value that is no longer valid is replaced
  by the new default on the next `GET`, not rejected: only `PUT` is strict.
  Don't remove an option outright without checking nothing still reads it
  from a widget's `options`; an option not in `WIDGET_OPTIONS` is stripped
  from both `GET` and `PUT` bodies.
- **The migration hook** (`dashboard.MIGRATIONS`, keyed by the version being
  migrated *from*) is empty today; a future document-shape change adds a
  function there rather than a new code path in `normalize_for_read`.
  `CURRENT_VERSION` moves up by one, and a stored layout runs through every
  migration between its version and the current one before normalisation.
- **The drag listens on `window`, not the handle, and does not use pointer
  capture.** Reordering keyed React children moves the handle's DOM node,
  and a moved node loses whatever pointer capture it held, so the release
  event would never arrive; listening on `window` for `pointermove` /
  `pointerup` / `pointercancel` survives the handle being relocated
  mid-drag. The landing spot (`Reorder.order` in `edit.tsx`) is held steady
  while the pointer sits over the dragged card's own placeholder, or cards
  would shuffle under a pointer that isn't moving.
- **The data cache** (`dashboard/data.ts`) is one page-lifetime `Map` keyed
  by request identity (several breakdown widgets with the same `tag`/
  `set_id` share one key, so they fetch once); a failed request is evicted
  so the next mount retries. It is invalidated (`invalidateData()`) by
  "Refresh melt values" and after a layout Save, since either can change
  what every widget should show. A widget added mid-edit and saved needs
  data nothing has fetched yet, which is why Save invalidates rather than
  only refetching what changed.
- **The setup checklist is now a widget**, not a fixed card. `setup.tsx`
  exports `setupChecks()` (the same checks, taking the settings/backups/
  health it needs as arguments instead of fetching them itself) and
  `SetupList` (just the list and the dismiss button); the `setup` widget
  (`widgets/value.tsx`'s `SetupWidget`) supplies the three requests through
  the shared cache. The empty-collection page still renders `SetupWidget`
  directly, outside the grid, since there is no layout to show yet.
- **`top_n` on the breakdown widget only trims a dimension sorted by size**
  (`country`, `type`, `grade`, `tag`; `DIMENSIONS[key].trim` in
  `widgets/breakdowns.tsx`): the rest become one "Other" bar. `decade` and
  `acquisition_year` run in time order, where an "Other" bucket would mean
  nothing, and keep every value regardless of `top_n`.
- **Widgets below the fold don't fetch until they are near the viewport**
  (`WidgetFrame`'s `IntersectionObserver`, `rootMargin: "300px"`), and each
  widget has its own error boundary, so one broken widget shows its error in
  its own card rather than blanking the page.

## Undated pieces and Numista varieties (v0.27.1)

Two bugs found on the owner's own pieces. Migration `0019` makes
`items.year` nullable and adds `items.year_nd` (not nullable, default
false); a data step turns an existing `year = 0` into `year = NULL,
year_nd = true`. There is no service logic in the migration to freeze
(unlike `0018`'s serial traits): the data step is a plain column update, so
a later change to the ND rule needs no matching migration.

- **The year-or-ND rule lives in the schema and `_apply_struck_date`, in one
  place each.** `ItemBase`'s `_year_or_nd` model validator (create) and
  `routers/items._apply_struck_date` (update, checked against the item as
  it will be after the patch) are the only places that enforce it; a new
  path that writes `year`/`year_nd` must go through one of them, not
  duplicate the check. Bulk edit deliberately skips both: `year_nd` isn't
  bulk-editable, so a bulk `year: null` is refused outright rather than
  checked against ND.
- **`item.year` can be `None` everywhere now.** Anything that does
  arithmetic on it (`stats.breakdowns`'s decade bucket, `pcgs._mint_mark`,
  `checklists.owned_by_issue`'s key, the insurance report, `metrics`, a
  serial "date note" trait that looks at the year) has to guard it. The
  decade breakdown puts a null year in its own `Undated` bucket
  (`routers/stats.UNDATED`), sorted after every decade.
- **Always print `year_label`, never `year` or `str(year)`.** `Item.year_label`
  (`"1922"`, `"ND"`, or `"ND (1922)"`) is what `Item.label` ends with, and
  what the frontend prints everywhere a year appears (title, list, trash,
  reports, dashboard widgets, duplicate warning, import preview); a list
  entry carries its own `year_label` for the same reason. A raw `item.year`
  in a template or an f-string will crash or print `None` on an ND item.
- **`importing.parse_year(value) -> tuple[int | None, bool]` is the one year
  parser for every import path** (the Cabinet CSV, the spreadsheet mapping,
  a Numista export file, `to_year` stays underneath it for the numeric
  read). An unparseable cell, an empty cell, and a literal `0` all read as
  undated; `"ND (1951)"` / `"(1951)"` read as undated with `1951`
  attributed. The Numista account import doesn't go through it (it works
  from the API's own `is_dated`/year fields via `numista.issue_nd`), but
  follows the same result shape.
- **Numista's candidate order and the 4-try cap.** `numista.candidate_issues`
  pools same-year issues (or same-ND issues for an ND item with no year, or
  a type's lone issue as a last resort, flagged `year_mismatch`), ranks the
  pool (mint letter, replacement agreement, a reference/variety/signatures
  text match, ND agreement, original order), and `numista_estimate` tries
  the ranked list, best first, capped at `MAX_CANDIDATES = 4`: each untried
  issue costs one Numista request for its prices. A 404 on one candidate's
  prices, or an issue with no priced grade at all, moves to the next (a
  price in another grade still stands in through `resolve_grade`); only the
  first success is used. Every candidate's prices sit under the same
  `prices:{type}:{issue}:{currency}` cache key as before, an empty price
  list included, so walking the list again inside the TTL costs no request
  (a 404 is an exception, never cached, and costs one each time). `pick_issue` still returns
  the first candidate, for `fetch_sales` and any other caller that wants
  one issue rather than a ranked list.
- **The web-search lookup links (`components/lookup.tsx`) still use the raw
  year.** An ND item's Friedberg/Pick/eBay search links carry the
  attributed year if there is one, or none; they were not taught the "ND"
  convention, since a search engine wouldn't understand it either.
- **"Add a run" still keys owned-issue matching on `(year, mint)`.** Two
  undated varieties of the same type with the same attributed year and
  mint mark collapse into one slot in `checklists.owned_by_issue` and one
  skip in a run, same as two dated varieties would; nothing in this release
  changed that key to include the reference or comment that tells them
  apart.

## Bullion stack figures (v0.28.0)

Roadmap Phase 7, P7. `services/stack.py`, `routers/stack.py`, migration
`0020`. What a later change here has to respect:

- **What the stack is has one definition, agreed on three sides.**
  `Item.fine_oz` (weight × fineness × quantity ÷ `TROY_OUNCE_G`, null unless
  `detect_metal(composition)` and `effective_fineness` both give an answer),
  `stack.in_scope` (the tag/set filter on top of it), and melt value
  (`pricing.py`) must never disagree about which pieces are bullion. A new
  path that changes what counts as a precious metal or a usable fineness has
  to update `detect_metal`/`effective_fineness` once, not separately in the
  stack service.
- **No network call on the item save path.** `spot_at_purchase` only ever
  arrives from a client (`manual`) or from `stack.backfill`/the hourly loop
  (`auto`); creating or updating an item never itself fetches a spot price.
  Filling one in is `POST /api/stack/backfill` (button) or the hourly tick,
  at most 20/50 items at a time.
- **Purchase-day spot comes only from the CC0 fawazahmed0 currency-api,
  never LBMA.** LBMA's public JSON price series goes back to 1968, further
  than the currency-api's 2024-03-02 start, but LBMA and ICE Benchmark
  Administration require a licence to use benchmark data for valuation, so
  Cabinet does not fetch it and must not gain an LBMA adapter without one.
  gold-api.com's history needs a key. A purchase before 2024-03-02 takes a
  hand-typed figure; there is no way around that without a licensed source.
- **The historic-spot cache never expires early, and never covers today.**
  `stack.historic_spot` caches under `spot_history` for ten years, because a
  past day's price never changes; it refuses today or a future date (422:
  use the current spot price instead) so nothing is ever cached that could
  still change.
- **A typed `spot_at_purchase` is never overwritten.** `stack.needs_spot`
  is the one eligibility check the backfill, the hourly loop, and
  `GET /api/stack`'s `missing_spot` count all use; a piece with any value
  already in `spot_at_purchase` is never eligible, auto or manual.
- **The per-item premium stays in the item's own currency; the per-metal
  premium aggregates in the report currency.** `Item.premium_paid_pct` never
  converts (cost and purchase-day spot are always in the same currency
  already). The metal bucket's `premium_paid_pct` sums `cost_basis` and
  `fine_oz * spot_at_purchase` in the report currency first, over only the
  pieces where both convert, then takes one ratio; an unconvertible item's
  premium is left out of the metal figure (though its ounces still count
  elsewhere).
- **Spot alerts are events, not conditions.** `stack.check_spot_alerts` calls
  `alerts.event`, the same one-shot delivery `wishlist_target` uses, not
  `alerts.fail`/`recover`: a threshold has no "recovery" message, isn't
  listed among the checks in Settings, and doesn't touch
  `cabinet_alert_failing`. State lives in the `spot_alert_state` setting
  (per threshold key, met or not), written only by the service; saving a new
  `spot_alerts` list prunes state for any threshold no longer in it, so
  re-adding one alerts again instead of staying quiet.
- **Both new hourly hooks sit inside the existing `maintenance.scheduled_task()`
  wrapper**, like every other loop, and each is wrapped in its own
  `try`/`except` that rolls back and logs: a missing purchase-day price or a
  failed spot fetch is not worth an alert of its own.
- **The widget is registered on both sides.** `stack` in the frontend
  `REGISTRY` (`frontend/src/dashboard/registry.tsx`) and in the backend
  `WIDGET_OPTIONS`/`DEFAULT_SIZES` (`services/dashboard.py`) have to agree on
  the same options (`metal`, `tag`), or the options form and the server's
  validation disagree too; it is deliberately left out of the default
  layout.
- `pricing._money` was renamed `pricing.money` (no longer private: the stack
  service uses it too for alert messages).
- `GET /api/stack` commits at the end of the request, so a spot price or
  exchange rate it had to fetch is cached for the next call, the same as
  other read endpoints that go through `pricing.cached_fetch`.
- `items.weight_g` widened from `Numeric(8, 3)` to `Numeric(9, 4)` in the
  same migration as the two new columns: a troy ounce is 31.1035 g, and
  three decimal places could not hold a one-ounce round weight (found by the
  new Playwright test). The item form's Weight field takes four decimals now.

## Note details, the item page, more widgets (v0.29.0)

Migration `0021`: `items.width_mm`, `height_mm` (Numeric(7, 2), for notes and
anything else not round; coins keep `diameter_mm`), `printer`, `watermark`
(String(200)), and `demonetized_on` (Date, coins and notes alike). None are
bulk-editable; the router drops them there like `spot_at_purchase`. Clone
needed no code change: it copies every column. What a later change here has
to respect:

- **A new item field needs a home or it is invisible.** The item page no
  longer shows a dash for every field: `components/item-facts.tsx`'s
  `groups` array is the only place a fact reaches the page, and a field left
  out of every group's `facts` list is never shown, filled or empty. A field
  essential enough to read before anything else (the grade, the value, a
  wishlist target) belongs in `components/item-hero.tsx` instead, or in
  both if the hero shows a short form and the facts card the full one.
- **Never print a dash for an empty field outside "Show empty fields".**
  `ItemFacts`'s `filled()` and the per-fact `forType` are what decide a
  field shows at all; a group holding nothing (or, per `inHero`, only a
  fact the hero already shows) is left out entirely rather than rendered
  empty. The "Show empty fields" choice lives in `localStorage`
  `cabinet.item.showEmpty` only, never on the server: it is a per-viewer
  reading preference, not collection data.
- **Keep the Playwright selectors the page promises.** The h1 text, the
  `$12.50`-style money text, cert/badge classes, and the Edit/Clone/Delete
  buttons moved into `ItemHero` and stayed outside the disabled `fieldset`
  so a trashed item can still be restored; a further split must keep them
  exactly as `smoke.spec.ts` and `docs/screenshots/capture.cjs` find them.
- **`services/insights.py` follows `routers/stats.py`'s currency rule**:
  amounts convert into the requested currency at cached daily rates,
  unconvertible ones are excluded and counted, nothing is guessed. `quality`
  and `value-spread` take `?currency=`; `data-health` counts items, not
  money, so it takes none.
- **The showcase choice must stay storage-free and stable within a day.**
  `insights.showcase`'s piece of the day is a hash of today's calendar date
  over owned items (preferring ones with a photo), so it is the same answer
  on every request that day and needs no column, cache row, or scheduled
  job to keep it that way. Don't replace the hash with anything that reads
  "now" more precisely than the date.
- **Widget types are registered on both sides.** The ten new types
  (`most_valuable` through `data_health`) and `metal` as a `breakdown`
  dimension are in both `backend/app/services/dashboard.py`
  (`WIDGET_OPTIONS`/`DEFAULT_SIZES`) and `frontend/src/dashboard/registry.tsx`
  (`REGISTRY`), same as any other widget; see the existing rule on adding or
  retiring one.
- **The Numista banknote mapping is unconfirmed and must never fail a
  fill.** `numista.catalogue_fields`'s reading of `size`/`size2`, `printers`,
  `watermark`, and `demonetization` was written without a live key on the
  dev machine, so every shape is read defensively (wrong type, missing key,
  or absent field all fall through to leaving that item field empty) and a
  fill never raises over it. Confirming it against a real response is an
  open item, like "Add a run" against live Numista; see the roadmap's road
  to v1.0.0.

## v0.29.1

Two things the owner hit on a real note. The photo tile's controls were
wider than the tile (150px), so every delete button but the last sat under
the next tile's first arrow: the tile is 190px and `.photo-card .row` wraps
compact controls inside it. Anything added to that row has to fit the tile;
the check is that each button is the top element at its own centre. A photo
whose file is gone (`img.missing`, set by `onError`) keeps a full-size tile
so it can be deleted. And `DELETE /api/items/{id}/estimates/{estimate_id}`
removes a typed-in value only: `pricing.source_key(source) in
pricing.ADAPTER_NAMES` is a source's estimate and answers 409, because
coverage, accuracy, and provenance read that history. Don't widen it to
sources without deciding what those reports should then say.

## Sign-in and encrypted backups (v0.30.0, being built)

Roadmap Phase 7, P8 A1, built stage by stage to
[SPEC_0300](specs/SPEC_0300.md) on the `p8-auth-a1` branch. Rules so far:

- **The renames are done**: `POST .../estimates/auto?source=`,
  `POST /api/estimates/refresh?source=melt` (only melt; anything else 422),
  and no `POST /api/items/import`. Tests import a Cabinet CSV with
  `tests.conftest.import_cabinet_csv`, which goes through `/api/imports`
  and forces `format: cabinet` (a hand-written CSV with a few export columns
  detects as `spreadsheet`). Its errors number data rows from 1, not file
  lines, and an exported id is a duplicate even when that item is in the
  trash, so a round-trip test purges (`?permanent=true`) before re-importing.
- **`age` is a program, not a library**: Debian's package in the backend
  image, called as a subprocess, so archives stream through it however large
  they are. The Dockerfile's `age --version` step fails the build if it is
  missing. The dev machine has no `age`, so tests go through monkeypatch
  points (`backup.encrypt_stream`/`decrypt_stream`, stage 5).
- `argon2-cffi` is in the lockfile (with `argon2-cffi-bindings`; `cffi` and
  `pycparser` were already there for `cryptography`). The real hashing
  parameters arrive with the password service (stage 6);
  `tests/test_dependencies.py` only proves it installs and round-trips.
- **Deployment settings are checked before anything starts.**
  `config.check_startup` runs first in the lifespan and raises `ConfigError`
  naming the variable (`PUBLIC_ORIGINS` required and made of exact origins,
  `AUTH_INSECURE_HTTP` only beside http origins, a supplied setup code at
  least 32 characters with no character over a quarter of it, a readable
  `SETUP_CODE_FILE`); uvicorn then exits 3. `config.normalize_origin` is the
  one origin parser (lowercase, default port dropped, no path); CSRF will use
  it. Tests get `PUBLIC_ORIGINS=https://testserver` from conftest. Once the
  claimed marker exists (stage 7) the setup code is ignored, so its check
  moves behind that.
- **Every proxied nginx location includes `cabinet-proxy.conf`**, and a
  location with its own `add_header` includes `cabinet-headers.conf`: nginx
  drops the server-level `proxy_set_header` and `add_header` lines in any
  location that sets one of its own, so a new location without the include
  would pass a client's `X-Forwarded-For` or identity headers straight
  through. Forwarded headers are overwritten, never appended; identity
  headers are set to `""` (not passed). The backend runs uvicorn with
  `--no-proxy-headers`, so it never rewrites the client from a header either.
- **Host names.** `proxy/40-cabinet-hosts.sh` writes `server_name` from the
  hosts of `PUBLIC_ORIGINS` plus `ALLOWED_HOSTS` (a union, so listing an
  internal name can't drop the public one); underscores are allowed
  (`cabinet_proxy`), `_` alone, ports, schemes, and wildcards are not. The
  nginx image's entrypoint stops the container when the script fails
  (confirmed). Anything else hits the `default_server` and gets 444.
- **Plain-text secrets are never used or healed.** `crypto.decrypt` returns
  `""` for unprefixed input and `get_setting` no longer encrypts it in place.
  `app_settings.clear_unusable_secrets` clears it and records the key in
  `secrets_cleared` (a setting written only by the service, shown in
  Settings, removed per key when that secret is saved again);
  `scheduled.clear_secrets` wraps it with a commit and an `alerts.event` that
  names, never shows. It runs at startup after migrations (only when
  `AUTO_MIGRATE` is on, since tests have no database there) and first in
  every hourly tick, which also covers a database put back by `restore.sh`.
  The in-app restore calls it with `undecryptable=True` (stage 4); the audit
  event `secrets_cleared` joins it in stage 6.
- **The PCGS cert route takes `^[0-9A-Za-z-]{1,20}$`** (`CERT_PATTERN`), so
  no real cert needs a percent-encoded path. An encoded digit (`%31`)
  decodes before routing, so only the gate's refusal of any `%` (stage 7)
  catches that form.
- **No `/api/docs`**: `docs_url`, `redoc_url`, and
  `swagger_ui_oauth2_redirect_url` are all `None`; `/api/openapi.json` stays.
- **Two schemas, two chains, no crossing.** `AuthBase` (`app/models/auth.py`,
  `MetaData(schema="cabinet_auth")`) is never on `Base.metadata`, so neither
  chain's autogenerate sees the other; `alembic_auth/env.py` creates the
  schema, keeps its version table inside it, and `include_name` limits it to
  it. `schema.upgrade_to_head(engine, auth=True)` runs the collection chain
  then the sign-in chain in one transaction under the one advisory lock; a
  restore calls it with `auth=False`. `tests/test_auth_schema.py` fails on a
  foreign key across the schemas and greps each `versions/` folder for the
  other schema's name, so an auth migration must never mention `public`,
  even in a comment. On SQLite, conftest maps `cabinet_auth` to no schema
  with `schema_translate_map` on the engine (the FK pragma listener stays on
  the raw engine) and creates both metadatas.
- **Dumps and restores never touch `cabinet_auth`.** `backup.dump_command`
  adds `--exclude-schema=cabinet_auth`, `restore.restore_command` has
  `--schema=public`, the leftover-table drop reads `schemaname = 'public'`
  only, and `backup.sh` / `restore.sh` match (tested by text). Refusal reads
  the dump's table of contents: `backup.list_dump` (a monkeypatch point) and
  `restore.refuse_auth`, which rejects any non-comment line naming
  `cabinet_auth`, at inspect and again just before the database step.
  `backup.dump_settings` (also a monkeypatch point) reads `app_settings` out
  of a dump through `pg_restore --data-only` to name the secrets it carries.
- **The private staging folder** (`backup.staging_dir`, `STAGING_DIR`,
  `/data/staging`, not an operator setting) is the only place a dump is
  unpacked: 0700, files 0600 (`backup.private_file`), refused inside the
  backup, photo, or document directories, emptied (`backup.empty_staging`,
  never the folder itself: it is a mount) at the start and end of every
  inspect and run and by `recover()` on every start. `ensure_room` checks
  free space first. `restore.upload_dir` (was `staging_dir`) in
  `BACKUP_DIR/.restore-staging` holds uploads only. Inspect takes the
  restore lock (409 while a restore runs) so two can't share staging.
- **The marker.** `_write_marker` (direct ORM on `AppSetting`, key
  `restore_marker`, never through `get_setting`) is committed just before
  the journal's `database` phase, which records the same value and, via
  `restore_database(on_drop=...)`, the leftover tables before they are
  dropped. `recover()` compares the row with the journal: equal means
  nothing committed (or partial, if tables were dropped); absent or
  different means replaced (clear marker rows and unusable secrets, roll
  the swap forward, let startup migrate); unreachable, or a journal with no
  marker, means stay in maintenance with the journal kept. `recover(engine)`
  takes the engine so tests can pass theirs. Don't move the marker out of
  `public`: it works because a restore replaces that table.
- **After the database step**, `_after_database` deletes marker rows and
  runs `scheduled.clear_secrets(undecryptable=True)`, skipping both when
  the restored database has no `app_settings` (an archive from before
  `0008`); the cleared names go into the outcome's `secrets_cleared`.
- **Every archive is encrypted, and nothing plain touches `BACKUP_DIR`.**
  `backup.write_archive(out, ...)` writes the zip into a stream (unseekable:
  zipfile uses data descriptors) that `backup.encrypt_stream` pipes into
  `age`, which writes `<name>.zip.age.partial`, renamed when complete and
  removed on any failure (`_write_encrypted`). The download is the same,
  into `.download-*.zip.age`. Decrypting happens only in
  `backup.decrypt_to_staging` (a 0600 file in `/data/staging`, after a
  free-space check against the archive's size); the pre-restore archive is
  verified by decrypting it there and deleting the copy (`verify_stored`).
  A new path that reads an archive must go through `restore.open_archive`,
  which also refuses plain `.zip` (`LEGACY_REFUSED`) before decrypting.
  `encrypt_stream` and `decrypt_stream` are the monkeypatch points;
  conftest's autouse `fake_age` stands in (authenticated, bound to the
  recipient, unseekable like a pipe), with `open_archive` and `seal` helpers
  for tests that read or build archives. Real `age` is only in the image.
- **Exactly the covered members.** After the MAC, `verify_archive` requires
  the zip's names to be unique and equal to the manifest's members plus
  `manifest.json` and `SHA256SUMS`, and `SHA256SUMS` to be exactly the one
  the manifest implies. `zipfile` reads the last of two same-named entries
  and `unzip` the first, so without this a doubled or extra member could
  reach `restore.sh` unverified (found in the stage 5 review). Both small
  members are size-capped (`MAX_SMALL_MEMBER`) before the MAC, since
  anyone can encrypt to the public key.
- **The MAC is checked first.** `backup.verify_archive` reads
  `manifest.json` and `SHA256SUMS`, verifies `mac` with the one configured
  identity its `mac_recipient` names (`archive_keys.verify`,
  `hmac.compare_digest`), and only then checks the members. The canonical
  form is `json.dumps(manifest without mac, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)` in UTF-8, then `SHA256SUMS`;
  `test_mac_is_exactly_the_specified_bytes` pins it. Don't change it
  without a new `info` string, or every stored archive stops verifying.
- **Keys** (`services/archive_keys.py`): bech32 and X25519 by hand over
  `cryptography` (checked against the real `age-keygen` both ways during
  the build), so no Python dependency. **A key is generated only by
  `ensure_key`, at startup, and only by `os.link` from a synced partial**,
  which fails if the name exists, so an existing key is never overwritten,
  even when a stat of it failed (ESTALE on NFS). At runtime
  `identities()` only reads; a key that can't be read raises
  `KeyUnavailable`, which `backup.signing_key` turns into a failed backup,
  never a new key. Writes are fsynced, file and folder. Identities must
  start `AGE-SECRET-KEY-1` in capitals, as `age` requires. A bad
  `BACKUP_KEY_FILE` is a `ConfigError`. The key file is also what `age
  --identity` reads, so the secret never goes on a command line. `rotate`
  only ever rewrites a generated file. Startup also runs `backup.self_test`
  (a real age round trip in staging; failure is logged as critical) and,
  after migrations, `backup.record_key_mismatch`, which alerts when the
  newest recorded archive was made with a key no longer configured.
- **The archive record** (`backup.record_archive`, `cabinet_auth.backup_ledger`)
  is written for every archive (`scheduled`, `manual`, `download`,
  `prerestore`, and `backup.sh` through `cli write-archive`), matched by
  `archive_keys.mac_digest` (SHA-256 of the MAC), pruned on write (180
  days, never below 50). Names are to the second, so a row with the same
  name is taken over rather than duplicated. `restore.provenance` compares
  the archive's verified `created_at` with the newest recorded (naive
  datetimes from SQLite are read as UTC); older means `RESTORE OLDER`, set
  in `_pending` at inspect, rechecked from the archive in `_confirm_age` at
  the start of the run, and recomputed after a failed run
  (`_refresh_phrase`), since that run's safety backup is now the newest.
- **Key location** (`archive_keys.compare_locations`) is pure over a
  mountinfo text, so tests pass fixtures. `separate` only for two
  `LOCAL_FS` filesystems on different devices; one mount or overlapping
  folders on one device are `shared`; everything else, sibling folders on
  one device included, is `not_verified`. False reassurance is the failure
  to avoid. Mount paths are unescaped as octal only. It compares POSIX
  paths as given; `location()` resolves the real ones first.
- **Staging is apart from every other data folder in both directions**
  (backup, photo, document, state), since it is emptied on every start.
  `empty_staging()` leaves `.cli-` files (a container command in another
  process); `recover()` empties everything and also deletes staged uploads
  a restart has orphaned. An upload is refused on its first bytes unless it
  is an age file, so a plain archive never lands on the share. The
  entrypoint puts back the owner and mode of `BACKUP_KEY_FILE` and
  `SETUP_CODE_FILE` if a folder hand-over touched them.
- **The CLI** (`app/cli.py`) drops to `PUID:PGID` when started as root.
  `write-archive` stages its ciphertext in `/data/staging` (a `mkstemp`
  name with the `.cli-` prefix) to learn the size for the record, then
  streams it to stdout; `verify-archive -` spools stdin there the same way
  and deletes it.
- **The credential services live in `app/auth/`**, one module per kind
  (`passwords`, `sessions`, `tokens`, `devices`, `throttle`, `audit`,
  `notify`), put together by `accounts`, which the routes (stage 7) and the
  container commands both call. Each `accounts` function is one unit of
  work and commits itself, so a failed sign-in's audit row, device failure,
  and counters persist although the caller answers with an error. **A
  password is only ever checked through `accounts._check_password`**: the
  throttles first (skipped for a known device), then the slot (the reserved
  one for a known device), then Argon2, then on failure the counters, the
  device's failure count, the audit row, and the burst alert. A new path
  that takes a password goes through it, never `passwords.verify` directly.
- **Time comes from `common.now()` and `common.monotonic()`**, called
  through the module (never imported by name), so tests freeze it by
  patching `common`. SQLite hands times back naive: compare through
  `common.aware`, and give bulk deletes with a time condition
  `synchronize_session: "fetch"`, or SQLAlchemy's in-Python evaluation
  compares naive with aware and raises.
- **Throttles and the reserved slot are per process**, in memory, as the
  spec says. `reset-password` runs in another process, so it touches
  `throttle_reset` on the state volume and every throttle check clears the
  map when that file's time changes (the first look only notes it). The
  spec says the gate checks the flag; every throttle check reads it
  instead, which covers the same requests, since only sign-in, confirm, and
  setup consult the throttles.
- **Tokens**: a live token's name is unique (the CLI revokes by name), at
  most 50 live, `read` and `write` 1 or 7 days, `metrics` also never. The
  secret is only in the creation answer; a pytest scans every tracked file
  for the token pattern, so never commit a real one, and build test tokens
  at run time. Revoked and expired tokens are kept 30 days for the list,
  then pruned hourly (`accounts.prune`, with ended sessions, expired
  devices, and old audit rows).
- **The audit log** refuses an unknown event name and a detail key naming a
  password, secret, or code. Failed sign-ins are labelled with the account's
  name only when the typed name is the account's, otherwise `unknown`. The
  JSON lines go to logger `cabinet.audit`, which `main._configure_logging`
  now includes; a container command writes its row but prints no line (its
  stdout is the operator's terminal). `secrets_cleared` is audited as
  `system` in `scheduled.clear_secrets`.
- **The container commands** (`status`, `reset-password`,
  `sign-out-everywhere`, `revoke-tokens`, and `backup-key show|rotate`)
  refuse until the instance is claimed, and when the database can't be
  reached, since neither can then be told apart. The archive commands
  (`decrypt-archive`, `verify-archive`, `write-archive`) don't: `backup.sh`
  and `restore.sh` must work on a fresh machine before setup (spec section
  6). `reset-password` reads the password only through `getpass`, twice.
  Tests reach a command through conftest's `cli_admin` (the admin exists,
  `app.db.SessionLocal` points at the test database).
- **Tests never touch `/data`.** conftest's autouse `_private_paths` points
  every data folder at a temporary one, also for tests that start the app
  without the `client` fixture (stage 5's key generation wrote a real
  key under `C:/data/state` on the dev machine and failed on CI, where
  `/data` isn't writable). Tests that hash use a cheap `PasswordHasher`;
  `test_hashing_parameters_are_pinned` checks the real one.
- Still to come in later stages, and not in this code yet: the setup code,
  the claimed marker, and the routes (stage 7), the restore grant, the
  recent-password check on inspect, run, downloads, and deleting
  unencrypted archives, the audit rows and alerts for downloads, exports,
  restores, and deleting unencrypted archives (they need the principal),
  and the Settings UI for the key (fingerprint, the saved tick, the location
  message) and for deleting unencrypted archives (stage 9).

## Releases


Pushing a `v*` tag runs CI's `publish` job, which pushes
`ghcr.io/jsaumer/cabinet-numismatics-{backend,proxy}` (version + `latest`;
nothing before v0.10.2 is published). The live homelab instance pins those
tags, so a release reaches it only once the tag's images exist; from v0.11.1
the backend migrates on startup, so an upgrade there is just a tag bump.
