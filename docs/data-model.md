# Data Model

The schema centers on **items**, with photos and price estimates hanging off
each item, plus a few reference tables for grades and catalog numbers.

**Migration status:** `items`, `item_photos`, and `price_estimates` exist as of
Phase 1 (revision `0002`). The reference tables (`grades`, `catalog_refs`,
`item_catalog_refs`) and the `items.grade_id` column arrive with grading in
Phase 2.

**Planned Phase 2 columns on `items`** (see the roadmap's "schema-complete
before data-complete" note): `status` (`owned` | `sold` | `wishlist`) with
`sold_date` / `sold_price`, `composition`, `weight_g`, `fineness`,
`cert_service` + `cert_number`, `acquired_from`, and `storage_location`.

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
| `country`          | text          |                                         |
| `denomination`     | text          | e.g. "25 cents", "10 dollars"           |
| `year`             | int           | issue year                              |
| `mint_mark`        | text null     | coins only                              |
| `series`           | text null     | series / variety name                   |
| `grade_id`         | fk → grades   | null if ungraded                        |
| `quantity`         | int           | default 1                               |
| `acquisition_date` | date null     |                                         |
| `acquisition_price`| numeric null  | what you paid                           |
| `currency`         | text          | ISO 4217, for acquisition price         |
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

### grades (reference)
Grade scales for coins and notes.

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
