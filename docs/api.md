# API

The service is titled **Cabinet API** in the OpenAPI spec.

The backend exposes a REST API under `/api/`. This document is a
human-readable summary; the authoritative, always-current spec is the
auto-generated OpenAPI documentation served at:

- Swagger UI: `http://localhost/api/docs`
- OpenAPI JSON: `http://localhost/api/openapi.json`

All request and response bodies are JSON unless noted (photo upload is
multipart). Since the app is single-user and self-hosted, endpoints are
described without an auth layer; add one before exposing the app publicly.

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
(`business`/`proof`/`specimen`), `country`, `year`,
`year_min`/`year_max`, `tag`, `set_id`, `grade_min`/`grade_max` (grade rank 1–70),
`value_min`/`value_max` (latest estimate), `q` (substring match over
notes/series/country/denomination/cert and serial numbers/prefix/issuer/catalog
refs/tags), `limit`,
`offset`, `sort` (field name or `grade`, `-` prefix for descending). The list
response includes each item's primary photo/thumbnail keys and its latest
estimated value: `latest_value` + `latest_value_currency`, plus
`latest_value_source` naming which source produced it (an adapter key, a
manual entry's own source text, or `average`). It is resolved by the app-wide
`value_strategy` setting (see Settings, below), not simply "whichever
estimate is newest."

Item payloads accept `tags` (list of names, get-or-create) and `catalog_refs`
(list of `{catalog, ref_code}`). CSV import consumes the export format;
derived columns are ignored, rows whose `id` already exists are skipped (so
re-importing an export never duplicates the collection), and per-row failures
are reported without aborting the rest.

Grading fields: `strike` (`business` default, `proof`, `specimen`),
`grade_plus`, `grade_star`, `designations` (list; `PL`, `DMPL`, `CAM`, `DCAM`,
`UCAM`, `RD`, `RB`, `BN`, `FB`, `FBL`, `FH`, `FS`, `FT`, `EPQ`; case-insensitive,
deduplicated), `grade_details` (the problem on a details grade), and
`cac_sticker` (`green`/`gold`). Physical: `diameter_mm`, `thickness_mm`, `edge`,
`shape`, `mintage`. Banknotes: `serial_number`, `prefix_block`, `signatures`,
`issuer`, `replacement_note`. Costs: `acquisition_fees` and, on sale,
`sold_fees` and `sold_to`. Responses add three derived fields: `grade_label`
(the grade as a holder reads, e.g. `PR-69 DCAM ★`), `cost_basis` (price plus
fees), and `sale_proceeds` (sold price less fees); these are the figures
every gain calculation uses. CSV import also reads label-style grades:
`PR-65`, `PF-65`, or `SP-65` on the Sheldon scale set the strike, and a
trailing `+` sets `grade_plus`.

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
response carries `details`: the provenance an automatic source recorded (see
[price-sources.md](price-sources.md)), `{"note": …}` for a manual entry given
a note, or `null`. `POST .../estimate` runs one automatic adapter, chosen
with `?source=`: `melt` (the default: spot × weight × fineness × quantity,
metal detected from `composition`), `numista` (by the item's `numista` catalog
ref and grade), `pcgs` (US coins by PCGS cert number, or `pcgs` catalog ref
+ grade; auction sales when PCGS has them, price guide otherwise), or `comps`
(the median of the item's logged sales; see Sales log below). The two
external sources need a credential in Settings. Any of them answers
422 with the missing prerequisite when the item can't be priced by that source
or the source is switched off, and 502 when the upstream is unreachable. See
[price-sources.md](price-sources.md). An in-process scheduler re-runs stale
melt estimates every 12h (estimates older than `REESTIMATE_DAYS`, default 7;
`0` disables); a melt refresh never supersedes an item whose latest estimate
is manual. The same 12h loop also refreshes Numista and/or PCGS when their
own cadence is switched on in Settings (each off by default), independently
of melt and of whichever source currently wins an item's overall-latest
estimate, since `value_strategy` may prefer or average a source that isn't
"latest" right now.

## Stats

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| `GET`  | `/api/stats/collection`  | Totals in a display currency (`?currency=`)    |
| `GET`  | `/api/stats/breakdowns`  | Owned items grouped by country/type/decade/grade/tag + acquisitions by year |
| `GET`  | `/api/stats/gains`       | Per-item unrealized (owned) and realized (sold) gain/loss |
| `GET`  | `/api/stats/value-history` | Month-end collection value over time (`?months=`) |

Counts by status/type, cost basis, estimated value (latest estimate per owned
item), unrealized gain (items with both price and estimate), and realized
gain (sold items). All stats endpoints share one currency rule: amounts in
other currencies are **converted** into the display currency at cached daily
ECB rates (frankfurter.dev, 24h cache, stale fallback); amounts with no
obtainable rate are **excluded** and counted, never guessed
(`converted_other_currency` / `excluded_other_currency` on `/collection`).

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

Grades are seeded by migration: `sheldon` for coins, `pmg` for notes. Catalog
references are managed inline on items rather than via a standalone endpoint.

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
Numista API key (`422`); an unknown type is `404`.

## Numista catalogue lookup

| Method | Path                         | Purpose                                          |
|--------|------------------------------|--------------------------------------------------|
| `GET`  | `/api/numista/search`        | Search the catalogue: `q` (2–100 chars), optional `category` (`coin`/`banknote`) |
| `GET`  | `/api/numista/types/{id}`    | A type as fillable item fields, catalogue refs, and issues |

Both need a Numista API key in Settings (422 without one) and answer 502 when
Numista is unreachable or the quota is exhausted; an unknown type is 404.
Search returns `count` and up to 20 `results` (`type_id`, `title`,
`category`, `issuer`, `min_year`, `max_year`, `thumbnail`). A type returns
`title`, `url`, `category`, and `fields` keyed like the item payload:
`type`, `country`, `denomination`, `series`, `composition`, `fineness`, and
`year` when the type has a single year; coins add `weight_g`, `diameter_mm`,
`thickness_mm`, `shape`, and `edge`; notes add `issuer` (the issuing bank).
Only values Numista has are present, trimmed to the item schema's limits.
`catalog_refs` holds `numista:N#<id>` and the type's other references
(`km:KM#273`, `pick:Pick#79a`…); `issues` lists `year`, `mint_letter`,
`mintage`, and `comment`. Responses are cached for 7 days in `source_cache`
(the longest Numista's API licence allows), issues shared with Numista pricing.

## PCGS cert lookup

| Method | Path                     | Purpose                                              |
|--------|--------------------------|------------------------------------------------------|
| `GET`  | `/api/pcgs/cert/{cert}`  | A PCGS-graded coin as item fields ready to fill in   |

Needs a PCGS API token (`422` without one, or when PCGS has no such cert;
`502` when PCGS can't be reached). Answers `cert`, `pcgs_number`, `name`,
`fields` (keyed like the item payload: `type`, `country`, `denomination`,
`year`, `mint_mark`, `series`, `variety`, `composition`, `weight_g`,
`diameter_mm`, `edge`, `mintage`, `cert_service`, `cert_number`; only what
PCGS has), `grade` (`rank`, `strike`, `plus`, `designations`, or `null` for a
Genuine/details holder), `catalog_refs` (the PCGS number), `population`,
`pop_higher`, `price_guide_value`, and `coinfacts_url`. Cached with the
pricing lookup for the same cert, so an estimate afterwards is free.

## Pricing reports

| Method | Path                          | Purpose                                            |
|--------|-------------------------------|----------------------------------------------------|
| `GET`  | `/api/pricing/coverage`       | Owned items lacking estimates, and per source why  |
| `GET`  | `/api/pricing/stale`          | Latest estimates `?days=` old (default 30, 1–3650) or built from expired source data |
| `GET`  | `/api/pricing/sources`        | Per-source breakdown and biggest disagreements (`?currency=`) |
| `GET`  | `/api/pricing/accuracy`       | Estimates standing on the sale date vs realized prices (`?currency=`) |

All four read existing data and call no upstream source. Estimates are
grouped by source key: `melt`, `numista`, `pcgs`, and `manual` for any
hand-entered source text.

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
- **sources**: per source: `items`, `total_value`, `avg_confidence`,
  `median_age_days`, `in_totals` (items whose shown value it supplies);
  `averaged_items` when the strategy is `average`; and up to ten
  `disagreements` (items with two or more sources, with each value and the
  `spread_pct` between highest and lowest).
- **accuracy**: sold items with a sold price. For each, the latest estimate
  per source recorded on or before `sold_date` (all estimates when there is
  no date) and the shown value as of then, each with `error_pct` =
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
The bulk endpoints answer `{"count": n}`, counting only items that changed.
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
`appraisal`, `correspondence`, `other`. Files may be PDF, JPEG, PNG, or WebP,
25 MB at most (413 above that), detected from their bytes; anything else is
415, with the reason. A PDF must open in PDFium; one that needs a password is
kept without a thumbnail or page count. Responses carry `id`, the fields above,
`filename` (the uploaded name with the detected extension), `content_type`,
`size`, `pages`, `has_thumb`, `items` (`id`, `label` of every item it's
attached to), and `created_at`; `GET /api/items/{id}` includes them as
`documents`. Uploads answer 503 when document storage isn't usable; see
`documents` in Health.

Files are served with `X-Content-Type-Options: nosniff`, `Cache-Control:
private`, a `Content-Disposition` carrying the filename (RFC 5987 for non-ASCII
names), and a content security policy: `default-src 'none'; sandbox` for
images, `default-src 'none'; frame-ancestors 'self'` for PDFs, because
`sandbox` stops Chrome's built-in PDF viewer rendering at all.

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
URL), and `issue_id`. A key without Numista's paid plan gets 422 with that
explanation; an unreachable Numista is 502. One request, cached for a day.

## Imports

| Method   | Path                              | Purpose                                          |
|----------|-----------------------------------|--------------------------------------------------|
| `POST`   | `/api/imports`                    | Stage a file (multipart, up to 1 GB); returns `upload_id` and the detected `format` |
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

A preview answers `total`, `new`, `duplicates` (already imported), `errors`,
`warnings`, `photos`, and up to 200 `rows` (`status` new / duplicate / error,
`label`, the resolved `grade`, `messages`, `error`). A run answers `created`,
`skipped`, `errors` (`row`, `error`), `photos_added`, and `photos_failed`;
each item commits on its own, so a bad row never undoes others. Imported
items record `import_source` + `import_key` (a Numista collected-item id,
an OpenNumismat record, a Cabinet export's id, or a row fingerprint), which is how a second import
of the same source skips them; their edit history notes the import.

The Numista endpoints take `catalogue_details` (default true: one request per
type not cached in the last week, on run only) and `fetch_photos` (default
false; pictures go through the same guarded fetch as photo URL import). They
authenticate as the API key's owner (OAuth client credentials, scope
`view_collection`); the collection is cached for an hour, so a preview and
the run that follows cost one fetch. 422 without a key or when the key has no
user; 502 when Numista is unreachable or refuses.

## Settings

| Method | Path             | Purpose                                          |
|--------|------------------|--------------------------------------------------|
| `GET`  | `/api/settings`  | App settings + source status + cached market data|
| `PUT`  | `/api/settings`  | Partial update                                   |

Settings cover the app-wide display currency (used by all stats endpoints
unless `?currency=` overrides), the melt refresh cadence (DB override of the
`REESTIMATE_DAYS` env var; takes effect without restart), source toggles, and
source credentials (Numista API key, PCGS token). **Secrets are write-only and
encrypted at rest**: reads return only a configured flag and a last-4 hint,
never the value, and stored credentials are Fernet-encrypted before they reach
the database. See [security.md](security.md).

Also covered: `value_strategy` (`latest` / `preferred_source` / `average`)
and `preferred_source`, which together control the single blended value used
by the items list, CSV/XLSX export, and dashboard totals (the item page
itself always shows every source's own latest value, unaffected by this
setting); and each source's scheduled-refresh cadence,
`numista_refresh_days` (`null` for off, else `7`/`14`/`30`) and
`pcgs_auto_refresh` (bool, fixed weekly when on). The response also reports
`numista_priceable_items`/`pcgs_priceable_items` (owned items eligible for
each source) so the UI can show the real projected monthly call count
before you turn Numista's cadence on. `backup_schedule` (`null` / `daily` /
`weekly`), `backup_keep` (1–365), and `backup_include_photos` configure
scheduled backups (see Backups below). `comps_enabled` switches the comps
source (on by default), and `numista_sales_enabled` (off by default) allows
fetching Numista's auction sales, which needs Numista's paid API plan.
`preferred_source` accepts `comps`. `trash_retention_days` (`0` = never, `7`,
`30`, `90`, or `365`; the default is `30`) is how long an item stays in the
trash.

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

An archive is a zip of `db.dump` (pg_dump custom format), `photos.tar.gz`
and `documents.tar.gz` (unless data-only), `manifest.json`, and `SHA256SUMS`; see
[backup-restore.md](backup-restore.md). A failed backup returns `500` with
the reason (for example, `pg_dump failed: …`) and is recorded as the last
run; a second `POST` while one is running returns `409`. Stored archive names
must match `cabinet-backup-YYYYMMDD-HHMMSS[-data].zip`; anything else is
`404`. **These endpoints hand over the whole collection and are
unauthenticated**; see [security.md](security.md).

## Alerts & metrics

| Method | Path               | Purpose                                                    |
|--------|--------------------|------------------------------------------------------------|
| `POST` | `/api/alerts/test` | Send a test alert through the saved webhook; `?target=heartbeat` pushes the heartbeat now |
| `GET`  | `/api/metrics`     | Prometheus metrics; `404` until `metrics_enabled`          |

The test answers `200` either way, with `at`, `ok`, and `detail`: `HTTP
404`, a connection error, or `No webhook URL is saved`; a detail never
repeats the URL. Metrics are cached for a minute. What alerts fire, the
payload of each format, and every metric are in
[monitoring.md](monitoring.md).

## Checklists (completeness tracking)

| Method   | Path                                    | Purpose                     |
|----------|-----------------------------------------|-----------------------------|
| `GET`    | `/api/checklists`                       | List with filled/total      |
| `POST`   | `/api/checklists`                       | Create with a slot list     |
| `POST`   | `/api/checklists/generate`              | Generate slots that fill themselves |
| `GET`    | `/api/checklists/{id}`                  | Detail with slots           |
| `PATCH`  | `/api/checklists/{id}/slots/{slot_id}`  | Check/uncheck or link item  |
| `DELETE` | `/api/checklists/{id}`                  | Delete a checklist          |

`POST /api/checklists/generate` takes `source: "numista"` with a `type_id`
(one slot per dated issue, matched by the type's Numista number) or
`source: "range"` with `country`, `denomination`, `year_from`, `year_to`,
`mint_marks` (`""` is the no-mint-mark slot) and `skip` (labels such as
`1933` or `1934-S`), matched by country and denomination; `name` is
optional, and 500 slots is the limit. A generated slot carries `year` and
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
- **IDs** are UUIDs for items/photos/estimates; reference tables use integers.
- **Errors** follow a consistent JSON shape: `{ "detail": "..." }`, matching
  FastAPI defaults, with appropriate HTTP status codes.
