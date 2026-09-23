# Deployment

Cabinet is designed for a single host running Docker Compose. This guide
covers a durable install: real secrets, a reverse proxy with TLS and
authentication, scheduled backups, and upgrades.

If you just want to try it, the quick start in the [README](../README.md) is
enough.

## 1. Install

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env
```

Edit `.env`:

- `PUBLIC_ORIGINS` (required): the exact address browsers use to reach
  Cabinet, `scheme://host[:port]`, comma-separated if there is more than one,
  for example `https://cabinet.example.com`. Both the backend and the proxy
  refuse to start without it, naming the variable. The sample,
  `http://localhost,http://proxy`, suits the local stack only.
- `ALLOWED_HOSTS` (optional): extra Host names nginx answers besides those of
  `PUBLIC_ORIGINS`: internal names such as `cabinet_proxy` (for Homepage or
  Prometheus on the same network) or a LAN name. **Any other Host gets no
  response at all**, so a request by bare IP address, or by a name you didn't
  list, is dropped. Names only: no scheme or port.
- `AUTH_INSECURE_HTTP` (optional, default `false`): sign-in cookies without
  `Secure`, for plain http. The sample sets it for the local stack; remove it
  for any real deployment. It is refused when any `PUBLIC_ORIGINS` entry is
  https.
- `CABINET_PORT` (optional, default `80`): the port the proxy publishes.
- `BACKUP_KEY_FILE` (optional): a file of [age](https://age-encryption.org)
  identities, the backup key every archive is encrypted with, typically a
  Docker secret. Unset, Cabinet generates one on the state volume on its
  first start. Either way, **save a copy outside Cabinet**
  (`docker compose exec backend python -m app.cli backup-key show`): without
  it the archives can't be opened. Supply it as a secret whenever backups
  leave the host; see
  [backup-restore.md](backup-restore.md#the-backup-key).
- `BACKUP_KEY` (optional, not with `BACKUP_KEY_FILE`): the key itself as a
  variable, the `AGE-SECRET-KEY-1...` line printed by `python -m app.cli
  backup-key new`, for a secret manager that delivers variables. It is
  visible to anything that can inspect the service, so the secret file is
  preferred where you have the choice.
- `SETUP_CODE` or `SETUP_CODE_FILE` (optional): the one-time code for creating
  the admin, at least 32 characters (`openssl rand -hex 32`); a code that is
  too short or mostly one character stops the backend. Unset, one is
  generated and printed once in the backend's log. `SETUP_CODE_FILE` names a
  file holding it, such as a Docker secret, and wins over `SETUP_CODE`. Once
  the admin exists both are ignored for good (a marker on the state
  volume), so they can stay set. The code's length is what protects an
  unclaimed instance: wrong codes are slowed after five, but a right one
  always passes, so use a random code, never a word.
- `DB_PASSWORD`: a generated password, not the sample value.
- `SECRET_KEY`: generate one; it encrypts the secrets saved in Settings
  (price-source credentials, the alert webhook and heartbeat URLs):

  ```bash
  docker compose run --rm backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  If you skip it, a key is generated onto a private volume: workable, but you
  lose the stored API keys if that volume is ever recreated. See
  [security.md](security.md).
- `PUID` / `PGID` (optional, not in `.env.example`): the user the backend
  runs as and that owns its files, default `1000`:`1000`. Set them when the
  data sits on bind mounts or NFS owned by another account.
- `RESTORE_ENABLED` (optional, default `true`): restore from Settings →
  Backups replaces the whole collection; it is for the admin only and asks
  for the password again. Set `false` to switch it off (the endpoints
  answer 404 and `scripts/restore.sh` is the only way).
- `RESTORE_MAX_GB` (optional, default `20`): the largest archive that may be
  uploaded for a restore. The bundled nginx allows 20 GB.
- `TAG` (optional): pins the image tag, e.g. `TAG=0.30.1`. `--build` builds
  locally whatever the tag; without `--build`, Compose pulls the published
  image of that tag from GHCR instead.

Then bring it up:

```bash
docker compose up --build -d
```

The app is at http://localhost/. **Set it up first**: until the admin
exists, the setup page is all Cabinet serves. It asks for the setup code,
which is your `SETUP_CODE`, or, if you set none, the one in the log:

```bash
docker compose logs backend | grep "setup code"
```

Choose a username and a password of at least 12 characters there; that
account is the only one. Scripts and dashboards use API tokens made in
Settings instead of the password ([api.md](api.md#sign-in-and-permissions)).
A restart before setup generates a new code.

There is no interactive API docs page; the OpenAPI schema is at
http://localhost/api/openapi.json for a signed-in browser. The backend
creates the database schema itself before it starts serving.
`curl http://localhost/api/health` answers `{"status":"ok"}`; signed in, or
with a token, it also reports database reachability, the running version,
`schema` (`status: "ok"` once migrations are applied), and `documents`
(`ok`, or `not_mounted` / `unwritable` when uploads would be refused).
Settings → About shows the same.

To run migrations by hand instead, set `AUTO_MIGRATE=false` in `.env` and run
`docker compose exec backend alembic upgrade head` after each deploy.

## 2. Storage

Data lives in six named Docker volumes:

| Volume | Contents |
|--------|----------|
| `db_data` | postgres: items, estimates, settings, history |
| `photo_data` | photo originals and generated thumbnails |
| `backend_state` | the generated encryption key, when `SECRET_KEY` is unset, and the generated backup key (`backup.key`), when neither `BACKUP_KEY_FILE` nor `BACKUP_KEY` is set. Keep it off the storage your backups go to: Settings says when it isn't |
| `backup_data` | in-app backup archives (`BACKUP_DIR`, Settings → Backups) |
| `document_data` | attached documents: receipts, certificates, invoices (`DOCUMENT_DIR`); private, served only through the API |
| `staging_data` | private working space (`/data/staging`, 0700): where an archive's database dump is unpacked to be checked and restored. Empty between restores. Keep it on this host's own disk, never on the share your backups go to |

If you'd rather keep data in a directory you manage (common when a host has
an established layout, or a NAS mount), replace the volume entries with bind
mounts in a `docker-compose.override.yml`:

```yaml
services:
  backend:
    volumes:
      - /srv/cabinet/photos:/data/photos
      - /srv/cabinet/state:/data/state
      - /mnt/nas/cabinet-backups:/data/backups
      - /srv/cabinet/documents:/data/documents
  proxy:
    volumes:
      - /srv/cabinet/photos:/usr/share/nginx/photos:ro
  db:
    volumes:
      - /srv/cabinet/db:/var/lib/postgresql/data
```

Keep the photo mount consistent between `backend` and `proxy`: the backend
writes the files and nginx serves them. The backup mount must not sit inside
the photo mount; the backend refuses to write archives where nginx would
serve them. On first start the backend hands these directories to its
unprivileged user (`PUID`:`PGID`); see section 6 if the log says it is
"staying root".

**Documents need their own mount** (from v0.19.0). The backend refuses
document uploads unless `/data/documents` is a mounted volume (otherwise they
would sit in the container and vanish on the next redeploy), and Settings →
About shows the storage status. On a Swarm, add a bind like the others to the
backend service, after creating the directory:

```yaml
      - /mnt/nfs/container/cabinet/documents:/data/documents
```

Don't mount it inside the photo directory, and don't give it to the proxy:
documents are served only by the backend. `REQUIRE_DOCUMENT_MOUNT=false`
turns the check off, for local development only.

## 3. TLS and an authenticating proxy in front

Cabinet has its own sign-in (section 1: one admin, sessions, and scoped API
tokens), so it no longer depends on a reverse proxy for authentication. Two
things still call for one:

- **TLS.** nginx serves plain HTTP; terminate TLS at a reverse proxy in
  front (the nginx config is baked into the proxy image, so terminating TLS
  there instead means building your own image with a certificate and a
  `443` server block).
- **A second door, until single sign-on.** Until v0.31.0 adds OpenID Connect
  and a trusted-header mode, keep an authenticating reverse proxy (any
  forward-auth or SSO gateway: Traefik + Authentik, Authelia, oauth2-proxy,
  Pomerium, Cloudflare Access) in front as well. It brings its own second
  factor today; Cabinet's own sign-in stays a second, independent check
  behind it, never a replacement for it and never trusted in its place (the
  gate ignores whatever identity a proxy asserts and always asks for its own
  credential).

Cabinet is built to work both ways, directly exposed behind TLS or behind
such a proxy, because which one a deployment uses is its own choice. Either
way, don't port-forward the stack to the internet without TLS in front of it.

**`PUBLIC_ORIGINS` is what the browser must match to sign in**, not just a
CSRF setting: a plain-http address on the LAN (`http://192.168.1.5`) can't
sign in once `PUBLIC_ORIGINS` names an `https` domain, because the session
cookie is `Secure`-only and the CSRF check compares the `Origin` against
that exact entry. Reach Cabinet by the domain in `PUBLIC_ORIGINS`, not a
bare LAN address, once it's set to `https`.

**The Host header and forwarded headers.** Cabinet's nginx answers only the
Host names from `PUBLIC_ORIGINS` and `ALLOWED_HOSTS`, so set
`PUBLIC_ORIGINS` to the public address the edge proxy serves (Traefik passes
the original Host through by default). nginx believes no forwarded header
from anyone: `X-Forwarded-For`, `X-Real-IP`, and `X-Forwarded-Proto` are
overwritten with what nginx itself saw (the edge proxy's address, and
`http`), and the identity headers forward-auth gateways add (`Remote-User`,
`X-authentik-*`, `X-Auth-Request-*`, and the like) are dropped before the
backend sees them, so an edge proxy's login is a door in front of Cabinet,
never a way into it. **Nothing but Cabinet's nginx should be able to reach
the backend**: keep the backend off any network other services share.

First, stop publishing the port directly. In `docker-compose.override.yml`:

```yaml
services:
  proxy:
    ports: []            # reach it over the proxy network instead
    networks: [edge]
networks:
  edge:
    external: true
```

### Traefik + Authentik (forward-auth)

This is the intended path for a private network: Authentik provides SSO, and
Cabinet needs no code changes. With a Traefik file provider:

```yaml
http:
  routers:
    cabinet:
      rule: "Host(`cabinet.example.com`)"
      entryPoints: [websecure]
      service: cabinet
      middlewares: [authentik@file]
      tls:
        certResolver: letsencrypt
  services:
    cabinet:
      loadBalancer:
        servers:
          - url: "http://cabinet-proxy:80"
```

Point `authentik@file` at your existing forward-auth middleware, and make
`cabinet-proxy` the name the proxy service has on the shared network. Make
sure the edge proxy's body-size limit is at least as generous as Cabinet's
own (nginx allows 25 MB, and 1 GB under `/api/imports` for OpenNumismat
files) or uploads will fail at the edge; likewise its timeouts, since a
backup download or a large import can take minutes before the first byte
(Cabinet's nginx allows 30).

Restoring from an uploaded archive needs more: under `/api/restore`
Cabinet's nginx allows 20 GB bodies, doesn't buffer the request, and waits
60 minutes, because the archive carries every photo and document and
checking a large one takes a while. Give the edge proxy a body limit at
least the size of your archives there, long read and write timeouts, and
no request buffering if it can be turned off (a proxy that buffers needs
room for the whole upload). Or skip the upload: copy the archive into the
backup directory under its own `cabinet-backup-….zip.age` name and restore
it from the list in Settings, which sends no body at all. While a restore
runs
the app answers 503 to everything but `/api/health` and
`/api/restore/status`; that is expected, not an outage.

### Other proxies

Any proxy works: Caddy with `basicauth`, nginx with `auth_request`, or a
tunnel that requires identity. The requirements are: TLS, authentication, and
a body-size limit that permits photo uploads. HSTS belongs on that proxy too;
Cabinet's nginx sets the other security headers itself
([security.md](security.md)).

### Checking a gateway is wired up correctly

Whichever gateway you put in front, confirm each of these before relying on
it:

- The public origin the browser actually uses matches `PUBLIC_ORIGINS`
  exactly (scheme, host, and port).
- The gateway passes Cabinet's cookies, `Origin`, `Referer`, and
  `Sec-Fetch-Site` through unchanged; most do by default, but a proxy that
  strips or rewrites headers will break sign-in or CSRF.
- A photo loads on an item page (it goes through nginx's own `auth_request`
  check, so a working photo confirms the gateway isn't interfering with
  cookies).
- The password-again dialog appears and succeeds on a fresh action (a
  backup download or a settings change).
- A `metrics`-token client (Homepage, Prometheus) still reaches Cabinet on
  the internal name in `ALLOWED_HOSTS`, around the gateway, since those
  aren't signed in through it.

## 4. Scheduled backups

A backup is only real once it's automatic. The simplest way: Settings →
Backups → **Schedule** daily or weekly, set how many to keep, and mount the
backup directory (`/data/backups`) on storage that isn't this host's disk
(see section 2). Click **Back up now** once to confirm the directory is
writable; the last run's outcome stays visible there.

To drive backups from the host instead, `scripts/backup.sh` captures the
database, photos, and documents together:

```cron
# 03:15 daily, keeping the last 30 days
15 3 * * * cd /srv/cabinet-numismatics && ./scripts/backup.sh /srv/backups/cabinet >> /var/log/cabinet-backup.log 2>&1
45 3 * * * find /srv/backups/cabinet -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

Copy backups off the host, and back up `.env` separately: it holds the
database password and the encryption key. Rehearse a restore at least once;
[backup-restore.md](backup-restore.md) has the drill.

So a failed backup doesn't go unnoticed, add an alert webhook and an Uptime
Kuma heartbeat in Settings → Alerts & metrics, and optionally scrape
`/api/metrics` with Prometheus (see [monitoring.md](monitoring.md)).

## 5. Upgrades

```bash
git pull
docker compose up --build -d
```

The backend applies any new migrations on startup, before serving, all in one
transaction. If one fails it rolls back and the backend refuses to start.
Check `docker compose logs backend`. Migrations are forward-only in practice,
and going back to an older image doesn't undo them; take a backup first
(Settings → Backups → **Back up now**).

**Upgrading to v0.30.0**: nothing but the setup page is served until the
admin is created (the setup code is your `SETUP_CODE`, or in the log), and
anything that called the API without signing in (the Homepage tile,
Prometheus, scripts) needs an API token from then on. From the first start
every backup is encrypted.
Save the backup key (`backup-key show`, above) or supply your own as a
secret (`BACKUP_KEY_FILE`) or a variable (`BACKUP_KEY`) before relying on them; take a new backup; then
delete the old unencrypted `cabinet-backup-*.zip` files from the backup
directory by hand (Cabinet ignores them from v0.30.1): they can no longer be
restored and are readable by anyone who can read the backup directory. Old `backup.sh` directories
are plain too. Going back then means the older
image plus that backup: an older Cabinet refuses an archive made by a newer
one, and a newer one migrates an older archive after restoring it. The
[CHANGELOG](../CHANGELOG.md) notes anything that needs attention.

To pick up security fixes in the base images and dependencies without a code
change, rebuild periodically:

```bash
docker compose build --pull && docker compose up -d
```

## 6. Operational notes

- **Run one backend replica.** The price-refresh and backup schedulers run
  in-process; additional replicas would duplicate refreshes and backups.
- **Outbound HTTPS** is needed for `api.gold-api.com` (metal spot prices),
  `api.frankfurter.dev` (ECB exchange rates), and `cdn.jsdelivr.net` with its
  fallback `*.currency-api.pages.dev` (purchase-day spot for the bullion
  stack), plus `api.numista.com` and `api.pcgs.com` once those sources have a
  key. All are optional (they degrade to cached values or a hand-typed
  figure), but allow them if your firewall filters egress. Importing a photo
  from a URL fetches from whatever public host you name.
- **The collection is never sent outward.** The spot and rate APIs receive
  only a metal symbol, a currency pair, or a date; Numista and PCGS receive
  the catalogue number, PCGS number or cert number, and grade being looked
  up, nothing else.
- **Timestamps are UTC**, including the month boundaries in value-over-time.
- **Logs**: `docker compose logs -f backend`. Secrets are never logged.
- **The backend runs unprivileged** (from v0.23.1), as `PUID`:`PGID`
  (default `1000`:`1000`). Its entrypoint starts as root, re-owns any data
  directory whose owner differs (once, not on every start), and drops to
  that user. On bind mounts or NFS, set `PUID`/`PGID` to the account that
  should own the files. A warning in the log that it is "staying root" means
  a directory couldn't be handed over (usually NFS root squash); fix the
  ownership on the server. `docker compose exec backend ...` still enters as
  root.
- **Alert webhooks and the heartbeat** are outbound requests to the URLs you
  save; allow them if egress is filtered.
- **Looking after the account from the container** (v0.30.0), for when the
  app can't be reached. Shell access to the machine is the proof of
  ownership; each command refuses until Cabinet is set up, and each change
  is written to the audit log as `cli`:

  ```bash
  docker compose exec backend python -m app.cli status
  ```

  `status` shows the account, its last sign-in, failed sign-ins in the past
  day, live sessions and tokens, and the backup key's public half and
  location check, never a secret. `reset-password` asks for the new password
  twice (it never takes it as an argument, so it stays out of your shell
  history); it ends every session and known device, revokes every API token
  and names them, and clears the running backend's sign-in delays.
  `sign-out-everywhere` ends every session and known device (a lost laptop),
  and `revoke-tokens [--name NAME]` revokes every token or one. There is
  deliberately no command that undoes the setup or deletes the admin. On a
  Swarm, `docker exec -it` into the backend task instead.

## 7. Swarm / multi-host deployment

A single host running `docker compose up` (sections 1–5) is the primary,
best-tested path. To run Cabinet as a Swarm stack instead, use
[`deploy/docker-stack.yaml`](../deploy/docker-stack.yaml):

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env        # edit secrets
set -a; . ./.env; set +a    # stack deploy reads the shell, not .env
TAG=0.30.1 CABINET_PORT=8080 docker stack deploy -c deploy/docker-stack.yaml cabinet
```

`PUBLIC_ORIGINS` and `CABINET_PORT` are required by the stack file (deploy
stops and names them if they are missing); add `cabinet_proxy` to
`ALLOWED_HOSTS` if Homepage or Prometheus reach Cabinet over an overlay by
its service name.

What that file does differently from `docker-compose.yaml`, and why:

- **Images are pulled, never built.** `docker stack deploy` ignores `build:`,
  so `TAG` must name a published release. Images are published to GHCR on
  every `v*` tag from **v0.10.2** on (nothing earlier exists), as public
  packages, so no node needs to log in to pull them.
- **No `depends_on`, no `restart:`, no `env_file`.** Swarm has none of the
  first two, and the stack file passes the backend only the variables it
  names: the database URL, the data paths, `SECRET_KEY` (left empty, the key
  falls back to the one generated on the `backend_state` volume),
  `REESTIMATE_DAYS`, `RESTORE_ENABLED`, `RESTORE_MAX_GB`, `PUID`/`PGID`,
  `TZ`, and `PUBLIC_ORIGINS`. A commented `secrets:` block shows the setup
  code as a Docker secret (`SETUP_CODE_FILE=/run/secrets/cabinet_setup_code`),
  preferred over `SETUP_CODE` on a Swarm because Portainer, Dozzle, and
  `docker service inspect` show environment variables but not secret
  contents. `AUTO_MIGRATE` and
  `REQUIRE_DOCUMENT_MOUNT` are not among them; add a line to the backend's
  `environment:` if you change either from its default. The backend waits up to 60 seconds for Postgres before migrating,
  and its health check gives a first boot 90 seconds;
  `restart_policy: any` replaces `restart`.
- **Memory limits**: 1 GB each for the backend and db, 256 MB for the proxy.
- **Logs rotate**: every service keeps three 10 MB `json-file` logs, here
  and in `docker-compose.yaml`.
- **One replica each.** The refresh, backup, and alert schedulers run inside
  the backend process; a second replica would run them twice.
- **Storage is named volumes so the file works as is.** On a real Swarm,
  point every volume at shared storage (NFS binds or a volume driver) so a
  task can follow its service to another node. Two mounts matter more than
  the rest: `/data/backups` (archives written inside the container are lost
  with the task) and `/data/documents` (uploads are refused unless it's a
  real mount, so the omission is loud rather than silent).
- **Networks.** `cabinet-internal` is an internal overlay for the three
  services. `cabinet-egress` is the backend's alone, its way out to price
  sources and the alert webhook; the proxy is not on it, since it needs no
  way out. **Nothing but nginx should reach the backend**, so don't replace
  `cabinet-egress` with a network other services share. Behind Traefik,
  put only the proxy on Traefik's network (a commented example is in the
  file), drop its `ports:` for Traefik's labels (see section 3), and keep
  Traefik in ingress mode or not as you prefer: Cabinet reads no forwarded
  client address either way. `/api/metrics` is easiest scraped over the
  internal network rather than exempted from the auth proxy
  ([monitoring.md](monitoring.md)); list the name it is reached by in
  `ALLOWED_HOSTS`.

Upgrading is a tag bump: change `TAG`, deploy again, and the backend
migrates on startup. Restore from Settings → Backups works on a Swarm as it
does under Compose: the backend's health check keeps answering during a
restore (`db: "restoring"`, without touching the database), so the task
isn't killed halfway. It has not been tried on NFS-backed volumes; see
[backup-restore.md](backup-restore.md#what-to-know-before-relying-on-it).
`restore.sh` needs `docker compose`, so the disaster-recovery restore on a
Swarm is done by hand (see [backup-restore.md](backup-restore.md#on-a-swarm)).
