# Changelog

All notable changes to Cabinet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Database changes always ship as Alembic revisions. From 0.11.1 the backend
applies them itself on startup; for earlier releases, run
`docker compose exec backend alembic upgrade head` after upgrading.

## [0.33.0] - 2026-09-24

Roadmap Phase 7, P8, A2: single sign-on
([SPEC_0330](docs/specs/SPEC_0330.md)). The same one admin can now sign in
through an OpenID Connect provider (Authentik, Keycloak, Authelia, Entra ID,
Google, or any other standards-compliant issuer), a GitHub button, or a
gateway that has already authenticated the browser and can present a
signed assertion (Authentik's proxy outpost, Cloudflare Access, Pomerium,
Google IAP). Cabinet builds no second factor of its own: the identity
provider's own multi-factor check is the second factor, and the local
admin password stays as a deliberately one-factor recovery credential, so
a provider outage or a lost phone can never lock the owner out. An
authenticating reverse proxy in front is now optional rather than a
recommended second door. This release also adds a hard exposure advisory
to the deployment guide: **Cabinet is designed for private networks and
should not be exposed to the internet**, under any sign-in configuration.

### Added
- **OpenID Connect sign-in**: authorization code flow with PKCE, `state`,
  and `nonce`; discovery; the ID token verified against the provider's own
  published keys. Presets for Google, Microsoft (Entra ID), and any custom
  OpenID Connect issuer, configured in a new Settings → Sign-in section
  (`GET`/`PUT /api/auth/signin-config`, `GET`/`POST /api/auth/providers`,
  `PATCH`/`DELETE /api/auth/providers/{id}`), each shown as its own
  sign-in button. Linking never happens on a first sign-in: an identity
  that isn't already linked is sent back to sign in with the password and
  link it from Settings on a fresh session.
- **A GitHub sign-in button**, through a new `oauth2_profile` provider
  kind that reads the identity from GitHub's profile endpoint instead of
  an ID token, since GitHub speaks OAuth 2.0 without one.
- **The trusted-header mode**: `POST /api/auth/trusted` signs in from a
  gateway's signed JWT assertion, verified against
  `TRUSTED_ASSERTION_JWKS_URL` with the configured issuer and audience;
  never a plain-text header or a shared secret. One button on the sign-in
  page, "Continue with the proxy's sign-in," never automatic. Four new
  environment variables (`TRUSTED_ASSERTION_HEADER`,
  `TRUSTED_ASSERTION_JWKS_URL`, `TRUSTED_ASSERTION_ISSUER`,
  `TRUSTED_ASSERTION_AUDIENCE`, all four or none) plus `SSO_CA_FILE` for a
  provider or gateway behind a local certificate authority. nginx's start
  script (renamed `40-cabinet-config.sh`) now also writes an identity
  include that blanks every gateway header except the one
  `TRUSTED_ASSERTION_HEADER` names.
- **Recovery from the container**: `unlink-identity <id>` removes one
  linked identity and ends its sessions; `disable-sso` turns every
  provider and the trusted-header mode off in one step, for a
  configuration that locks the sign-in page itself; `status` now lists the
  configured providers, linked identities, and which sign-in methods are
  on. Every command takes effect in the running backend at once, with no
  restart, since provider rows and the sign-in configuration are read from
  the database on every use, never cached.
- **`password_sign_in_alerts`** (off, switched on automatically the first
  time any provider is enabled), a Settings switch that alerts on every
  password sign-in, not only a new device, as a tripwire on the recovery
  path once single sign-on is the everyday door.
- **Confirming a fresh action at the provider**: the password-again dialog
  offers "Confirm at your sign-in provider" for a session that signed in
  through a provider that supports it, so a sensitive action doesn't
  always need the password typed by hand; a GitHub or trusted-header
  session always confirms with the password instead.
- A mock identity provider (`scripts/ci/mock_idp.py`, CI only) and a new
  `sso` phase in the smoke script and `frontend/e2e/sso.spec.ts`, proving
  both flows, a long list of deliberately broken tokens and a replayed
  callback, the credentials-rejected alert, and the trusted-header mode
  through real nginx.
- Migration `a0002` (the `cabinet_auth` chain only): sign-in providers,
  linked identities, the new-browser alert's rows, the sign-in switches,
  and each session's identity; the unused, always-empty external-identity
  columns on `users` are dropped.

### Changed
- **An authenticating reverse proxy in front is now optional.**
  Cabinet's own sign-in no longer needs a second door: what such a proxy
  still offers is a door before the sign-in page is shown, and the
  trusted-header mode's one-click sign-in. `docs/deployment.md` section 4
  is rewritten with worked setup for Authentik, Keycloak, Authelia, Entra
  ID, Google, and GitHub, and the trusted-header contract for Authentik,
  Cloudflare Access, Pomerium, and Google IAP.
- **A new-browser cookie**, with no role in authentication or throttling,
  decides the new-device alert for every sign-in method, single sign-on
  and the trusted-header mode included; only a password sign-in or
  password confirm still issues the known-device cookie that lifts the
  password throttles.

### Security
- **A hard exposure advisory.** `docs/deployment.md` gains a section
  stating plainly that Cabinet is designed for private networks and
  should not be exposed to the internet under any configuration, TLS and
  single sign-on included; the same paragraph is copied verbatim into
  `docs/security.md`, `README.md`, `SECURITY.md`, and `.env.example`.
- The provider callback passes the deny-by-default gate with no
  credential lookup at all (it is a cross-site navigation back from the
  provider), bound instead to the one-use state in an encrypted,
  short-lived flow cookie; no other route joins that anonymous allowance
  without the same binding.
- A provider rejecting Cabinet's client credentials (an expired or wrong
  client secret) is a new alert condition with recovery, shown on the
  provider's row in Settings.
- Repeated rejected single sign-ons are throttled and audited apart from
  password failures, so a flood of them can't push real events out of the
  audit log or exhaust the sign-in throttle's shared map.
- The trusted-header mode's header name is checked against the same
  blocklist on the backend and the proxy's start script, so it can never
  be set to a header nginx or the gate already relies on (hop-by-hop
  headers nginx sets itself included).
- A fresh-context security review before the release found no critical or
  high issue; its one medium and six low findings are fixed: switching the
  trusted-header mode off in Settings now ends its sessions, a callback
  inside its throttle wait exchanges nothing at the provider, a failed key
  fetch is not retried for a minute, `next` refuses dot segments, the
  Microsoft preset is never offered for a provider confirm (Entra issues
  `auth_time` only as an optional claim), and the header sign-in verifies
  before it throttles so a shared edge address can't keep the owner out.
- The proxy image now applies Alpine's pending updates at build time (`apk
  upgrade`), as the backend image already does Debian's, so a fix already
  in Alpine's repository (this release, `libexpat`'s, flagged by Trivy)
  ships with it.

**Upgrading**: nothing changes for an existing deployment until a provider
is configured in Settings → Sign-in; the password sign-in path is
untouched. On an https deployment the new flow and browser cookies are
`__Host-` prefixed, like the session cookie. An authenticating reverse
proxy kept in front is optional from this release; if you keep one,
continue to exempt `/s/`, `/api/share/`, and `/robots.txt` from its
authentication check, as before.

## [0.32.2] - 2026-09-23

An adversarial review of v0.32.1 found four edges in the share photo path
and one availability gap; all closed here. Nothing exploitable existed on a
volume whose cleaning pass reported no unreadable files.

### Fixed
- **The per-file check is an allowlist walk of the whole file.** A JPEG
  is sent from disk only when every segment before and after its first
  scan is one the encoder writes (no reserved or unknown markers, JFIF and
  Adobe bodies of their exact lengths, a real ICC segment, one EOI with
  nothing after it); a PNG only when every chunk is allowed, sized as
  specified, with a correct CRC and nothing after IEND. A single bit flip
  at an EXIF marker used to make a file unreadable to the pass yet clean
  to the check; it is now refused and re-encoded.
- **The bytes the check read are the bytes sent.** The share route no
  longer reopens the file to stream it, so a file replaced between the
  check and the send (a `restore.sh` unpack) cannot be served unchecked.
  `Range` requests no longer apply to a shared photo.
- **Files the pass could not rewrite are refused until they are.** The
  marker now lists them, and the share route answers 404 for a listed
  file even when it would otherwise pass.
  One limit stays, by design: bytes hidden inside a file's compressed
  pixel stream (text before a JPEG's EOI, an extra PNG `IDAT`) are
  invisible without decoding, so a file crafted that way and copied onto
  the volume by hand after the pass is served as it is until the pass
  rewrites it; two tests record this as expected. The pass, and every
  upload, re-encode from pixels, so Cabinet never writes such a file.

### Changed
- **A clean WebP is served from disk** (its RIFF chunks are walked like a
  JPEG's segments), and on-the-fly re-encodes are capped at two at a time
  (503 with `Retry-After` beyond that), so a link holder can no longer
  turn a share into a CPU loop by requesting a full-size WebP repeatedly.
- The README no longer carries the share-link screenshots.

## [0.32.1] - 2026-09-23

A post-release review of v0.32.0 (a third fresh-context pass, over Codex's
findings) found one latent gap in the photo-metadata work and a
deployment omission; both are closed here.

### Fixed
- **A share photo is checked before it is trusted.** The one-time cleaning
  pass wrote its "all clean" marker even when a stored file could not be
  decoded, and once the marker existed the share route streamed such a file
  from disk as it was, metadata included. A file like that only arrives
  after upload (damage on the volume, a `restore.sh` interrupted while
  unpacking photos, a file copied onto the volume by hand), and the pass
  logs each one, but the marker is now only an optimisation: the share
  route serves a file from disk only when a header-only check finds no
  metadata and, for a JPEG, no trailer after the image; anything else is
  re-encoded on the fly or refused, as before the marker. A pass that was
  already running when a restore removed the marker no longer writes it
  afterwards, and the pass's summary line ("rewrote X of Y stored photos")
  reaches the backend's log.

### Changed
- The Traefik example in `deployment.md` now carries an `hsts` headers
  middleware on both routers, with the rule that `Strict-Transport-Security`
  belongs on whatever terminates TLS (Cabinet's nginx only sees plain HTTP),
  and a note that the edge proxy's own access log records share URLs in
  clear. Two stale sentences corrected in `security.md` and the
  implementation notes.

## [0.32.0] - 2026-09-23

Roadmap Phase 7, P9: the share and showcase view
([SPEC_0320](docs/specs/SPEC_0320.md)).

### Added
- **Share links** (API): a read-only link to the collection, a set, or a
  checklist, opened without signing in. `GET /api/share/{token}` and its
  `items`, `items/{id}`, `checklist` (filled slots only), and
  `photos/{photo_id}/{thumb|full}` routes answer anyone holding the link;
  a session or token on the request is ignored. What a piece shows is an
  allowlist (identity, physical facts, and quantity, plus photos, grades,
  cert numbers, tags, notes, and the estimated value as the link chooses;
  cert numbers and values off by default): never a cost, gain, storage
  location, document, serial number, or custom field. A wrong, unknown, or
  revoked token is the same `404`. The link is looked up first, so a live
  link is never throttled; failed lookups answer `429` rather than `404`
  per address past 20 (an IPv6 address by its /64) and past 300 a minute
  overall, in a throttle kept apart from sign-in's (it doesn't slow
  guessing: the 256-bit token is the defence). Every answer carries
  `X-Robots-Tag: noindex, nofollow`, a shared photo carries no file time
  (`Last-Modified`, `ETag`), and no public route makes a network call.
- **Managing links**: `GET`/`POST /api/share-links`, `PATCH` and `DELETE
  /api/share-links/{id}`, and `POST /api/share-links/{id}/regenerate`. The
  URL is shown once, on the admin's own address when it is one of
  `PUBLIC_ORIGINS` (else the first https one), and only its hash is kept;
  making, changing, regenerating, and revoking a link ask for the password
  again, and at most 20 links exist. Deleting a set or checklist deletes
  its links. Changing and revoking work while sharing is off; making and
  regenerating answer `409` then.
- **The switch**: `share_enabled` in Settings, off by default. Off, a
  stranger gets the same `401` under `/api/share/` as on any other path
  (answered from memory, no database read) and no link can be made; the
  links are kept. Switching it, and each link event, is audited and sent
  through the alert webhook (`sharing_switched`, `share_link_created`,
  `share_link_regenerated`, `share_link_revoked`, and `share_link_changed`
  when a link starts showing notes, values, or cert numbers).
- **A restore keeps the live share links and switch.** Links are access
  grants, so an in-app restore puts back the links and switch it found,
  whatever the archive held: a revoked link can't return with an older
  archive, and an archive can't switch sharing on. The outcome says what
  the archive held, it is audited (`restore_sharing`), and the restore's
  alert says so when they differed. If they can't be put back, every link
  is removed and sharing switched off, and the links from before wait in
  `pending_sharing.json` on the state volume to be tried again. A backend
  restarted mid-restore puts them back after its startup migrations, so an
  archive from before share links existed keeps them too. `restore.sh`
  can't keep them: it ends by saying to check Settings, Sharing.
- Metrics `cabinet_share_links` and `cabinet_share_opens_total`, and a
  sharing line in `python -m app.cli status`.
- Migration `0022`: the `share_links` table.
- **The share page**: `/s/{token}` and `/s/{token}/items/{id}`, rendered
  outside the sign-in gate entirely (no sign-in boot check ever runs for a
  visitor). A grid of the shared pieces with a search box, a piece's own
  page with its photos in a lightbox and its allowed facts, and a
  checklist link's filled slots; a dead link shows one page, "This link
  isn't active." Settings gains a Sharing section: the switch, the links
  table (Rename, Options, Regenerate, Revoke), and a form to create one,
  with the new URL shown once and a Copy button, the same as a new API
  token. Each link's six toggles (photos, grades, tags, notes, the
  estimated value, the cert number) sit in the create form and a row's
  Options panel, the last two with a line saying why they are off by
  default. nginx marks `/s/` non-indexable (`X-Robots-Tag` and the page's
  own `noindex` tag; `robots.txt` disallows `/api/` only, since a crawler
  has to fetch the page to see the tag) and keeps a share token out of its
  own access log too.

### Changed
- **Photos are stored without their metadata.** A phone photo taken at home
  carries GPS coordinates, the time, and the camera's details, and a share
  link can now show a full-size photo to anyone holding it. Every upload,
  URL import, and edited image is re-encoded before it is stored: turned
  upright, with every EXIF block, XMP, IPTC, comment, and PNG text chunk
  dropped and the colour profile kept (JPEG at quality 95; an animated
  image keeps its first frame). Thumbnails are written the same way.
  Photos already stored, thumbnails included (an older thumbnail could
  carry the photo's JPEG comment), are all re-encoded once, in the
  background, on the first start after upgrading, whether or not
  `AUTO_MIGRATE` is on, and again after an in-app restore brings photos;
  `restore.sh` runs the same pass (`python -m app.cli strip-photo-metadata`)
  itself. Until that pass has finished, the share view re-encodes each
  photo without its metadata as it serves it, rather than trusting the
  file on disk. Found, with the throttle, restore, and cert-number fixes
  above, by two security reviews before release
  ([SPEC_0320](docs/specs/SPEC_0320.md#the-security-review-and-stage-4-23-september-2026)).

**Deploying:** if you keep an authenticating reverse proxy in front of
Cabinet (recommended as a second door until single sign-on in v0.33.0) and
turn sharing on, exempt `/s/`, `/api/share/`, and `/robots.txt` from its
authentication check. Cabinet's own gate already lets those routes through
without a session or token; a forward-auth proxy that doesn't know that
will show its own sign-in page instead of the share, blocking a link
Cabinet itself would answer. See
[deployment.md](docs/deployment.md#sharing-and-the-forward-auth-exemption).

## [0.31.0] - 2026-09-23

Roadmap Phase 7, P11: bars and rounds ([SPEC_0310](docs/specs/SPEC_0310.md)).

### Fixed
- **Metal detection** no longer counts a named alloy as the metal it is
  named after, or a coating as the metal: nickel silver, German silver, and
  Nordic gold (the euro 10, 20, and 50 cent alloy) are not precious, "Gold
  plated brass" is not gold, "Gold plated silver" is silver, "golden" is not
  gold, and with two metals named the one with the larger share wins. The
  metal breakdown, the stack's skipped count, melt coverage, and the item
  form's spot field all follow.
- **Fineness read from a composition** takes the percentage attached to the
  metal, so "Copper 10%, Silver 90%" is .900 (it read .100). One parser now
  serves melt, the stack, and the Numista fill, and also reads ".925", "999.9",
  sterling, Britannia, coin silver, and gold carats (24K to 9K).

### Added
- **A third item type, `bullion`** ("Bar or round"), on the API side. No year
  is required for it (neither `year` nor `year_nd`), its label reads
  "PAMP Suisse 1 oz silver bar" with no mint mark, and it never gets fancy
  serial traits. The list's `type=` filter and bulk edit accept it; the type
  breakdown and `/api/metrics` pick it up automatically. Filling an item in
  from Numista, and both the account and file imports, now take a bar or
  round from Numista's exonumia catalogue (still refusing tokens and
  medals), and a spreadsheet's Type column reads "bar", "round", "ingot",
  or "bullion" the same way.
- **The bullion type on the frontend.** The item form's type choice gains
  "Bar or round" (`/items/new?type=bullion` presets it); a bullion piece
  gets a Metal select that writes the composition, a fineness that defaults
  to .999, a g / oz switch beside Weight (coins too), and a suggested
  product name from its weight, metal, and shape, kept until the owner
  types their own. A coin's Composition field gains a hint about the
  bullion stack, and the Stack page's empty state links to
  `/items/new?type=bullion`. The item page's hero and facts show a bar's
  own fields (refiner, weight, fineness, size, shape, serial number) and
  hide the coin- and note-only ones. The list's type filter and bulk edit,
  and the dashboard's value hero and type breakdown, all know "Bars and
  rounds"; the Numista fill searches its exonumia catalogue for a bullion
  piece and shows what kind of object each hit is.
- **A value from the start.** A new bullion piece (or any precious-metal
  item) gets a melt estimate without a button press: saving an item adds one
  from the cached spot price only (no network call on the save path). `GET
  /api/stack` gains `skipped_items` (which pieces are left out, and whether
  it's the weight, the fineness, or both), shown on the Stack page under
  "Left out". `GET /api/items` gains `metal=` (`gold`, `silver`, `platinum`,
  `palladium`, `none`), with a Metal filter on the list page.

### Changed
- **Melt estimates reach existing pieces sooner, not only new bullion
  ones.** The scheduled melt refresh now also picks up any owned,
  untrashed coin or note with a detected precious metal and no estimate at
  all, never one whose latest estimate is manual or from another source;
  saving an item (create, update, a run, or an import) does the same from
  the cached spot price, skipping a piece that already carries a melt
  estimate matching its current metal, weight, fineness, and quantity.
- **Two response shapes grow a field, additively.**
  `GET /api/stats/collection`'s `counts` gains `bullion` alongside `coins`
  and `notes`; `Item.year_label` reads `""`, not `"ND"`, for a bullion piece
  with no year (coins and notes are unchanged, since the year-or-ND rule
  still applies to them).

## [0.30.2] - 2026-09-22

The owner's second first-run pass, all on the Settings page.

### Changed
- **Settings is six sections with their own addresses** (`/settings/general`,
  `pricing`, `backups`, `alerts`, `account`, `about`; `/settings` opens
  General), a section list beside the content on a desktop and a strip
  above it on a phone, and one layout for every setting: what it is on the
  left, the control on the right, saved as you change it. Price sources and
  cached market data share the Pricing section; Backups runs key, schedule
  and retention, archives, then restore. Links to `/settings#account` now
  open `/settings/account`.
- **Retention choices follow the schedule.** Weekly backups offer 4, 8, 13,
  26, or 52 weeks (stored as 28, 56, 91, 182, and 365 days); daily or off
  keeps 7, 14, 30, 90 days, or 1 year; Forever stays in both, with its
  warning. Switching schedule snaps a retention that isn't in the new set
  to the nearest choice and says so. `GET /api/settings` carries the two
  sets as `backup_retention_choices`.
- **The backup key is shown as a masked field** with an eye and a copy
  button, and says what it is: the public half, shown so you can confirm
  which key is in use; the secret half never leaves the container.

## [0.30.1] - 2026-09-22

### Changed
- **Backup retention is by age.** Settings → Backups keeps archives for 7,
  14, 30, or 90 days, 1 year, or forever (with a warning: the directory then
  grows without limit), in place of the "keep newest N" count. After each
  run, archives older than the retention are deleted, but the newest full
  archive and the newest data-only archive always stay, whatever their age,
  so a schedule that stopped can never leave nothing. The default is 90
  days; a saved `backup_keep` is ignored. Pre-restore safety archives keep
  their own rule (newest three).
- **Plain `.zip` archives from before v0.30.0 are no longer detected or
  managed.** They were never restorable; now they are not listed or
  deleted by Cabinet either (`DELETE /api/backups/unencrypted` and the
  `encrypted` flag on the listing are gone). Delete any you still have by
  hand from the backup directory.

### Added
- **Delete a stored backup** from Settings → Backups (`DELETE
  /api/backups/{name}`): admin, asks for the password again, refused while
  a backup or restore is running, audited and alerted. The stack smoke
  suite and Playwright cover it.

## [0.30.0] - 2026-09-22

Roadmap Phase 7, P8 A1: sign-in and encrypted backups.

**Upgrading: read this before you deploy.**
- **Nothing but the setup page is served until the admin exists.** On the
  first start, open Cabinet and enter the setup code: your `SETUP_CODE` (or
  the file `SETUP_CODE_FILE` names, the better choice on a Swarm), or, if you
  set neither, the one the backend prints once in its log (`docker compose
  logs backend | grep "setup code"`, or `docker service logs
  cabinet_backend`). Delete the secret or the variable afterwards; Cabinet
  ignores it from then on.
- **`PUBLIC_ORIGINS` is required**: the exact address browsers use, for
  example `PUBLIC_ORIGINS=https://cabinet.example.com`. The backend and the
  proxy refuse to start without it. Add any internal name other services
  use (`cabinet_proxy` for Homepage or Prometheus) to `ALLOWED_HOSTS`: nginx
  now gives no answer to any other Host. Don't set `AUTH_INSECURE_HTTP`
  beside an https origin (it is refused).
- **Anything that called the API without signing in stops** until it has an
  API token (Settings, Account): the Homepage tile and Prometheus need a
  `metrics` token (header snippets in `docs/monitoring.md`), scripts a `read`
  or `write` token. Uptime Kuma or a container health check on `/api/health`
  keeps working: it answers `{"status":"ok"}` without one.
- **Every backup is encrypted from the first start.** Save the backup key
  (`docker compose exec backend python -m app.cli backup-key show`) in your
  password manager, or supply your own as a Docker secret
  (`BACKUP_KEY_FILE`) or a variable (`BACKUP_KEY`), before you rely on the
  archives: without it they
  can't be opened by anyone. Then take a new backup and delete the old
  unencrypted archives (Settings, Backups, **Delete unencrypted archives**):
  they are readable copies of the collection and can no longer be restored.
- **A Swarm deployment adds the `staging_data` volume** (`/data/staging`,
  on the node's own disk) and the settings above; see
  `deploy/docker-stack.yaml`.
- An authenticating proxy in front (forward-auth or an SSO gateway) keeps
  working and is recommended until single sign-on arrives in v0.33.0.
- Any stored secret still in plain text is cleared and named, to be entered
  again. Every secret saved since v0.10 is already encrypted.
- Revision `a0001` creates the `cabinet_auth` schema; the backend applies it
  on startup after the collection's migrations, which are unchanged.

### Added
- **Sign-in, always on, and every endpoint denied by default.** One admin,
  created on the first visit with a one-time setup code (`SETUP_CODE` or
  `SETUP_CODE_FILE`, or one printed in the backend's log); until then only
  the setup is served. Browsers sign in with a session cookie; scripts use
  API tokens (`Authorization: Bearer cabinet_...`) with a scope: `read`,
  `write` (both 1 or 7 days), or `metrics` (totals only, may never expire).
  Only health (just `{"status":"ok"}` without a credential), the setup
  state, setup, and sign-in answer anonymously; every other route declares
  who may call it, and a route that declares nothing is refused. Downloads,
  exports, restores, settings changes, deleting for good, and managing
  tokens and sessions ask for the password again (5 minutes, per session).
  Cookie requests from another site are refused whatever their method.
  New routes under `/api/auth` (setup, sign-in and out, the account, its
  sessions and tokens, the audit log); see `docs/api.md`. Sign-in delays
  grow per username and per address and never lock the account; a browser
  that signed in before gets past them and keeps a password check reserved
  for it during a flood. New-device sign-ins, repeated failures, new tokens,
  password changes, downloads, exports, and restores reach the alert
  webhook.
- **Photos are only for the signed-in.** nginx asks the backend before
  serving anything under `/photos/`: the admin's browser, or a `read` or
  `write` token, gets the file (never cached); anyone else gets 401 or 403,
  and 503 while the backend is restarting. The app's own files and the
  logo stay public. Measured on a page of 50 thumbnails: about 3.5 ms per
  photo.
- **The setup and sign-in pages, and the rest of the frontend for all of the
  above.** `/setup` and `/login` (a plain warning when the connection isn't
  secure, the server's error and throttle text shown as it happens); a
  password-confirmation dialog that opens itself when a "fresh" action needs
  it and retries; a failed-sign-ins notice after signing in; Settings →
  Account (change the password or username, see and end sessions, create
  and revoke API tokens, read the audit log); and, in Settings → Backups,
  the backup key's fingerprint, a reminder to save it until it's ticked
  done, and deleting old unencrypted archives.
- **Commands in the container for the account**, for when the app can't be
  reached (`docker compose exec backend python -m app.cli ...`): `status`,
  `reset-password` (asked twice, never an argument; ends every session and
  known device and revokes every API token), `sign-out-everywhere`, and
  `revoke-tokens [--name NAME]`. They, and `backup-key`, refuse until Cabinet
  is set up, and each change is audited.
- **`PUBLIC_ORIGINS` is required**: the exact address browsers use for
  Cabinet (`https://cabinet.example.com`). The backend and the proxy both
  refuse to start without it, naming the variable. `.env.example` has values
  for the local stack. Also new: `ALLOWED_HOSTS` (extra Host names nginx
  answers, such as `cabinet_proxy` for Homepage or Prometheus),
  `AUTH_INSECURE_HTTP` (plain-http cookies, local stack only, refused beside
  https), `SETUP_CODE` / `SETUP_CODE_FILE` (checked at start: at least 32
  characters), and `CABINET_PORT` (the published port).
- **nginx answers only Cabinet's own Host names**; any other Host, a bare IP
  address, or no Host gets no response at all (444). Add internal names to
  `ALLOWED_HOSTS`.
- Sign-in and setup bodies are capped at 8 KiB by nginx.
- Every service in `docker-compose.yaml` and the Swarm stack file keeps its
  log to three 10 MB files; the compose backend has the stack file's 1 GB
  memory limit.

### Changed
- **nginx believes no forwarded header.** `X-Forwarded-For`, `X-Real-IP`,
  and `X-Forwarded-Proto` are overwritten with what nginx itself saw, and the
  identity headers forward-auth gateways add (`Remote-User`,
  `X-authentik-*`, `X-Auth-Request-*`, and others) are dropped before the
  backend; uvicorn runs with `--no-proxy-headers`.
- **A secret stored as plain text is never used.** It reads as unset and is
  cleared (never encrypted in place) at startup and hourly, named in the log,
  through the alert webhook, and in a Settings banner until entered again.
  Every secret saved since v0.10 is already encrypted.
- **The Swarm stack file:** the backend alone is on `cabinet-egress`, the
  proxy leaves it (it needs no way out), `PUBLIC_ORIGINS` and `CABINET_PORT`
  are required, and commented Docker secrets show the setup code and backup
  key.
- `GET /api/pcgs/cert/{cert}` takes only letters, digits, and dashes (1 to
  20); anything else is 422.
- **Sign-in data gets a database schema of its own, `cabinet_auth`**, with its
  own migration chain (`backend/alembic_auth/`, revision `a0001`), migrated on
  startup right after the collection's. `/api/health` reports it as
  `auth_schema`, and Settings → About shows it. No foreign key crosses
  between it and the collection.
- **Backups never contain sign-in data and restores never change it.** Dumps
  leave out `cabinet_auth` (in-app and `backup.sh`), restores take `public`
  only (in-app and `restore.sh`), and an archive whose dump holds any sign-in
  data is refused by both. The restore summary says your sign-in is kept and
  names the stored secrets the archive would set or have cleared; the
  manifest gains `auth_excluded`.
- **An archive's database dump is unpacked only in a new private volume,
  `staging_data` at `/data/staging`** (0700), never in the backup directory,
  and it is emptied after every check and restore. Add the volume when
  upgrading a Swarm stack; keep it on the node's own disk.
- **Every backup is encrypted** with a backup key, as a standard
  [age](https://age-encryption.org) file (`cabinet-backup-….zip.age`), and
  carries a MAC keyed by that key: an archive on the backup share can be
  neither read nor forged without it. Every write path (download, scheduled,
  run now, the safety backup before a restore, and `backup.sh`) streams the
  zip straight into `age`, so nothing unencrypted is ever written to the
  backup directory. The key comes from `BACKUP_KEY_FILE` (a Docker secret)
  or is generated on the state volume at first start; `python -m app.cli
  backup-key show` prints it inside the container (it never crosses the
  API) and `backup-key rotate` replaces it while older archives stay
  readable. The key can also be supplied as a variable, `BACKUP_KEY`, for a
  secret manager that sets variables (the secret file stays the better
  choice where you have it), and `backup-key new` prints a fresh key for
  either form. **Save a copy outside Cabinet**: without it the archives can't
  be opened. Settings reports whether the key sits beside the backups.
- **Restores take only encrypted archives made with this deployment's key.**
  An archive is decrypted in private staging and its MAC checked before
  anything in it is read. Every archive Cabinet writes is recorded, by its
  MAC, in a record no restore rewrites; the restore summary says whether
  this Cabinet made the archive and how many newer ones exist, and restoring
  an older one needs `RESTORE OLDER`, whatever its file name or time.
  `restore.sh` decrypts into a private temporary folder, removed afterwards,
  and verifies the MAC through the backend (`decrypt-archive`,
  `verify-archive`). An archive must hold exactly the members its MAC
  covers, each once, on every path. A plain upload is refused on its first
  bytes, before any of it is stored.
- The backup key is generated only on a first start, and never over an
  existing one; at runtime a key that can't be read fails the backup and
  alerts instead. Startup checks the key with a real encrypt and decrypt,
  and alerts when the newest recorded archive was made with a key this
  Cabinet no longer has.
- **Deleting a photo or a document asks for the password again**, as
  deleting an item for good does: `DELETE /api/photos/{id}`, `PUT
  /api/photos/{id}/image` (the old files are deleted), `DELETE
  /api/documents/{id}`, and unlinking a document from its last item are for
  the admin with a recent password. There is no trash for either, so an API
  token can no longer remove one. Other photo and document edits are
  unchanged.
- A `read` or `metrics` token is refused on any write before its body is
  read; a wrong setup code is audited; a container command's decrypted
  working file is removed once it is stale.
- **Retention keeps full and data-only archives separately**: each kind
  keeps the newest `backup_keep`, so data-only backups never push out the
  last archives that hold the photos and documents.
- New: `POST /api/backups/key/saved`, `DELETE /api/backups/unencrypted`;
  `GET /api/backups` gains `encrypted` per archive and the key's status;
  the restore inspection gains `provenance` and `confirm_phrase`.
- **A restore interrupted during the database step is now resolved exactly.**
  A marker row written just before it tells the next start whether the
  database was replaced; if the database can't be reached, the backend stays
  in maintenance until a restart can decide. A restore also clears, and
  names, any stored secret it brings that this deployment can't use.

- **Three API endpoints renamed, before 1.0 makes paths stable** (breaking,
  for scripts that call them):
  - `POST /api/items/{id}/estimate?source=` is now
    `POST /api/items/{id}/estimates/auto?source=`, so it no longer sits one
    letter from the manual `POST /api/items/{id}/estimates`.
  - `POST /api/estimates/refresh-melt` is now
    `POST /api/estimates/refresh?source=melt`. `source` is required, and
    only `melt` is accepted for now.
  - `POST /api/items/import` is removed. `POST /api/imports`, then
    `POST /api/imports/{upload_id}/run`, reads a Cabinet export (the
    `cabinet` format) and is the one import path; the app already used it.
- New dependencies for sign-in and encrypted backups: `argon2-cffi` (password
  hashing, with `argon2-cffi-bindings`) in the backend lockfile, and Debian's
  `age` package in the backend image (backup encryption, called as a
  program).
- `docs/api.md` gains a stability policy: breaking changes are allowed and
  announced here until 1.0; from 1.0, `/api/` paths and response fields are
  stable within a major version, and additions are never breaking.

### Removed
- **The interactive API docs page, `/api/docs`**, so no third-party script
  runs in the app's origin. The schema is still at `/api/openapi.json`.
- **Restoring unencrypted archives.** Plain `.zip` archives from before
  v0.30.0, and `backup.sh` directories, can't be restored by any path. They
  are listed as unencrypted; **Delete unencrypted archives** removes them
  once a new encrypted backup exists.

## [0.29.1] - 2026-09-20

### Added
- **A typed-in value can be deleted.** `DELETE
  /api/items/{id}/estimates/{estimate_id}` and a "delete" link on the row in
  the item page's value history, for a value recorded by hand (one entered
  by mistake, or one a source has since replaced). What a price source said
  is still kept: deleting one of those answers `409`, because the reports
  and the provenance are built on that history.

### Fixed
- **Photos could not be deleted, except the last one.** The controls under a
  photo were wider than its tile, so each delete button sat underneath the
  next tile's first arrow. The tile is wider, its controls are compact and
  wrap inside it, and a photo whose file is missing now keeps a full-size
  tile, so it can be found and deleted.

## [0.29.0] - 2026-09-20

### Added
- **Note details.** Five new item fields: `width_mm` and `height_mm` (for
  notes and anything else not round; coins keep `diameter_mm`), `printer`,
  `watermark`, and `demonetized_on` (coins and notes alike). `q` search also
  matches `printer`. "Fill from Numista" fills all five for a banknote type
  when the catalogue gives them. Migration `0021`.
- **Ten more dashboard widgets** (the roadmap's "group C"): Most valuable,
  Piece of the day, Oldest piece, Newest acquisition, On this day, Photo
  mosaic, Certified share, Value spread, Population highlights, and Data
  health, plus a `metal` dimension on the breakdown widget. None are in the
  default layout; add them from "Edit dashboard".
- Two new list sorts, `sort=value` (the newest estimate) and
  `sort=pcgs_pop_higher`, and four stats endpoints behind the new widgets:
  `GET /api/stats/quality`, `/value-spread`, `/data-health`, `/showcase`.

### Changed
- **The item page.** A hero at the top shows the primary photo large beside
  the title, grade, certification, value, and wish-list details; the facts
  below are grouped (Identity, Grade & certification, Physical, Acquisition,
  Custom fields) and only show what has a value, with a "Show empty fields"
  toggle for the full sheet. Split into `components/item-hero.tsx` and
  `components/item-facts.tsx`.

## [0.28.0] - 2026-09-20

### Added
- **Bullion stack figures** (roadmap Phase 7, P7). A Stack page (`/stack`)
  showing fine troy ounces, melt value at spot, cost per ounce (also the
  break-even spot price), gain or loss, and the premium paid over spot at
  purchase, by metal and per item, scoped to a tag; "Fetch purchase-day spot"
  backfills what it can. A new item field, `spot_at_purchase` (the metal's
  spot price per troy ounce on the day it was bought, in the item's own
  currency), with a "Look up" button on the item form for purchases from 2
  March 2024 (`GET /api/reference/historic-spot`); older purchases take a
  hand-typed figure. Purchase-day spot is filled automatically by
  `POST /api/stack/backfill` and by the hourly loop (at most 20 a run), never
  overwriting a typed value; it comes from the public-domain fawazahmed0
  currency-api, never LBMA (see docs/price-sources.md for why). Spot-price
  threshold alerts (Settings → Alerts, `spot_alerts`, at most 12) fire once
  through the existing webhook when a metal's spot crosses a saved price and
  re-arm silently when it moves back. A `stack` dashboard widget (by metal,
  or a table of all four). The item page shows fine weight and, when known,
  the premium paid over spot at purchase. A `cabinet_stack_fine_ounces{metal}`
  metrics gauge. CSV/XLSX export and import carry `spot_at_purchase`.

### Changed
- `items.weight_g` now keeps four decimal places (was three), since a troy
  ounce is 31.1035 g and three decimals could not hold a one-ounce round;
  migration `0020`, which also adds `spot_at_purchase` and
  `spot_at_purchase_source`.

## [0.27.1] - 2026-09-20

### Added
- **Undated pieces (ND).** Year is now optional: tick "ND (no date on the
  piece)" on the item form for a piece that carries no date, with an
  optional attributed year the way catalogues write it ("ND" or
  "ND (1951)"). Migration `0019` makes `items.year` nullable and adds
  `items.year_nd`; a year of 0, the workaround people typed when the field
  was required, becomes `year_nd = true` with a null year on upgrade. Every
  item response gains `year_label` (`"1922"`, `"ND"`, or `"ND (1922)"`),
  used everywhere a year is printed (the item title, the collection list,
  the trash, the reports, the dashboard, duplicate warnings, import
  previews). The collection list gained an Undated filter (`nd=`) and sorts
  undated pieces last in either direction; the decade breakdown puts them
  in their own `Undated` bucket, after the decades. `GET /api/items/similar`
  accepts `nd` and matches an undated candidate against undated items with
  no year. CSV/XLSX export gained a `year_nd` column; import (the Cabinet
  format, a spreadsheet mapping, a Numista export file or account, and
  OpenNumismat) now reads `ND`, `N.D.`, `undated`, and `ND (1951)` /
  `(1951)` year cells, and an empty year cell imports as ND instead of
  failing the row. Fill from Numista and Add a run show `ND` / `ND (1951)`
  for an undated issue, plus its reference and comment when Numista gives
  them, and can fill or add an undated item.

### Fixed
- **A same-year Numista variety could be priced as the wrong issue.** A
  type can list more than one issue for the same year, such as a
  replacement note beside the regular one; the adapter took whichever came
  first, which for N#223126 (a 1951 Military Payment Certificate) was the
  rare, unpriced replacement note, and the estimate failed with "no priced
  grade" even though the common issue was priced. Same-year issues are now
  ranked (mint letter, replacement agreement with the item's own
  replacement flag, a match on the item's catalogue reference, variety, or
  signatures, then ND agreement) and tried in order, up to four, until one
  prices; the estimate's details record which one it used ("Priced as" on
  the item page).
- **An undated Numista issue had no way into the collection.** A German
  notgeld note Numista lists with no year (N#228576) could only be saved
  by typing year 0, which broke both its title and its Numista pricing. An
  ND item now pools against Numista's own undated issues, or against a
  type's single issue when nothing else matches (recorded as a year
  mismatch in the estimate's details).

## [0.27.0] - 2026-09-20

### Added
- **A customisable dashboard** (roadmap Phase 7, P10). The dashboard is now
  an ordered list of widgets you can add, remove, resize (full, half, or a
  third of the row), duplicate, retitle, and set options on, then arrange by
  drag or with move-earlier/move-later buttons; a keyboard path (Space or
  Enter to pick up, arrows to move, Space or Enter to drop, Escape to put
  back) with aria-live announcements does the same without a pointer. Twenty
  widget types cover value, breakdowns, the collection, pricing, and
  operations, including a breakdown chart that can be scoped to one tag or
  set. Nothing is saved until you press Save; Cancel discards the draft, and
  Reset to default puts back today's fixed dashboard, which is exactly what
  a fresh install now starts from. The layout is saved on the server
  (`GET`/`PUT`/`DELETE /api/dashboard/layout`), so it follows the
  collection, not the browser, and is carried by backups like any other
  setting. `GET /api/stats/breakdowns` gained optional `tag` and `set_id`
  filters for the breakdown widget.

## [0.26.1] - 2026-09-20

### Fixed
- **A restore could replace the database and then fail to replace the
  files.** Found on the first restore on an NFS deployment: photos uploaded
  before v0.23.1, when the backend still ran as root, sat in folders owned
  by root, and the unprivileged backend can't move a folder it doesn't own.
  The files were put back and nothing was lost, but the check belongs at the
  start. Restore now looks for folders it couldn't move before it does
  anything (the summary step refuses with the reason, and nothing is
  changed), and the backend's startup hands over any first-level entry in
  its data folders that belongs to another user, not only the folders
  themselves.

## [0.26.0] - 2026-09-20

### Added
- **Restore from inside the app.** Settings → Backups gains a Restore block:
  pick a stored archive, or upload one, and Cabinet replaces the whole
  collection (the database, and the photos and documents when the archive
  carries them) with it. An archive from an older Cabinet is migrated
  afterwards; one from a newer Cabinet is refused. Restore is destructive
  and Cabinet has no login yet, so it is fenced:
  - The archive is verified first (its manifest, a checksum for every
    member, a schema revision this build knows, and nothing but plain files
    and folders inside), and a summary shows what it holds beside what is
    here now.
  - A **safety backup** of the current state is written to the backup
    directory first (`cabinet-backup-…-prerestore.zip`) and checked. If it
    fails, the restore doesn't start. Safety backups are listed with a
    "before restore" badge, restore like any archive, sit outside **Keep
    newest**, and the newest three are kept.
  - You type `RESTORE` to confirm.
  - Nothing live changes until the archive's files are unpacked beside the
    current ones; the database is then restored in one transaction, and the
    files are swapped in only after it commits. A failure before that ends
    "Nothing was changed."; a failed file swap puts the previous files back
    and names the safety backup.
  - While it runs the rest of the app answers "restoring, try again in a
    moment", scheduled backups and price refreshes sit out, and a restore
    is refused while a backup or a scheduled task is running.
  - `RESTORE_ENABLED=false` switches the feature off: the block disappears
    and the endpoints answer 404. `RESTORE_MAX_GB` (default 20) caps an
    uploaded archive.

  `scripts/restore.sh` stays the path for when the app itself won't start.
  Saved API keys in a restored database work only with the `SECRET_KEY` in
  use when the archive was made, as with the script. Upgrading needs only
  the tag bump: there is no migration. Behind your own reverse proxy, allow
  large uploads and long timeouts under `/api/restore`
  (see docs/deployment.md). Not yet tried on NFS-backed volumes or with an
  archive made by a genuinely older release; see docs/backup-restore.md.

### Changed
- `GET /api/health` answers `db: "restoring"` (with `schema.status`
  `unknown`) while a restore runs, without touching the database, so a
  container healthcheck doesn't hang behind it.
- `GET /api/backups` rows carry `prerestore`, and stored archive names may
  end `-prerestore.zip`. Safety backups count in the
  `cabinet_backup_archives` and newest-archive metrics.
- During a restore every other API request answers `503` with
  `Retry-After: 5`.
- nginx answers 404 for any dot-name under `/photos/` (a restore's working
  folders sit inside the photo volume for a moment), and photo and document
  archives leave those folders out.

## [0.25.1] - 2026-09-20

### Fixed
- **Dashboard bar charts start at the left edge of their card.** Labels sat
  right-aligned in a fixed-width gutter, so with short labels the whole
  chart looked centred in the tile. The label column now fits the longest
  label and reads from the left.
- The Pick and Friedberg lookup links didn't appear on a note filled from
  Numista, which writes Pick as `p: P#109`. The links now recognise the
  short catalogue names (`p`, `fr`) and search for the bare number.

## [0.25.0] - 2026-09-20

### Added
- **The PCGS population on the item page.** A coin keeps how many PCGS has
  graded at its grade and how many higher, shown beside the grade with the
  date the figures were read. The cert fill brings them in, a PCGS estimate
  refreshes them from the response it already fetched (no extra call), and
  the form has the two fields for typing them in. Both are in the CSV and
  Excel export.
- **A wish list with targets.** A wishlist item takes a target price (in its
  own currency) and a priority (high, medium, low). The item page shows how
  far the newest estimate is over or under the target; the collection list,
  filtered to the wishlist, shows Priority and Target columns with a
  "reached" badge, sorts by either, and has a "Target reached" filter. Bulk
  edit sets a priority. When an estimate first comes in at or under the
  target, the alert webhook says so once. The comparison is never converted:
  it needs an estimate in the item's currency. Both fields stay with a piece
  after it is bought.
- **Paper money depth.** Notes gain a charter number, bank city, bank state,
  and plate position for National Bank Notes; search matches the charter
  number and the bank city as well as the issuer. The form suggests `pick`
  and `friedberg` as catalogues for a note, and the item page links to a web
  search for either number. The dashboard lists owned notes by series and
  signature pair.
- **Fancy serial numbers.** Cabinet reads a note's serial number and badges
  what collectors look for: solid, ladder, radar and super radar, repeater
  and super repeater, binary, trinary, low and high numbers, double quad, a
  date, and star notes. Badges show on the item page and in the list, and
  "More…" filters by any fancy serial or by one trait. Serial numbers
  already entered are read during the upgrade.
- **Die axis and dates as struck.** A coin records its die axis (medal
  alignment, coin alignment, or degrees) and, for a date written in another
  calendar, the calendar and the year as struck: Islamic, Persian, Thai
  Buddhist, Hebrew, Japanese eras (Meiji to Reiwa), Vikram Samvat, Saka,
  Minguo, Chula Sakarat, Rattanakosin, and Ethiopian. The form shows the
  Gregorian year and fills Year with it when Year is empty; a year you typed
  is never replaced. The item page reads "AH 1335 (1917)".
- Migration `0018` adds the columns (all optional) and fills in the serial
  traits. The upgrade needs nothing but the tag bump. The demo collection
  swaps two pieces for a 1902 National Bank Note and an Egyptian 20 qirsh
  dated AH 1335.

### Changed
- **The roadmap has a next phase again: Phase 7, parity with other
  collection tools**, chosen by the owner from a survey of fourteen product
  groups: population on the item page, wish-list depth, paper money depth,
  fancy serial numbers, die axis and foreign dates, bullion stack figures,
  authentication (local accounts with a first-run superuser, then single
  sign-on), and a share view that waits on authentication and is switched on or off
  as a whole in the admin's Settings (off by default); in-app restore
  is no longer blocked on authentication and comes second, with an
  automatic safety backup before it runs; labels and a
  phone app are optional. This reverses the earlier decision to ship v1.0.0
  without login, and every document that stated it now says login is
  planned and not built yet. `docs/security.md` carries the proposed
  permission table (admin, editor, viewer, API tokens, share links) and the
  decisions taken so far (one admin first, a setup code from the log,
  always on, scoped tokens from the start, more accounts optional) so it can be reviewed before any
  of it is coded.

## [0.24.9] - 2026-09-20

### Fixed
- The header and page no longer shift sideways between a short page and one
  long enough to scroll: room for the scrollbar is always reserved.

## [0.24.8] - 2026-09-20

### Fixed
- **`deploy/docker-stack.yaml` set a broken `DOCUMENT_DIR`.** One
  over-indented line (since v0.23.1) folded `REESTIMATE_DAYS` into the line
  above it, so a Swarm deployed from the repo's stack file got
  `DOCUMENT_DIR=/data/documents - REESTIMATE_DAYS=7` and refused document
  uploads. The stack file now also passes `SECRET_KEY` through; before, a
  Swarm silently used the key generated on the state volume whatever `.env`
  said.

### Changed
- **The documentation matches the build again.** Every document was checked
  against the code at v0.24.7: `docs/api.md` (about forty corrections:
  field names, limits, response shapes, error cases, the PCGS rules), the
  data model (tables, keys, and settings that had gone undocumented),
  architecture, deployment, backups, and security (the real headers and
  policy, every outbound destination, documents in backups), the README's
  feature list, CI description, and configuration table, CONTRIBUTING,
  `docs/claude-code.md`, the price-source and monitoring guides, and
  `frontend/README.md`, which still described a Phase 0 skeleton. The
  roadmap now records what shipped from the data-entry pass, the tabled API
  call counter, and the v1.0.0 decision: no application login, a stable
  API, and the checklist to get there.

## [0.24.7] - 2026-09-20

### Fixed
- The first date under a value-history chart was cut off at the left edge.

## [0.24.6] - 2026-09-20

### Fixed
- **PCGS: one old auction sale no longer outvotes the price guide.** The
  live API dates auction lots by month (`07-2003`), which Cabinet couldn't
  read, so the first real coin priced was valued from a single 2003 sale at
  a quarter of its guide value, at 75% confidence. Dates are read now; only
  sales from the last five years count (85% with five or more, 75% with
  three or four, 65% with one or two); otherwise the price guide is used,
  and old sales alone only when there is no guide value (35%). Older lots
  still appear in the estimate's details, marked as not counted. Re-run
  "PCGS value" on an item to replace an estimate made before this.
- `check_sources.py -i` takes a cert number as well as an item id, and says
  so plainly when it finds neither.

## [0.24.5] - 2026-09-20

### Fixed
- **A PCGS cert fill now spells things the way the rest of Cabinet does.**
  PCGS returns "The United States of America" and marks every Philadelphia
  coin "P", so a filled coin counted as a second country and never matched a
  checklist slot or a hand-entered duplicate. The country becomes "United
  States", and "P" is kept only where the coin carries it: wartime nickels,
  the 1979 dollar, everything but the cent from 1980, and the 2017 cent.
  Found with the first real cert (an 1864 two cents, PR-65 RB), which also
  confirmed the grade and designation parsing against the live API.

## [0.24.4] - 2026-09-20

### Fixed
- **PCGS's daily limit is 100 calls, not 1,000.** PCGS cut its documented
  default; Settings, the cert fill, and the docs now say 100 (more on
  request from PCGS), and Settings warns when a weekly refresh would need
  more than a day allows.
- The docs cited the wrong clause of Numista's API licence for the 7-day
  cache: §8.3 covers only catalogue metadata, and §8.4 (personal projects)
  is what permits a self-hosted cache at all.

## [0.24.3] - 2026-09-20

### Fixed
- The header's subtitle, navigation, and icons sat above centre once the
  logo made the wordmark taller; everything in the header is centred again.

## [0.24.2] - 2026-09-20

### Added
- **A logo**: a bronze coin with a C, in the header, as the browser-tab icon
  (`favicon.ico` with 16 to 256 px, plus SVG and an Apple touch icon), and
  at `/logo.svg` and `/logo-512.png` for dashboards.
- **A Homepage tile**: docs/monitoring.md has a ready `services.yaml` block
  for gethomepage.dev showing owned coins, owned notes, and the estimated
  collection value, read from the existing `/api/stats/collection`.

## [0.24.1] - 2026-09-20

### Changed
- **One clean typeface.** The serif titles are gone: the whole interface
  uses a Calibri-style humanist sans (Calibri on Windows, Carlito where it's
  installed on Linux, the system's own sans elsewhere), sized so the
  fallbacks match. Still nothing downloaded.
- **Dark is the default.** A browser that hasn't chosen a theme opens dark,
  whatever the system prefers; the header toggle switches and remembers.
  The README shows every page in both themes, dark first.

## [0.24.0] - 2026-09-20

### Changed
- **A look of its own.** A bronze accent in place of the blue, a warm
  off-white page (a warm near-black in dark mode), a gold rule under the
  header, and a serif for the wordmark, page titles, and the dashboard's
  headline value. The serif comes from fonts already on your system, so
  nothing is downloaded. Card headings are small capitals, so page titles
  clearly outrank them. Gain and loss colours and the badges are unchanged.
  Screenshots retaken.
- **Money reads as money**: `$2,733.42`, `CA$253.92`, `€52.00` instead of
  `2,733.42 USD`, everywhere an amount is shown. List columns no longer wrap
  an amount onto two lines, and number columns are right-aligned with
  fixed-width digits.
- **The collection page has a title row** holding "Add item" and "Add a
  run"; CSV, Excel, and Import moved into one "Export / import" menu, so the
  filter bar is one row again.
- **Import and the trash are in the navigation**, and the header's emoji
  (settings, dark mode) and the ones on buttons are now drawn icons that
  look the same on every system. On a phone the navigation wraps instead of
  running off the edge.
- **File pickers look like buttons.** Photos get one drop area with "Add
  photos", "Camera", and "Webcam"; documents and imports get a single
  button in place of the browser's "Choose File" control.
- **Plainer punctuation.** The em dashes are gone from the interface, the
  API's messages, and the documentation; sentences were rewritten rather
  than re-punctuated. Empty values show an en dash. Release headings here
  now use the Keep a Changelog form, `## [x.y.z] - date`.

## [0.23.2] - 2026-09-20

### Fixed
- The insurance report's **Acquired** column printed a dash above the source
  ("– / inherited") when an item had a source but no date.
- Asking Numista to price an item that has no Numista number (anything
  entered by hand) now links to where that's fixed ("Find it on Numista",
  the edit page's fill card) instead of only saying a reference is missing.

## [0.23.1] - 2026-09-20

### Security
- **The backend no longer runs as root.** Its container starts as root only
  long enough to hand the data directories (photos, state, backups,
  documents) to an unprivileged user, then drops to it for good. `PUID` and
  `PGID` choose that user (default `1000:1000`). Upgrading needs nothing:
  volumes and bind mounts written by earlier releases are re-owned once, on
  the first start. If they can't be (an NFS export with root squash), the
  backend says so in its log and stays root rather than failing to start.
  `restore.sh` gives restored files to the volume's owner.
- **Security headers from the proxy**: a Content-Security-Policy on the app
  (its own scripts only, no plugins, no framing), `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, and a `Permissions-Policy` that
  allows the camera and nothing else; the nginx version is no longer
  announced. Documents keep their own stricter policy.
- **A Security workflow** on every change and weekly: `pip-audit` on exactly
  what the image installs, `npm audit` on what the frontend ships, and a
  Trivy scan of both images for fixable high and critical vulnerabilities.
  Its first run found 43 in the backend image's Debian packages and two in
  libraries bundled inside pip; the image now applies Debian's pending
  updates when it's built and removes pip, and scans clean.
- **The backend image installs from a lockfile** (`backend/requirements.txt`,
  every package pinned and verified by hash), so two builds of one commit
  are the same image.

## [0.23.0] - 2026-09-19

### Added
- **Add a run.** Collection → **Add a run**: look a type up on Numista, tick
  the dates and mints you have, fill in what they share (status, grade,
  date and price paid for each, source, storage, set, tags), and get one item
  per issue, each with the type's country, denomination, composition,
  weight, and catalogue references plus its own year, mint mark, and
  mintage. Issues you already own are marked and skipped. A fifty-coin run is
  one form instead of fifty.
- **Checklists that fill themselves.** Generate a checklist from a Numista
  type (one slot per issue) or from a date range (country, denomination,
  first and last year, mint marks, and any to leave out). A slot fills when
  you own an item of that type (or that country and denomination) with
  the same year and mint mark, links to it, and reopens if the item is sold
  or trashed. Each checklist shows its completion percentage and a **needed
  to complete** view. Hand-written checklists and hand ticks work as before.
- "Fill from Numista" and the API's type lookup now say which issues you own.
- API: `POST /api/items/run`, `POST /api/checklists/generate`; checklist
  slots carry `year`, `mint_mark`, `matched_item_id`, and `matched_label`,
  checklists `match_*`, `total`, and `filled`, summaries `generated`.
  Migration `0017`.

## [0.22.0] - 2026-09-19

### Added
- **Fill from a PCGS cert.** A slabbed coin's cert number fills the item
  form in from PCGS: type, country, denomination, year, mint mark, series,
  variety, composition, weight, diameter, edge, mintage, the cert, the PCGS
  number as a catalogue reference, and, when no grade is set, the grade,
  strike, plus, and designations. Empty fields only, like the Numista fill;
  the same cached answer prices the item afterwards, so one request covers
  both. The message also says how many PCGS has graded at that grade and
  higher. Needs a PCGS API token (Settings → Price sources).
- **A duplicate warning.** As an item is entered or edited, the form checks
  for one already here with the same cert number, the same catalogue
  reference, or the same country, denomination, year, and mint mark
  (trash included), and links to it. The import preview adds the same note
  to rows it doesn't already know by their import key.
- **Look it up links** on the item page: eBay's sold listings for the same
  piece, PCGS Photograde for judging a grade, and CoinFacts when a PCGS
  number is known.
- API: `GET /api/pcgs/cert/{cert}` and `GET /api/items/similar`.

### Changed
- The dashboard's setup checklist now has **Don't show this again** instead
  of a 30-day snooze.

## [0.21.1] - 2026-09-19

### Added
- **A setup checklist on the dashboard**: what's still switched off on a
  fresh install (scheduled backups, an alert webhook or heartbeat, a
  price-source key, document storage not mounted, an empty collection), each
  linking to where it's fixed. **Hide for 30 days** puts it away; a new
  problem brings it back.
- **Browser tests.** Playwright smoke tests (`frontend/e2e/`) drive the real
  pages against the compose stack in CI: add an item, record a value, find
  it in the collection, trash it, restore it, delete it for good, and check
  every Settings section renders. `npm run e2e` locally.
- **A Swarm stack file**, `deploy/docker-stack.yaml`, ready for
  `docker stack deploy` with pulled images, one replica each, a health check
  that waits out a first boot, and named volumes to swap for shared storage.

### Changed
- The frontend's three largest files were split: the API client into
  `src/api/` (types by area, the fetch wrapper, the calls), the item page's
  photos, value history, and provenance into their own components, and the
  item form's state model and Numista fill card into `pages/item-form/`.
  Nothing changes on screen.
- README screenshots retaken on v0.21.0 (the dashboard as the home page,
  the Alerts & metrics card).
- `CLAUDE.md` is a third of its former length; the per-release
  implementation notes moved to `docs/implementation-notes.md`.

## [0.21.0] - 2026-09-18

### Added
- **Alerts.** Settings → Alerts & metrics takes a webhook URL: generic JSON
  (n8n, Home Assistant, Node-RED), ntfy, Discord, Slack/Mattermost, or
  Gotify. It sends an alert when a backup fails, Numista or PCGS rejects its
  key or runs out of quota, or a scheduled refresh has failures: once when it
  starts, and once when it's working again, never on every repeat. **Send
  test** checks the URL. The URL is stored encrypted, like the API keys, and
  only its host is shown.
- **Heartbeat** for an Uptime Kuma *Push* monitor: every hour Cabinet pushes
  `up`, or `down` with what's failing, so Kuma also notices Cabinet not
  running at all. **Push now** sends one immediately.
- **Prometheus metrics** at `/api/metrics`, off until turned on in Settings:
  items by status and type, the trash, photos and documents, collection
  value, cost basis and gains, backup and refresh outcomes, estimate
  attempts, and which alerts are failing. Computed when scraped, cached for a
  minute. See [docs/monitoring.md](docs/monitoring.md).
- Settings shows each check's state and each source's last scheduled refresh
  (updated, skipped, failed, and why).
- API: `POST /api/alerts/test` (`?target=heartbeat` for the heartbeat) and
  `GET /api/metrics`; settings `alert_webhook_url`, `alert_webhook_format`,
  `heartbeat_url`, and `metrics_enabled`, and read-only `alerts`,
  `alert_delivery`, `heartbeat`, and `refresh_last_run`.

### Changed
- A scheduled Numista or PCGS refresh **stops at the first rejected key or
  exhausted quota** instead of trying, and failing, every remaining item.
- The scheduled melt refresh counts an item that no longer qualifies (its
  weight or metal was removed) as skipped rather than failed.
- PCGS answering 401 is reported as a rejected token and 429 as an exhausted
  quota, alongside its existing 500 = bad token.

## [0.20.0] - 2026-09-18

### Added
- **A trash for deleted items.** Deleting an item (on its page, or several
  selected on the Collection page with the new **Move to trash**) moves it to
  the Trash with its photos, documents, values, sales log, and history, and
  **Restore** brings it back exactly as it was. The Trash page (linked from
  the Collection page) restores or deletes items for good one at a time, by
  selection, or all at once with **Empty trash**. A trashed item still opens,
  read-only, with a banner saying so. The edit history records "trashed" and
  "restored".
- **The trash empties itself**: items deleted more than 30 days ago are
  deleted for good by the hourly background task. Settings → General sets
  it to 7, 30, 90, or 365 days, or never.
- Trashed items are left out everywhere else: the collection, dashboard,
  Pricing reports, exports, the insurance report, set and tag counts, and
  scheduled refreshes. A document shared with a trashed item stays until
  that item is deleted for good, and importing a source again skips items in
  the trash and says so.
- API: `POST /api/items/{id}/restore`; `GET /api/trash`, `DELETE /api/trash`
  (empty it), and `POST /api/trash/{items,restore,purge}` for several items;
  items carry `deleted_at`; the setting `trash_retention_days`. Backup
  manifests count items in the trash. Migration `0016`.

### Changed
- **`DELETE /api/items/{id}` moves the item to the trash** instead of deleting
  it; `?permanent=true` deletes it for good, as does deleting an item that's
  already in the trash. Item endpoints treat a trashed item as missing (404)
  until it's restored, except `GET /api/items/{id}`.

## [0.19.0] - 2026-09-18

**Upgrading: documents need a volume.** The backend now stores attached
documents in `/data/documents` (`DOCUMENT_DIR`). Compose adds a
`document_data` volume for it; a Swarm or bind-mount deployment must add a
mount there, as for photos. See
[deployment.md](docs/deployment.md#2-storage). Until it's mounted, document
uploads are refused (Settings → About says so) rather than stored inside the
container, where a redeploy would lose them.

### Added
- **Documents on items**: receipts, invoices, certificates of authenticity,
  grading labels, appraisals, correspondence (PDFs, JPEG, PNG, or WebP up to
  25 MB), dropped onto or picked in the item page's new Documents card, each
  with a kind, title, date, and note, and a thumbnail (a PDF's first page).
  They open in the browser's own viewer, or download with their original
  name.
- **One document, several items**: "attach to other items…" links a lot's
  invoice to every coin in it. Removing a document from an item leaves it on
  the others; the file is deleted with the last item that holds it.
- Documents are stored on their own volume, never the public photo path,
  and served only through the API: the type is detected from the file's
  bytes (PDFs must open in PDFium), SVG, HTML, and everything else are refused,
  and responses carry `nosniff` and a content security policy. HEIC photos are
  refused with a note to export them as JPEG.
- **Backups include documents**: `documents.tar.gz` in the in-app archive
  (with its checksum in the manifest), in `scripts/backup.sh`, and restored
  by `scripts/restore.sh`. Data-only archives leave them out, like photos;
  archives from before this release leave existing documents in place.
- API: `GET/POST /api/items/{id}/documents`, `PATCH/DELETE
  /api/documents/{id}`, `POST /api/documents/{id}/items`, `DELETE
  /api/items/{id}/documents/{doc}`, `GET /api/documents/{id}/file` and
  `/thumb`; item details include `documents`; `/api/health` reports
  `documents` storage status. Migration `0015` adds `documents` and
  `item_documents`. New dependency: pypdfium2 (PDF thumbnails;
  Apache-2.0/BSD).

## [0.18.2] - 2026-09-18

### Fixed
- **Numista imports read titles written with quotes.** Numista titles come as
  `¼ Dollar "Washington Quarter"` as well as `1 Dollar - Eisenhower`; the
  quoted form was taken whole as the series. Now the name becomes the series
  and the rest the denomination, for the account import and the export file.
- **Importing your Numista collection brings the type's other catalogue
  numbers** (KM#, Schön#, Pick#…) along with the Numista number, from the same
  catalogue lookup, as "Fill from Numista" on the item form already did.
- The preview no longer says a denomination was "taken from the type's title"
  when the import is about to fill it in from Numista's catalogue; it says so.

## [0.18.1] - 2026-09-18

### Fixed
- **A Cabinet export imports in full from the Import page**, as CSV *or*
  Excel. It's recognised by its columns and read with every field (grades
  with designations, sets, custom fields, sale details…), with a preview
  like the other formats. The export's item id is the import key, so
  importing the same export twice (into this Cabinet or another) skips
  what's already there. In v0.18.0 it was read as an ordinary spreadsheet,
  which left out 27 of its columns.
- Spreadsheet columns named with underscores (`acquisition_date`,
  `cert_number`) are matched to their fields.
- The CSV export starts with a UTF-8 byte-order mark, so Excel shows accented
  names ("Schön") correctly instead of "SchÃ¶n", and an export with nothing
  in it still has its header row.

### Changed
- The Import page's separate "A Cabinet export" choice is folded into "A
  file from another tool", which detects the format.
  `POST /api/items/import` still takes the CSV directly.

## [0.18.0] - 2026-09-18

### Added
- **Import from other collection tools.** A new Import page (Collection →
  Import) with a preview before anything is added:
  - **My Numista collection**: reads the collection on your own Numista
    account with the API key already in Settings: grade, quantity, price
    paid, acquisition date and place, storage, comments, and slab details
    (grading company, slab grade, number, CAC sticker, designations). It
    fills in denomination, composition, weight, and size from the catalogue
    (one request per type, cached a week). Pictures can be downloaded too
    (off by default). Tokens and medals aren't imported.
  - **Numista's export file** (CSV or Excel), read by column name.
  - **OpenNumismat collections** (the `.db` file, OpenNumismat 1.9 to 1.11,
    including 1.11's new layout for purchases and sales), with their photos.
  - **Any spreadsheet** (CSV or Excel), whether from uCoin, CoinSnap,
    Colnect, PCGS's registry, or a hand-kept sheet, with its columns matched
    to Cabinet's fields: Cabinet suggests the matches from the column names,
    finds a header below lines of preamble, and takes defaults for type,
    status, country, and currency. Prices like "$1,250.00" and "1.234,50" and
    US or European dates are understood.
  - Grades written any usual way are read: MS-64, PF-69 DCAM, 64 EPQ, XF,
    "Choice Very Fine", BU. Numista's G…UNC bands become the lowest grade of
    each band (VF → VF-20), noted in the preview.
  - Importing the same source again skips items already imported: each
    imported item remembers where it came from.
  - Cabinet's own CSV export still imports as before, now from the same page.
- `docs/import-samples/` holds synthetic files in each format to try it with
  (built by `python -m tests.import_samples`).
- API: `POST /api/imports` (stage a file), `POST /api/imports/{id}/preview`,
  `POST /api/imports/{id}/run`, `DELETE /api/imports/{id}`, and
  `POST /api/imports/numista/{preview,run}`. Migration `0014` adds
  `items.import_source` and `import_key`.

### Changed
- The Collection page's "Import CSV" button is now "Import", opening the
  Import page. nginx accepts uploads up to 1 GB on `/api/imports` (an
  OpenNumismat file carries its photos).

## [0.17.0] - 2026-09-18

### Added
- **Sales log and comps estimates** (sold-listing comparables). Each item has
  a sales log of what pieces like it actually sold for: date, where (with a
  link and lot), the grade as sold, price, whether buyer's premium is
  included, and any fees on top. A new **comps** price source estimates the
  median of recent logged sales (the last three years, or older ones when
  fewer than three are that recent), converted into the display currency,
  with confidence from the number of sales and how far apart they are. The
  sales behind each estimate show in its value-history details, and a sale
  can be left out without deleting it. Comps works everywhere a source does:
  the value strategy (preferred or averaged), the item list's source column,
  and the Pricing reports. The item page also lists free places to look up
  sold prices.
- **Numista auction sales** (Settings → Price sources, off by default): a
  button on the sales log that copies the auction results Numista records
  for the item's year and mint into the log. **This needs Numista's paid API
  plan**: a free key gets "Permission denied", which Cabinet explains
  rather than reporting a bad key. Runs only when clicked; a repeat the same
  day is served from cache.
- `scripts/check_sources.py` probes `comps` and `numista-sales` too.
- API: `GET/POST /api/items/{id}/comparables`,
  `PATCH/DELETE /api/comparables/{id}`, `POST /api/items/{id}/comparables/numista`;
  `?source=comps` on `POST /api/items/{id}/estimate`; item details include
  `comparables`. Migration `0013` adds the `comparables` table.

### Changed
- Numista catalogue data (a type, its issues, and searches) is cached for 7
  days instead of 30, the longest Numista's API licence allows.

## [0.16.0] - 2026-09-18

### Added
- **Photo tools on the item page** (the roadmap's "photo niceties" bundle):
  - **Lightbox**: click a photo to view it full size; click or scroll to zoom
    where you point, move the pointer to pan, ←/→ to step through, Esc to
    close.
  - **Edit**: crop, turn 90°, and straighten (±15°, scaled so no empty
    corners appear) in the browser at full resolution, then replace the photo
    or save the edit as a new photo.
  - **Drag and drop** image files onto the Photos card, or **paste** an image
    anywhere on the item page.
  - **Import from URL**: the backend fetches the image, following up to three
    redirects and stopping at 25 MB, and refuses private and local network
    addresses.
  - **Webcam**: take photos straight into the item from a webcam or a phone's
    camera (needs HTTPS or localhost).
  API: `POST /api/items/{id}/photos/url` and `PUT /api/photos/{id}/image`.

### Changed
- **The dashboard is the home page**, first in the menu; the collection list
  moved to `/collection`. Old links still work: `/dashboard` and `/` with list
  filters redirect to the new addresses.
- Photo upload errors show on the Photos card instead of replacing the whole
  item page.

## [0.15.0] - 2026-09-15

### Added
- **Fill an item in from the Numista catalogue.** The item form's new
  **Fill from Numista** card takes a Numista number (`N#1493`, or just
  `1493`) or a name search, and fills the fields that are still empty:
  country, denomination, series, composition, fineness (read from the
  composition for precious metals), weight, diameter, thickness, edge, and
  shape for coins; country, denomination, and issuing bank for notes; the
  year when the type has only one. It adds the Numista number and the type's
  other catalogue references (KM, Pick…) as catalog refs, and lists the
  type's issues so picking one sets the year, mint mark, and mintage.
  API: `GET /api/numista/search?q=&category=` and
  `GET /api/numista/types/{id}`.
- Lookups need only a Numista API key, not Numista pricing switched on.
  They use the same cache and quota as pricing: a search or a type costs one
  request, cached for 30 days, and a type's issues share their cache entry
  with Numista estimates.

## [0.14.0] - 2026-09-15

### Added
- **Grading depth.** A strike type on every item (business, proof, specimen):
  a proof or specimen on the Sheldon scale reads PR-/SP- with the same grade
  number. Plus grades, the NGC/PMG star, designations (PL, DMPL, CAM, DCAM,
  UCAM, RD, RB, BN, FB, FBL, FH, FS, FT, and PMG's EPQ), CAC stickers, and
  "details" grades recording the problem (cleaned, damaged…). Items carry a
  `grade_label` that reads like the holder (`PR-69 DCAM ★`, `MS-64+ RD`,
  `VF-20 Details (Cleaned)`), shown in the list, item page, and report. PMG's
  grades 1–3 are now on the scale.
- **Coin physical fields** (diameter, thickness, edge, shape, mintage) and
  **banknote fields**: serial number, prefix/block, signatures, issuer, and a
  replacement/star-note flag. Serial numbers, prefixes, and issuers are
  searchable.
- **Fees in gains.** `acquisition_fees` (buyer's premium, shipping, tax) count
  toward cost basis; `sold_fees` and `sold_to` record the sale. Items expose
  `cost_basis` and `sale_proceeds`.
- **Certificate verification links** on the item page: PCGS opens the
  certificate directly; NGC and PMG open their lookup pages.
- A **strike filter** on the list (`?strike=`), and all new fields in CSV/XLSX
  export and CSV import. Import also reads grades written the way holders
  write them: `PR-65`/`PF-65`/`SP-65` set the strike, and a trailing `+` sets
  the plus grade.

### Changed
- **Cost basis, unrealized and realized gain are net of fees** everywhere:
  dashboard, gains tables, breakdowns, and the insurance report's Cost column.
  The accuracy report still compares estimates with the gross sold price,
  since estimates are market prices.
- **Numista no longer prices proofs, specimens, or details grades**: its
  prices are for problem-free circulation strikes. **PCGS** passes the plus
  grade through, labels proofs PR-, and prices a details-graded coin only by
  its cert number.

### Fixed
- CSV import no longer loses the rows it had already imported when a later
  row fails validation.

### Upgrade notes
- Revision `0012` adds the new item columns and PMG grades 1–3; the backend
  applies it on startup.

## [0.13.0] - 2026-09-14

### Added
- **Pricing reports.** A new **Pricing** page (also linked from the
  dashboard's "based on X of Y owned items" line) with four reports:
  - **Coverage**: per automatic source, how many owned items are priced,
    can't be priced, failed, or haven't been tried, and for each item that
    needs attention, why: the source is off, a prerequisite is missing (no
    catalog ref, no grade, no weight…), what the source itself said, or the
    fetch error.
  - **Stale estimates**: each item's latest estimate per source older than
    7/30/90/365 days (manual entries included), plus any built from source
    data already past its cache window, marking which ones feed the shown
    value.
  - **By source**: items priced, total, average confidence, and median age
    per source; how many items' shown value each supplies under the current
    value strategy; and the items where sources disagree most.
  - **Accuracy against sales**: for sold items, the estimates standing on
    the sale date against the realized price: median error, bias, and how
    many landed within 20%, for the shown value and for each source.
  API: `GET /api/pricing/coverage`, `/stale?days=`, `/sources`, `/accuracy`.

### Changed
- Every automatic pricing attempt (from the item page or the scheduled
  refresh) now records its outcome per item and source (revision `0011`,
  `estimate_attempts`), so a failed fetch or an upstream "can't price this"
  is visible later instead of vanishing with the error message. Applied
  automatically on startup.

## [0.12.0] - 2026-09-14

### Added
- **Backups from inside the app** (Settings → Backups). **Download backup**
  builds one `.zip` holding the database dump, the photos, a
  `manifest.json` (app version, schema revision, counts, SHA-256 per member),
  and a `SHA256SUMS` file; **Data only** leaves the photos out. **Scheduled
  backups** write archives daily or weekly into a backup directory, keep the
  newest N, retry a failed run within the hour, and show the last outcome.
  **Back up now** writes one on demand, and stored archives are listed for
  download. API: `GET /api/backup.zip`, `GET`/`POST /api/backups`,
  `GET /api/backups/{name}`; settings `backup_schedule`, `backup_keep`,
  `backup_include_photos`.
- `scripts/restore.sh` restores an in-app archive directly: it verifies the
  checksums first, and a data-only archive restores the database without
  touching photos.
- CI rehearses a restore on every push: download an archive, delete an item,
  restore, and check the item is back.

### Changed
- The backend image carries `pg_dump` and `pg_restore` for PostgreSQL 14–18
  and dumps with the one matching the server's major version, so archives
  restore with the server's own `pg_restore`.
- nginx gives `/api/backup*` up to 30 minutes to respond, since an archive is
  built before the download starts.

### Upgrade notes
- `docker-compose.yaml` adds a `backup_data` volume mounted at `/data/backups`
  (`BACKUP_DIR`). **On a Swarm or custom stack, mount a directory there**
  (ideally NAS storage), or scheduled archives live inside the container and
  disappear with it. It must not be inside the photo directory; the backend
  refuses that, because nginx serves photos publicly.
- The backup endpoints are unauthenticated, like the rest of the API, and one
  request returns the whole collection. Keep Cabinet behind an
  authenticating proxy (see docs/deployment.md).

## [0.11.1] - 2026-09-14

No manual migration step from this release on: the backend applies pending
migrations itself when it starts (set `AUTO_MIGRATE=false` to opt out).

### Added
- **Settings → About** shows the running version (linked to its release) and
  the database schema: current revision, and whether it's up to date, waiting
  on a migration, or ahead of this build. `GET /api/health` reports the same
  under a new `schema` field.

### Changed
- **The backend applies database migrations itself on startup**, before it
  serves anything, so upgrading is now just deploying the new image, with no
  separate `alembic upgrade head`. All pending migrations run in one
  transaction under a Postgres advisory lock; a failure rolls back and stops
  startup instead of leaving new code running on an old schema. On Swarm,
  where there's no startup ordering, the backend waits up to 60 seconds for
  Postgres first. Set `AUTO_MIGRATE=false` to keep running migrations by hand.
  Going back to an older image still doesn't undo a migration.

### Fixed
- The backend's own INFO logs never reached the container log (uvicorn only
  configures its own loggers), so scheduled price refreshes ran silently. The
  `app` and `alembic` loggers now log at INFO, which also shows migrations
  applied at startup.

## [0.11.0] - 2026-09-14

After upgrading, run `alembic upgrade head` (revision `0010`).

### Added
- **Estimate provenance** (pricing program M4). Automatic estimates now keep
  what produced them in a new `price_estimates.details` column (revision
  `0010`) instead of just a value and a terse source string: melt records the
  weight, fineness (and whether it came from the field or the composition
  text) and spot price; Numista the matched issue, the grade wanted versus
  priced, and the full per-grade price list; PCGS the lookup, the auction lots
  behind the median, the price-guide value, and the CoinFacts link. Each also
  records when the upstream data was fetched and whether a stale cached copy
  was served because a refresh failed. On the item page, a "details" toggle
  under each value-history row shows it.
- Value history on the item page can be filtered by source; the chart then
  plots one source at a time instead of zig-zagging between them.
- Manual values take an optional note (up to 500 characters), kept and shown
  the same way.

### Changed
- On-demand and scheduled estimates now build their rows through one helper
  (`pricing.estimate_row`); the scheduled melt refresh had been dropping
  `sample_size`. `pricing.cached_response` became `cached_fetch`, which also
  returns when the payload was fetched.

## [0.10.2] - 2026-08-12

### Added
- **Published images.** Tagged releases now build and push
  `ghcr.io/jsaumer/cabinet-numismatics-backend` and `...-proxy` to GHCR
  (`.github/workflows/ci.yml`, `publish` job), tagged with both the release
  version and `latest`. `docker-compose.yaml` gained matching `image:`
  entries alongside its existing `build:` blocks: local dev keeps building
  from source with `docker compose up --build`, while `docker stack deploy`
  (which cannot build at all) now has something to pull. Documented in
  `docs/deployment.md` §7, including the two Compose keys (`depends_on`,
  `restart`) that Swarm doesn't honor and what that actually means in
  practice for this stack.

### Changed
- `nginx.conf` is now baked into the proxy image at build time instead of
  bind-mounted from the host, because a bind mount can't be relied on to exist
  across every node in a multi-host deployment. The proxy image's build
  context moved from `frontend/` to the repo root so its Dockerfile can
  reach `proxy/nginx.conf`; a new root `.dockerignore` keeps that context
  from also picking up `backend/`, `.git`, and other irrelevant content.

## [0.10.1] - 2026-08-11

### Added
- A `SOURCE` column on the collection list, next to `VALUE`: the blended
  value shown there was giving no indication of which price source (or
  "average") it came from. Backed by a real schema change: `GET /api/items`
  entries now carry `latest_value_source`, resolved by the same
  `pricing.resolve_display_value` used for the value itself, not guessed
  separately on the frontend.

### Fixed
- The item page's per-source value chips could wrap mid-pill (value on one
  line, the "time since" label pushed to a second) once a source's key or
  timestamp made a chip too wide for its grid cell. Chips now lay out in a
  wrapping flex row spanning the full card width, each pinned to a single
  line.

## [0.10.0] - 2026-08-11

### Added
- **Numista price adapter** (pricing program M2): coins *and* notes priced by
  their `numista` catalog reference and grade. `POST /api/items/{id}/estimate`
  takes a `?source=` parameter (`melt`, the default, or `numista`), and the
  item page shows a button per configured source. Requires a free Numista API
  key in Settings; the source stays off until you switch it on.
- New `source_cache` table (revision `0009`) caching upstream price-source
  responses (Numista catalogue data for 30 days, prices for 7), so repeated
  estimates don't burn the free tier's 2,000 requests a month. A stale entry
  is preferred to a failed request, matching how spot prices and exchange
  rates behave.

- **PCGS price adapter** (pricing program M3): US coins priced by PCGS cert
  number, or by `pcgs` catalog reference + Sheldon grade, via
  `?source=pcgs`. CoinFacts returns both numbers in one request: realized
  auction prices win when PCGS has any (median of up to the ten most recent
  lots, confidence 0.85 with five or more sales, 0.75 below), and the price
  guide is the fallback at 0.60. Coins only: PCGS Banknote responses carry
  no price fields. Requires a token from pcgs.com/publicapi.

- `backend/scripts/check_sources.py` runs one price adapter against one real
  item and prints the upstream calls, the raw payload, and the parsed
  estimate, without saving anything. The unit tests prove the parsing; this
  checks the contract. Ships in the backend image, so
  `docker compose exec backend python scripts/check_sources.py --list` works.
  Long string fields in a payload (e.g. PCGS's `CoinFactsNotes` essays) are
  now trimmed like long lists already were.

- **Per-source value display and a configurable value strategy.** With more
  than one price source configured, they don't agree, so the item page now
  shows each source's own latest value as a chip instead of collapsing to
  whichever is newest. A new `value_strategy` setting (Settings → General)
  controls the single blended number used everywhere else (items list,
  CSV/XLSX export, dashboard totals): latest estimate (default, unchanged
  behavior), a preferred source (falling back to latest if that source
  hasn't priced the item yet), or an average across melt/Numista/PCGS
  (currency-converted; manual entries excluded from the average for now).

- **Scheduled auto-refresh for Numista and PCGS, and item-level freshness.**
  The existing 12h melt-refresh loop now also refreshes each owned item's own
  Numista and/or PCGS estimate independently of whichever source currently
  wins the item, needed since `value_strategy` can be "preferred source" or
  "average," where a non-winning source still needs its own data current.
  Both are off by default: Numista offers 7/14/30-day cadences (Settings
  shows the real projected monthly call count against the free tier's
  2,000/month, since Numista costs 2 calls per estimate against PCGS's 1),
  PCGS is a simple weekly on/off (its 1,000 calls/day quota comfortably
  covers weekly refresh at any realistic collection size). `GET /api/settings`
  now reports `numista_priceable_items`/`pcgs_priceable_items` to drive that
  math. The item page's per-source value chips now show a relative
  "time since" next to each value, and manual per-item refresh buttons now
  show a success message, not just silence on success / an error on failure.
  The blended value shown in the items list/export/dashboard has no single
  "since" timestamp when averaging sources, so this freshness label is
  deliberately scoped to the item detail page only.

### Changed
- Price adapters now share one contract: `NotApplicable` for a missing
  prerequisite (422) and `SourceUnavailable` for an upstream failure (502).
  `SpotUnavailable` is a subclass, so melt behavior is unchanged. Response
  caching is shared too (`pricing.cached_response`).

## [0.9.1] - 2026-08-10

No user-facing changes: no schema change (still revision `0008`), no API
change, and identical application behavior. This release exists mainly
because the test suite could not be run from a fresh checkout of 0.9.0.

### Fixed
- `pytest` failed on a clean clone with nine collection errors
  (`ModuleNotFoundError: No module named 'tests'`). The suite needs the
  project root on `sys.path`; that only happened by accident under legacy
  editable installs, which add the whole directory, while modern setuptools
  exposes just the configured `app*` packages. Fixed with
  `pythonpath = ["."]` in the pytest config.
- Committed `frontend/package-lock.json`. Without it, CI's Node setup had no
  lock file to cache from, and every build floated to the newest matching
  dependency versions. CI and the container build now use `npm ci`.

### Changed
- Base images updated: backend to Python 3.14, frontend build to Node 26,
  proxy to nginx 1.31. The CI matrix now covers Python 3.10 (the supported
  floor) and 3.14 (what the container runs).
- GitHub Actions updated: `checkout` v7, `setup-node` v7, `setup-python` v7.
- Frontend toolchain updated: Vite 8, `@vitejs/plugin-react` 6, TypeScript 7.
  Vite 8 and the plugin must move together: their peer ranges don't overlap
  across the boundary. TypeScript 7 also requires `src/vite-env.d.ts`, which
  supplies the type declarations for `import './styles.css'`.

### Added
- `frontend/src/vite-env.d.ts` referencing Vite's client types.

## [0.9.0] - 2026-08-09

First public release. Pre-1.0 signals that the HTTP API may still change; the
data model and migration path are considered stable.

### Cataloging
- Coins and notes with country, denomination, year, mint mark, series,
  variety, composition, weight, fineness, quantity, and notes.
- Sheldon and PMG grading scales, seeded by migration; certification tracking
  (service + cert number).
- Provenance (acquisition date, price, source), storage location, and
  `owned` / `sold` / `wishlist` status with sold date and realized price.
- Tags, catalog references (Krause / Numista / Red Book), sets and lots, and
  up to 20 custom fields per item.
- Search across notes, series, variety, cert numbers, catalog refs, and tags;
  combined filters for type, status, country, year range, grade range,
  latest-value range, tag, and set; filters and paging persist in the URL.
- Clone an item, bulk-edit a selection, and per-item append-only edit history
  with field-level diffs.
- Completeness checklists for target sets, with progress tracking.

### Photos
- Multiple photos per item with angle designation, a primary image, and
  reordering; multi-file upload and a direct camera input on mobile.
- Uploads are validated as real JPEG/PNG/WebP by decoding them; EXIF
  orientation is corrected and thumbnails are generated automatically.

### Valuation
- Manual estimates with source and optional confidence, stored append-only.
- Melt-value estimates (spot × weight × fineness × quantity) with the metal
  detected from composition; spot prices cached 12h with stale fallback.
- Scheduled re-estimation of stale melt values; a melt refresh never
  supersedes a manual value.
- Multi-currency totals converted at cached daily ECB rates; amounts with no
  obtainable rate are excluded and counted rather than guessed.
- Collection and per-item value-over-time charts.

### Insights and reporting
- Dashboard with collection value, cost basis, realized and unrealized
  gain/loss, breakdowns by country, type, decade, grade and tag, and
  acquisitions by year.
- CSV and Excel export honoring the current filters; CSV import round-trips
  the export format with per-row error reporting and id-based deduplication.
- Print-optimized insurance report (browser Print → PDF).

### Platform
- Three-service Docker Compose stack (nginx proxy, FastAPI backend,
  postgres); the frontend builds inside the proxy image, so no host Node or
  Python is required.
- Alembic migrations end to end (revisions `0001`–`0008`).
- Settings page for display currency, melt cadence, and price-source
  credentials. Credentials are **encrypted at rest** (Fernet, with key
  rotation via `SECRET_KEY`) and are write-only through the API.
- Backup and restore in one script pair covering the database and photos
  together, with a rehearsed restore drill.
- Dark mode, responsive layout, and auto-generated OpenAPI docs.
- `GET /api/health` reports status, database reachability, and version.

### Known gaps
- No application-level authentication: deploy behind an authenticating
  reverse proxy. See [docs/security.md](docs/security.md).
- Sold-listing comparables are not integrated (eBay's Marketplace Insights
  API is closed to new applicants); record those values manually.
- Numista and PCGS adapters are planned; their credentials can be configured
  in Settings already.
- Photo lightbox, drag-and-drop upload, URL import, and in-browser editing
  are not built yet.

[Unreleased]: https://github.com/jsaumer/cabinet-numismatics/compare/v0.9.1...HEAD
[0.9.1]: https://github.com/jsaumer/cabinet-numismatics/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/jsaumer/cabinet-numismatics/releases/tag/v0.9.0
