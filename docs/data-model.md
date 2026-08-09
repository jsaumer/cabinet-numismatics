# Data Model

The schema centers on **items**, with photos and price estimates hanging off
each item, plus a few reference tables for grades and catalog numbers.

**Migration status:** the full schema below exists as of Phase 3. Revision
`0002` created `items`, `item_photos`, `price_estimates`; revision `0003`
added the Phase 2 item columns, `grades` (seeded with the Sheldon and PMG
scales), `tags` + `item_tags`, `catalog_refs` + `item_catalog_refs`, and
photo ordering; revision `0004` added `spot_prices`.

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
