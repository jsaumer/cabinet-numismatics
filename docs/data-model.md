# Data Model

The schema centers on **items**, with photos, price estimates, a sales log,
documents, and edit history hanging off each item, plus reference tables for
grades and catalog numbers, caches for market data, and a key/value settings
table.

**Migration status:** revisions `0001`–`0017`. `0001` is an empty baseline;
`0002` created `items`, `item_photos`, `price_estimates`; `0003` added the
Phase 2 item columns, `grades` (seeded), `tags`, `catalog_refs` + joins, and
photo ordering; `0004` added `spot_prices`; `0005` `exchange_rates`; `0006` `sets`
plus `items.variety` / `set_id` / `custom_fields`; `0007` `item_events` and
`checklists` + `checklist_slots`.

Revision `0008` (pricing program M1) added `app_settings`: key/value JSON
settings (display currency, source toggles, API credentials, melt cadence;
later grew `value_strategy`/`preferred_source` for the blended-value display,
`numista_refresh_days`/`pcgs_auto_refresh` for scheduled refresh,
`comps_enabled`/`numista_sales_enabled` for the sales log,
`backup_schedule`/`backup_keep`/`backup_include_photos`/`backup_last_run`
for in-app backups, `trash_retention_days` for the trash, and
`alert_webhook_url`/`alert_webhook_format`/`heartbeat_url`/`metrics_enabled`
plus the service-written `refresh_last_run`/`alert_state` for alerts and
metrics, with no migration needed, since it's a generic key/value table),
read through `app/services/app_settings.py` with defaults and env fallbacks.
The four secrets (`numista_api_key`, `pcgs_api_token`, `alert_webhook_url`,
`heartbeat_url`) are stored encrypted; see [security.md](security.md).
Revision `0009` (M2) added `source_cache`; `0010` (M4) added
`price_estimates.details`;
`0011` (M5) added `estimate_attempts`, the latest automatic pricing attempt
per item and source (`item_id` + `source` primary key, cascade with the item;
`outcome` `ok` / `not_applicable` / `unavailable`, `message`,
`attempted_at`), which the coverage report reads to explain gaps a failed
attempt leaves no estimate for. `0012` (v0.14.0, catalog depth) added the
grading, physical, banknote, and cost columns on `items` below, and PMG
grades 1–3. `0013` (v0.17.0) added `comparables`, the per-item sales log. `0014`
(v0.18.0) added `items.import_source` / `import_key`. `0015` (v0.19.0) added
`documents` and `item_documents`. `0016` (v0.20.0) added `items.deleted_at`
for the trash. `0017` (v0.23.0) added `checklists.match_catalog`,
`match_ref`, `match_country`, and `match_denomination` (what fills a
generated checklist) and `checklist_slots.year` and `mint_mark`; which item
fills a slot is computed on read, never stored.

**Phase 5 tables in brief:** `exchange_rates` (base+quote PK, cached daily
rate); `sets` (id, unique name, notes; `items.set_id` SET NULL on delete);
`item_events` (append-only history: `at`, an action of `created` /
`updated` / `trashed` / `restored`, and `{field: [old, new]}` JSON on an
update; integer PK, cascade with the item); `checklists`/`checklist_slots`
(completeness targets: a named checklist, and per slot a label, position,
`filled` hand tick, and optional item link SET NULL; slots cascade with the
checklist). `items` also gained `variety` (text) and `custom_fields` (JSON
key→value, max 20).

**Money convention:** `acquisition_price`, `sold_price`, and
`estimated_value` are all **per row** (the whole lot as entered), never
per-piece. Automatic estimates multiply per-piece value by `quantity` to
match.

## Entity relationships

```
items ──1:N── item_photos
  │
  ├──1:N── price_estimates
  ├──1:N── estimate_attempts (the latest per source)
  ├──1:N── comparables     (the sales log)
  ├──1:N── item_events     (edit history)
  │
  ├──N:M── documents       (via item_documents)
  ├──N:M── tags            (via item_tags)
  ├──N:M── catalog_refs    (reference, via item_catalog_refs)
  │
  ├──N:1── grades          (reference)
  └──N:1── sets

checklists ──1:N── checklist_slots ──N:1── items (optional link)
```

## Tables

### items
The core record for a single coin or note (or a lot of identical pieces via
`quantity`). Enums are stored as short strings, checked by the application,
not as native postgres enum types.

| Column             | Type          | Notes                                   |
|--------------------|---------------|-----------------------------------------|
| `id`               | uuid PK       |                                         |
| `type`             | enum          | `coin` \| `note`; indexed               |
| `status`           | enum          | `owned` \| `sold` \| `wishlist`; indexed |
| `country`          | text          | indexed                                 |
| `denomination`     | text          | e.g. "25 cents", "10 dollars"           |
| `year`             | int           | issue year; indexed                     |
| `mint_mark`        | text null     | coins only                              |
| `series`           | text null     | series / variety name                   |
| `variety`          | text null     | die variety, overdate…                  |
| `strike`           | enum          | `business` \| `proof` \| `specimen`     |
| `composition`      | text null     | e.g. "90% silver"                       |
| `weight_g`         | numeric null  | grams; enables melt value (Phase 3)     |
| `fineness`         | numeric null  | 0–1, e.g. 0.9000                        |
| `diameter_mm`      | numeric null  | coins                                   |
| `thickness_mm`     | numeric null  | coins                                   |
| `edge`             | text null     | reeded, plain, lettered…                |
| `shape`            | text null     | round, polygonal…                       |
| `mintage`          | bigint null   | mintage, or print run for a note        |
| `grade_id`         | fk → grades   | null if ungraded                        |
| `cert_service`     | text null     | PCGS, NGC, PMG…                         |
| `cert_number`      | text null     | slab certification number               |
| `grade_plus`       | bool          | a "+" grade                             |
| `grade_star`       | bool          | NGC/PMG ★ designation                   |
| `designations`     | json null     | list, e.g. `["DCAM"]`, `["RD"]`, `["EPQ"]` |
| `grade_details`    | text null     | the problem on a details grade          |
| `cac_sticker`      | text null     | `green` \| `gold`                        |
| `serial_number`    | text null     | notes                                   |
| `prefix_block`     | text null     | notes                                   |
| `signatures`       | text null     | notes                                   |
| `issuer`           | text null     | notes: issuing bank or authority        |
| `replacement_note` | bool          | notes: replacement / star note          |
| `quantity`         | int           | default 1                               |
| `acquisition_date` | date null     |                                         |
| `acquisition_price`| numeric null  | what you paid                           |
| `acquisition_fees` | numeric null  | premium, shipping, tax (in cost basis)  |
| `currency`         | text          | ISO 4217, for acquisition price         |
| `acquired_from`    | text null     | dealer, show, auction, inheritance…     |
| `storage_location` | text null     | album, slab box, safe…                  |
| `sold_date`        | date null     | when status = `sold`                    |
| `sold_price`       | numeric null  | realized price (gross), in `currency`   |
| `sold_fees`        | numeric null  | commission, listing fees                |
| `sold_to`          | text null     | buyer or venue                          |
| `set_id`           | fk → sets null | the set or lot it belongs to; SET NULL when the set is deleted |
| `custom_fields`    | json null     | user-defined key→value, max 20          |
| `notes`            | text null     | free-form                               |
| `import_source`    | text null     | where an imported item came from: `numista`, `numista-file`, `opennumismat`, `cabinet`, `spreadsheet` |
| `import_key`       | text null     | its id there; unique with `import_source`, so a re-import skips it; not copied by clone |
| `deleted_at`       | timestamptz null | in the trash since; indexed. Every ORM query leaves trashed items out unless it opts in (`include_deleted`) |
| `created_at`       | timestamptz   |                                         |
| `updated_at`       | timestamptz   |                                         |

### item_photos
Photo metadata; the binary lives on the photo volume, served by nginx.

| Column        | Type         | Notes                                     |
|---------------|--------------|-------------------------------------------|
| `id`          | uuid PK      |                                           |
| `item_id`     | fk → items   | cascade delete, indexed                   |
| `file_key`    | text         | relative path under PHOTO_DIR             |
| `thumb_key`   | text null    | generated thumbnail path                  |
| `angle`       | enum null    | `obverse` \| `reverse` \| `edge` \| `other` |
| `is_primary`  | bool         | one primary per item                      |
| `position`    | int          | display order within the item             |
| `width`       | int null     |                                           |
| `height`      | int null     |                                           |
| `uploaded_at` | timestamptz  |                                           |

Files are served at `/photos/{file_key}` (and `/photos/{thumb_key}`); only the
keys are stored in the database, not the bytes.

### price_estimates
Timestamped estimates so history is retained rather than overwritten.

| Column            | Type        | Notes                                    |
|-------------------|-------------|------------------------------------------|
| `id`              | uuid PK     |                                          |
| `item_id`         | fk → items  | cascade delete, indexed                  |
| `source`          | text        | which source produced the estimate       |
| `estimated_value` | numeric     |                                          |
| `currency`        | text        | ISO 4217                                 |
| `confidence`      | numeric null| 0.0–1.0; null for manual entries         |
| `sample_size`     | int null    | number of comparables used               |
| `details`         | json null   | provenance: what the source returned (see price-sources.md), or `{"note": …}` on a manual entry; null on rows before `0010` |
| `fetched_at`      | timestamptz |                                          |

### comparables
The item's sales log: sales of comparable pieces, which the `comps` estimate
takes its median from. Integer PK so same-day sales still order; cascade
delete with the item. Cloning an item leaves its sales behind.

| Column             | Type          | Notes                                       |
|--------------------|---------------|---------------------------------------------|
| `id`               | int PK        |                                             |
| `item_id`          | fk → items    | cascade delete, indexed                     |
| `sold_on`          | date          |                                             |
| `venue`            | text          | eBay, Heritage, a dealer…                   |
| `title`            | text null     | sale or listing title                       |
| `lot`              | text null     |                                             |
| `url`              | text null     | the lot or listing                          |
| `grade`            | text null     | as the lot described it, e.g. "NGC MS64"    |
| `grade_bucket`     | text null     | Numista's g…unc when known; must match the item's to count |
| `price`            | numeric       | per piece                                   |
| `currency`         | text          | ISO 4217                                    |
| `premium_included` | bool null     | null = unknown                              |
| `fees`             | numeric null  | premium or shipping on top, added to price  |
| `included`         | bool          | counts toward the comps estimate            |
| `source`           | text          | `manual` \| `numista`                       |
| `external_id`      | text null     | Numista lot URL; unique per item, so a re-fetch skips known sales |
| `note`             | text null     |                                             |
| `created_at`       | timestamptz   |                                             |

### documents / item_documents
Attached files: receipts, certificates, invoices. The file and its
thumbnail live under `DOCUMENT_DIR/<id>/` (never the public photo volume);
the row holds the metadata. `item_documents` links a document to any number
of items (both keys cascade); the API deletes a document when its last link
goes.

| Column         | Type         | Notes                                        |
|----------------|--------------|----------------------------------------------|
| `id`           | uuid PK      |                                              |
| `kind`         | text         | receipt, invoice, certificate, grading_label, appraisal, correspondence, other |
| `title`        | text         | defaults to the file name                    |
| `doc_date`     | date null    | the document's own date                      |
| `note`         | text null    |                                              |
| `filename`     | text         | uploaded name, extension from the detected type |
| `content_type` | text         | detected from the bytes: `application/pdf`, `image/jpeg`, `image/png`, `image/webp` |
| `size`         | bigint       | bytes                                        |
| `sha256`       | text         | indexed                                      |
| `pages`        | int null     | PDFs; null when password-protected           |
| `file_key`     | text         | `<id>/original.<ext>` under `DOCUMENT_DIR`   |
| `thumb_key`    | text null    | `<id>/thumb.jpg`                             |
| `created_at`   | timestamptz  |                                              |

### tags / item_tags
Free-form labels for arbitrary grouping (`tags.id`, unique `tags.name`;
`item_tags` joins item ↔ tag, both cascade). Tags are created on first use
via item payloads; tags no item uses remain listed with count 0.

### spot_prices (cache)
Per-metal spot price cache for melt estimates (`metal` PK, `price_per_gram`,
`currency`, `source`, `fetched_at`). Refreshed on demand when older than 12
hours; a stale row is used if the upstream fetch fails.

### exchange_rates (cache)
Daily ECB rates for converting between currencies (`base` + `quote` composite
PK, `rate`, `source`, `fetched_at`). Refreshed on demand when older than 24
hours; a stale row is used if the upstream fetch fails.

### source_cache (cache)
Raw responses from external price sources, so repeated estimates don't spend a
request against a small free-tier quota (`source` + `cache_key` composite PK,
`payload` JSON, `fetched_at`). Numista caches catalogue data (a type, its
issues, searches) and prices for 7 days, auction sales for 1 day, and the
user's own collection (for import) for 1 hour; PCGS caches CoinFacts
responses for 7 days. A stale row is used if the upstream fetch fails.

### grades (reference)
Grade scales for coins and notes. Seeded by migration `0003` from
`app/models/grades_seed.py`: `sheldon` (PO-1 through MS-70) and `pmg`
(1 through 70; 1–3 were added by `0012`, which inserts them only where
missing). Proofs and specimens reuse the Sheldon rows (the item's `strike`
turns `MS-65` into `PR-65` or `SP-65`), and designations, plus grades, stars,
and details grades live on the item, not the grade.

| Column        | Type    | Notes                                        |
|---------------|---------|----------------------------------------------|
| `id`          | int PK  |                                              |
| `scale`       | text    | `sheldon` or `pmg`                           |
| `code`        | text    | e.g. `MS-65`, `VF-20`, `64`; unique per scale |
| `label`       | text    | human-readable description                   |
| `rank`        | int     | sortable ordering, low → high                |

### catalog_refs (reference)
Catalog numbers used to match items to external price sources.

| Column      | Type   | Notes                                          |
|-------------|--------|------------------------------------------------|
| `id`        | int PK |                                                |
| `catalog`   | text   | e.g. `krause`, `numista`, `redbook`            |
| `ref_code`  | text   | the catalog's identifier; unique per catalog   |

### item_catalog_refs (join)
Associates an item with one or more catalog references.

| Column           | Type              | Notes       |
|------------------|-------------------|-------------|
| `item_id`        | fk → items        | PK, cascade |
| `catalog_ref_id` | fk → catalog_refs | PK, cascade |

A catalog reference is a shared row: two items with the same Krause number
point at the same `catalog_refs` row.

## Notes on design choices

- **UUID primary keys** on user-facing tables keep photo file keys and API
  URLs non-enumerable.
- **Price estimates are append-only**, giving a value history over time rather
  than a single mutable field.
- **`quantity`** on `items` supports holding multiples of an identical piece
  without duplicate rows; split into separate rows if grades differ.
- **Grades and catalogs are reference tables** so the app can present valid
  options and match against external sources consistently.
