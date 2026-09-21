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
in Settings. A value stored as plaintext by a release from before encryption
existed is encrypted in place the first time it is read.

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

- **Verification before anything changes**: the manifest, a SHA-256 for
  every member, a schema revision this build knows, and the tar-member rules
  under Input handling. The manifest is not itself covered by `SHA256SUMS`,
  so this catches corruption, not an archive rewritten on purpose; an
  attacker who can call the API needs no forged archive anyway.
- **A safety backup first**: the current state is written to `BACKUP_DIR`
  and verified, and the restore doesn't start without it. Pre-restore
  archives are outside the retention count, and the newest three are kept.
- **A typed phrase** (`RESTORE`) on the request that starts it. That guards
  against accidents, not against an attacker.
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

- Put it behind an authenticating reverse proxy (Traefik + Authentik
  forward-auth is the intended path), which requires no application changes.
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
| CSRF | Origin, or Referer's origin, must exactly match an entry in a required `PUBLIC_ORIGINS` setting; any cookie-authenticated request marked `Sec-Fetch-Site: cross-site` or `same-site` is refused, whatever its method. No token plumbing |
| Passwords | Argon2id through `argon2-cffi`, at least 12 characters. Per-username limits are a delay that grows to a cap, never a lock, and a signed known-device cookie from a successful sign-in bypasses them |
| Photos | nginx `auth_request` declared server-wide, one subrequest per photo. Photos are sent `Cache-Control: private, no-cache`. Caching the check only if measurement asks for it, and only with a reviewed cache key |
| Proxies | nginx decides, by the immediate peer, whose forwarded headers to believe (`TRUSTED_PROXIES`, CIDR ranges, default none) and overwrites them towards the backend. The backend sits only on the internal network and a private egress network, and believes only that pinned internal subnet |
| Restore | Credentials are deployment state, not collection data: backups leave them out and a restore keeps the current ones. The session that starts a restore keeps an in-memory grant, so its progress page still answers while the database is replaced |
| API tokens | 256-bit, with a recognisable prefix; recognised only as `Authorization: Bearer` carrying that prefix. Scopes `read`, `write`, and `metrics` (which covers `/api/metrics` and the collection totals, so a dashboard tile never holds an inventory-reading token). Shown once, stored hashed, revocable, with a last-used time |

It has to work **both** behind an authenticating proxy and directly exposed,
because which of those the deployment uses is not decided. The table includes
the changes from an independent review on 21 September 2026; its findings,
with a verdict on each, are recorded in the project's planning notes.

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
| View and download documents | yes | yes | yes | `read` | never |
| Export CSV and Excel | yes | yes | yes | `read` | no |
| Add and edit items, photos, documents, tags, sets, checklists, sales log | yes | yes | no | `write` | no |
| Bulk edit, "Add a run", imports | yes | yes | no | `write` | no |
| Ask a price source for an estimate (spends quota) | yes | yes | no | `write` | no |
| Move to the trash, restore from the trash | yes | yes | no | `write` | no |
| Delete for good, empty the trash | yes | no | no | no | no |
| Switch sharing on or off for the whole app | yes | no | no | no | no |
| Create and revoke share links (only while sharing is on) | yes | own links | no | no | no |
| Settings: display currency, value strategy, refresh cadence, trash retention | yes | view only | no | no | no |
| Save, reset, or delete the dashboard layout | yes | no | no | no | no |
| Secrets: price-source keys, alert webhook, heartbeat URL | yes (write-only, as today) | no | no | no | no |
| Backups: download, run now, schedule | yes | no | no | no | no |
| Restore from an archive | yes | no | no | no | no |
| Alerts test, monitoring status | yes | no | no | no | no |
| `/api/metrics` | yes | no | no | `metrics` | no |
| The collection totals (`/api/stats/collection`) | yes | yes | yes | `read` or `metrics` | no |
| Users: add, disable, change role, reset a password | yes | no | no | no | no |
| Own password, own API tokens, own sessions | yes | yes | yes | no | no |
| `/api/docs` (the API reference) | yes | yes | yes | no | no |
| `/api/health` | full | full | full | full | status only, as for anyone not signed in |

Rules that go with the table:

- The last enabled admin can't be disabled, demoted, or deleted.
- Disabling a user ends their sessions and revokes their tokens.
- Passwords are hashed with Argon2id; sign-in is rate limited per account and
  per address; sessions are HttpOnly, SameSite cookies with a CSRF check on
  anything that changes data; a token is shown once and stored hashed.
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
  download, and restore is written to an audit log the admin can read.
- The whole API is denied by default behind one gate, with a short
  allow-list (sign-in, setup, and a health check that tells an anonymous
  caller only "ok" or not); a test fails if any other route answers without
  a login. `/api/docs` sits behind the login.
- A forgotten admin password is reset with a command inside the backend
  container: shell access to the deployment is the proof of ownership.
- On the first start after upgrading an open install, nothing is served but
  the setup page until the admin exists, and the log says so.
- Forwarded headers are believed at exactly one place: nginx, by the
  immediate peer, against `TRUSTED_PROXIES`. It overwrites them towards the
  backend, and blanks identity headers (`Remote-User`, `X-Forwarded-User`,
  and the like) from every peer. Listing a shared network's range trusts every
  service on that network. On a Swarm, ports published in the default ingress
  mode arrive from the ingress network's address, not the client's, which is
  why sign-in limits lean on the known-device cookie rather than on addresses.
- **Credentials are deployment state, not collection data.** Backups leave
  out the rows of the users, sessions, tokens, and audit tables, and a restore
  keeps the current ones. A credential withdrawn since a backup can therefore
  never come back to life, nobody can plant one in an archive, API tokens keep
  working through a restore, the audit log survives it, and an archive made
  before login existed never reopens setup. A restore onto a brand new machine
  starts unclaimed and is claimed with a fresh setup code. A timestamp on the
  state volume, written as soon as a restore's database step returns, makes
  the gate refuse anything issued before it, covering a crash mid-restore.
- An archive carries no credentials, but it carries everything else,
  settings included, and its checksums live inside it. Anyone who can write to
  `BACKUP_DIR`, often a network mount, could alter an archive (for instance to
  plant a webhook address) for a later restore to bring in: treat the backup
  mount as sensitive.


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
package fixes arrive by regenerating the lockfile. After changing
dependencies, regenerate it in the image's own Python:

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
