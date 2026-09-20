# API

The service is titled **Cabinet API** in the OpenAPI spec.

The backend exposes a REST API under `/api/`. This document is a
human-readable summary; the authoritative, always-current spec is the
auto-generated OpenAPI documentation served at:

- Swagger UI: `http://localhost/api/docs`
- OpenAPI JSON: `http://localhost/api/openapi.json`

All request and response bodies are JSON unless noted (photo, document, and
import uploads are multipart; exports, backups, document files, and metrics
answer files or text). The app has no login yet, so
endpoints are described without an auth layer; put an authenticating proxy
in front before exposing it beyond a trusted network. Login is planned
(roadmap Phase 7, P8), and
[security.md](security.md#planned-accounts-and-permissions) has the proposed
table of who will be able to call what.

## Items

| Method   | Path                      | Purpose                             |
|----------|---------------------------|-------------------------------------|
| `GET`    | `/api/items`              | List items (filter/paginate)        |
| `POST`   | `/api/items`              | Create an item                      |
| `POST`   | `/api/items/import`       | Import items from CSV in the export format (multipart); other formats: see Imports |
| `GET`    | `/api/items/export.csv`   | Export the collection as CSV        |
| `GET`    | `/api/items/export.xlsx`  | Export the collection as Excel      |
| `GET`    | `/api/items/{id}`         | Get one item with photos/estimates  |
| `PATCH`  | `/api/items/{id}`         | Update fields on an item            |
| `POST`   | `/api/items/{id}/clone`   | Duplicate an item (not its photos)  |
| `GET`    | `/api/items/{id}/history` | Edit history (created/updated diffs)|
| `POST`   | `/api/items/bulk`         | Bulk field updates + add/remove tags|
| `DELETE` | `/api/items/{id}`         | Move an item to the trash; `?permanent=true` (or an item already there) deletes it for good |
| `POST`   | `/api/items/{id}/restore` | Take an item out of the trash       |
| `GET`    | `/api/items/similar`      | Items that look like one being entered (see below) |
| `POST`   | `/api/items/run`          | One item per chosen issue of a Numista type (see Add a run) |

**List query parameters** (all optional): `type`, `status`, `strike`
(`business`/`proof`/`specimen`), `country`, `year`, `year_min`/`year_max`,
`tag`, `set_id`, `grade_min`/`grade_max` (grade rank 1–70),
`value_min`/`value_max` (the newest estimate, whatever the value strategy),
`q` (substring match over notes/series/variety/country/denomination/cert and
serial numbers/prefix/issuer/charter number/bank city/catalog refs/tags),
`fancy=true` (notes with any fancy-serial trait), `serial_trait` (one trait
key from `/api/reference/serial-traits`; an unknown one is 422),
`target_reached=true` (see the wish-list fields below), `limit` (default 50,
1–500), `offset`, `sort` (`created_at`, `year`, `country`, `denomination`,
`acquisition_date`, `acquisition_price`, `priority`, `target_price`, or
`grade`; `-` prefix for descending; default `-created_at`; anything else is
422; with `priority` and `target_price`, items without a value come last in
either direction). The response is
`items`, `total`, `limit`, and `offset`. Each item includes its primary
photo/thumbnail keys (`primary_photo_key`, `primary_thumb_key`) and its latest
estimated value: `latest_value` + `latest_value_currency`, plus
`latest_value_source` naming which source produced it (an adapter key, a
manual entry's own source text, or `average`). It is resolved by the app-wide
`value_strategy` setting (see Settings, below), not simply "whichever estimate
is newest." Both exports take the same filters (not `sort`, `limit`, or
`offset`) and use the same resolved value. List rows carry the same fields
as a single item, so `target_price`, `priority`, `target_gap`,
`target_reached`, and `serial_traits` are there too.

Item payloads accept `tags` (list of names, get-or-create), `catalog_refs`
(list of `{catalog, ref_code}`), `grade_id`, `set_id` (an unknown one is 422),
and `custom_fields` (up to 20 name → text pairs; names up to 50 characters,
values up to 500). CSV import consumes the export format; derived columns
are ignored, rows whose `id` already exists are skipped (so
re-importing an export never duplicates the collection), and per-row failures
are reported without aborting the rest; it answers `created`, `skipped`, and
`errors` (`row`, `error`). `POST /api/items/bulk` takes `ids` (1–500), `set`
(item fields applied to every item; tags and catalog refs inside it are
ignored), `add_tags`, and `remove_tags`, and answers `updated`; 404 when any
id is missing or in the trash. `set` validates like an update, so `priority`
(1–3, or `null` to clear) can be set in bulk, and a bulk change to
`replacement_note` or `serial_number` recomputes `serial_traits`.

Grading fields: `strike` (`business` default, `proof`, `specimen`),
`grade_plus`, `grade_star`, `designations` (list; `PL`, `DMPL`, `CAM`, `DCAM`,
`UCAM`, `RD`, `RB`, `BN`, `FB`, `FBL`, `FH`, `FS`, `FT`, `EPQ`;
case-insensitive, deduplicated), `grade_details` (the problem on a details
grade), and `cac_sticker` (`green`/`gold`). Physical: `diameter_mm`,
`thickness_mm`, `edge`, `shape`, `mintage`. Banknotes: `serial_number`,
`prefix_block`, `signatures`, `issuer`, `replacement_note`. Costs:
`acquisition_fees` and, on sale, `sold_fees` and `sold_to`. Responses add
three derived fields: `grade_label` (the grade as a holder reads, e.g. `PR-69
DCAM ★`), `cost_basis` (price plus fees), and `sale_proceeds` (sold price less
fees); these are the figures every gain calculation uses. CSV import also
reads label-style grades: `PR-65`, `PF-65`, or `SP-65` on the Sheldon scale
set the strike, and a trailing `+` sets `grade_plus`.

Added in v0.25.0, all optional and accepted on create, update, and bulk
`set`:

- **Population**: `pcgs_population` and `pcgs_pop_higher` (whole numbers, 0
  or more). The response adds `population_as_of`, set by the server and never
  accepted from a client: now when either figure changes through create,
  update, or clone (cleared when both are), and the time the PCGS response
  was fetched when a PCGS estimate updates them.
- **Wish list**: `target_price` (above 0, in the item's `currency`) and
  `priority` (`1` high, `2` medium, `3` low). They are accepted on any
  status and are kept when a wishlist item becomes owned. The response adds
  `target_gap`, the item's **newest** estimate less the target (not the
  `value_strategy` value), and `target_reached` (the gap is zero or less).
  Nothing is converted: the gap is `null`, and `target_reached` false, unless
  that estimate's currency equals the item's. `target_reached=true` on the
  list applies the same rule.
- **National Bank Notes**: `charter_number` (up to 10 characters),
  `bank_city` (100), `bank_state` (50), `plate_position` (20); trimmed, and
  blank becomes `null`.
- **Fancy serials**: the response's `serial_traits` is a list of trait keys
  (empty when none), worked out by the server from `serial_number` and
  `replacement_note` on every path that changes either; it is never accepted
  from a client. Only the digits are read (leading zeros kept), and digit
  patterns need at least four. Keys, in the order they are listed: `solid`,
  `ladder`, `radar`, `super_radar`, `repeater`, `super_repeater`, `binary`,
  `trinary`, `low`, `high`, `double_quad`, `date`, `star`. A solid is only
  `solid`; `super_radar` and `super_repeater` replace `radar` and
  `repeater`; `star` is a `*` or `★` in the serial, or `replacement_note`.
- **Die axis**: `die_axis`, 0–359 degrees (`0` medal alignment, `180` coin
  alignment).
- **Date as struck**: `struck_calendar` (a key from
  `/api/reference/calendars`), `struck_year` (1–9999), and `struck_era`
  (`meiji`, `taisho`, `showa`, `heisei`, `reiwa`); calendar and era are
  lowercased. The Japanese calendar requires an era, and an era with any
  other calendar, or none, is 422. On create, a missing or `null` `year` is
  filled from the conversion, and a `year` that is given stands. On update, a
  `PATCH` without `year` leaves it alone; only an explicit `"year": null`
  beside a struck calendar and year (in the request or already on the item)
  is answered with the converted year, and `"year": null` without them is
  422.

The CSV and Excel exports, and both ways of importing them back, carry
`die_axis`, `struck_calendar`, `struck_year`, `struck_era`,
`pcgs_population`, `pcgs_pop_higher`, `charter_number`, `bank_city`,
`bank_state`, `plate_position`, `target_price`, and `priority`. An export
from an older version imports as before. `serial_traits` and
`population_as_of` are not exported: the import recomputes them.

## Photos

| Method   | Path                              | Purpose                        |
|----------|-----------------------------------|--------------------------------|
| `GET`    | `/api/items/{id}/photos`          | List an item's photos          |
| `POST`   | `/api/items/{id}/photos`          | Upload a photo (multipart)     |
| `POST`   | `/api/items/{id}/photos/order`    | Reorder photos (full id list)  |
| `PATCH`  | `/api/photos/{photo_id}`          | Set angle / mark primary       |
| `DELETE` | `/api/photos/{photo_id}`          | Delete a photo                 |
| `POST`   | `/api/items/{id}/photos/url`      | Import a photo from a URL (JSON `url`, optional `angle`) |
| `PUT`    | `/api/photos/{photo_id}/image`    | Replace a photo's image (multipart), keeping its angle, primary flag, and position |

Upload accepts a single image file plus optional `angle`. Files are validated
as real JPEG/PNG/WebP images (the declared content-type is not trusted), EXIF
orientation is corrected, and a JPEG thumbnail is generated alongside the
original. The first photo uploaded becomes the primary image. Responses
include the file keys; the files themselves are served by nginx at
`/photos/{file_key}` and `/photos/{thumb_key}`.

URL import fetches the image on the server: http(s) only, public addresses
only (a host resolving to a private, loopback, or link-local address is
refused, and so is a redirect to one), up to three redirects, 25 MB at most. It
then validates and stores it exactly like an upload: 422 for a URL that isn't
allowed or doesn't return a file, 502 when it can't be reached, 415 when the
file isn't a supported image. Replacing an image (what the in-browser editor
saves) writes it under a new file name, so cached copies of the old image
aren't shown, and deletes the old files.

## Price estimates

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|------------------------------------------|
| `POST` | `/api/items/{id}/estimates`   | Record a manually researched value       |
| `GET`  | `/api/items/{id}/estimates`   | List estimate history for an item        |
| `POST` | `/api/items/{id}/estimate`    | Produce an automatic estimate            |
| `POST` | `/api/estimates/refresh-melt` | Re-run stale melt estimates now          |

Estimates are append-only: each `POST .../estimates` adds a timestamped record
(`estimated_value`, `currency`, `source`, optional `confidence` 0–1, optional
`note` up to 500 characters), never overwriting history. Every estimate in a
response carries `id`, `item_id`, `source`, `estimated_value`, `currency`,
`confidence`, `sample_size`, `fetched_at`, and `details`: the provenance an
automatic source recorded (see [price-sources.md](price-sources.md)),
`{"note": …}` for a manual entry given a note, or `null`. `POST .../estimate`
runs one automatic adapter, chosen with `?source=`: `melt` (the default: spot
× weight × fineness × quantity, metal detected from `composition`), `numista`
(by the item's `numista` catalog ref and grade), `pcgs` (US coins by PCGS cert
number, or `pcgs` catalog ref + grade; see below), or `comps` (the median of
the item's logged sales; see Sales log below). The two external sources need a
credential in Settings. Any of them answers 201 with the new estimate, 422
with the missing prerequisite when the item can't be priced by that source,
the source is switched off, or the source name is unknown, and 502 when the
upstream is unreachable. See [price-sources.md](price-sources.md).

A PCGS estimate's `details` say what it stands on. `basis` is `apr` (the
median of auction lots from the last five years; confidence 0.85 with five
or more, 0.75 with three or four, 0.65 with one or two), `guide` (the price
guide, 0.60, when no lot is that recent), or `apr_old` (the median of older
lots, 0.35, when there is no guide value either). `lots` are the sales
counted and `older_lots` the ones kept but not counted (each `date`, `price`,
`auctioneer`, `sale`, `url`; ten at most between them), alongside `median`,
`price_guide_value`, `coinfacts_url`, `population`, `pop_higher`, `quantity`,
the lookup (`cert`, or `pcgs_number` + `grade`), and `data_as_of`/`stale`.
`sample_size` is the number of lots counted, `null` on `guide`. When the
response reports a population, the estimate also writes it to the item
(`pcgs_population`, `pcgs_pop_higher`, and `population_as_of`, the time the
PCGS response was fetched), at no extra request; without one the item is
left alone.

Every new estimate, manual or automatic, scheduled refreshes included, is
checked against a wish-list target: for an item with status `wishlist` and a
`target_price`, an estimate in the item's own currency at or under the
target sends one event through the alert webhook, unless the estimate before
it was already there. See [monitoring.md](monitoring.md).

`POST /api/estimates/refresh-melt` answers `updated`, `skipped`, and `failed`,
or 422 when melt is switched off. An in-process scheduler re-runs stale melt
estimates every 12h (estimates older than `REESTIMATE_DAYS`, default 7; `0`
disables); a melt refresh never supersedes an item whose latest estimate is
manual. The same 12h loop also refreshes Numista and/or PCGS when their own
cadence is switched on in Settings (each off by default), independently of
melt and of whichever source currently wins an item's overall-latest estimate,
since `value_strategy` may prefer or average a source that isn't "latest"
right now.

## Stats

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| `GET`  | `/api/stats/collection`  | Totals in a display currency (`?currency=`)    |
| `GET`  | `/api/stats/breakdowns`  | Owned items grouped by country/type/decade/grade/tag + acquisitions by year |
| `GET`  | `/api/stats/gains`       | Per-item unrealized (owned) and realized (sold) gain/loss |
| `GET`  | `/api/stats/value-history` | Month-end collection value over time (`?months=`, default 24, 1–120) |
| `GET`  | `/api/stats/notes-by-signature` | Owned notes grouped by series and signature pair |

`/collection` answers `currency`, `counts` (`total`, `owned`, `sold`,
`wishlist`, and `coins` / `notes`, which count owned items only),
`cost_basis` (owned items, fees included), `estimated_value` (each owned
item's shown value under `value_strategy`) with `estimated_items` (how many
contribute), `unrealized_gain` (owned items with both a cost and a value),
and `realized_gain` (sold items, net of fees). A count is a row, not its
`quantity`. [monitoring.md](monitoring.md) builds a Homepage tile from this
endpoint. `/breakdowns` answers `by_country`, `by_type`, `by_decade`,
`by_grade`, `by_tag`, and `acquisitions_by_year`, each a list of `key`,
`count`, `cost_basis`, and `estimated_value`; `/gains` answers `unrealized`
and `realized` lists of `item_id`, `label`, `cost_basis`, `value`, and
`gain`; `/value-history` answers `points` of `date`, `value`, and
`estimated_items`, starting at the first month with an estimate. All take
`?currency=` and share one currency rule: amounts in
other currencies are **converted** into the display currency at cached daily
ECB rates (frankfurter.dev, 24h cache, stale fallback); amounts with no
obtainable rate are **excluded** and counted, never guessed
(`converted_other_currency` / `excluded_other_currency` on `/collection`).

`/notes-by-signature` takes no parameters and answers `total` (owned notes)
and `groups`, one per (`series`, `signatures`) pair, either of which may be
`null`: `count` (items), `quantity` (pieces), and `items` (`id`, `label`,
`serial_number`, `grade_label`) ordered by serial number. Groups are ordered
by series, then signatures, ignoring case, with `null` last.

The dashboard and the printable insurance report (`/report` in the UI;
export to PDF via the browser's print dialog) are built on these endpoints.

## Reference data

| Method   | Path                | Purpose                                        |
|----------|---------------------|------------------------------------------------|
| `GET`    | `/api/grades`       | List grade scales and codes (`?scale=` filter) |
| `GET`    | `/api/tags`         | List tags with usage counts                    |
| `GET`    | `/api/sets`         | List sets/lots with item counts                |
| `POST`   | `/api/sets`         | Create a set (409 on duplicate name)           |
| `PATCH`  | `/api/sets/{id}`    | Rename / edit a set                            |
| `DELETE` | `/api/sets/{id}`    | Delete a set (items are detached, not deleted) |
| `GET`    | `/api/reference/serial-traits` | The fancy-serial traits, in order   |
| `GET`    | `/api/reference/calendars`     | Calendars for a date as struck, and the Japanese eras |
| `GET`    | `/api/reference/convert-date`  | A struck year as a Gregorian year   |

Grades are seeded by migration: `sheldon` for coins, `pmg` for notes. Catalog
references are managed inline on items rather than via a standalone endpoint;
the catalogue name is free text (the form suggests `krause`, `numista`, and
`pcgs`, and for notes `pick` and `friedberg`).

`/reference/serial-traits` answers a list of `key`, `label`, and
`description`. `/reference/calendars` answers `calendars` (`key`, `label`:
`hijri`, `solar_hijri`, `thai_buddhist`, `hebrew`, `japanese`,
`vikram_samvat`, `saka`, `minguo`, `chula_sakarat`, `rattanakosin`,
`ethiopian`) and `eras` (`key`, `label`, `offset`; year 1 of an era is
`offset` + 1). `/reference/convert-date` takes `calendar`, `year` (1–9999),
and `era` (required for `japanese`, refused otherwise) and answers
`calendar`, `year`, `era`, and `gregorian_year`: the Gregorian year the
struck year mostly falls in (a fixed offset per calendar; the lunar Hijri
year uses `floor(year × 0.970224 + 621.5774)`). Bad input is 422.

## Duplicate check

`GET /api/items/similar` takes any of `country` + `denomination` + `year`
(+ `mint_mark`, blank meaning none), `cert_number`, and `ref` (repeatable,
`catalog:code`), plus `exclude` (the item being edited), and answers up to
ten items that match on any of them, each with `id`, `label`, `grade_label`,
`status`, `in_trash`, and the `reason` (`same cert number`, `same pcgs
reference`, `same country, denomination, year, and mint mark`). Matching
ignores case and spacing; trashed items are included and listed last. With
nothing to go on it answers `[]`. The import preview runs the same check
and notes lookalikes in a row's `messages`.

## Add a run

`POST /api/items/run` takes `type_id` (a Numista type), `issues` (1–200 of
`{year, mint_mark, mintage}`), `shared` (`status`, `grade_id`, `quantity`,
`acquisition_date`, `acquisition_price` and `acquisition_fees` per item,
`currency`, `acquired_from`, `storage_location`, `set_id`, `tags`, `notes`),
and `skip_owned` (default `true`). Each item gets the type's fields and
catalogue references as "Fill from Numista" would, plus the issue's year,
mint mark, and mintage. Issues already owned (same Numista number, year, and
mint mark) and repeats within the request are skipped. Answers `201` with
`created`, `skipped`, and `item_ids`; everything is one transaction. Needs a
Numista API key (`422`); an unknown type is `404`, an unreachable Numista
`502`, and an issue that doesn't validate `422`, naming the year and field.

## Numista catalogue lookup

| Method | Path                         | Purpose                                          |
|--------|------------------------------|--------------------------------------------------|
| `GET`  | `/api/numista/search`        | Search the catalogue: `q` (2–100 chars), optional `category` (`coin`/`banknote`) |
| `GET`  | `/api/numista/types/{id}`    | A type as fillable item fields, catalogue refs, and issues |

Both need a Numista API key in Settings (422 without one) and answer 502 when
Numista is unreachable or the quota is exhausted; an unknown type is 404.
Search returns `count` and up to 20 `results` (`type_id`, `title`, `category`,
`issuer`, `min_year`, `max_year`, `thumbnail`). A type returns `type_id`,
`title`, `url`, `category`, and `fields` keyed like the item payload: `type`,
`country`, `denomination`, `series`, `composition`, `fineness`, and `year`
when the type has a single year; coins add `weight_g`, `diameter_mm`,
`thickness_mm`, `shape`, and `edge`; notes add `issuer` (the issuing bank).
Only values Numista has are present, trimmed to the item schema's limits.
`catalog_refs` holds `numista:N#<id>` and the type's other references
(`km:KM#273`, `pick:Pick#79a`…); `issues` lists `year`, `mint_letter`,
`mintage`, `comment`, and `owned` (an owned item already carries this type,
year, and mint mark). Responses are cached for 7 days in `source_cache` (the
longest Numista's API licence allows), issues shared with Numista pricing.

## PCGS cert lookup

| Method | Path                     | Purpose                                              |
|--------|--------------------------|------------------------------------------------------|
| `GET`  | `/api/pcgs/cert/{cert}`  | A PCGS-graded coin as item fields ready to fill in   |

Needs a PCGS API token, whether or not the PCGS price source is on (`422`
without one, or when PCGS has no such cert; `502` when PCGS can't be
reached). `cert` is up to 20 characters, and anything but its digits is
dropped. Answers `cert`, `pcgs_number`, `name`,
`fields` (keyed like the item payload: `type`, `country`, `denomination`,
`year`, `mint_mark`, `series`, `variety`, `composition`, `weight_g`,
`diameter_mm`, `edge`, `mintage`, `cert_service`, `cert_number`,
`pcgs_population`, `pcgs_pop_higher`; only what PCGS has, and a population of
zero counts), `grade` (`rank`, `strike`, `plus`, `designations`, or `null`
for a Genuine/details holder), `catalog_refs` (the PCGS number),
`population`, `pop_higher`, `price_guide_value`, and `coinfacts_url` (the
two population figures are inside `fields` so the form's fill carries them,
and at the top level as before). Fields are made to
match hand-entered ones: `country` is `United States` however PCGS spells it
(and when it gives none), `denomination` is spelled out (`25C` becomes
`25 cents`), and a `P` mint mark is kept only where the coin carries the
letter (1942–1945 nickels, the 1979 dollar, everything but the cent from
1980, and the 2017 cent), since checklists match mint marks as written.
Cached for 7 days with the pricing lookup for the same cert, so an estimate
afterwards is free.

## Pricing reports

| Method | Path                          | Purpose                                            |
|--------|-------------------------------|----------------------------------------------------|
| `GET`  | `/api/pricing/coverage`       | Owned items lacking estimates, and per source why  |
| `GET`  | `/api/pricing/stale`          | Latest estimates `?days=` old (default 30, 1–3650) or built from expired source data |
| `GET`  | `/api/pricing/sources`        | Per-source breakdown and biggest disagreements (`?currency=`) |
| `GET`  | `/api/pricing/accuracy`       | Estimates standing on the sale date vs realized prices (`?currency=`) |

All four read existing data and call no upstream source. Estimates are
grouped by source key: `melt`, `numista`, `pcgs`, `comps`, and `manual` for
any hand-entered source text.

- **coverage**: `owned_items`, `estimated_items`, `manual_only_items`; per
  source a summary (`enabled`, `priced`, `not_applicable`, `failed`,
  `not_tried`); and `items` needing attention, each with a status per source
  (`priced`, `not_applicable`, `failed`, `not_tried`, `disabled`), a
  `reason`, and the latest `estimated_at` / `attempted_at`. An item is listed
  when it has no estimate, a source failed or was never tried, or a source's
  last attempt came after its last estimate and didn't succeed. Reasons come
  from each adapter's local prerequisites, or from the latest recorded
  attempt; every `POST /api/items/{id}/estimate` and scheduled refresh
  records one per item and source.
- **stale**: `days`, `checked` (latest estimates examined, one per item and
  source), and `stale` entries oldest first: value, `age_days`,
  `upstream_stale` (built from source data past its cache window), and
  `in_totals` (it feeds the item's shown value under `value_strategy`).
- **sources**: the `strategy` and `preferred_source` in force; per source:
  `items`, `total_value`, `avg_confidence`,
  `median_age_days`, `in_totals` (items whose shown value it supplies);
  `averaged_items` when the strategy is `average`; and up to ten
  `disagreements` (items with two or more sources, with each value and the
  `spread_pct` between highest and lowest).
- **accuracy**: sold items with a sold price (`sold_items`; `compared_items`
  of them had an estimate to compare). For each, the latest estimate
  per source recorded on or before `sold_date` (all estimates when there is
  no date) as `by_source`, and the shown value as of then as `blended`, each
  with `error_pct` =
  (estimate − sold) / sold. `summary` rows (`blended` plus each source) give
  `sales`, `median_abs_error_pct`, `mean_error_pct` (bias; positive means
  estimates ran high), and `within_20_pct`. Money follows the stats currency
  rule; unconvertible amounts are skipped and counted.

## Trash

| Method   | Path                  | Purpose                                              |
|----------|-----------------------|------------------------------------------------------|
| `GET`    | `/api/trash`          | Items in the trash, most recently deleted first      |
| `POST`   | `/api/trash/items`    | Move several items to the trash (`{"ids": [...]}`)   |
| `POST`   | `/api/trash/restore`  | Restore several items                                |
| `POST`   | `/api/trash/purge`    | Delete several trashed items for good                |
| `DELETE` | `/api/trash`          | Empty the trash                                      |

A trashed item keeps everything (photos, documents, values, sales, history)
and is hidden from every other endpoint: lists, stats, reports, exports,
set and tag counts, refreshes. `GET /api/items/{id}` still returns it, with
`deleted_at` set; every other item endpoint answers 404 until it's restored.
`GET /api/trash` answers `retention_days` (0 = never emptied automatically)
and `items` (`id`, `label`, `type`, `status`, `grade_label`, `series`,
`thumb_key`, `deleted_at`, and `purge_at`, when it will be deleted for good).
The bulk endpoints take 1–5000 `ids` and answer `{"count": n}`, counting
only items that changed; emptying answers the same.
Deleting for good removes the item's photos, values, history, sales, and any
document no other item, trashed or not, holds. Items older than
`trash_retention_days` are deleted for good by the hourly background task.

## Documents

| Method   | Path                                     | Purpose                                  |
|----------|------------------------------------------|------------------------------------------|
| `GET`    | `/api/items/{id}/documents`              | The item's documents, newest first       |
| `POST`   | `/api/items/{id}/documents`              | Attach a file (multipart: `file`, optional `kind`, `title`, `doc_date`, `note`) |
| `PATCH`  | `/api/documents/{doc_id}`                | Change `kind`, `title`, `doc_date`, `note` |
| `POST`   | `/api/documents/{doc_id}/items`          | Attach it to more items (`{"item_ids": [...]}`) |
| `DELETE` | `/api/items/{id}/documents/{doc_id}`     | Remove it from one item; the file goes with its last item |
| `DELETE` | `/api/documents/{doc_id}`                | Delete it from every item                |
| `GET`    | `/api/documents/{doc_id}/file`           | The file, inline; `?download=true` to save it |
| `GET`    | `/api/documents/{doc_id}/thumb`          | A JPEG thumbnail (404 when there's none) |

`kind` is one of `receipt`, `invoice`, `certificate`, `grading_label`,
`appraisal`, `correspondence`, `other` (the default); `title` (up to 200
characters) defaults to the file's name, `doc_date` is `YYYY-MM-DD`, and
`note` runs to 2000. Linking takes 1–200 `item_ids` and is 404 when one
doesn't exist. Files may be PDF, JPEG, PNG, or WebP,
25 MB at most (413 above that), detected from their bytes; anything else is
415, with the reason. A PDF must open in PDFium; one that needs a password is
kept without a thumbnail or page count. Responses carry `id`, the fields above,
`filename` (the uploaded name with the detected extension), `content_type`,
`size`, `pages`, `has_thumb`, `items` (`id`, `label` of every item it's
attached to), and `created_at`; `GET /api/items/{id}` includes them as
`documents`. Uploads answer 503 when document storage isn't usable; see
`documents` in Health.

Files are served with `X-Content-Type-Options: nosniff`, `Cache-Control:
private, max-age=3600`, a `Content-Disposition` carrying the filename (RFC
5987 for non-ASCII names), and a content security policy: `default-src 'none';
sandbox` for images, `default-src 'none'; frame-ancestors 'self'` for PDFs,
because `sandbox` stops Chrome's built-in PDF viewer rendering at all.

## Sales log (comparables)

| Method   | Path                                   | Purpose                                   |
|----------|----------------------------------------|-------------------------------------------|
| `GET`    | `/api/items/{id}/comparables`          | The item's logged sales, newest first     |
| `POST`   | `/api/items/{id}/comparables`          | Log a sale                                |
| `PATCH`  | `/api/comparables/{sale_id}`           | Change a sale, or leave it out (`included`) |
| `DELETE` | `/api/comparables/{sale_id}`           | Remove a sale                             |
| `POST`   | `/api/items/{id}/comparables/numista`  | Add Numista's recorded auction sales (paid Numista API plan) |

A sale has `sold_on`, `venue`, and a per-piece `price` with its `currency`
(required), plus optional `title`, `lot`, `url`, `grade` (as the lot
described it), `premium_included` (true / false / null for unknown), `fees`
(premium or shipping on top of the price, added to it), `note`, and
`included` (default true). Responses add `id`, `item_id`, `source`
(`manual` or `numista`), `grade_bucket` (Numista's g…unc, on fetched sales),
and `created_at`; `GET /api/items/{id}` includes them as `comparables`.

`POST /api/items/{id}/estimate?source=comps` takes the median of the included
sales that match (a sale with a `grade_bucket` counts only when it matches
the item's grade) from the last three years, or all of them when fewer than
three are that recent, at most twenty, converted into the display currency.
Confidence starts at 0.30 for one sale and rises to 0.70 at ten, less 0.08 or
0.15 when the prices spread more than 25% or 50% from the median, 0.05 with
no item grade, and 0.10 when older sales were needed. Its `details` list the
sales used. 422 when no sale counts or none converts.

The Numista fetch needs `numista_sales_enabled`, an API key, and a `numista`
catalog ref; it answers `found`, `added`, `already_logged` (matched by lot
URL, or by auction house, date, and lot number when there is none), and
`issue_id`. A key without Numista's paid plan gets 422 with that
explanation; an unreachable Numista is 502. One request, cached for a day.

## Imports

| Method   | Path                              | Purpose                                          |
|----------|-----------------------------------|--------------------------------------------------|
| `POST`   | `/api/imports`                    | Stage a file (multipart, up to 1 GB, 413 above); returns `upload_id`, `filename`, `size`, and the detected `format` |
| `POST`   | `/api/imports/{upload_id}/preview`| What importing it would do; nothing is written   |
| `POST`   | `/api/imports/{upload_id}/run`    | Import its new items                             |
| `DELETE` | `/api/imports/{upload_id}`        | Discard a staged file (they expire after a day anyway) |
| `POST`   | `/api/imports/numista/preview`    | Preview importing your Numista collection        |
| `POST`   | `/api/imports/numista/run`        | Import it                                        |

File formats: `cabinet` (Cabinet's own export, CSV or XLSX, every field,
read by the same row reader as `POST /api/items/import`, keyed by the
exported `id`, and a duplicate when that id is still here), `spreadsheet` (any
CSV/XLSX, read through a field → column `mapping`), `numista_file`
(numista.com's collection export, by column name), and `opennumismat` (an
OpenNumismat `.db`). Preview and run take the same JSON
options: `format` (default: as detected), `mapping` (spreadsheet; default:
suggested from the header names), `skip_rows` (lines above the header;
default: found automatically), and `defaults`: `type`, `status`,
`currency`, `country` for rows that don't say. A spreadsheet preview also
returns `headers`, `header_row`, the `mapping` used, and the mappable
`fields`.

A preview answers `format`, `filename`, `total`, `new`, `duplicates` (already
imported), `errors`, `warnings`, `photos`, and up to 200 `rows` (`row`,
`status` new / duplicate / error, `label`, the resolved `grade`, `type`,
`status_value` (the item's status), `quantity`, `price`, `currency`, `photos`,
`messages`, `error`). An unknown or expired `upload_id` is 404; a file that
can't be read as the chosen format, or a `mapping` naming a field or column
that isn't there, is 422. A run answers `created`, `skipped`, `errors` (`row`,
`error`), `photos_added`, and `photos_failed`; each item commits on its own,
so a bad row never undoes others. Imported items record `import_source` +
`import_key` (a Numista collected-item id, an OpenNumismat record, a Cabinet
export's id, or a row fingerprint), which is how a second import of the same
source skips them; their edit history notes the import.

The Numista endpoints take `catalogue_details` (default true: one request per
type not cached in the last week, on run only) and `fetch_photos` (default
false; pictures go through the same guarded fetch as photo URL import). They
authenticate as the API key's owner (OAuth client credentials, scope
`view_collection`); the collection is cached for an hour, so a preview and the
run that follows cost one fetch. Their preview's `format` is
`numista_account`, and it adds `types`, `types_to_fetch` (requests a run would
spend on catalogue details), and `fetched_at`. 422 without a key or when the
key has no user; 502 when Numista is unreachable or refuses.

## Settings

| Method | Path             | Purpose                                          |
|--------|------------------|--------------------------------------------------|
| `GET`  | `/api/settings`  | App settings + source status + cached market data|
| `PUT`  | `/api/settings`  | Partial update                                   |

Settings cover the app-wide `display_currency` (used by all stats endpoints
unless `?currency=` overrides), the melt refresh cadence `reestimate_days`
(0–365, `0` for off; a DB override of the `REESTIMATE_DAYS` env var that takes
effect without restart, with `reestimate_days_overridden` saying whether one
is set), source toggles (`melt_enabled`, `numista_enabled`, `pcgs_enabled`),
and source credentials (`numista_api_key`, `pcgs_api_token`; `""` clears). A
`PUT` changes only the fields it names and answers the same body as `GET`. The
toggles and credentials are read back through `sources`: per source `key`,
`name`, `enabled`, `configured`, `available`, `secret_hint`, and `note`.
`cached` lists the stored spot prices and exchange rates (`label`, `value`,
`source`, `fetched_at`). **Secrets are write-only and encrypted at rest**:
reads return only a configured flag and a last-4 hint, never the value, and
stored credentials are Fernet-encrypted before they reach the database. See
[security.md](security.md).

Also covered: `value_strategy` (`latest` / `preferred_source` / `average`) and
`preferred_source`, which together control the single blended value used by
the items list, CSV/XLSX export, and dashboard totals (the item page itself
always shows every source's own latest value, unaffected by this setting); and
each source's scheduled-refresh cadence, `numista_refresh_days` (`null` for
off, else `7`/`14`/`30`) and `pcgs_auto_refresh` (bool, fixed weekly when on).
The response also reports `numista_priceable_items`/`pcgs_priceable_items`
(owned items eligible for each source) so the UI can show the real projected
monthly call count before you turn Numista's cadence on. `backup_schedule`
(`null` / `daily` / `weekly`), `backup_keep` (1–365, default 7), and
`backup_include_photos` configure scheduled backups (see Backups below).
`comps_enabled` switches the comps source (on by default), and
`numista_sales_enabled` (off by default) allows fetching Numista's auction
sales, which needs Numista's paid API plan. `preferred_source` accepts
`comps`. `trash_retention_days` (`0` = never, `7`, `30`, `90`, or `365`; the
default is `30`) is how long an item stays in the trash.

Alerts and metrics: `alert_webhook_url` and `heartbeat_url` are secrets like
the API keys (`""` clears; reads return only `alert_webhook_hint` /
`heartbeat_hint`, the URL's `scheme://host/…`), `alert_webhook_format` is
`generic`, `ntfy`, `discord`, `slack`, or `gotify`, and `metrics_enabled`
serves `/api/metrics`. Read-only: `alerts` (each check that has ever failed:
`key`, `label`, `failing`, `since`, `message`), `alert_delivery` and
`heartbeat` (the last attempt since the backend started: `at`, `ok`,
`detail`), and `refresh_last_run` (per source: `at`, `updated`, `skipped`,
`failed`, and `error` or `stopped` when set).

## Backups

| Method | Path                    | Purpose                                              |
|--------|-------------------------|------------------------------------------------------|
| `GET`  | `/api/backup.zip`       | Build and download a fresh archive; `?photos=false` for data only |
| `GET`  | `/api/backups`          | Backup directory, free space, last run, stored archives (newest first) |
| `POST` | `/api/backups`          | Write an archive into the backup directory now, then apply retention; `?photos=` overrides the setting |
| `GET`  | `/api/backups/{name}`   | Download a stored archive                            |

An archive is a zip of `db.dump` (pg_dump custom format), `photos.tar.gz` and
`documents.tar.gz` (unless data-only), `manifest.json`, and `SHA256SUMS`; see
[backup-restore.md](backup-restore.md). A failed backup returns `500` with the
reason (for example, `pg_dump failed: …`) and is recorded as the last run
(`at`, `ok: false`, `error`); a successful `POST` answers, and records, `at`,
`ok`, `file`, `size`, `includes_photos`, and `pruned`. `GET /api/backups`
answers `directory`, `free_bytes`, `last_run`, and `backups` (`name`, `size`,
`created_at`); a second `POST` while one is running returns `409`. Stored
archive names must match `cabinet-backup-YYYYMMDD-HHMMSS[-data].zip`; anything
else is `404`. **These endpoints hand over the whole collection and are
unauthenticated**; see [security.md](security.md).

## Alerts & metrics

| Method | Path               | Purpose                                                    |
|--------|--------------------|------------------------------------------------------------|
| `POST` | `/api/alerts/test` | Send a test alert through the saved webhook; `?target=heartbeat` pushes the heartbeat now |
| `GET`  | `/api/metrics`     | Prometheus metrics; `404` until `metrics_enabled`          |

The test answers `200` either way, with `at`, `ok`, and `detail`: `HTTP 404`,
a connection error, or `No webhook URL is saved` (`No heartbeat URL is saved`
for the heartbeat); a detail never repeats the URL. Metrics are cached for a
minute. What alerts fire, the payload of each format, and every metric are in
[monitoring.md](monitoring.md). Besides the failing/recovered checks there is
one event, sent once and never listed under `alerts`: a wish-list target
reached (generic JSON `alert` `wishlist_target`, `status` `event`).

## Checklists (completeness tracking)

| Method   | Path                                    | Purpose                     |
|----------|-----------------------------------------|-----------------------------|
| `GET`    | `/api/checklists`                       | List with filled/total      |
| `POST`   | `/api/checklists`                       | Create with a slot list     |
| `POST`   | `/api/checklists/generate`              | Generate slots that fill themselves |
| `GET`    | `/api/checklists/{id}`                  | Detail with slots           |
| `PATCH`  | `/api/checklists/{id}/slots/{slot_id}`  | Check/uncheck or link item  |
| `DELETE` | `/api/checklists/{id}`                  | Delete a checklist          |

`POST /api/checklists` takes `name` (up to 100 characters) and `slots` (1–500
labels; blank ones are dropped). Patching a slot takes `filled` and/or
`item_id`: linking an item ticks the slot, and unticking it clears the link.
Both creating endpoints answer 201 with the detail.

`POST /api/checklists/generate` takes `source: "numista"` with a `type_id`
(one slot per dated issue, matched by the type's Numista number) or
`source: "range"` with `country`, `denomination`, `year_from`, `year_to`,
`mint_marks` (up to 20; `""` is the no-mint-mark slot, and the default) and
`skip` (labels such as `1933` or `1934-S`), matched by country and
denomination; `name` is optional, and 500 slots is the limit. It answers 422
when a required field is missing, the range is backwards or leaves no slots,
the type has no dated issues, or there is no Numista API key; an unknown
type is 404 and an unreachable Numista 502. A generated slot carries `year` and
`mint_mark`; when the checklist is read, a slot is `filled` if it was ticked
by hand **or** an owned, untrashed item matches it, in which case
`matched_item_id` and `matched_label` name that item. Matching is never
stored, so selling or trashing the item reopens the slot. Mint marks match
as written: an item marked `P` doesn't fill a no-mint-mark slot. Details
also carry `match_catalog`/`match_ref` or `match_country`/
`match_denomination`, `total`, and `filled`; summaries carry `generated`.

## Health

| Method | Path           | Purpose                             |
|--------|----------------|-------------------------------------|
| `GET`  | `/api/health`  | Liveness/readiness probe            |

Returns `status`, `db` (`ok` / `unreachable`), the app `version`, and
`schema`: the database's `current` Alembic revision, the `expected` one this
build ships, and a `status`, one of `ok`, `pending` (migrations not yet
applied), `ahead` (the database was migrated by a newer build), or `unknown`
(database unreachable). `documents` says whether attached documents can be
stored: `ok`, `not_mounted` (`DOCUMENT_DIR` isn't a mounted volume, so
uploads are refused), `unwritable`, or `inside_photos`. Settings → About
displays both.

## Conventions

- **Timestamps** are ISO 8601 UTC (`timestamptz`).
- **Money** fields carry an explicit ISO 4217 `currency` alongside the amount.
- **IDs** are UUIDs for items/photos/estimates/documents; sales, checklists,
  edit-history events, and reference tables use integers.
- **Errors** follow a consistent JSON shape: `{ "detail": "..." }`, matching
  FastAPI defaults, with appropriate HTTP status codes.
