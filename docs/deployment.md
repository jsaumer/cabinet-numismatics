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

- `DB_PASSWORD` — a generated password, not the sample value.
- `SECRET_KEY` — generate one; it encrypts stored price-source credentials:

  ```bash
  docker compose run --rm backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  If you skip it, a key is generated onto a private volume — workable, but you
  lose the stored API keys if that volume is ever recreated. See
  [security.md](security.md).

Then bring it up and migrate:

```bash
docker compose up --build -d
docker compose exec backend alembic upgrade head
```

Check `curl http://localhost/api/health` — it reports database reachability
and the running version.

## 2. Storage

Data lives in three named Docker volumes:

| Volume | Contents |
|--------|----------|
| `db_data` | postgres — items, estimates, settings, history |
| `photo_data` | photo originals and generated thumbnails |
| `backend_state` | the generated encryption key, when `SECRET_KEY` is unset |

If you'd rather keep data in a directory you manage (common when a host has a
established layout, or a NAS mount), replace the volume entries with bind
mounts in a `docker-compose.override.yml`:

```yaml
services:
  backend:
    volumes:
      - /srv/cabinet/photos:/data/photos
      - /srv/cabinet/state:/data/state
  proxy:
    volumes:
      - /srv/cabinet/photos:/usr/share/nginx/photos:ro
  db:
    volumes:
      - /srv/cabinet/db:/var/lib/postgresql/data
```

Keep the photo mount consistent between `backend` and `proxy` — the backend
writes the files and nginx serves them.

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

Any proxy works — Caddy with `basicauth`, nginx with `auth_request`, or a
tunnel that requires identity. The requirements are: TLS, authentication, and
a body-size limit that permits photo uploads.

## 4. Scheduled backups

A backup is only real once it's automatic. `scripts/backup.sh` captures the
database and photos together:

```cron
# 03:15 daily, keeping the last 30 days
15 3 * * * cd /srv/cabinet-numismatics && ./scripts/backup.sh /srv/backups/cabinet >> /var/log/cabinet-backup.log 2>&1
45 3 * * * find /srv/backups/cabinet -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

Copy backups off the host, and back up `.env` separately — it holds the
database password and the encryption key. Rehearse a restore at least once;
[backup-restore.md](backup-restore.md) has the drill.

## 5. Upgrades

```bash
git pull
docker compose up --build -d
docker compose exec backend alembic upgrade head
```

Migrations are forward-only in practice; take a backup first. The
[CHANGELOG](../CHANGELOG.md) notes anything that needs attention.

To pick up security fixes in the base images and dependencies without a code
change, rebuild periodically:

```bash
docker compose build --pull && docker compose up -d
```

## 6. Operational notes

- **Run one backend replica.** The melt re-estimation scheduler runs in-process;
  additional replicas would duplicate refreshes.
- **Outbound HTTPS** is needed for `api.gold-api.com` (metal spot prices) and
  `api.frankfurter.dev` (ECB exchange rates). Both are optional — they degrade
  to cached values — but allow them if your firewall filters egress.
- **No collection data is ever sent outward**; those two APIs receive only a
  metal symbol or a currency pair.
- **Timestamps are UTC**, including the month boundaries in value-over-time.
- **Logs**: `docker compose logs -f backend`. Secrets are never logged.
