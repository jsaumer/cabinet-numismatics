# Data Model

The schema centers on **items**, with photos, price estimates, a sales log,
documents, and edit history hanging off each item, plus reference tables for
grades and catalog numbers, caches for market data, and a key/value settings
table.

**Migrations:** two Alembic chains. The collection (`backend/alembic/`,
schema `public`) is at revision `0022`; sign-in data (`backend/alembic_auth/`,
schema `cabinet_auth`, from v0.30.0) is at `a0002`. The backend applies both
on startup, collection first, in one transaction. What each release added is
in [implementation-notes.md](implementation-notes.md).

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

## Sign-in data: the cabinet_auth schema (v0.30.0)

Credentials live in a Postgres schema of their own, `cabinet_auth`, with
their own Alembic chain (`backend/alembic_auth/`, revisions `a0001` and
`a0002` (single sign-on, v0.33.0), version
table `cabinet_auth.alembic_version`) and their own declarative base
(`AuthBase` in `app/models/auth.py`). **No foreign key crosses between it
and the collection in either direction**, and the collection never stores a
user id. Backups dump every schema but this one and restores replace
`public` only, so an archive never carries a credential and a restore never
changes one (see [backup-restore.md](backup-restore.md)). The backend
migrates it on startup right after the collection chain, in the same
transaction; by hand, `alembic -c alembic_auth.ini upgrade head`.

| Table | Holds |
|-------|-------|
| `users` | The admin (`username` unique, lowercased; `password_hash` Argon2id, null for a provider-only account later; `role` `admin` / `editor` / `viewer`; `is_active`; `created_at`, `last_login_at`, `password_changed_at`) |
| `claim` | One row (`id` is always 1) once the admin exists: its insert is the atomic claim of the instance (`claimed_at`, `user_id`) |
| `sessions` | Signed-in browsers: the secret's SHA-256 (never the secret), `user_id`, `auth_method`, `created_at`, `last_seen_at`, `expires_at` (7 days at most), `confirmed_until` (the recent-password window), `user_agent`, `address`, `revoked_at`, `identity_id` (v0.33.0: the linked identity an `oidc` or `trusted_header` session came through, set null if it goes), `notice_failed`, `notice_since` (v0.33.0: the failed-sign-ins figures of an external sign-in, handed over once by `GET /api/auth/me` and cleared) |
| `api_tokens` | `public_id` (unique), the secret's SHA-256, `user_id`, `name`, `scope` (`read` / `write` / `metrics`, one each), `created_at`, `last_used_at`, `expires_at`, `revoked_at` |
| `known_devices` | Browsers that signed in successfully: the cookie's SHA-256, `user_id`, `created_at`, `expires_at`, `failures` |
| `audit_log` | One row per event: `at`, the actor (`actor_user_id`, set null if the user goes; `actor_label`; `actor_kind` `session` / `token` / `anonymous` / `cli` / `system`), `action`, `target`, `detail` (JSON), `address`, `user_agent`. Never anything from the collection |
| `auth_providers` | v0.33.0. Sign-in providers, at most 8: `kind` (`oidc` / `oauth2_profile`), `preset` (`google` / `microsoft` / `github` / `custom`; `github` is the one `oauth2_profile`, a check), `display_name`, `enabled`, `issuer`, `client_id` (unique with `issuer`), `client_secret` (Fernet ciphertext, write-only), `scopes`, `logout_at_provider`, `created_at`, `updated_at` |
| `identities` | v0.33.0. An outside identity linked to an account, `(issuer, subject)`, never an email: `user_id`, `kind` (`provider` / `trusted_header`), `provider_id` (set exactly for `provider`, a check), `display` (for the Settings list), `linked_at`, `last_used_at`. One per provider per account; one `trusted_header` row per account and per `(issuer, subject)` (partial unique indexes) |
| `known_browsers` | v0.33.0. The new-browser alert's cookie: its SHA-256, `user_id`, `created_at`, `last_seen_at`, `expires_at`. No role in authentication or throttling |
| `auth_config` | v0.33.0. One row (`id` is always 1): `password_sign_in_alerts`, `trusted_header_enabled` (defaults to true; with the four `TRUSTED_ASSERTION_*` variables, what turns header mode on; `disable-sso` sets it false), `alerts_defaulted_at` (when the first enabled provider switched the alerts on, once), `updated_at`. Read on every use, never cached |
| `backup_ledger` | Every archive this Cabinet writes: `name`, `kind`, `created_at`, `mac_recipient`, `mac_digest`, `size`. Here, not in `public`, so no restore can rewrite the record of what came before it |

SQLite tests map `cabinet_auth` away (`schema_translate_map`) and create
both metadatas.

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

share_links ──N:1── sets or checklists (cascade; a collection link has neither)
```

## Tables

### app_settings
Key/value JSON settings: display currency, source toggles, API credentials,
melt cadence, `value_strategy`/`preferred_source` for the blended-value
display, `numista_refresh_days`/`pcgs_auto_refresh` for scheduled refresh,
`comps_enabled`/`numista_sales_enabled` for the sales log,
`backup_schedule`/`backup_retention_days` (v0.30.1; `backup_keep` before
it)/`backup_include_photos`/`backup_last_run`
for in-app backups, `trash_retention_days` for the trash, and
`alert_webhook_url`/`alert_webhook_format`/`heartbeat_url`/`metrics_enabled`
plus the service-written `refresh_last_run`/`alert_state` for alerts and
metrics, `dashboard_layout` (v0.27.0, the customisable dashboard) for
the saved widget layout, written only by `/api/dashboard/layout`, never by
`PUT /api/settings`, and `spot_alerts` (v0.28.0, bullion stack figures: a
list of spot-price thresholds, at most 12) with the service-written
`spot_alert_state` (per threshold, whether it is currently met). From
v0.30.0 the service-written `secrets_cleared` (the keys of stored secrets
cleared because they weren't encrypted with this deployment's key, until
each is saved again) and `backup_key_saved` (the public key of the backup
key the owner said they saved), and from v0.32.0 `share_enabled` (the
share view's switch, off by default), read through
`app/services/app_settings.py` with defaults and env fallbacks. One more
key is not a setting at all: `restore_marker`, written and deleted by
direct ORM during an in-app restore and never read through `get_setting`
(see [backup-restore.md](backup-restore.md#when-it-fails)); a finished
restore leaves none.
The four secrets (`numista_api_key`, `pcgs_api_token`, `alert_webhook_url`,
`heartbeat_url`) are stored encrypted; see [security.md](security.md).

### items
The core record for a single coin, note, or bar or round (or a lot of
identical pieces via `quantity`). Enums are stored as short strings, checked
by the application, not as native postgres enum types.

| Column             | Type          | Notes                                   |
|--------------------|---------------|-----------------------------------------|
| `id`               | uuid PK       |                                         |
| `type`             | enum          | `coin` \| `note` \| `bullion` (v0.31.0); indexed |
| `status`           | enum          | `owned` \| `sold` \| `wishlist`; indexed |
| `country`          | text          | indexed                                 |
| `denomination`     | text          | e.g. "25 cents", "10 dollars"           |
| `year`             | int null      | issue year; indexed; null on an undated piece (`year_nd`), where a given value is the attributed year |
| `year_nd`          | bool          | the piece carries no date                |
| `mint_mark`        | text null     | coins only                              |
| `series`           | text null     | series / variety name                   |
| `variety`          | text null     | die variety, overdate…                  |
| `strike`           | enum          | `business` \| `proof` \| `specimen`     |
| `composition`      | text null     | e.g. "90% silver"                       |
| `weight_g`         | numeric(9,4) null | grams; enables melt value (Phase 3); four decimal places since v0.28.0 (a troy ounce is 31.1035 g) |
| `fineness`         | numeric null  | 0–1, e.g. 0.9000                        |
| `diameter_mm`      | numeric null  | coins                                   |
| `thickness_mm`     | numeric null  | coins                                   |
| `width_mm`         | numeric(7,2) null | notes (and anything not round); coins keep `diameter_mm` |
| `height_mm`        | numeric(7,2) null | notes (and anything not round)          |
| `edge`             | text null     | reeded, plain, lettered…                |
| `shape`            | text null     | round, polygonal…                       |
| `mintage`          | bigint null   | mintage, or print run for a note        |
| `die_axis`         | smallint null | coins: degrees 0–359; `0` medal, `180` coin alignment |
| `struck_calendar`  | text null     | the calendar of a non-Gregorian date as struck: a key of `services/calendars.CALENDARS` (`hijri`, `japanese`…) |
| `struck_year`      | int null      | the year as written on the piece, in that calendar; `year` stays Gregorian |
| `struck_era`       | text null     | `meiji` … `reiwa`; required with `japanese`, null otherwise |
| `grade_id`         | fk → grades   | null if ungraded                        |
| `cert_service`     | text null     | PCGS, NGC, PMG…                         |
| `cert_number`      | text null     | slab certification number               |
| `grade_plus`       | bool          | a "+" grade                             |
| `grade_star`       | bool          | NGC/PMG ★ designation                   |
| `designations`     | json null     | list, e.g. `["DCAM"]`, `["RD"]`, `["EPQ"]` |
| `grade_details`    | text null     | the problem on a details grade          |
| `cac_sticker`      | text null     | `green` \| `gold`                        |
| `pcgs_population`  | int null      | PCGS population at this grade           |
| `pcgs_pop_higher`  | int null      | graded higher                           |
| `population_as_of` | timestamptz null | server-set: when the two figures last changed, or when the PCGS response that supplied them was fetched |
| `serial_number`    | text null     | notes                                   |
| `prefix_block`     | text null     | notes                                   |
| `signatures`       | text null     | notes                                   |
| `issuer`           | text null     | notes: issuing bank or authority        |
| `replacement_note` | bool          | notes: replacement / star note          |
| `charter_number`   | text null     | notes: National Bank Note charter       |
| `bank_city`        | text null     | notes                                   |
| `bank_state`       | text null     | notes                                   |
| `plate_position`   | text null     | notes: plate and position letters       |
| `printer`          | text null     | notes: printing firm (e.g. BEP, De La Rue) |
| `watermark`        | text null     | notes: watermark description             |
| `demonetized_on`   | date null     | coins and notes alike: when it stopped being legal tender |
| `serial_traits`    | text null     | server-set fancy-serial traits, stored comma-wrapped (`,radar,binary,`) so one trait is a `LIKE '%,radar,%'`; null when none. The API returns a list |
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
| `spot_at_purchase` | numeric(14,4) null | the metal's spot price per troy ounce on the day it was bought, in `currency` |
| `spot_at_purchase_source` | text null | server-set: `manual` (typed in) or `auto` (the backfill looked it up) |
| `target_price`     | numeric null  | wish list: the most to pay, in `currency`; kept when the status changes |
| `priority`         | smallint null | wish list: `1` high, `2` medium, `3` low |
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
responses for 7 days; the bullion stack's purchase-day spot lookups
(source `spot_history`) cache for ten years, since a past day's price never
changes. A stale row is used if the upstream fetch fails.

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

### share_links
A read-only public link to the collection, a set, or a checklist (v0.32.0,
migration `0022`; the share view, see [api.md](api.md#sharing)). In
`public`, so backups carry it; it has no key into `cabinet_auth`. An in-app
restore puts the live rows (and `share_enabled`) back after the archive's
database is in place, since a link is an access grant: a revoked or
replaced token never comes back with an older archive. `restore.sh` can't
do that; after a script restore the archive's links are the ones in force.

| Column           | Type                | Notes                                          |
|------------------|---------------------|------------------------------------------------|
| `id`             | uuid PK             |                                                |
| `token_hash`     | text(64)            | unique; SHA-256 hex of the token, never the token |
| `kind`           | text(10)            | `collection` \| `set` \| `checklist`           |
| `set_id`         | fk → sets null      | a set link's target; cascade delete, indexed   |
| `checklist_id`   | fk → checklists null | a checklist link's target; cascade delete, indexed |
| `name`           | text(100)           | the shared page's title                        |
| `show_photos`    | bool                | default true                                   |
| `show_grades`    | bool                | grade, designations, grading service; default true |
| `show_tags`      | bool                | default true                                   |
| `show_notes`     | bool                | default false                                  |
| `show_values`    | bool                | the shown estimate only; default false         |
| `show_certs`     | bool                | the cert number; default false (added to `0022` before release) |
| `created_at`     | timestamptz         |                                                |
| `created_by`     | text(100)           | the admin's username as text                   |
| `last_opened_at` | timestamptz null    | stamped by each manifest request               |
| `opens`          | int                 | manifest requests, default 0                   |

Revoking a link deletes its row (there is no `revoked_at`), and deleting its
set or checklist deletes it too. The spec's single `target_id` became two
columns so each can carry its own foreign key and cascade. Whether any link
works at all is the `share_enabled` setting.

## Notes on design choices

- **UUID primary keys** on user-facing tables keep photo file keys and API
  URLs non-enumerable.
- **Price estimates are append-only**, giving a value history over time rather
  than a single mutable field. Only a value typed in by hand can be deleted
  (v0.29.1); a source's estimates never are.
- **`quantity`** on `items` supports holding multiples of an identical piece
  without duplicate rows; split into separate rows if grades differ.
- **Grades and catalogs are reference tables** so the app can present valid
  options and match against external sources consistently.
