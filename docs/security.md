# Security

Cabinet is a single-user, self-hosted application. The design assumes the
stack runs on a network you control, and that the operator is the only user.
This document records what that means concretely, what is protected and how,
and what you must do before exposing the app more widely. There is no
application login yet: it is the next thing built, as v0.30.0 and v0.31.0,
both before v1.0.0. See Authentication & network exposure below.

## Secrets at rest

Price-source credentials (Numista API key, PCGS token), and the alert webhook
and heartbeat URLs (which usually carry a token) are **encrypted before
they reach the database**, using [Fernet](https://cryptography.io/en/latest/fernet/)
from the `cryptography` library: AES-128-CBC with an HMAC-SHA256
authentication tag. Encryption is authenticated, so a tampered value fails to
decrypt rather than yielding garbage, and each write uses a fresh random IV,
so storing the same key twice produces different ciphertext.

Stored values carry an `enc:v1:` prefix identifying the scheme, which leaves
room for future algorithm changes without ambiguity.

**These credentials are also write-only through the API.** `GET /api/settings`
returns whether a secret is configured plus a last-4 hint (`…abcd`), never
the value. There is no endpoint that reveals a stored secret, and secrets are
never written to logs, error messages, or URLs (they travel only in `PUT`
request bodies).

If a secret cannot be decrypted (the key was rotated away or lost), the app
reports that source as *not configured* rather than failing. Re-enter the key
in Settings. **A value stored as plain text is never used** (from v0.30.0):
Cabinet only ever writes encrypted values, so plain text came from somewhere
else, such as an edited backup archive planting a webhook address. It reads
as unset, and at startup and every hour it is cleared, never encrypted in
place, and named (by name only) in the log, through the alert webhook if one
is still saved, and in a Settings banner ("Re-enter: alert webhook") until
it is entered again. Every secret saved since v0.10 is already encrypted.

## Key management

The encryption key comes from the `SECRET_KEY` environment variable, set in
`.env`. Generate one with:

```bash
docker compose run --rm backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**If `SECRET_KEY` is unset**, the backend generates a key on first use and
persists it to `SECRET_KEY_FILE` (default `/data/state/secret.key`) on the
private `backend_state` volume, created with owner-only (`0600`) permissions.
This keeps the app working out of the box, but setting `SECRET_KEY` explicitly
is strongly preferred: it survives a rebuilt volume, and it puts key custody
where you can see it.

The key file is deliberately **not** stored under `PHOTO_DIR`. nginx serves
that directory publicly at `/photos/`, so a key placed there would be
retrievable over HTTP.

### Rotation

`SECRET_KEY` accepts a comma-separated list. The **first** key encrypts; **any**
key in the list can decrypt. To rotate:

1. Put the new key first, keep the old one: `SECRET_KEY=<new>,<old>`
2. Restart the stack, then re-save each key in Settings (which re-encrypts it
   under the new key).
3. Drop the old key from the list.

## What is *not* encrypted

The collection data itself (items, photos, documents, estimates) is stored
unencrypted in postgres and on the photo and document volumes. For a
personal catalog on your own
hardware this is the appropriate trade-off: it keeps backup, restore, and
inspection simple. If the host is untrusted or portable, use full-disk or
volume-level encryption underneath the stack rather than application-level
encryption.

Backups (`scripts/backup.sh`, and archives from Settings → Backups) contain
the database, so they contain the **encrypted** credentials, but not the
key, which lives in `.env` or on the state volume. A backup restored without
the matching key works fine; you just re-enter the source API keys. Treat
`.env` as sensitive: it holds the database password and the encryption key.

**Every archive is itself encrypted** (v0.30.0) with the backup key, an
[age](https://age-encryption.org) X25519 identity from `BACKUP_KEY_FILE` or
generated into `backup.key` on the state volume, and carries a MAC keyed by
that key: an archive on the backup share can be neither read nor forged
without it, and only encrypted archives made with this deployment's key are
restored. Nothing unencrypted is ever written to `BACKUP_DIR`; decryption
happens only in the private `/data/staging` volume. The key is shown only by
`python -m app.cli backup-key show` in the container, never over the API;
keep a copy outside Cabinet, since losing it makes the archives unreadable
by design. Cabinet reports whether a generated key shares storage with the
backups (separate, shared, or not verified); supply it as a secret when
backups leave the host. See
[backup-restore.md](backup-restore.md#the-backup-key).

The in-app backup endpoints (`/api/backup.zip`, `/api/backups/…`) are as
unauthenticated as the rest of the API, but they hand over the entire
collection (database, photos, and documents) in one request. That is
acceptable on a
trusted LAN or behind an authenticating proxy, and a clear reason not to
expose the stack directly. The backup directory is kept out of the publicly
served photo volume: the backend refuses a `BACKUP_DIR` inside `PHOTO_DIR`.

**Restore from inside the app** (`/api/restore/…`, v0.26.0) is open in the
same way, and it is the most destructive thing the API does: it replaces
the database, the photos, and the documents. The owner chose to ship it
before login because anyone who can reach an open Cabinet can already
download everything and delete everything. Until authentication ships
(when it becomes admin-only, see the table below), what stands in front of
it:

- **Verification before anything changes**: the archive decrypted with the
  backup key, in private staging; its MAC (v0.30.0), which covers the
  manifest and every member's checksum, so an altered or forged archive is
  refused; a SHA-256 for every member; a schema revision this build knows;
  and the tar-member rules under Input handling. An archive older than the
  newest this Cabinet recorded needs `RESTORE OLDER`, so a rollback can't
  happen quietly.
- **A safety backup first**: the current state is written to `BACKUP_DIR`
  and verified, and the restore doesn't start without it. Pre-restore
  archives are outside the retention count, and the newest three are kept.
- **A typed phrase** (`RESTORE`, or `RESTORE OLDER`) on the request that
  starts it. That guards against accidents, not against an attacker.
- **An off switch**: `RESTORE_ENABLED=false` makes every restore endpoint
  answer 404, leaving `scripts/restore.sh` (which needs a shell on the
  host) as the only way. Set it on any deployment where restore from the
  browser isn't wanted.

A restored database carries its own encrypted secrets; they decrypt only
with the `SECRET_KEY` in force when the archive was made, otherwise they
read as not set. An uploaded archive can therefore replace saved keys and
webhook addresses only with values it could already have set through
Settings.

`/api/metrics` is off by default. Turned on, it's as open as the rest of the
API and includes the collection's value and cost; scrape it over the
internal Docker network (see [monitoring.md](monitoring.md)) rather than
exempting it from an authenticating proxy. Alert webhooks and heartbeats send
only a check's name and its error message, never collection data.

Importing a photo from a URL makes the backend fetch it, so the fetch is
fenced: only http(s), only hosts that resolve to public addresses (private,
loopback, link-local (including cloud metadata at 169.254.169.254), and other
non-global addresses are refused, at every redirect hop), at most three
redirects, 25 MB, and 15 seconds, and the result must still pass the same
image validation as an upload. A DNS answer that changes between the check
and the fetch is not covered; for a single-user app behind its own proxy
that is an accepted gap.

## Authentication & network exposure

Cabinet has **no application-level authentication yet, and it is the next
thing being built**: roadmap Phase 7, P8, shipping as **v0.30.0** (one admin,
database-backed sessions, scoped API tokens, and a deny-by-default gate) and
**v0.31.0** (OpenID Connect single sign-on and a trusted-header mode). The
design is settled rather than sketched, and is written out under "Next:
accounts and permissions" below. Until those releases land, everything in
this section is what stands between the collection and anyone who can reach
the port:

- Put it behind an authenticating reverse proxy (for example Traefik with a
  forward-auth or SSO gateway such as Authentik, Authelia, or oauth2-proxy),
  which requires no application changes. Keep one there after v0.30.0 too,
  until v0.31.0 brings single sign-on and two-factor sign-in.
  [deployment.md](deployment.md) has the configuration.
- Terminate TLS at the proxy so credentials entered in Settings and photos are
  not transmitted in the clear.
- Do not port-forward the stack to the internet as-is.

Photos under `/photos/` are served by nginx without going through the API;
their UUID file names are not guessable, but only the reverse proxy's
authentication actually protects them, like everything else. Any path under
`/photos/` with a segment starting with a dot answers 404, so a restore's
working folders inside the photo volume are never served. When login ships,
nginx authorises each photo request against the session (`auth_request`), so
one rule covers the files and the API alike.

Four things concentrate the most in a single unauthenticated request, which
is why the proxy matters today: `GET /api/backup.zip` (the whole collection
in one download), the restore endpoints (destructive, and they replace
everything), `GET /api/settings` (what is configured, though the secrets
themselves are masked), and `/api/metrics` (counts and the collection's
value, which is why it is off by default).

## Next: accounts and permissions

**Not built yet, and next in line.** A1 ships as **v0.30.0**: one admin,
database-backed sessions, scoped API tokens, and a deny-by-default gate. A2
follows as **v0.31.0**: OpenID Connect and a trusted-header mode for that
same admin. This is a settled design, not a proposal awaiting research, and
this section is replaced by a description of what shipped once A1 lands.

Decided on 20 September 2026: the first cut is **one admin and nothing
else**, onboarded when the app is initialised; the setup page asks for a
**one-time setup code the backend prints in its log** (or takes from an
environment variable), so an open instance can't be claimed by whoever gets
there first; login is **always on**, with no switch to turn it off; and
**scoped API tokens ship with that first cut**. Single sign-on for that
admin is the second part. **More accounts (the editor and viewer roles and
user maintenance) are optional**, off the planned path: the table below
keeps their columns so the design is ready if they are ever wanted.

Decided on 21 September 2026, the details that shape the code:

| Decision | What ships |
|---|---|
| Session lifetime | One day from last use, a 7 day hard cap, and the session id rotated on sign-in |
| Session cookie | Database-backed, HttpOnly, Secure over HTTPS, `SameSite=Lax` |
| CSRF | Fails closed, whatever the method: a cookie-authenticated `/api/` request passes only with `Sec-Fetch-Site: same-origin`, or with no such header and an Origin (or Referer's origin) exactly matching an entry in a required `PUBLIC_ORIGINS` setting. `none` (a typed address) is accepted only on the two addresses meant to be opened directly (the OpenAPI schema and a document's file). Bearer tokens are not CSRF-checked. No token plumbing |
| Passwords | Argon2id through `argon2-cffi`, at least 12 characters. Per-username limits are a delay that grows to a cap, never a lock. A known-device cookie from a successful sign-in (a random value stored hashed, 7 days, dropped after 5 failed sign-ins with it, revoked with the password or "sign out everywhere") lifts the per-username, per-address, and global limits and has a password-check slot reserved for it, so a flood can't keep the owner out; it never lifts the setup throttle or skips the password |
| Recent password | Downloading a backup, exporting, restoring, deleting old unencrypted archives, any settings change, creating or revoking a token, ending another session or signing out everywhere, deleting for good, and changing the password or username ask for the password again; a correct answer opens a 5-minute window for that session only, never for a token. Signing out of the current session never asks |
| Password change | Revokes every other session, every known device, and every API token of every scope, naming each. The reset command in the container does the same |
| Backups | Every archive is encrypted ([age](https://age-encryption.org), X25519) with a backup key from a Docker secret or generated on the state volume, and carries a MAC keyed by that key, so an archive on the backup share can be neither read nor forged without it. The key is shown only by a command in the container, never in the browser; losing it makes the archives unreadable, by design. Old unencrypted archives are flagged and can be deleted |
| Anonymous requests | The only two routes that read a body without a login (sign-in and setup) accept at most 8 KiB, in nginx and in the gate |
| Photos | nginx `auth_request` declared server-wide, one subrequest per photo. Photos, documents, and exports are sent `Cache-Control: private, no-store`, and signing out clears the browser's cache of Cabinet. Caching the check only if measurement asks for it, and only with a reviewed cache key |
| Hosts | nginx answers only the host names in `ALLOWED_HOSTS` (by default the hosts of `PUBLIC_ORIGINS`, plus any internal names an operator adds) and closes the connection for any other. It is separate from `PUBLIC_ORIGINS` so an internal name never becomes a trusted CSRF origin |
| Proxies | nginx believes no forwarded header and overwrites them towards the backend with its own immediate peer and scheme. Cabinet pins no network ranges (the operator's infrastructure decides); the backend should be reachable by nothing but nginx, and uvicorn runs with `--no-proxy-headers`. The address nginx saw is recorded in the audit log for information only |
| Setup | A setup code from a Docker secret (`SETUP_CODE_FILE`, preferred), the environment, or generated and logged; compared first, so wrong guesses can't block the right code; one winner; the setup page closes for good |
| Alerts | Through the existing webhook, carrying no collection data: a sign-in from a new device, repeated failures, a password change or reset, a new token, a backup download or export, a restore, secrets cleared |
| API docs | The interactive `/api/docs` page is off; `/api/openapi.json` stays, for a signed-in session only |
| Restore | Credentials are deployment state, not collection data: they live in their own Postgres schema, `cabinet_auth`, with their own migrations; backups leave that schema out and a restore never touches it. The session that starts a restore keeps an in-memory grant, so its progress page still answers while the database is replaced |
| API tokens | 256-bit, with a recognisable prefix; recognised only as `Authorization: Bearer` carrying that prefix. Scopes `read`, `write`, and `metrics` (which covers `/api/metrics` and the collection totals, so a dashboard tile never holds an inventory-reading token). `read` and `write` tokens expire within 7 days (a day by default); creating or revoking one needs the password, and creating one sends an alert; the page says plainly that a `read` token sees every item and where it is kept. No token can export, download a backup, or read a document file. Shown once, stored hashed, revocable, with a last-used time |

It has to work **both** behind an authenticating proxy and directly exposed,
because which of those the deployment uses is not decided. The table includes
the changes from four outside reviews on 21 September 2026, the last of them
Codex's adversarial review; the contract, with a verdict on each finding, is
[docs/specs/SPEC_0300.md](specs/SPEC_0300.md), and
[SPEC_0300-how-it-works.md](specs/SPEC_0300-how-it-works.md) walks through
setup, sign-in, password changes, and the break-glass reset.

Accounts are logins to **one shared collection**, not separate collections.
The setup page works only while no account exists. Three roles, of which
only the admin is planned; editor and viewer are the optional part:

- **Admin**: everything, including users, settings, secrets, backups, and
  restore. The superuser created at setup is an admin.
- **Editor**: the collection itself (add, edit, photograph, value, import,
  trash and restore) but nothing about the deployment.
- **Viewer**: read-only.

Two more kinds of caller are not accounts:

- **API token**: created by a user for the Homepage tile, Prometheus, or a
  script. It carries scopes (`read`, `write`, `metrics`), can never do more
  than the user who made it, and can never manage users, settings, secrets,
  backups, or tokens.
- **Share link** (Phase 7, P9): an anonymous, read-only, revocable link to
  one set, one checklist, or the collection. Sharing as a whole is a switch
  in the admin's Settings, **off by default**: while it is off the public
  routes answer "not found", no link can be made, and existing links stop
  working (kept, not deleted, so switching it back on restores them).

| Action | Admin | Editor | Viewer | API token | Share link |
|---|---|---|---|---|---|
| View items, photos, checklists, dashboard, reports, edit history | yes | yes | yes | `read` | only what the link shares |
| View costs, values, and gains | yes | yes | yes (an admin can hide them per viewer) | `read`, if its owner can | never |
| View storage locations | yes | yes | yes | `read` | never |
| View and download documents | yes | yes | yes | no (a session only) | never |
| Export CSV and Excel | yes, with the password again | yes | yes | no (a session only) | no |
| Add and edit items, photos, documents, tags, sets, checklists, sales log | yes | yes | no | `write` | no |
| Bulk edit, "Add a run", imports | yes | yes | no | `write` | no |
| Ask a price source for an estimate (spends quota) | yes | yes | no | `write` | no |
| Move to the trash, restore from the trash | yes | yes | no | `write` | no |
| Delete for good, empty the trash | yes, with the password again | no | no | no | no |
| Switch sharing on or off for the whole app | yes | no | no | no | no |
| Create and revoke share links (only while sharing is on) | yes | own links | no | no | no |
| Settings: display currency, value strategy, refresh cadence, trash retention | yes, with the password again | view only | no | no | no |
| Save, reset, or delete the dashboard layout | yes | no | no | no | no |
| Secrets: price-source keys, alert webhook, heartbeat URL | yes (write-only, as today) | no | no | no | no |
| Backups: download (with the password again), run now, schedule | yes | no | no | no | no |
| Restore from an archive (with the password again) | yes | no | no | no | no |
| Alerts test, monitoring status | yes | no | no | no | no |
| `/api/metrics` | yes | no | no | `metrics` | no |
| The collection totals (`/api/stats/collection`) | yes | yes | yes | `read` or `metrics` | no |
| Users: add, disable, change role, reset a password | yes | no | no | no | no |
| Own password, own API tokens, own sessions | yes | yes | yes | no | no |
| `/api/openapi.json` (the API schema; there is no docs page) | yes | yes | yes | no | no |
| `/api/health` | full | full | full | full | status only, as for anyone not signed in |

Rules that go with the table:

- The last enabled admin can't be disabled, demoted, or deleted.
- Disabling a user ends their sessions and revokes their tokens.
- Passwords are hashed with Argon2id; sign-in is rate limited per account and
  per address; sessions are HttpOnly, SameSite cookies with a CSRF check on
  every request; a token is shown once and stored hashed. Any `/api/`
  request whose path is percent-encoded is refused (400), so no encoding can
  route around the gate.
- Photos need the same check as the API. nginx serves them directly today,
  so that becomes an `auth_request` to the backend, declared for the whole
  server and switched off only for the static app and for `/api/` (where the
  backend is the gate). It was chosen over signed, expiring photo URLs, which
  would keep photo links plain but need a key rotation story of their own.
- Single sign-on (OpenID Connect) signs in as the admin through an identity
  linked to that account; a trusted-header mode does the same for a
  forward-auth proxy. The local password stays so a provider outage can't
  lock the admin out. Only if more accounts are ever built would it create
  accounts and map a provider's groups to roles (an admin group, an editor
  group, and viewer for anyone else allowed in).
- Every sign-in, failed sign-in, role change, token, share link, backup
  download, export, and restore is written to an audit log the admin can
  read. Failed sign-ins have their own cap, so a flood of them can never
  push out the record of anything else, and nothing from the collection is
  ever written to the audit log, a log line, or a webhook.
- The whole API is denied by default behind one gate, with a short
  allow-list (sign-in, setup, and a health check that tells an anonymous
  caller only "ok" or not). Anonymous callers are refused on the raw method
  and path, before routing, so unknown paths, HEAD, OPTIONS, and redirects
  are refused too; each route's permission is checked after routing, and a
  route that declares none is refused. Tests enumerate the OpenAPI document
  (not the route list, which hides included routers) and fail if any route
  answers without a login or lacks a permission. The interactive API docs
  page (`/api/docs`) is turned off, so no third-party script ever runs in
  the signed-in page; `/api/openapi.json` stays, for a session only.
- The admin looks after the account in Settings (password, username,
  sessions, tokens, the audit log, and a notice of failed sign-ins since the
  last visit) and, when the app can't be reached, with commands inside the
  backend container: reset the password, sign out everywhere, revoke tokens,
  and show the account's status. Shell access to the deployment is the proof
  of ownership. No command un-claims the instance or deletes the admin, since
  that would reopen setup to whoever reaches it first.
- On the first start after upgrading an open install, nothing is served but
  the setup page until the admin exists, and the log says so.
- nginx believes no forwarded header from anyone: towards the backend it
  overwrites the client address with its own immediate peer and the scheme
  with its own, and blanks identity headers (`Remote-User`,
  `X-Forwarded-User`, and the like). Nothing in the first release depends on
  a forwarded address or scheme: cookies are `Secure` by configuration, and
  the CSRF check compares against `PUBLIC_ORIGINS`. Cabinet pins no network
  ranges; the rule it documents is that nothing but nginx should be able to
  reach the backend, and uvicorn ignores forwarded headers entirely. On a
  Swarm, ports published in the default ingress mode arrive from the ingress
  network's address anyway, which is why sign-in limits lean on the
  known-device cookie rather than on addresses. Sign-in limits are counted
  in memory, so a restart clears them.
- **Credentials are deployment state, not collection data.** Users,
  sessions, tokens, known devices, and the audit log live in the Postgres
  schema `cabinet_auth`, with an Alembic chain and version table of their
  own, and no foreign key crosses between it and the collection. Every dump
  (downloaded, scheduled, the pre-restore safety copy, and `backup.sh`)
  excludes that schema; every restore (in the app and `restore.sh`) restores
  only `public`; and a restore refuses an archive whose table of contents
  lists anything in `cabinet_auth`. So a credential withdrawn since a backup
  can never come back to life, nobody can plant one in an archive, sessions
  and API tokens keep working through a restore, the audit log survives it,
  and an archive made before login existed never reopens setup. A restore
  never revokes anything. A restore onto a brand new machine starts
  unclaimed and is claimed with a fresh setup code.
- An archive carries no credentials, by the mechanism above, but it
  carries everything else,
  settings included, and its checksums live inside it. Anyone who can write to
  `BACKUP_DIR`, often a network mount, could alter an archive (for instance to
  plant a webhook address) for a later restore to bring in: treat the backup
  mount as sensitive. Stored secrets are only ever used if they decrypt with
  the deployment's own key, so an archive edited without that key cannot
  plant a working webhook; a restore clears any that don't, and says which.
  The restore summary lists which secrets the archive would set.
- **Archives are encrypted.** An archive holds the whole collection, storage
  locations included, so from v0.30.0 every one is encrypted with the backup
  key and authenticated with a MAC derived from it: someone who can read the
  backup share learns nothing, and someone who can write to it cannot make an
  archive that restores. The key must be kept outside Cabinet (a password
  manager); `restore.sh` and the in-app restore both need it. Decryption
  happens only in a private staging volume (`/data/staging`) and, for
  `restore.sh`, a private temporary folder, so no plain copy of an archive
  is ever written to `BACKUP_DIR`. Each archive names the key that made it
  (`mac_recipient`, covered by the MAC); Cabinet keeps a record of the
  archives it wrote, in the sign-in schema a restore never touches, so
  restoring an older one than the newest needs a separate typed
  confirmation. Plain archives from before v0.30.0 cannot be restored.
  (Until v0.30.0 ships, the restore staging described under "Input
  handling" still sits in `BACKUP_DIR`.) Cabinet does
  not encrypt the database's own files or the photo and document volumes:
  protecting that storage is the operator's responsibility, as for any
  service. A generated backup key is only as private as the state volume it
  sits on, so a deployment whose backups leave the host should supply the
  key as a secret (`BACKUP_KEY_FILE`); Cabinet says whether the key and the
  backups are separate, shared, or impossible to tell apart, and never
  treats silence as safe.


## Input handling

- **Uploads** are validated as real JPEG/PNG/WebP images by decoding them with
  Pillow; the client-declared content type is not trusted. Images are
  re-encoded for thumbnails, and originals are stored under generated UUID
  filenames, so user-supplied filenames never reach the filesystem or a URL.
- **Database access** goes exclusively through SQLAlchemy's parameter binding;
  there is no string-built SQL.
- **Documents** are stored on their own volume, never the photo volume nginx
  serves, and only the API returns them. The type is read from the bytes
  (a PDF must start with `%PDF-` and open in PDFium, an image must decode in
  Pillow), and anything else (SVG and HTML, which can run script, above all)
  is refused. Files are served with the detected `Content-Type`,
  `X-Content-Type-Options: nosniff`, and a CSP with no sources (`sandbox` too
  for images; not for PDFs, which it stops Chrome's viewer rendering). PDFs
  open in the browser's own viewer rather than a bundled pdf.js, so a PDF's
  scripts never run in Cabinet's origin. Thumbnails render only page one, at
  a fixed size. Like everything else here, documents are protected by the
  reverse proxy's authentication, not by Cabinet, and they often carry
  names and addresses.
- **Import files** are staged under random ids in a temp folder, capped at
  1 GB, and deleted after a day. An OpenNumismat file is opened read-only as
  SQLite and only queried; nothing in it is executed. Imported values pass
  the same schema validation as the item form, and photos inside it the same
  image validation as uploads. Pictures linked from a Numista collection are
  fetched only when asked, through the guarded photo-URL fetch.
- **Restore archives** are streamed into `BACKUP_DIR/.restore-staging/`
  under a random id (never the container's temp folder, never a name the
  client chose), capped at `RESTORE_MAX_GB` (default 20), deleted at once
  when they fail verification, and cleared after a day otherwise. That
  folder is never listed, pruned as an archive, downloadable, or backed up.
  The photo and document archives inside are unpacked by hand, not with
  `extractall`: only plain files and folders, no ownership or modes, and
  links, devices, absolute paths, drive letters, and `..` are refused, when
  the archive is inspected (422) and again at extraction. Files are unpacked
  into `.restore-new` inside the volume and the old ones wait in
  `.restore-old`; both are left out of backups, and nginx serves no
  dot-name under `/photos/`. `pg_restore` runs with `--no-owner` as the
  app's own database user, with no shell.
- **Custom fields** are bounded (20 keys, 50-char names, 500-char string
  values) so arbitrary payloads can't be stashed in the JSON column.
- **Outbound requests** go to the two keyless market-data APIs
  (`api.gold-api.com`, `api.frankfurter.dev`), the keyless purchase-day spot
  lookup for the bullion stack (`cdn.jsdelivr.net`, falling back to
  `*.currency-api.pages.dev`), to Numista and PCGS once you give them a key,
  to the alert webhook and heartbeat URLs you save, and to a photo URL you
  ask for, all with timeouts, and the price and rate lookups with cached
  fallbacks. The collection is never sent outward: a price source receives
  only the catalogue number, PCGS number or cert number, and grade being
  looked up; the purchase-day lookup sends only a date and a metal code.

## Containers and the browser

The backend runs as an unprivileged user (`cabinet`, or `PUID`:`PGID`). Its
entrypoint starts as root only to make the data directories writable by
that user (volumes from releases before v0.23.1, and bind mounts, are
owned by root) and then drops privileges with `setpriv`; a bug in an image
or PDF parser runs with no more than the app's own files. If the hand-over
fails (NFS with root squash), the log says which directory and the backend
stays root: fix the ownership on the server, or set `PUID`/`PGID` to the
owner. nginx's workers were already unprivileged. The backend image carries
no pip: nothing is installed at runtime.

The proxy sets a Content-Security-Policy on the app and its static files
(`location /` in `proxy/nginx.conf`):

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https:; media-src 'self' blob:;
connect-src 'self'; font-src 'self'; object-src 'none'; frame-src 'none';
base-uri 'self'; form-action 'self'; frame-ancestors 'self'
```

That is: scripts, connections, and fonts from itself only (no inline script,
no CDN, no web fonts; the logo and icons are the app's own files), images
from itself, `data:`/`blob:` (the photo editor) and any `https:` host
(Numista thumbnails), media from itself and `blob:`, inline styles (React
sets style attributes), no plugins, no iframes, and framing only by the same
origin. On every response, `/photos/` and the proxied API included, it also
sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
`Referrer-Policy: strict-origin-when-cross-origin`, and a
`Permissions-Policy` allowing only the camera (webcam capture) and denying
the microphone, geolocation, payment, and USB; `server_tokens` is off. nginx
adds no CSP under `/api/`, which is left to the API: documents carry
`default-src 'none'`, and the API docs page loads its viewer from a CDN.
HSTS belongs to whatever terminates TLS in front of the stack. A browser
test fails the build if the headers are missing or one of the main pages
trips the policy.

## Dependencies

The backend image installs from `backend/requirements.txt`, a lockfile with
every package pinned and hash-verified (`pip install --require-hashes`);
`pyproject.toml` keeps the minimum versions for development. The frontend is
built with `npm ci` from `package-lock.json`. Rebuild periodically
(`docker compose build --pull`) to pick up security fixes in the base images
(the backend image also applies Debian's pending updates at build); Python
package fixes arrive by regenerating the lockfile. Two pieces arrive for
sign-in and encrypted backups (v0.30.0): `argon2-cffi` (with
`argon2-cffi-bindings`) in the lockfile, for password hashing, and Debian's
`age` package in the backend image, which encrypts archives; `age` is
called as a program, so it adds no Python dependency, and its version is
the one Debian ships for the image's release (the build fails if
`age --version` does). After changing dependencies, regenerate the lockfile
in the image's own Python:

```bash
docker run --rm -v "$PWD/backend:/src" -w /src python:3.14-slim sh -c \
  "pip install -q pip-tools && pip-compile -q --generate-hashes --strip-extras --no-header -o requirements.txt pyproject.toml"
```

`.github/workflows/security.yml` runs on every push to `main`, every pull
request, and weekly: `pip-audit` against that lockfile, `npm audit` on the
frontend's runtime dependencies (high and above), and Trivy on both built
images, failing on fixable high or critical findings. It is separate from
CI on purpose: a CVE published against an unchanged base image shows up
there without blocking a release that didn't cause it. The usual fix is a
rebuild (the image applies Debian's pending updates) or regenerating the
lockfile.
