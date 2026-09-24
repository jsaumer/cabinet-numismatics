# API

The service is titled **Cabinet API** in the OpenAPI spec.

The backend exposes a REST API under `/api/`. This document is a
human-readable summary; the authoritative, always-current spec is the
auto-generated OpenAPI documentation served at:

- OpenAPI JSON: `http://localhost/api/openapi.json`

There is no interactive docs page (`/api/docs` is gone since v0.30.0): it
would run a third-party script in the signed-in page. Load the schema into a
viewer of your own instead.

All request and response bodies are JSON unless noted (photo, document, and
import uploads and restore archives are multipart; exports, backups,
document files, and metrics answer files or text).

**Every endpoint needs a credential** (v0.30.0) except these: `GET
/api/health` (just `{"status": ...}` for anonymous callers), `GET
/api/auth/state`, `POST /api/auth/setup`, and `POST /api/auth/login`; the
single sign-on routes (v0.33.0) `GET /api/auth/oidc/start`,
`GET /api/auth/oidc/callback`, and `POST /api/auth/trusted`; and
the share view's `GET /api/share/...` routes (v0.32.0), which need a share
link's token instead, and only while sharing is on (see
[Sharing](#sharing)). A
browser signs in and carries a session cookie; scripts send an API token
(`Authorization: Bearer cabinet_...`). What each route allows is in
[Sign-in and permissions](#sign-in-and-permissions) below. The three
endpoint renames of that release are in the stability policy.

## Stability policy

Until v1.0.0, an endpoint's path, parameters, or response may change in a
minor release when it has to; every such change is announced in
[CHANGELOG.md](../CHANGELOG.md) under the release that makes it, with the
old and new forms. From v1.0.0 on, paths under `/api/` and the fields of
their responses are stable within a major version: nothing is renamed,
removed, or given a new meaning without a new major version. Additions are
not breaking changes: a new endpoint, a new optional parameter, a new field
in a response, or a new value where a field already lists several (a source
name, a status) may arrive in any release, so clients should ignore fields
they don't know. Error messages (`detail`) are for people, not for matching.

Renamed for v0.30.0, the one pass made before 1.0:

| Before | Now |
|--------|-----|
| `POST /api/items/import` | removed; `POST /api/imports` then `.../{upload_id}/run` (the `cabinet` format) is the one import path |
| `POST /api/estimates/refresh-melt` | `POST /api/estimates/refresh?source=melt` |
| `POST /api/items/{id}/estimate?source=` | `POST /api/items/{id}/estimates/auto?source=` |

## Sign-in and permissions

**Credentials.** A session cookie from `POST /api/auth/login` (or from
setup): `__Host-cabinet_session` (`Secure; HttpOnly; SameSite=Lax; Path=/`,
no expiry of its own), or `cabinet_session` without `Secure` when the
deployment sets `AUTH_INSECURE_HTTP`. It ends a day after its last use and
seven days after sign-in. A known-device cookie
(`__Host-cabinet_device`, `SameSite=Strict`, 7 days) lets a browser that
signed in before past the sign-in delays; it authenticates nothing, and
only a password sign-in or confirm issues one. A browser cookie
(`__Host-cabinet_browser`, `SameSite=Lax`, 90 days, v0.33.0), issued on
every sign-in of any method when absent, decides only whether a sign-in
alerts as a new browser; it lifts no throttle and authenticates nothing.
A single sign-on flow cookie (`__Host-cabinet_oidc`, `SameSite=Lax`,
`Path=/`, 10 minutes, encrypted) lives from the start route to the
callback. Each has the bare name without `Secure` under
`AUTH_INSECURE_HTTP`. An API
token is `cabinet_<10 characters>_<43 characters>`, sent only as
`Authorization: Bearer ...`, never in a query string or a cookie. A Cabinet
token that isn't valid is `401` with no fall back to the cookie; any other
`Authorization` value (another proxy's) is ignored.

**Scopes and classes.** Every route has a class:

| Caller | public | read | write | admin |
|---|---|---|---|---|
| Nobody signed in | yes | 401 | 401 | 401 |
| The admin's session | yes | yes | yes | yes |
| `write` token | yes | yes | yes | 403 |
| `read` token | yes | yes | 403 | 403 |
| `metrics` token | yes | 403 | 403 | 403 |

`GET /api/stats/collection` (read) and `GET /api/metrics` (admin) also
accept a `metrics` token; a `read` or `write` token gets `403` on the
metrics. `read` covers every listing and report (items, their values and
where they are kept, photos' metadata, stats, the dashboard layout, the
trash). `write` adds creating, editing, and moving to the trash, and the
lookups that spend Numista or PCGS quota. Admin, session only: settings,
backups and restore, the exports, document files and thumbnails, the alerts
test, saving the dashboard layout, deleting for good, `/api/openapi.json`,
and everything under `/api/auth` that changes the account. The full table,
route by route, is the appendix of
[SPEC_0300](specs/SPEC_0300.md#appendix-route-permissions-v0300).

A fifth class, `share` (v0.32.0), sits outside this table: every route
under `/api/share/` is open to anyone holding a share link, session or
token on the request or not, and only while the admin has switched sharing
on. See [Sharing](#sharing).

**Recent password.** A few admin routes also need the password confirmed
in the last 5 minutes by this session (`POST /api/auth/confirm`); a token
can never have that. Without it they answer `403`
`{"detail": "Confirm your password to continue.", "reauth_required": true}`.
They are: both exports, `GET /api/backup.zip`, `GET /api/backups/{name}`,
`DELETE /api/backups/{name}`, `POST /api/restore/inspect`, `POST
/api/restore/{id}/run`, every `PUT /api/settings`, `POST /api/trash/purge`,
`DELETE /api/trash`, `DELETE /api/items/{id}` when it deletes for good
(`?permanent=true`, or an item already in the trash), `DELETE
/api/photos/{id}`, `PUT /api/photos/{id}/image` (the old files are
deleted), `DELETE /api/documents/{id}`, `DELETE
/api/items/{id}/documents/{id}` when this item is the document's last
holder (the file goes with it), creating or revoking a token, creating,
changing, regenerating, or revoking a share link, changing the sign-in
settings, adding, changing, or removing a sign-in provider, unlinking an
identity, ending another session, and signing out everywhere. On a session
that signed in through a provider that can re-authenticate (see
`confirm_methods` below), the window can also be opened at the provider
with `GET /api/auth/oidc/start?intent=confirm`. Changing the password or the
username takes the current password in the body instead.

A `read` or `metrics` token is refused on any `POST`, `PUT`, `PATCH`, or
`DELETE` before the request body is read (every such route is `write` or
`admin`), except the public setup and sign-in.

**Cross-site requests.** A request carrying the session cookie, whatever
its method, passes only with `Sec-Fetch-Site: same-origin`, or with no such
header and an `Origin` (or a `Referer`) exactly matching an entry of
`PUBLIC_ORIGINS`; otherwise `403 "Cross-site request refused."`.
`Sec-Fetch-Site: none` (an address typed or bookmarked) is accepted only on
`/api/openapi.json` and a document's file. Token requests aren't checked.
Scripts that use the cookie send `Origin`.

**Paths.** A path containing `%` is `400` before anything else, and
anonymous callers get `401` for every path but the public ones below
(unknown ones included), and, while sharing is on, a `GET` or `HEAD` under
`/api/share/`, which passes with no credential looked up (see
[Sharing](#sharing)); signed in, an unknown path is `404`. Responses without their
own `Cache-Control` get `private, no-store`.

| Method | Path | Class | Purpose |
|--------|------|-------|---------|
| `GET` | `/api/auth/state` | public | `{"setup_required": bool, "methods": {"password": true, "providers": [{id, name, preset}], "trusted_header": {"available": true} or null}}`: one entry per enabled provider, read from the database on every call; `trusted_header` is `{"available": true}` when the four `TRUSTED_ASSERTION_*` variables are set and the mode is switched on, else `null`. This route never reads or verifies the request's assertion (v0.33.0) |
| `POST` | `/api/auth/setup` | public | `{code, username, password}`: create the admin; `201` and both cookies, `403` wrong code, `409` already set up, `413` over 8 KiB, `422` a rule broken, `429` too many wrong codes |
| `POST` | `/api/auth/login` | public | `{username, password}`: `200 {username, previous_sign_in_at, failed_since_previous}`, the session and device cookies, and the browser cookie when absent; `401`, `413`, `429` and `503` with `Retry-After` |
| `POST` | `/api/auth/logout` | admin | End this session; `204`, cookies cleared, `Clear-Site-Data: "cache"`. A session from a provider with "sign out there too" on, whose discovery names an end-session endpoint, gets `200 {"redirect": <that URL with client_id and post_logout_redirect_uri={origin}/login>}` for the browser to follow |
| `GET` | `/api/auth/me` | read | `username`, `role`, `via` (`session` or `token`), `scope`, `confirmed_until`, `auth_method` (`password`, `oidc`, `trusted_header`; null for a token), `provider_id` (the provider an `oidc` session signed in through, else null), `confirm_methods` (`["password"]`, plus `"provider"` on an `oidc` session whose provider can re-authenticate), and, once after a single sign-on and then null, `failed_since_previous` and `previous_sign_in_at` |
| `POST` | `/api/auth/confirm` | admin | `{password}`: open the 5-minute window (`204`); a wrong password is `403` |
| `POST` | `/api/auth/password` | admin | `{current_password, new_password}`: ends every other session, every known device, and every token; `200 {revoked_tokens}` and a new cookie |
| `POST` | `/api/auth/username` | admin | `{current_password, username}`; `204` |
| `GET` | `/api/auth/sessions` | admin | Live sessions: `id`, `created_at`, `last_seen_at`, `address`, `user_agent`, `current` |
| `DELETE` | `/api/auth/sessions/{id}` | admin | End one (recent password unless it is this one, which signs out) |
| `DELETE` | `/api/auth/sessions` | admin, recent password | Sign out everywhere, this session and every known device included |
| `GET` | `/api/auth/tokens` | admin | Live tokens, never their secrets |
| `POST` | `/api/auth/tokens` | admin, recent password | `{name, scope, days}`: `201`, the `token` shown this once. `read` and `write` last `1` or `7` days; a `metrics` token may take `null`, never expiring. Names are unique among live tokens, at most 50 |
| `DELETE` | `/api/auth/tokens/{id}` | admin, recent password | Revoke |
| `GET` | `/api/auth/audit` | admin | The audit log, newest first: `?before=<id>&limit=` (at most 200) |
| `GET` | `/api/auth/photo` | read | `204`: nginx asks this before serving a photo (a `metrics` token and `Sec-Fetch-Site: cross-site` get `403`) |
| `GET` | `/api/auth/oidc/start` | public | `?provider=<id>&next=<path>&intent=login\|link\|confirm`: `302` to the provider with the flow cookie. `404` for an unknown or disabled provider; `link` needs a session inside its recent-password window (`401`, or the `reauth_required` `403`); `confirm` needs a live `oidc` session that signed in through this provider, which must be able to re-authenticate (`403` with `code` `confirm_identity` or `not_qualified`). `next` is a path on this origin, never `/api/`, `/photos/`, or `/s/` (anything else becomes `/`). A provider that can't be reached is a `303` to the failure page below with `provider` |
| `GET` | `/api/auth/oidc/callback` | public | The provider's redirect back; the gate looks up no credential for it. Always clears the flow cookie and answers `303`: a sign-in to `next` with the session and browser cookies (never a device cookie), or `/login?error=<code>`; a link to `/settings/signin?linked=<provider id>` or `/settings/signin?error=<code>`; a confirm to `next`, with `confirm_error=<code>` added on failure. Codes: `cookie`, `expired`, `state`, `navigation`, `provider`, `denied`, `token`, `profile`, `unlinked`, `session`, `already_linked`, `subject`, `confirm_identity`, `not_qualified`. Failures are audited (`sso_sign_in_rejected`, with the reason and any `sub`, never a token or code) and slowed per address in a map of their own (`429` with `Retry-After` past 20 in 15 minutes, or 300 a minute from all addresses); a refusal at the provider (`denied`) is not counted |
| `GET` | `/api/auth/signin-config` | admin | `providers` (`id`, `preset`, `kind`, `display_name`, `enabled`, `issuer`, `client_id`, `scopes`, `logout_at_provider`, `has_secret`, `credentials_failing`, `linked`; never a secret), `identities`, `trusted_header` (`configured`, `enabled`, `header_name` and `issuer` as the deployment sets them or null, and `link_ready`: the header is present on this very request, checked without reading or verifying it), `password_sign_in_alerts`, `presets` (`name`, `kind`, `issuer` or null, `needs_tenant`, `needs_issuer`, `scopes`), and `callback_urls` (one per `PUBLIC_ORIGINS` entry) |
| `PUT` | `/api/auth/signin-config` | admin, recent password | `{password_sign_in_alerts?, trusted_header_enabled?}`: the answer is the new configuration; switching the trusted-header mode back on after `disable-sso` is only done here |
| `POST` | `/api/auth/providers` | admin, recent password | `{preset, display_name, client_id, client_secret?, issuer?, tenant?, scopes?, logout_at_provider?, enabled?, dry_run?}`: `201` with the provider and `callback_urls`. `issuer` only for `custom` (https), `tenant` only for `microsoft`; `422` otherwise. `dry_run: true` fetches the discovery document only and saves nothing: `{ok, issuer, claims_supported_auth_time, prompt_login}`, or `{ok: false, issuer, error}`. `409` for an issuer and client id already configured, a ninth provider, or two `PUBLIC_ORIGINS` entries on one host |
| `PATCH` | `/api/auth/providers/{id}` | admin, recent password | Any of the same fields but `dry_run`; a `client_secret` replaces the old one and is never read back. `issuer`, `client_id`, `preset` (and so the kind) are `409` while an identity is linked through it. `enabled: false` ends the sessions that came through it |
| `DELETE` | `/api/auth/providers/{id}` | admin, recent password | `204`: the provider and its linked identities go, after the sessions that came through them end |
| `DELETE` | `/api/auth/identities/{id}` | admin, recent password | `204`: unlink; the sessions that came through it end |
| `POST` | `/api/auth/trusted` | public | Sign in with the gateway's assertion (the trusted-header mode, v0.33.0). No body (an empty JSON object is fine; at most 8 KiB); refused from another site (`Sec-Fetch-Site` `cross-site` or `same-site`). `404 {"detail": "Not found"}` unless the four `TRUSTED_ASSERTION_*` variables are set and the mode is switched on. The header `TRUSTED_ASSERTION_HEADER` names must carry one JWT signed by a key at `TRUSTED_ASSERTION_JWKS_URL` (never a URL the request names), with that `iss`, exactly that `aud`, an `exp` (60 s leeway), and a `sub`; `RS256`, `PS256`, `ES256`, or `EdDSA` only. `200 {"username"}` with the session and browser cookies (never a device cookie), ending any session the browser held; `403 {"detail", "code": "assertion"}` for an assertion that doesn't verify (a repeated header included) or `"unlinked"` for an identity nobody linked, both audited (`sso_sign_in_rejected`) and slowed per address with the provider callbacks (`429` with `Retry-After`); `502 {"code": "provider"}` when the gateway's keys can't be fetched (sign in with the password) |
| `POST` | `/api/auth/identities/trusted_header` | admin, recent password | Link the identity the current request's assertion names (verified as above) to the signed-in account: `201` with the identity (`id`, `kind` `trusted_header`, `issuer`, `subject`, `display`); `404` while the mode is off; `403` with `code` `assertion`, or `subject` for a `sub` holding `@` or equal to the assertion's `email` or `preferred_username`; `409` `already_linked` when the account already has one or another account holds it. Audited and alerted (`identity_linked`) |

Photos themselves (`/photos/{file_key}`, `/photos/{thumb_key}`) are files
nginx serves after that check: the same credentials as a `read` route, the
check's `401` or `403` otherwise (before nginx looks for the file, so a
missing photo tells a stranger nothing), `503` with `Retry-After: 5` while
the backend can't answer, and `Cache-Control: private, no-store`.

Codes: `401` for a missing, invalid, expired, or revoked credential; `403`
for a valid one that isn't allowed; `429` with `Retry-After` when sign-in
is being slowed down. Sign-in delays grow per username (after 5 failures)
and per address (after 20), up to a minute, and never lock the account.

## Items

| Method   | Path                      | Purpose                             |
|----------|---------------------------|-------------------------------------|
| `GET`    | `/api/items`              | List items (filter/paginate)        |
| `POST`   | `/api/items`              | Create an item                      |
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
(`business`/`proof`/`specimen`), `country`, `year`, `year_min`/`year_max`
(none of the three match an undated item's null year), `nd` (`true` only
undated, `false` only dated), `tag`, `set_id`, `grade_min`/`grade_max`
(grade rank 1–70),
`value_min`/`value_max` (the newest estimate, whatever the value strategy),
`q` (substring match over notes/series/variety/country/denomination/cert and
serial numbers/prefix/issuer/charter number/bank city/printer/catalog
refs/tags),
`fancy=true` (notes with any fancy-serial trait), `serial_trait` (one trait
key from `/api/reference/serial-traits`; an unknown one is 422),
`target_reached=true` (see the wish-list fields below), `metal` (`gold`,
`silver`, `platinum`, `palladium`, or `none`; P11, v0.31.0, evaluated in
Python with the same detector the metal breakdown uses, not a column, since
a few hundred pieces need no index for it; an unknown value is 422),
`limit` (default 50,
1–500), `offset`, `sort` (`created_at`, `year`, `country`, `denomination`,
`acquisition_date`, `acquisition_price`, `priority`, `target_price`,
`value`, `pcgs_pop_higher`, or `grade`; `-` prefix for descending; default
`-created_at`; anything else is 422; with `priority`, `target_price`,
`year`, `value`, and `pcgs_pop_higher`, items without a value come last in
either direction). `value` sorts by the newest estimate, the same
subquery the value filters use, not the blended `value_strategy` figure.
The response is
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

**Year, or ND.** `year` is nullable: a piece with no date on it ticks
`year_nd` and may leave `year` empty, or give the year it's attributed to
("ND (1951)"). A missing `year` without `year_nd` is 422 ("Enter the year,
or tick ND for a piece with no date."), and `year: 0` is always 422 ("There
is no year 0. Tick ND for a piece with no date."); `PATCH` checks the rule
against the item as it will be after the patch. **Bullion is exempt**
(v0.31.0): a bar may leave both `year` and `year_nd` empty. Every response carries a
read-only `year_label` (`"1922"`, `"ND"`, or `"ND (1922)"`), used everywhere
a year is shown; `Item.label` ends with it. `year_nd` is not accepted in a
bulk `set` (a bulk `year` stays as it is, and can't be cleared without it).

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

**Bullion stack fields (v0.28.0, roadmap Phase 7, P7)**: `spot_at_purchase`
(above 0), the metal's spot price per troy ounce on the day the piece was
bought, in the item's own `currency`. Not accepted in a bulk `set` (it's per
piece, and looked up per piece). The response adds `spot_at_purchase_source`
(`manual` when a client sent a value, `auto` when
`POST /api/stack/backfill` or the hourly loop filled it, `null` when empty),
server-set and never accepted from a client; clearing `spot_at_purchase`
clears its source too. Also read-only: `fine_oz` (fine troy ounces:
`weight_g * fineness * quantity / TROY_OUNCE_G`, null unless the composition
names a precious metal and both weight and fineness are known, which is also
what puts a piece in the stack) and `premium_paid_pct` (how far the cost
basis ran over `fine_oz * spot_at_purchase`, as a percentage in the item's
own currency; null without a purchase-day spot price or a cost). See
[Bullion stack](#bullion-stack) below.

**Note details (v0.29.0)**: `width_mm` and `height_mm` (above 0, up to 2000;
for notes and anything else not round, coins keep `diameter_mm`), `printer`
(up to 200 characters), `watermark` (up to 200), and `demonetized_on` (a
date; coins and notes alike). None of the five are accepted in a bulk
`set` (they're per piece). "Fill from Numista" fills them for a banknote
type from the catalogue's `size`/`size2`, `printers`, `watermark`, and
`demonetization` fields, when present.

**Bullion (v0.31.0, roadmap Phase 7, P11)**: a third item
`type`, `bullion` ("Bar or round" in the UI), alongside `coin` and `note`.
The year-or-ND rule is exempt for it: a bar may have both `year` and
`year_nd` empty, and its `year_label` is then `""` rather than `"ND"` (a bar
needs no "ND" convention). `Item.label` for bullion is `issuer` (falling
back to `country`), then `denomination`, then the year if there is one, with
no mint mark: `"PAMP Suisse 1 oz silver bar"`. Fancy-serial traits are never
computed for a bullion item (a bar's serial isn't "radar" or "solid"):
`serial_traits` is always empty, and changing an item's `type` to `bullion`
clears it. `GET /api/items?type=` accepts `bullion`, and it can be set in a
bulk `set`. `GET /api/stats/collection`'s `counts` gains `bullion` (owned
items of that type; `coins` and `notes` keep their own meaning), and
`by_type` in `/api/stats/breakdowns` and `cabinet_items{type=...}` in
`/api/metrics` pick it up automatically. `GET /api/numista/search` accepts
`category=exonumia`, and filling in or importing an exonumia type maps it to
`bullion` when it reads as a bar, round, or ingot (never a token or medal,
which is refused); see Numista catalogue lookup and Imports below. The item
form's own Add/edit UI (a Metal select, a g/oz weight switch, a suggested
product name) is frontend behaviour, not part of this API.

The CSV and Excel exports, and both ways of importing them back, carry
`die_axis`, `struck_calendar`, `struck_year`, `struck_era`,
`pcgs_population`, `pcgs_pop_higher`, `charter_number`, `bank_city`,
`bank_state`, `plate_position`, `target_price`, `priority`, `spot_at_purchase`
(v0.28.0), and (v0.29.0) `width_mm`, `height_mm`, `printer`, `watermark`, and
`demonetized_on`. An export from an older version imports as before.
`serial_traits`, `population_as_of`, and `spot_at_purchase_source` are not
exported: the import recomputes them (a `spot_at_purchase` cell always
imports as `manual`).

The export also carries `year_nd` (`true` or empty like the other flags,
next to `year`; the
year cell is empty when null). Every import path (the Cabinet CSV, a
mapped spreadsheet, a Numista export file or account, OpenNumismat) reads a
year cell of `ND`, `N.D.`, `n.d`, `undated`, `ND (1951)`, `ND(1951)`, or
`(1951)` as `year_nd = true` with the parenthesised year attributed, if
any; a cell with no year at all, or an older export with no `year_nd`
column, is no longer a rejected row: it imports as ND. A Numista export row
that gives only a year range (its way of marking an undated issue) becomes
ND with the range's first year attributed.

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
original. **The original is stored re-encoded, without its metadata**
(v0.32.0): the orientation is applied, then every EXIF block (GPS, camera,
dates), XMP, IPTC, comment, and PNG text chunk is dropped; only the colour
profile (and a palette's transparency) is kept, and from v0.32.2 a profile
only when it is shaped like one. A JPEG is written at
quality 95, so the stored file is not byte for byte the upload, and an
animated WebP or PNG keeps its first frame only. The thumbnail is written
the same way. Photos stored before v0.32.0, thumbnails included, are
re-encoded once, in the background, on the first start (see
[backup-restore.md](backup-restore.md#photo-metadata)); a file that can't
be decoded is left as it is, which is why the share view checks each file
before sending it from disk. The first photo uploaded becomes the primary image. Responses
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
| `DELETE` | `/api/items/{id}/estimates/{estimate_id}` | Delete a value that was typed in |
| `POST` | `/api/items/{id}/estimates/auto` | Produce an automatic estimate (`?source=`) |
| `POST` | `/api/estimates/refresh`      | Re-run one source's stale estimates now (`?source=melt`) |

Estimates are append-only: each `POST .../estimates` adds a timestamped record
(`estimated_value`, `currency`, `source`, optional `confidence` 0–1, optional
`note` up to 500 characters), never overwriting history. The one exception is
a value typed in by hand, which `DELETE .../estimates/{estimate_id}` removes
(`204`): a mistake shouldn't have to stay in the chart. An estimate from a
price source (`melt`, `numista`, `pcgs`, `comps`) is `409`, and one that
belongs to another item is `404`. Every estimate in a
response carries `id`, `item_id`, `source`, `estimated_value`, `currency`,
`confidence`, `sample_size`, `fetched_at`, and `details`: the provenance an
automatic source recorded (see [price-sources.md](price-sources.md)),
`{"note": …}` for a manual entry given a note, or `null`.
`POST .../estimates/auto` runs one automatic adapter, chosen with `?source=`: `melt` (the default: spot
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

A Numista estimate tries the type's matching issues in turn, best first (up
to four), since a type can list more than one issue for the same year (a
replacement note beside the regular one). `details` gains `issue_comment`,
`issue_reference`, `issue_nd`, `candidates_tried`, and `year_mismatch`
(present and true only when no issue matched the item's year and a type's
single issue stood in for it). The item page's provenance line shows
"Priced as: {reference}, {comment}" when Numista gave them. An item with no
matching issue at all is 422 ("Numista lists no {year or ND} issue for
N#{id}"); one where nothing tried had a priced grade is 422 ("Numista has
no priced grade for any of the {n} {year or ND} issue(s) of N#{id}").

Every new estimate, manual or automatic, scheduled refreshes included, is
checked against a wish-list target: for an item with status `wishlist` and a
`target_price`, an estimate in the item's own currency at or under the
target sends one event through the alert webhook, unless the estimate before
it was already there. See [monitoring.md](monitoring.md).

`POST /api/estimates/refresh?source=melt` answers `updated`, `skipped`, and
`failed`, or 422 when melt is switched off. `source` is required, and only
`melt` is accepted for now: any other value is 422 ("Only melt can be
refreshed by hand for now."). An in-process scheduler re-runs stale melt
estimates every 12h (estimates older than `REESTIMATE_DAYS`, default 7; `0`
disables) and, since P11 (v0.31.0), also takes owned pieces that qualify for
melt and have no estimate at all yet (a new bullion piece gets a value
without waiting on the 12h loop or a button press); a melt refresh never
supersedes an item whose latest estimate is manual, or from another source.
**Saving an item** (create, update, "Add a run", and an import) also adds a
melt estimate itself, from the cached spot price only, when the piece
qualifies (metal, weight, fineness) and the cache for that metal is not
stale: no network call ever happens on the save path (an absent or stale
cache means nothing is added; the scheduled refresh above catches it later).
It's skipped, too, when the piece already has a melt estimate with the same
inputs (metal, weight, fineness, quantity), so an edit that doesn't touch any
of those adds no duplicate row. The same 12h loop also refreshes Numista and/or PCGS when their own
cadence is switched on in Settings (each off by default), independently of
melt and of whichever source currently wins an item's overall-latest estimate,
since `value_strategy` may prefer or average a source that isn't "latest"
right now.

## Stats

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| `GET`  | `/api/stats/collection`  | Totals in a display currency (`?currency=`)    |
| `GET`  | `/api/stats/breakdowns`  | Owned items grouped by country/type/decade/grade/tag + acquisitions by year (`?tag=`, `?set_id=`) |
| `GET`  | `/api/stats/gains`       | Per-item unrealized (owned) and realized (sold) gain/loss |
| `GET`  | `/api/stats/value-history` | Month-end collection value over time (`?months=`, default 24, 1–120) |
| `GET`  | `/api/stats/notes-by-signature` | Owned notes grouped by series and signature pair |
| `GET`  | `/api/stats/quality`     | Certified vs. raw owned items, by count and value, plus a breakdown by grading service (`?currency=`) |
| `GET`  | `/api/stats/value-spread` | Min/median/max/mean of owned items' shown values, and the share held by the top 10% (`?currency=`) |
| `GET`  | `/api/stats/data-health` | Owned items missing a photo, grade, cost, value, weight, storage, or reference |
| `GET`  | `/api/stats/showcase`    | Piece of the day, oldest, newest, and pieces acquired on this day in an earlier year (`?currency=`) |

`/collection` answers `currency`, `counts` (`total`, `owned`, `sold`,
`wishlist`, and `coins` / `notes` / `bullion` (v0.31.0), which count owned
items only),
`cost_basis` (owned items, fees included), `estimated_value` (each owned
item's shown value under `value_strategy`) with `estimated_items` (how many
contribute), `unrealized_gain` (owned items with both a cost and a value),
and `realized_gain` (sold items, net of fees). A count is a row, not its
`quantity`. [monitoring.md](monitoring.md) builds a Homepage tile from this
endpoint. `/breakdowns` answers `by_country`, `by_type`, `by_decade`,
`by_grade`, `by_tag`, `by_metal` (v0.29.0: `detect_metal` on the
composition, title-cased, or `Other` for none), and `acquisitions_by_year`,
each a list of `key`,
`count`, `cost_basis`, and `estimated_value`; `?tag=` and `?set_id=` scope
every breakdown to items carrying that tag or belonging to that set (an
unknown tag or set gives empty breakdowns, not an error); `/gains` answers `unrealized`
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

Four more endpoints (v0.29.0, `services/insights.py`, behind the new
dashboard widgets): owned items only, trashed already hidden by the ORM.

- **`/quality?currency=`**: `{"currency", "owned", "certified": {"items",
  "value"}, "raw": {"items", "value"}, "by_service": [{"key", "count",
  "estimated_value"}], "graded", "ungraded"}`. "Certified" means a cert
  service or number is set; `by_service` groups certified items by
  `cert_service`, highest value first. Money follows the stats currency
  rule.
- **`/value-spread?currency=`**: `{"currency", "items", "min", "median",
  "max", "mean", "top_share_pct"}` over owned items' shown value (the same
  `resolve_display_value` the dashboard totals use). `top_share_pct` is the
  share of total value held by the most valuable 10% of priced pieces (at
  least one); every field is `null` when no owned item has a value.
- **`/data-health`**: `{"owned", "checks": [{"key", "label", "count",
  "items": [{"id", "label"}]}]}`. Checks, always in this order: `no_photo`,
  `no_grade`, `no_cost`, `no_value` (no estimate at all), `no_weight` (a
  detected precious metal with no weight or fineness to melt-price it),
  `no_storage`, `no_reference` (no catalogue reference). `items` lists the
  first 5 matching items; `count` is the true total. Takes no `?currency=`:
  it counts items, not money.
- **`/showcase?currency=`**: `{"piece_of_the_day", "oldest", "newest",
  "on_this_day": [...]}`, each piece `{"id", "label", "year_label",
  "thumb_key", "photo_key", "value", "currency", "acquisition_date"}` or
  `null`. Piece of the day is chosen by hashing today's calendar date over
  owned items that have a photo (falling back to every owned item when none
  do), so it is the same piece all day and needs no storage of its own.
  Oldest is the smallest non-null `year` among owned items; newest is the
  latest `acquisition_date`, falling back to `created_at` when that's
  unset. "On this day" lists owned items whose acquisition month and day
  match today's, from an earlier year.

The dashboard and the printable insurance report (`/report` in the UI;
export to PDF via the browser's print dialog) are built on these endpoints.

## Dashboard

| Method   | Path                    | Purpose                                  |
|----------|-------------------------|-------------------------------------------|
| `GET`    | `/api/dashboard/layout` | The dashboard's widget layout            |
| `PUT`    | `/api/dashboard/layout` | Save a layout                            |
| `DELETE` | `/api/dashboard/layout` | Forget the saved layout (back to default) |

A layout is `{"version": 1, "widgets": [...]}`, plus `is_default` on the
response. A widget is `{"id", "type", "size", "title", "options"}`: `id` is
1 to 36 characters of `a`-`z`, `0`-`9`, and `-`, unique in the layout; `size`
is `full`, `half`, or `third`; `title` is an optional override (max 80
characters, `null` for the widget's own); `options` are per type, below. A
layout holds at most 40 widgets.

`GET` is **lenient**: a widget of a type this build no longer knows is
dropped silently, a missing option takes its default, and an invalid stored
value is replaced by its default, so a release that retires a widget or
narrows an option never breaks the page. Nothing saved yet answers the
built-in default layout with `is_default: true`. A layout saved by an older
Cabinet is migrated forward on read.

`PUT` takes `{"widgets": [...]}` and is **strict**: a `422` names the
widget's `id` and, for a bad option, the option's name. It rejects an
unknown type, an invalid size, a duplicate or malformed id, more than 40
widgets, a title over 80 characters, or an option value outside its
choices, range, or type.

`DELETE` removes the saved layout and returns the default, same shape as
`GET`.

The layout is stored under the `dashboard_layout` key in `app_settings` (see
[data-model.md](data-model.md)), so it is carried by backups, but it is
**not** part of `GET`/`PUT /api/settings`: it has its own endpoints because
it changes far more often and in a different shape.

**Widget types and options** (unlisted options take the default in
parentheses):

| Type | Options | Default size |
|---|---|---|
| `setup` | none | full |
| `value_summary` | none | full |
| `value_history` | `months`: 12, 24, 60, or 120 (24) | full |
| `breakdown` | `dimension`: `country`, `type`, `decade`, `grade`, `tag`, `metal`, `acquisition_year` (`country`); `measure`: `value`, `count`, `cost` (`value`); `top_n`: 3-20 (8); `tag`: a tag name or `null` (`null`); `set_id`: a set id or `null` (`null`) | third |
| `notes_by_signature` | none | full |
| `unrealized_movers` | `top_n`: 3-25, best and worst each (5) | full |
| `realized_gains` | `top_n`: 3-50 (20) | full |
| `counts` | none | third |
| `recent_additions` | `count`: 3-20 (6) | half |
| `wishlist` | `mode`: `priority`, `reached` (`priority`); `count`: 3-20 (6) | half |
| `fancy_serials` | `count`: 3-20 (6) | half |
| `checklists` | `count`: 3-20 (6) | half |
| `stack` | `metal`: `all`, `gold`, `silver`, `platinum`, `palladium` (`all`); `tag`: a tag name or `null` (`null`) | half |
| `pricing_coverage` | none | third |
| `stale_estimates` | `days`: 7, 30, 90, or 365 (30); `count`: 3-20 (6) | half |
| `source_disagreements` | `count`: 3-20 (5) | half |
| `estimate_accuracy` | none | half |
| `backup_status` | none | third |
| `alerts_status` | none | third |
| `signin_status` | none | third |
| `market_data` | none | third |
| `trash` | `count`: 3-20 (5) | third |
| `most_valuable` | `count`: 3-20 (5) | half |
| `piece_of_the_day` | none | third |
| `oldest_piece` | none | third |
| `newest_acquisition` | none | third |
| `on_this_day` | none | third |
| `photo_mosaic` | `count`: 6-30 (12) | half |
| `certified_share` | none | third |
| `value_spread` | none | third |
| `population_highlights` | `count`: 3-20 (5) | half |
| `data_health` | none | half |

`breakdown`'s `top_n` trims only the dimensions sorted by size (`country`,
`type`, `grade`, `tag`) into an "Other" bucket; `decade` and
`acquisition_year` run in time order and keep every bucket.

The default layout reproduces the dashboard as it was before this feature:
`setup`, `value_summary`, `value_history` (24 months), five `breakdown`
widgets (country/value, tag/value, decade/count, acquisition_year/count,
grade/count), `notes_by_signature`, `unrealized_movers`, `realized_gains`,
in that order, 11 widgets in all. The ten "group C" types added in v0.29.0
(`most_valuable` through `data_health`, above) are not in the default
layout; add them from "Edit dashboard".

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
| `GET`    | `/api/reference/historic-spot` | A metal's spot price on a past day (see [Bullion stack](#bullion-stack)) |

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
or `nd` (an undated candidate with no year matches undated items with no
year) (+ `mint_mark`, blank meaning none), `cert_number`, and `ref`
(repeatable, `catalog:code`), plus `exclude` (the item being edited), and
answers up to
ten items that match on any of them, each with `id`, `label`, `grade_label`,
`status`, `in_trash`, and the `reason` (`same cert number`, `same pcgs
reference`, `same country, denomination, year, and mint mark`). Matching
ignores case and spacing; trashed items are included and listed last. With
nothing to go on it answers `[]`. The import preview runs the same check
and notes lookalikes in a row's `messages`.

## Add a run

`POST /api/items/run` takes `type_id` (a Numista type), `issues` (1–200 of
`{year, nd, mint_mark, mintage}`; `year` is optional but `nd` must be true
when it's empty, the same year-or-ND rule as an item), `shared` (`status`,
`grade_id`, `quantity`, `acquisition_date`, `acquisition_price` and
`acquisition_fees` per item, `currency`, `acquired_from`, `storage_location`,
`set_id`, `tags`, `notes`), and `skip_owned` (default `true`). Each item gets
the type's fields and catalogue references as "Fill from Numista" would,
plus the issue's year, `year_nd`, mint mark, and mintage: an undated issue
with no year makes an ND item with no year, an undated issue with a year
makes "ND (year)". Issues already owned (same Numista number, year, and
mint mark, `None` included) and repeats within the request are skipped.
Answers `201` with `created`, `skipped`, and `item_ids`; everything is one
transaction. Needs a Numista API key (`422`); an unknown type is `404`, an
unreachable Numista `502`, and an issue that doesn't validate `422`, naming
the year (or `ND`) and field.

## Bullion stack

Roadmap Phase 7, P7. The stack is owned, untrashed items with a detected
precious metal (gold, silver, platinum, palladium), a `weight_g`, and an
`effective_fineness`; that's the same set melt value can price.

| Method | Path                              | Purpose                                     |
|--------|-----------------------------------|----------------------------------------------|
| `GET`  | `/api/stack`                      | Fine ounces, melt value, cost, gain, and premium, by metal and by item |
| `POST` | `/api/stack/backfill`             | Look up purchase-day spot for pieces that qualify and have none (at most 50) |
| `GET`  | `/api/reference/historic-spot`    | A metal's spot price per troy ounce on a past day |

`GET /api/stack?currency=&tag=&set_id=` scopes to a tag or a set (default:
everything that qualifies) and answers all money in one currency (the
app-wide display currency unless `currency` overrides), converted at the
cached daily rates exactly as `/api/stats/collection` does: an amount with no
rate is left out of the money figures and counted in
`excluded_other_currency`, but its ounces always count, and each item's own
`spot_at_purchase` stays in its own currency (`items[].converted` says
whether its other money was converted). It answers:

- `metals`: one row per metal that has ounces, with `items` and `pieces`
  (quantity summed) counted, `fine_oz` and `fine_g`, the current
  `spot_per_oz` (`null` when the spot price can't be had; a metal without one
  still lists its ounces) with `spot_fetched_at` and `spot_stale`,
  `melt_value` (fine ounces × spot), `cost_basis` and `costed_oz` (the
  ounces of pieces that have a cost: uncosted pieces count toward `fine_oz`
  but not `cost_basis`/`costed_oz`), `cost_per_oz` (cost basis ÷ costed
  ounces, **which is also the break-even spot price**), `gain` and
  `gain_pct` (melt value of the costed ounces less their cost), and
  `premium_paid_pct` (the same ratio as the item field, below, but summed
  over the pieces whose purchase-day spot is known, in the report currency)
  with `premium_known_oz` (how many of the metal's ounces that covers; `null`
  when none do).
- `totals`: `melt_value`, `cost_basis`, `gain` across every metal, and
  `fine_oz_by_metal`.
- `items`: one row per piece, sorted by metal then `fine_oz` descending:
  `item_id`, `label`, `metal`, `quantity`, `fine_oz`, `cost_basis`,
  `cost_per_oz`, `spot_at_purchase` and `spot_at_purchase_source` (in the
  item's own `currency`), `premium_paid_pct`, `melt_value`, `gain`, and
  `converted`.
- `missing_spot`: pieces eligible for the purchase-day-spot backfill.
  `skipped`: pieces with a detected metal but no weight or fineness (so
  they're not in `metals`/`items` at all); `skipped_items` (P11, v0.31.0)
  lists them: `item_id`, `label`, and `missing` (`"weight"`, `"fineness"`, or
  `"weight and fineness"`). `history_start`: the earliest date the
  purchase-day lookup covers (`2024-03-02`).

`POST /api/stack/backfill` looks up the purchase-day spot for eligible
pieces (in the stack, no `spot_at_purchase` yet, an `acquisition_date` on or
after `history_start` and before today, and a cost basis above 0), at most
50 per call; a value typed in by hand is never overwritten. Answers
`{"filled", "failed", "remaining"}`. The same lookup, at most 20 items, runs
in the hourly background loop.

`GET /api/reference/historic-spot?metal=silver&date=2025-01-15&currency=USD`
answers `{"metal", "date", "currency", "per_oz", "source"}`. It's a past day
only: before `2024-03-02` or today or later is `422` with a plain reason (use
the current spot price for today; type the figure by hand for an earlier
purchase), an unknown metal or currency is `422`, and both source hosts
failing is `502`. See [price-sources.md](price-sources.md) for where the
price comes from and why.

## Numista catalogue lookup

| Method | Path                         | Purpose                                          |
|--------|------------------------------|--------------------------------------------------|
| `GET`  | `/api/numista/search`        | Search the catalogue: `q` (2–100 chars), optional `category` (`coin`/`banknote`/`exonumia`) |
| `GET`  | `/api/numista/types/{id}`    | A type as fillable item fields, catalogue refs, and issues |

Both need a Numista API key in Settings (422 without one) and answer 502 when
Numista is unreachable or the quota is exhausted; an unknown type is 404.
Search returns `count` and up to 20 `results` (`type_id`, `title`, `category`,
`issuer`, `min_year`, `max_year`, `thumbnail`). A type returns `type_id`,
`title`, `url`, `category`, and `fields` keyed like the item payload: `type`,
`country`, `denomination`, `series`, `composition`, `fineness`, and `year`
when the type has a single year (left out, with `year_nd: true`, when every
issue is undated); coins add `weight_g`, `diameter_mm`,
`thickness_mm`, `shape`, and `edge`; notes add `issuer` (the issuing bank).
Only values Numista has are present, trimmed to the item schema's limits.

**Exonumia (v0.31.0)**: an `exonumia` type maps to `type: "bullion"` when
its object type is a bar or round (`object_type.name` of `Bars`, `Rounds`,
`Ingots`, or `Bullion`, or `object_type.id` 36; confirmed against the live
API on 22 September 2026). `denomination` comes straight from the title
(there is no face value to read), `issuer` (the item's "Refiner or mint"
field) is the first of the type's `mints` (PAMP on a PAMP bar), `country`
is Numista's issuer, and `size`/`size2` fill `width_mm`/`height_mm` rather
than a diameter. Any other exonumia (a token, a medal, or a "Collector
coins" piece with a face value) is refused with 422: "Cabinet takes bars
and rounds from Numista's exonumia, not tokens or medals." Search hits in
that category carry `object_type` (the name) so a client can show it.
`catalog_refs` holds `numista:N#<id>` and the type's other references
(`km:KM#273`, `pick:Pick#79a`…); `issues` lists `year` (null for an undated
issue), `nd`, `mint_letter`, `mintage`, `comment`, `reference` (the issue's
own catalogue references, e.g. `"P# M22a"`, telling apart two issues of the
same year), and `owned` (an owned item already carries this type, year, and
mint mark). Responses are cached for 7 days in `source_cache` (the
longest Numista's API licence allows), issues shared with Numista pricing.

## PCGS cert lookup

| Method | Path                     | Purpose                                              |
|--------|--------------------------|------------------------------------------------------|
| `GET`  | `/api/pcgs/cert/{cert}`  | A PCGS-graded coin as item fields ready to fill in   |

Needs a PCGS API token, whether or not the PCGS price source is on (`422`
without one, or when PCGS has no such cert; `502` when PCGS can't be
reached). `cert` is 1 to 20 letters, digits, and dashes (anything else is
`422`, so no cert ever needs encoding in the path), and anything but its
digits is dropped. Answers `cert`, `pcgs_number`, `name`,
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
  attempt; every `POST /api/items/{id}/estimates/auto` and scheduled refresh
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
| `DELETE` | `/api/items/{id}/documents/{doc_id}`     | Remove it from one item; from its last item the file goes too, which needs the admin and a recent password |
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
private, no-store`, a `Content-Disposition` carrying the filename (RFC
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

`POST /api/items/{id}/estimates/auto?source=comps` takes the median of the included
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
keyed by the exported `id`, and a duplicate when that id is still here,
trash included; this is the one way to import a Cabinet export, since
v0.30.0 removed `POST /api/items/import`), `spreadsheet` (any
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

**Bullion exonumia (v0.31.0)**: the Numista account import and the
`numista_file` export-file import both read an exonumia type the same way
the fill route does, mapping it to `type: "bullion"` when it reads as a bar,
round, or ingot; a token or medal is still skipped, with an error message on
its row. The account import now looks catalogue types up for exonumia items
too (it used to skip them), so telling a bar from a token needs the type's
own catalogue data; an exonumia item whose type isn't cached yet is skipped
in a preview and resolved on the run that follows (`catalogue_details`
fetches it there). The spreadsheet mapping reads a `type` cell of `bar`,
`round`, `ingot`, or `bullion` the same way.

## Sharing

The share view (v0.32.0, [SPEC_0320](specs/SPEC_0320.md)): a read-only
page for the collection, a set, or a checklist behind an unguessable link,
opened without signing in. The whole feature is the `share_enabled`
setting (off by default, see [Settings](#settings)).

**Public routes** (class `share`). While sharing is on, the gate lets any
`GET` or `HEAD` under `/api/share/` through without looking up a
credential, and the routes ignore one: a session or a token on the request
changes nothing, so the admin previewing a link sees what a stranger sees.
While it is off the gate has no such rule: an anonymous request there is
`401 {"detail": "Sign in to continue."}` like any other unlisted path,
answered from memory with no database read, so a closed instance looks the
same as one without the feature. The token is read from the path only.
Every answer carries `X-Robots-Tag: noindex, nofollow`; the JSON ones
`Cache-Control: no-store`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/share/{token}` | The manifest: `kind`, `name`, `show_photos`, `show_grades`, `show_tags`, `show_notes`, `show_values`, `show_certs`, `item_count`, and for a checklist `filled` and `total`. Counts one open |
| `GET` | `/api/share/{token}/items` | `?offset=&limit=` (`offset` 0 to 1,000,000, `limit` 1 to 100, default 50; `422` outside them): `{"items": [...], "total": n}`, newest first |
| `GET` | `/api/share/{token}/items/{item_id}` | One piece, if it is in the share |
| `GET` | `/api/share/{token}/checklist` | A checklist link's **filled** slots only, `{"slots": [{position, label, year, mint_mark, item_id}]}` (`item_id` is `null` for a slot ticked by hand with no piece); other kinds `404` |
| `GET` | `/api/share/{token}/photos/{photo_id}/{variant}` | `thumb` or `full`: the file, when `show_photos` is on and the photo's piece is in the share; `Cache-Control: private, max-age=3600`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, and no `Last-Modified` or `ETag` (both would give the upload time). The photo carries no metadata (see [Photos](#photos)): the file is sent as it is only when the one-time pass over stored photos has written its marker and the file passes an allowlist walk of its structure (a JPEG, PNG, or WebP; WebP from v0.32.2), and then as the bytes that were checked; otherwise the route re-encodes it without metadata on the request. A file the pass couldn't rewrite (listed in its marker) and one that can't be decoded are the same `404`. At most two photos are re-encoded at once: past that the route answers `503` with `Retry-After: 5` (and `no-store`). Either way the body is built in memory, so a `Range` (with `If-Range` or without) gets the whole photo, `200`, never a `206` |

**One 404.** A malformed token, an unknown one, a revoked one, a set or
checklist that is gone, and a piece or photo outside the share all answer
the same `404 {"detail": "Not found"}`. The link is looked up first, so a
live link is never throttled, whoever else shares its viewer's address
(behind a gateway or a Swarm ingress, every viewer does). Only a failed
lookup reaches the throttle: an address inside its wait gets `429` with
`Retry-After` (not counted), otherwise the failure is counted and answered
`404`. An address may fail 20 times in 15 minutes, then waits the sign-in
curve (1 second, doubling, at most a minute); an IPv6 address is counted by
its /64. Past 300 failed lookups a minute across every address, a failed
lookup is `429` too. Share failures are kept apart from the sign-in
throttles, so a flood of them can't weaken those. A piece or photo outside
a resolved share is never counted.

**What a link covers.** `collection`: every owned piece (not sold, not the
wish list, never the trash). `set`: the set's owned pieces. `checklist`: the
owned pieces that fill its slots (a slot's match, or the piece linked to a
slot ticked by hand).

**What a piece shows** is an allowlist, pinned by a test: `id`, `type`,
`country`, `denomination`, `year_label`, `mint_mark`, `series`, `variety`,
`composition`, `weight_g`, `fineness`, `diameter_mm`, `width_mm`,
`height_mm`, `shape`, `issuer`, `quantity`; with `show_photos`, `photos`
(`id`, `angle`, `has_thumbnail`); with `show_grades`, `grade_label`,
`grade_details`, `designations`, `cac_sticker`, `cert_service`; with
`show_certs` (off by default), `cert_number`, which looks a slab up in
auction archives that often give its sale price and date; with `show_tags`,
`tags` (names); with `show_notes`, `notes`;
with `show_values`, `value`: the list's shown value (the `value_strategy`
setting) in the display currency, `{"amount", "currency"}`, or `null` when
the piece has none or it can't be converted from the cached exchange rates
(a public route never fetches a rate). Never a cost, fee, gain, acquisition
or sale field, the estimate's source or history, a storage location, a
document, a serial number, custom fields, the population, wish-list fields,
spot at purchase, the import origin, timestamps, or the edit history.
Composition, weight, fineness, and quantity are always shown, so a
precious-metal piece's melt value can be worked out from the spot price
even with `show_values` off.

**Managing links** (admin):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/share-links` | Every link: `id`, `kind`, `set_id`, `checklist_id`, `target_name`, `name`, the six `show_*`, `created_at`, `created_by`, `last_opened_at`, `opens`. Never the token or its hash |
| `POST` | `/api/share-links` | Recent password. `{kind, set_id?, checklist_id?, name, show_*?}` (`show_photos`, `show_grades`, `show_tags` default on; `show_notes`, `show_values`, `show_certs` off): `201`, the row plus `url` (`{origin}/s/{token}`, below), shown this once. `422` when the target is missing or the wrong one is given; `409` `"Switch sharing on in Settings first."` while sharing is off, and `409` with 20 links already |
| `PATCH` | `/api/share-links/{id}` | Recent password. `{name?, show_*?}`: rename or change what it shows; the link stays the same. Works while sharing is off. Audited as `share_link_changed` with the options that changed (and the old name on a rename); alerted when `show_notes`, `show_values`, or `show_certs` is switched on, since that shows every holder of the link more than before |
| `POST` | `/api/share-links/{id}/regenerate` | Recent password. A new `url`, shown once; the old one stops working at once; `409` while sharing is off |
| `DELETE` | `/api/share-links/{id}` | Recent password. Revoke for good (the row is deleted); `204`. Works while sharing is off |

The token is `share_` and 43 base64url characters (32 random bytes), stored
only as its SHA-256. A lost link is replaced with regenerate. Deleting a set
or a checklist deletes its links. Creating, regenerating, and revoking a
link, and switching sharing on or off, are audited (`share_link_created`,
`share_link_regenerated`, `share_link_revoked`, `sharing_switched`, with the
link's id, name, and kind, never the token) and sent through the alert
webhook. Switched off, the links are kept and work again when it is
switched back on.

**The link's origin.** A new or regenerated `url` is built on the request's
own `Origin` when that is one of `PUBLIC_ORIGINS` (the address the admin is
using), else on the first `https://` entry, else on the first entry. With
`PUBLIC_ORIGINS=http://cabinet.lan,https://cabinet.example.com`, a link made
from the LAN name is on the LAN name, and one made anywhere else is on the
public https name, never on plain http when an https origin exists.

**A restore keeps the links** (v0.32.0). Share links are access grants, so
an in-app restore treats them like sign-in data: the live links and the
`share_enabled` switch are put back after the archive's database is in
place, whatever the archive held. See [Restore](#restore).

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
(`null` / `daily` / `weekly`), `backup_retention_days`, and
`backup_include_photos` configure scheduled backups (see Backups below).
`backup_retention_days` (v0.30.2) accepts a day count from either schedule's
set (7, 14, 30, 90, or 365 for a daily schedule or none; 28, 56, 91, 182, or
365, i.e. 4/8/13/26/52 weeks, for a weekly one), or 0 for forever; default
90; anything else is `422`. A value from the other schedule's set is still
accepted (only the frontend snaps to the current schedule's set), since a
sensible number of days doesn't stop being one when the schedule changes.
The response's read-only `backup_retention_choices` (`{"daily": [...],
"weekly": [...]}`) gives both sets so a client never has to hard-code them.
`comps_enabled` switches the comps source (on by default), and
`numista_sales_enabled` (off by default) allows fetching Numista's auction
sales, which needs Numista's paid API plan. `preferred_source` accepts
`comps`. `trash_retention_days` (`0` = never, `7`, `30`, `90`, or `365`; the
default is `30`) is how long an item stays in the trash.

Alerts and metrics: `alert_webhook_url` and `heartbeat_url` are secrets like
the API keys (`""` clears; reads return only `alert_webhook_hint` /
`heartbeat_hint`, the URL's `scheme://host/…`), `alert_webhook_format` is
`generic`, `ntfy`, `discord`, `slack`, or `gotify`, and `metrics_enabled`
serves `/api/metrics`. `share_enabled` (v0.32.0, default `false`) is the
share view's switch: off, no share link opens (an anonymous caller gets the
gate's `401`) and none can be made or regenerated; turning it on or off is
audited and alerted (see [Sharing](#sharing)). Read-only: `alerts` (each check that has ever failed:
`key`, `label`, `failing`, `since`, `message`), `alert_delivery` and
`heartbeat` (the last attempt since the backend started: `at`, `ok`,
`detail`), `refresh_last_run` (per source: `at`, `updated`, `skipped`,
`failed`, and `error` or `stopped` when set), and `secrets_cleared` (v0.30.0:
the names, such as `"alert webhook"`, of stored secrets Cabinet cleared
because they weren't encrypted with this deployment's key; each leaves the
list when it is saved again).

`spot_alerts` (v0.28.0): a list of at most 12 spot-price thresholds,
`{"metal": "gold"|"silver"|"platinum"|"palladium", "direction":
"above"|"below", "price": number, "currency": "USD"}`; `price` must be above
0, `currency` a 3-letter code, upper-cased on the way in. On read, each entry
also carries `met` (`true`/`false` once it has been checked by the hourly
loop, `null` before that); `met` is never accepted on write. Saving the list
drops the checked state of any threshold that is no longer in it, so
re-adding one alerts again rather than staying quiet. The service-written
`spot_alert_state` (per threshold, whether it is currently met) is never
returned by `GET` or accepted by `PUT`. See
[Bullion stack](#bullion-stack) and [monitoring.md](monitoring.md) for how
the alert fires.

## Backups

| Method | Path                    | Purpose                                              |
|--------|-------------------------|------------------------------------------------------|
| `GET`  | `/api/backup.zip`       | Build and download a fresh encrypted archive (`….zip.age`); `?photos=false` for data only |
| `GET`  | `/api/backups`          | Backup directory, free space, last run, stored archives (newest first), the backup key's status |
| `POST` | `/api/backups`          | Write an archive into the backup directory now, then apply retention; `?photos=` overrides the setting |
| `GET`  | `/api/backups/{name}`   | Download a stored archive                            |
| `POST` | `/api/backups/key/saved` | Record that the owner saved the backup key (v0.30.0) |
| `DELETE` | `/api/backups/{name}` | Delete a stored archive (v0.30.1); `409` while a backup or restore runs |

An archive (v0.30.0) is an [age](https://age-encryption.org) file, encrypted
with the backup key, around a zip of `db.dump` (pg_dump custom format, never
the `cabinet_auth` schema), `photos.tar.gz` and `documents.tar.gz` (unless
data-only), `manifest.json` (with a MAC keyed by the backup key), and
`SHA256SUMS`; see [backup-restore.md](backup-restore.md). The download is
`application/octet-stream` and built as ciphertext before it is sent. A failed backup returns `500` with the
reason (for example, `pg_dump failed: …`) and is recorded as the last run
(`at`, `ok: false`, `error`); a successful `POST` answers, and records, `at`,
`ok`, `file`, `size`, `includes_photos`, and `pruned`. `GET /api/backups`
answers `directory`, `free_bytes`, `last_run`, `backups` (`name`, `size`,
`created_at`, `prerestore`: true for the safety archive an in-app restore
took first, and `encrypted`: false for a plain `.zip` from before v0.30.0,
which can't be restored), and `key`: `fingerprint` (the backup key's public
key, `age1…`; the key itself never crosses the API), `saved`, `supplied`
(from `BACKUP_KEY_FILE` or `BACKUP_KEY`), `location` (`separate`, `shared`, `not_verified`,
`secret` for a supplied file, or `environment` for a supplied variable), and
`location_message`. `POST /api/backups/key/saved` records
the current public key as saved (a rotated key asks again) and answers the
`key` object. `DELETE /api/backups/{name}` (v0.30.1) deletes one stored
archive and answers `{"deleted": name}`; it is `409` while a backup or a
restore holds the directory. A second `POST /api/backups` while one is
running returns `409`. Stored archive names must match
`cabinet-backup-YYYYMMDD-HHMMSS[-data|-prerestore].zip.age`; anything else,
a plain `.zip` from before v0.30.0 included, is `404`. Retention
(`backup_retention_days`) deletes archives older than that many days after
each run, keeping the newest full and the newest data-only archive whatever
their age; `0` keeps everything. Pre-restore archives sit outside it: the
newest three are kept. Every backup route is admin-only; both downloads and
deleting an archive also need a recent password, and each download, the
saved-key tick, and each deletion is written to the audit log (downloads and
deletions also alert).

## Restore

Replaces the whole collection with a backup archive; the procedure, the
safeguards, and what a failure leaves behind are in
[backup-restore.md](backup-restore.md#restore-from-inside-the-app).

| Method   | Path                              | Purpose                                   |
|----------|-----------------------------------|-------------------------------------------|
| `GET`    | `/api/restore/status`             | Whether restore is on, the run in progress, and the last outcome |
| `POST`   | `/api/restore/inspect`            | Verify an archive and say what restoring it would replace; changes nothing |
| `POST`   | `/api/restore/{restore_id}/run`   | Start the restore in the background       |
| `DELETE` | `/api/restore/{restore_id}`       | Discard a staged upload                   |

With `RESTORE_ENABLED=false` every endpoint but the status answers `404`.

`GET /api/restore/status` (admin) answers during a restore and when the
feature is off. While a restore runs it answers only the session that
started it (an in-memory grant, looked up without the database, ending 10
minutes after the restore does and 2 hours after it began at the latest);
anyone else gets `401`:

```json
{
  "enabled": true,
  "state": "idle",
  "step": null,
  "started_at": null,
  "last": {
    "at": "2026-09-20T18:04:11+00:00", "ok": true,
    "archive": "cabinet-backup-20260920-180301.zip.age",
    "archive_created_at": "2026-09-20T18:03:01+00:00",
    "safety_backup": "cabinet-backup-20260920-180402-prerestore.zip.age",
    "error": null, "items": 212, "photos": 388, "documents": 9,
    "secrets_cleared": []
  },
  "confirm_phrase": "RESTORE"
}
```

`state` is `idle`, `running`, `done`, or `failed` (kept in memory, so `idle`
again after a backend restart); `step`, while running, is one of
`safety_backup`, `photos`, `documents`, `database`, `migrations`,
`finishing`, in that order (`photos` and `documents` are the unpacking; the
files are swapped in during `finishing`). `last` is read from a file on the
state volume and is `null` until a restore has run; `items`, `photos`, and
`documents` are the archive's counts; `secrets_cleared` (v0.30.0) names the
stored secrets the restore cleared because this deployment couldn't use
them (plain text, or encrypted with another key), and
`finished_after_restart` is `true` when the backend stopped after the
database step and finished the restore on its next start. `sharing`
(v0.32.0) says what happened to the share links, which a restore keeps
like sign-in data: `links_kept` (put back), `links_dropped` (a set or
checklist link whose target, by id and name, the archive doesn't hold),
`archive_links` and `archive_enabled` (what the archive held, now
replaced), `enabled` (the switch, as it was before), and `differed`; an
`error` there means the links couldn't be put back, so every link was
removed and sharing switched off, and the links from before wait in
`pending_sharing.json` on the state volume to be tried again (at the next
start, every hour, and when Settings is opened). After a restart during a
restore, `sharing` is added once the links have gone back, right after the
startup migrations. It is audited as `restore_sharing`, and the restore's
alert says so when the archive differed. Switched off, it answers `enabled:
false`, `state: "idle"`, and `null` for `step`, `started_at`, and `last`.

`POST /api/restore/inspect` takes either a multipart upload (field `file`),
streamed into `BACKUP_DIR/.restore-staging/`, or `?name=` of a stored
archive with no body. It answers:

```json
{
  "restore_id": "3f0c…",
  "archive": {
    "name": "cabinet-backup-20260920-180301.zip.age", "size": 48211934,
    "created_at": "2026-09-20T18:03:01+00:00", "app_version": "0.26.0",
    "revision": "0018", "includes_photos": true, "includes_documents": true,
    "items": 212, "photos": 388, "documents": 9, "trashed": 3
  },
  "current": {"revision": "0018", "items": 214, "photos": 390,
              "documents": 9, "trashed": 0},
  "will_migrate": false,
  "replaces_files": true,
  "secrets_note": "Saved API keys and webhook addresses in the archive…",
  "credentials_note": "Your sign-in, sessions, API tokens, and audit log are kept.",
  "secrets": ["Numista API key"],
  "secrets_cleared": ["alert webhook"],
  "provenance": {
    "made_here": true, "made_at": "2026-09-20T18:03:01+00:00", "newer": 3,
    "older": true, "record_empty": false,
    "message": "Made by this Cabinet on 20 September 2026. 3 newer backups exist."
  },
  "confirm_phrase": "RESTORE OLDER"
}
```

`provenance` (v0.30.0) says whether this Cabinet made the archive (matched
in its record of archives by the verified MAC, never the name), how many
newer ones it recorded, and whether the archive is older than the newest;
`confirm_phrase` is then `RESTORE OLDER` instead of `RESTORE`. With no
record at all, `record_empty` is true and the message says Cabinet can't
tell whether this is the newest.

`secrets` and `secrets_cleared` (v0.30.0) name, never show, the stored
secrets the archive would set and those it holds that would be cleared.
The archive's dump is unpacked for this only into the private staging
folder, checked, and removed again.

It answers `422` with a plain reason for an unencrypted archive from before
v0.30.0, one that can't be opened with the backup key (another key made it,
or it was altered), one whose MAC doesn't verify ("This archive was not made
with your backup key."), a file that isn't a Cabinet archive,
a checksum that doesn't match, an unexpected member, a schema revision newer
than this build knows, a tar member that is a link, a device, an absolute
path, or holds `..`, an unreadable upload, or a request with neither `file`
nor `name`, a dump holding anything in the `cabinet_auth` schema ("This
archive contains sign-in data, which Cabinet never restores. It was not made
by Cabinet's own backup."), or too little room to unpack its dump ("Not
enough space to open this archive…"); `404` for a `name` that isn't a stored
archive; `409` while a restore runs; `413` for an upload over
`RESTORE_MAX_GB`. A rejected upload is deleted at once; others
are cleared after a day. The `restore_id` lives in memory: after a backend
restart, inspect again.

`POST /api/restore/{restore_id}/run` takes `{"confirm": "RESTORE"}` (or the
inspection's `confirm_phrase`, `RESTORE OLDER` for an older archive) and
answers `202` `{"state": "running"}`; poll the status. The run decrypts and
verifies the archive again and checks its age again from the archive
itself, failing with "type RESTORE OLDER" if it has become older since the
inspection. After a failed run the id stays for another try, with the phrase
rechecked (the safety backup it took is now the newest). `404` for an
unknown id, `422` for a wrong phrase, `409` while a restore, a backup, or a
scheduled task is running. The outcome, including a failure's `error`
(ending "Nothing was changed." when that is true), arrives in the status's
`last`.

`DELETE /api/restore/{restore_id}` answers `204`. It deletes a staged upload
and only forgets the id of a stored archive, which is never deleted here;
`404` for an unknown id.

**While a restore runs**, every request except `GET /api/health` and
`GET /api/restore/status` (for the session that started it) answers `503`
with `Retry-After: 5` and
`{"detail": "Cabinet is restoring a backup; try again in a moment"}`.

## Alerts & metrics

| Method | Path               | Purpose                                                    |
|--------|--------------------|------------------------------------------------------------|
| `POST` | `/api/alerts/test` | Send a test alert through the saved webhook; `?target=heartbeat` pushes the heartbeat now |
| `GET`  | `/api/metrics`     | Prometheus metrics; `404` until `metrics_enabled`          |

The test answers `200` either way, with `at`, `ok`, and `detail`: `HTTP 404`,
a connection error, or `No webhook URL is saved` (`No heartbeat URL is saved`
for the heartbeat); a detail never repeats the URL. Metrics are cached for a
minute. What alerts fire, the payload of each format, and every metric are in
[monitoring.md](monitoring.md). Besides the failing/recovered checks there
are events, sent once and never listed under `alerts`: a wish-list target
reached (generic JSON `alert` `wishlist_target`, `status` `event`), and a
spot-price threshold crossed (`alert` `spot_gold` / `spot_silver` /
`spot_platinum` / `spot_palladium`, `status` `event`, one per metal that has
a saved threshold), and the share view's `sharing_switched`,
`share_link_created`, `share_link_regenerated`, `share_link_revoked`, and
`share_link_changed` (when notes, values, or cert numbers go on) (v0.32.0).

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

Anonymous callers (a container health check, Uptime Kuma) get only
`{"status": "ok"}`, and so does everyone while an in-app restore runs (the
check then looks nothing up). Any signed-in session or token gets the full
body: `status`, `db` (`ok` / `unreachable`), the app `version`, and
`schema`: the database's `current` Alembic revision, the `expected` one this
build ships, and a `status`, one of `ok`, `pending` (migrations not yet
applied), `ahead` (the database was migrated by a newer build), or `unknown`
(database unreachable). `auth_schema` (v0.30.0) is the same for the sign-in
chain (`cabinet_auth`, revision `a0001` onward). `documents` says whether attached documents can be
stored: `ok`, `not_mounted` (`DOCUMENT_DIR` isn't a mounted volume, so
uploads are refused), `unwritable`, or `inside_photos`. Settings → About
displays both.

## Conventions

- **Timestamps** are ISO 8601 UTC (`timestamptz`).
- **Money** fields carry an explicit ISO 4217 `currency` alongside the amount.
- **IDs** are UUIDs for items/photos/estimates/documents; sales, checklists,
  edit-history events, and reference tables use integers.
- **Errors** follow a consistent JSON shape: `{ "detail": "..." }`, matching
  FastAPI defaults, with appropriate HTTP status codes. The one addition is
  `reauth_required: true` on a `403` that wants the password again.
