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

- `DB_PASSWORD`: a generated password, not the sample value.
- `SECRET_KEY`: generate one; it encrypts stored price-source credentials:

  ```bash
  docker compose run --rm backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  If you skip it, a key is generated onto a private volume: workable, but you
  lose the stored API keys if that volume is ever recreated. See
  [security.md](security.md).

Then bring it up:

```bash
docker compose up --build -d
```

The backend creates the database schema itself before it starts serving.
Check `curl http://localhost/api/health`: it reports database reachability,
the running version, and `schema` (`status: "ok"` once migrations are
applied). Settings → About shows the same.

To run migrations by hand instead, set `AUTO_MIGRATE=false` in `.env` and run
`docker compose exec backend alembic upgrade head` after each deploy.

## 2. Storage

Data lives in five named Docker volumes:

| Volume | Contents |
|--------|----------|
| `db_data` | postgres: items, estimates, settings, history |
| `photo_data` | photo originals and generated thumbnails |
| `backend_state` | the generated encryption key, when `SECRET_KEY` is unset |
| `backup_data` | in-app backup archives (`BACKUP_DIR`, Settings → Backups) |
| `document_data` | attached documents: receipts, certificates, invoices (`DOCUMENT_DIR`); private, served only through the API |

If you'd rather keep data in a directory you manage (common when a host has a
established layout, or a NAS mount), replace the volume entries with bind
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
serve them.

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

## 3. Reverse proxy, TLS, and authentication

**Cabinet has no application-level login.** Do not expose it directly to the
internet. Put it behind a reverse proxy that terminates TLS and handles
authentication.

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

Point `authentik@file` at your existing forward-auth middleware. Make sure the
proxy's body-size limit is at least as generous as Cabinet's own (nginx allows
25 MB) or photo uploads will fail at the edge.

### Other proxies

Any proxy works: Caddy with `basicauth`, nginx with `auth_request`, or a
tunnel that requires identity. The requirements are: TLS, authentication, and
a body-size limit that permits photo uploads.

## 4. Scheduled backups

A backup is only real once it's automatic. The simplest way: Settings →
Backups → **Schedule** daily or weekly, set how many to keep, and mount the
backup directory (`/data/backups`) on storage that isn't this host's disk
(see section 2). Click **Back up now** once to confirm the directory is
writable; the last run's outcome stays visible there.

To drive backups from the host instead, `scripts/backup.sh` captures the
database and photos together:

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
(Settings → Backups → **Back up now**). The
[CHANGELOG](../CHANGELOG.md) notes anything that needs attention.

To pick up security fixes in the base images and dependencies without a code
change, rebuild periodically:

```bash
docker compose build --pull && docker compose up -d
```

## 6. Operational notes

- **Run one backend replica.** The price-refresh and backup schedulers run
  in-process; additional replicas would duplicate refreshes and backups.
- **Outbound HTTPS** is needed for `api.gold-api.com` (metal spot prices) and
  `api.frankfurter.dev` (ECB exchange rates). Both are optional (they degrade
  to cached values), but allow them if your firewall filters egress.
- **No collection data is ever sent outward**; those two APIs receive only a
  metal symbol or a currency pair.
- **Timestamps are UTC**, including the month boundaries in value-over-time.
- **Logs**: `docker compose logs -f backend`. Secrets are never logged.
- **The backend runs unprivileged** (from v0.23.1). It re-owns its data
  directories once on first start; on bind mounts or NFS, set `PUID`/`PGID`
  to the account that should own the files. A warning in the log that it is
  "staying root" means a directory couldn't be handed over (usually NFS
  root squash); fix the ownership on the server.
- **Alert webhooks and the heartbeat** are outbound requests to the URLs you
  save; allow them if egress is filtered.

## 7. Swarm / multi-host deployment

A single host running `docker compose up` (sections 1–5) is the primary,
best-tested path. To run Cabinet as a Swarm stack instead, use
[`deploy/docker-stack.yaml`](../deploy/docker-stack.yaml):

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env        # edit secrets
set -a; . ./.env; set +a    # stack deploy reads the shell, not .env
TAG=0.24.5 docker stack deploy -c deploy/docker-stack.yaml cabinet
```

What that file does differently from `docker-compose.yaml`, and why:

- **Images are pulled, never built.** `docker stack deploy` ignores `build:`,
  so `TAG` must name a published release. Images are published to GHCR on
  every `v*` tag from **v0.10.2** on (nothing earlier exists), as public
  packages, so no node needs to log in to pull them.
- **No `depends_on`, no `restart:`.** Swarm has neither. The backend waits
  up to 60 seconds for Postgres before migrating, and its health check gives
  a first boot 90 seconds; `restart_policy: any` replaces `restart`.
- **One replica each.** The refresh, backup, and alert schedulers run inside
  the backend process; a second replica would run them twice.
- **Storage is named volumes so the file works as is.** On a real Swarm,
  point every volume at shared storage (NFS binds or a volume driver) so a
  task can follow its service to another node. Two mounts matter more than
  the rest: `/data/backups` (archives written inside the container are lost
  with the task) and `/data/documents` (uploads are refused unless it's a
  real mount, so the omission is loud rather than silent).
- **Networks.** `cabinet-internal` is an internal overlay for the three
  services; `cabinet-egress` is a plain overlay so the backend can reach its
  price sources and the proxy can be reached. Replace it with your Swarm's
  own ingress network (`external: true`) and, behind Traefik or similar,
  drop the proxy's `ports:` for that proxy's labels (see section 3 for the
  Traefik + Authentik pattern). `/api/metrics` is easiest scraped over the
  internal network rather than exempted from the auth proxy
  ([monitoring.md](monitoring.md)).

Upgrading is a tag bump: change `TAG`, deploy again, and the backend
migrates on startup. `restore.sh` needs `docker compose`, so restore on a
Swarm by hand (see [backup-restore.md](backup-restore.md#on-a-swarm)).
