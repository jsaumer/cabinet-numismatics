# Data Model

The schema centers on **items**, with photos and price estimates hanging off
each item, plus a few reference tables for grades and catalog numbers.

**Migration status:** the full schema exists as of Phase 5. Revision `0002`
created `items`, `item_photos`, `price_estimates`; `0003` added the Phase 2
item columns, `grades` (seeded), `tags`, `catalog_refs` + joins, and photo
ordering; `0004` added `spot_prices`; `0005` `exchange_rates`; `0006` `sets`
plus `items.variety` / `set_id` / `custom_fields`; `0007` `item_events` and
`checklists` + `checklist_slots`.

Revision `0008` (pricing program M1) added `app_settings` — key/value JSON
settings (display currency, source toggles, API credentials, melt cadence),
read through `app/services/app_settings.py` with defaults and env fallbacks.

**Phase 5 tables in brief:** `exchange_rates` (base+quote PK, cached daily
rate); `sets` (id, unique name, notes; `items.set_id` SET NULL on delete);
`item_events` (append-only edit history: action + `{field: [old, new]}`
JSON, cascade with the item); `checklists`/`checklist_slots` (completeness
targets: label, position, filled, optional item link SET NULL). `items` also
gained `variety` (text) and `custom_fields` (JSON key→value, max 20).

**Money convention:** `acquisition_price`, `sold_price`, and
`estimated_value` are all **per row** — the whole lot as entered — never
per-piece. Automatic estimates multiply per-piece value by `quantity` to
match.

## Entity relationships

```
items ──1:N── item_photos
  │
  ├──1:N── price_estimates
  │
  └──N:1── grades          (reference)
  └──N:M── catalog_refs    (reference, via item_catalog_refs)
```

## Tables

### items
The core record for a single coin or note (or a lot of identical pieces via
`quantity`).

| Column             | Type          | Notes                                   |
|--------------------|---------------|-----------------------------------------|
| `id`               | uuid PK       |                                         |
| `type`             | enum          | `coin` \| `note`                        |
| `status`           | enum          | `owned` \| `sold` \| `wishlist`         |
| `country`          | text          |                                         |
| `denomination`     | text          | e.g. "25 cents", "10 dollars"           |
| `year`             | int           | issue year                              |
| `mint_mark`        | text null     | coins only                              |
| `series`           | text null     | series / variety name                   |
| `composition`      | text null     | e.g. "90% silver"                       |
| `weight_g`         | numeric null  | grams — enables melt value (Phase 3)    |
| `fineness`         | numeric null  | 0–1, e.g. 0.9000                        |
| `grade_id`         | fk → grades   | null if ungraded                        |
| `cert_service`     | text null     | PCGS, NGC, PMG…                         |
| `cert_number`      | text null     | slab certification number               |
| `quantity`         | int           | default 1                               |
| `acquisition_date` | date null     |                                         |
| `acquisition_price`| numeric null  | what you paid                           |
| `currency`         | text          | ISO 4217, for acquisition price         |
| `acquired_from`    | text null     | dealer, show, auction, inheritance…     |
| `storage_location` | text null     | album, slab box, safe…                  |
| `sold_date`        | date null     | when status = `sold`                    |
| `sold_price`       | numeric null  | realized price, in `currency`           |
| `notes`            | text null     | free-form                               |
| `created_at`       | timestamptz   |                                         |
| `updated_at`       | timestamptz   |                                         |

### item_photos
Photo metadata; the binary lives on the photo volume, served by nginx.

| Column        | Type         | Notes                                     |
|---------------|--------------|-------------------------------------------|
| `id`          | uuid PK      |                                           |
| `item_id`     | fk → items   | cascade delete                            |
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
| `item_id`         | fk → items  | cascade delete                           |
| `source`          | text        | which source produced the estimate       |
| `estimated_value` | numeric     |                                          |
| `currency`        | text        | ISO 4217                                 |
| `confidence`      | numeric null| 0.0–1.0; null for manual entries         |
| `sample_size`     | int null    | number of comparables used               |
| `fetched_at`      | timestamptz |                                          |

### tags / item_tags
Free-form labels for arbitrary grouping (`tags.id`, unique `tags.name`;
`item_tags` joins item ↔ tag, both cascade). Tags are created on first use
via item payloads; tags no item uses remain listed with count 0.

### spot_prices (cache)
Per-metal spot price cache for melt estimates (`metal` PK, `price_per_gram`,
`currency`, `source`, `fetched_at`). Refreshed on demand when older than 12
hours; a stale row is used if the upstream fetch fails.

### source_cache (cache)
Raw responses from external price sources, so repeated estimates don't spend a
request against a small free-tier quota (`source` + `cache_key` composite PK,
`payload` JSON, `fetched_at`). Numista caches catalogue data (a type's issues)
for 30 days and prices for 7; PCGS caches CoinFacts responses for 7 days. A
stale row is used if the upstream fetch fails.

### grades (reference)
Grade scales for coins and notes. Seeded by migration `0003` from
`app/models/grades_seed.py`: `sheldon` (PO-1 through MS-70) and `pmg`
(4 through 70).

| Column        | Type    | Notes                                        |
|---------------|---------|----------------------------------------------|
| `id`          | int PK  |                                              |
| `scale`       | text    | e.g. `sheldon`, `pmg`                        |
| `code`        | text    | e.g. `MS-65`, `VF-20`, `64 EPQ`              |
| `label`       | text    | human-readable description                   |
| `rank`        | int     | sortable ordering, low → high                |

### catalog_refs (reference)
Catalog numbers used to match items to external price sources.

| Column      | Type   | Notes                                          |
|-------------|--------|------------------------------------------------|
| `id`        | int PK |                                                |
| `catalog`   | text   | e.g. `krause`, `numista`, `redbook`            |
| `ref_code`  | text   | the catalog's identifier                       |

### item_catalog_refs (join)
Associates an item with one or more catalog references.

| Column           | Type              |
|------------------|-------------------|
| `item_id`        | fk → items        |
| `catalog_ref_id` | fk → catalog_refs |

## Notes on design choices

- **UUID primary keys** on user-facing tables keep photo file keys and API
  URLs non-enumerable.
- **Price estimates are append-only**, giving a value history over time rather
  than a single mutable field.
- **`quantity`** on `items` supports holding multiples of an identical piece
  without duplicate rows; split into separate rows if grades differ.
- **Grades and catalogs are reference tables** so the app can present valid
  options and match against external sources consistently.
