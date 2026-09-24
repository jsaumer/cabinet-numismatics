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
- `TAG` (optional): pins the image tag, e.g. `TAG=0.32.0`. `--build` builds
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

## 2. Exposure: Cabinet is for private networks

Cabinet is intended for private use on private networks: a home LAN, a
homelab, or a VPN you control. **Do not expose it to the internet.** That
holds whatever else sits in front of it: not behind TLS alone, not behind
single sign-on, not behind an authenticating gateway. None of those change
the recommendation. No port forward on the router, no public DNS name
pointing at it, and no "just for a while while I show someone": a port
left open is a port left open.

**To reach Cabinet from outside your network, use the network's own remote
access**: a VPN (WireGuard, Tailscale, or your router's own built-in VPN)
or an identity-aware tunnel that terminates before Cabinet, so that Cabinet
itself is never reachable from the internet, only from inside the tunnel.
That is how the owner's own deployment works: Cabinet sits behind Traefik
and Authentik on the LAN, and the LAN itself is reached over a VPN.

**Why this matters.** Cabinet has one admin account, and by design a
password sign-in path with a single factor: a provider outage or a lost
phone must never be able to lock the owner out of their own collection, so
the password stays a working recovery credential no matter what else is
configured. Single sign-on adds the identity provider's own multi-factor
check to the provider's sign-in button; it does not add a second factor to
that password path, which is the point of keeping it simple enough to
recover from a shell. The sign-in itself is hardened (Argon2id password
hashing, per-account and per-address throttles that only grow into a
delay, a known-device cookie, alerts on a new device or provider), but
none of that changes what one guessed or leaked password would hand over
on an internet-facing instance: the whole collection, every item's storage
location, and every attached document. Cabinet has no way to make a
guessed password fail; a private network is what makes the guess
impossible to attempt in the first place. Exposing any self-hosted service
that holds personal records invites automated credential guessing,
vulnerability scanning, and exploitation of any future defect, typically
within hours of the port opening, not months.

**What still applies inside the network.** None of this is a reason to
skip the rest of the hardening this guide describes: TLS from a local
certificate authority or your reverse proxy, so traffic on the LAN itself
isn't plaintext; a long, random password kept in a password manager rather
than memorised; the alert webhook and the "alert on every password
sign-in" switch turned on, so a password sign-in becomes a tripwire rather
than routine; and single sign-on with multi-factor authentication enabled
at the provider for everyday use, so the password is rarely typed at all.

**Share links are for people on your network or your VPN.** A share link
(`/s/<token>`) is meant to be opened by someone who can already reach
Cabinet: a family member on the LAN, or a guest on your VPN. It is never a
reason to expose Cabinet itself to the internet, and exposing only the
share paths through a gateway's path-based rule is not a recipe this
project stands behind: it takes only one path rule written slightly too
broadly, or one gateway update that changes how it matches paths, for the
sign-in page to end up reachable as well. The forward-auth exemption
described below is for a gateway that already sits inside your network,
guarding an instance that is itself never reachable from the internet.

**If you expose Cabinet to the internet anyway**, this document does not
offer a "safe" recipe for doing so, because there is none the project
stands behind. It says only this: the owner of such a deployment carries
that risk themselves, and the project cannot see or control how Cabinet is
deployed and takes no responsibility for an exposed instance. The least
that should then be true is TLS terminated properly at the edge, single
sign-on with multi-factor authentication enforced at the provider, an
authenticating gateway in front of Cabinet's own sign-in, the alert
webhook switched on, and a password no human has memorised.

<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->
Cabinet is designed for private networks (a home LAN, a homelab, or a VPN
you control), not the open internet. Do not expose it directly to the
internet, even behind TLS, single sign-on, or an authenticating gateway;
reach it from outside through your own network's remote access instead,
such as a VPN (WireGuard, Tailscale, or your router's own) or an
identity-aware tunnel that terminates before Cabinet. Cabinet has one
admin account and, by design, a password sign-in path with a single
factor, so that a provider outage or a lost phone can never lock you out;
exposing any self-hosted service that holds personal records invites
automated credential guessing and vulnerability scanning within hours of
the port opening. The project cannot see or control how Cabinet is
deployed and takes no responsibility for an exposed instance. If you
deploy it this way regardless, at minimum use TLS, single sign-on with
multi-factor authentication enforced at the provider, an authenticating
gateway in front, the alert webhook switched on, and a password no human
has memorised.
<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->

## 3. Storage

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
unprivileged user (`PUID`:`PGID`); see section 7 if the log says it is
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

## 4. TLS, single sign-on, and an optional gateway in front

Cabinet has its own sign-in (section 1: one admin, sessions, and scoped API
tokens), and from v0.33.0 that sign-in can be through an OpenID Connect
provider or GitHub, or through a gateway that has already authenticated the
browser. Two things still call for a reverse proxy in front:

- **TLS.** nginx serves plain HTTP; terminate TLS at a reverse proxy in
  front (the nginx config is baked into the proxy image, so terminating TLS
  there instead means building your own image with a certificate and a
  `443` server block).
- **An authenticating gateway is now optional.** With single sign-on built,
  an authenticating reverse proxy (Traefik + Authentik, Authelia,
  oauth2-proxy, Pomerium, Cloudflare Access) in front is no longer required
  as a second door; Cabinet's own sign-in is the door. What such a gateway
  still gives you: a door before the sign-in page is ever shown (useful if
  you'd rather a stranger not even see that Cabinet exists), and, if it can
  assert a signed identity, the trusted-header mode below for a one-click
  sign-in through it. Cabinet's own sign-in is never replaced by a gateway
  in front: the gate ignores whatever identity a proxy asserts unless the
  trusted-header mode is explicitly configured for it, and even then it is
  one click, never automatic.

**Read the exposure warning above (section 2) before deciding how to reach
Cabinet from outside your network.** Neither TLS nor single sign-on nor a
gateway in front is a substitute for keeping Cabinet off the internet.

**`PUBLIC_ORIGINS` is what the browser must match to sign in**, not just a
CSRF setting: a plain-http address on the LAN (`http://192.168.1.5`) can't
sign in once `PUBLIC_ORIGINS` names an `https` domain, because the session
cookie is `Secure`-only and the CSRF check compares the `Origin` against
that exact entry. Reach Cabinet by the domain in `PUBLIC_ORIGINS`, not a
bare LAN address, once it's set to `https`. It is also where a single
sign-on redirect URI comes from: Settings → Sign-in shows one callback URL
per `PUBLIC_ORIGINS` entry, and each has to be registered at the provider
exactly as shown.

**The Host header and forwarded headers.** Cabinet's nginx answers only the
Host names from `PUBLIC_ORIGINS` and `ALLOWED_HOSTS`, so set
`PUBLIC_ORIGINS` to the public address the edge proxy serves (Traefik passes
the original Host through by default). nginx believes no forwarded header
from anyone: `X-Forwarded-For`, `X-Real-IP`, and `X-Forwarded-Proto` are
overwritten with what nginx itself saw (the edge proxy's address, and
`http`), and the identity headers forward-auth gateways add (`Remote-User`,
`X-authentik-*`, `X-Auth-Request-*`, and the like) are dropped before the
backend sees them, except for the one header named by
`TRUSTED_ASSERTION_HEADER`, passed through only when the trusted-header mode
is configured (below). So an edge proxy's login is a door in front of
Cabinet, never a way into it, unless you deliberately wire up the
trusted-header mode. **Nothing but Cabinet's nginx should be able to reach
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

### Setting up a single sign-on provider

Any of the platforms below can be configured at once; the sign-in page
shows one button per provider you enable in Settings → Sign-in. Each
subsection is self-contained: read only the one for your provider. The
redirect URI (callback URL) is always `https://<your PUBLIC_ORIGIN>/api/auth/oidc/callback`,
one per `PUBLIC_ORIGINS` entry; Settings → Sign-in shows the exact value(s)
under the Add form. After creating a provider, sign in with your password,
open Settings → Sign-in, and use **Link** next to the provider: you're sent
to the provider, and back in Settings you should see "Linked." **No
identity is ever trusted on its first sign-in**: an identity that isn't
already linked gets "This account is not linked to Cabinet. Sign in with
your password and link it in Settings," never a new account. Console steps
below are as of September 2026 and described by intent (what to create,
which fields matter), since exact menu paths change over time; what was
actually verified in this build is noted at the end of each subsection.

Keep the provider's client id and client secret in your password manager:
**they are never included in a Cabinet backup** (section 5, and
[backup-restore.md](backup-restore.md)), so restoring onto a fresh machine
means re-entering them and relinking.

#### 1. Authentik (OpenID Connect)

Create an **OAuth2/OpenID provider** with client type **Confidential**, the
redirect URI above, and an **asymmetric signing key selected** (leaving it
unset makes Authentik sign with HS256 by the client secret, which Cabinet
refuses). Leave subject mode at Authentik's default (a stable hashed user
id): Cabinet refuses to link an identity whose subject looks like an email
address. Bind the provider to an **Application**. The issuer to paste into
Cabinet's Custom preset is the provider's OpenID configuration issuer,
typically `https://<authentik>/application/o/<slug>/`.

Cabinet preset: **Custom OpenID Connect**. "Confirm at your sign-in
provider" (the fresh-action dialog's provider option) works with
Authentik, since it supports `prompt=login` and reports `auth_time`.

*Verified in this build*: against `tests/fake_idp.py` and CI's
`scripts/ci/mock_idp.py` only. The owner's own Authentik is the live check
recorded in [SPEC_0330](specs/SPEC_0330.md)'s build log.

#### 2. Keycloak

Create a client with **client authentication on** and the **standard
flow** enabled, and set the redirect URI above. The issuer is
`https://<keycloak>/realms/<realm>`. Cabinet preset: **Custom OpenID
Connect**. "Confirm at your sign-in provider" works with Keycloak.

*Verified in this build*: not against a live Keycloak; the protocol is
identical to Authentik's, and Cabinet's client requires nothing
Keycloak-specific.

#### 3. Authelia

Add a client under `identity_providers.oidc.clients`: a client id, a
secret hashed the way Authelia's own documentation requires, the redirect
URI above under `redirect_uris`, `scopes: [openid, profile, email]`,
`token_endpoint_auth_method: client_secret_basic`, and whatever consent
mode you prefer. The issuer is Authelia's own base URL. Cabinet preset:
**Custom OpenID Connect**. "Confirm at your sign-in provider" works.

Authelia also offers forward-auth, the way Traefik + Authentik does, but
its forward-auth response does not include a signed assertion Cabinet can
verify the way Authentik's outpost does, so **use OpenID Connect with
Authelia, not the trusted-header mode** (SPEC_0330 Q4).

*Verified in this build*: not against a live Authelia.

#### 4. Microsoft Entra ID

Create an **App registration** with a **Web** platform and the redirect
URI above, then a **client secret** (note that it expires, at most 24
months; when it does, Cabinet shows "credentials rejected" on the
provider's row in Settings and sends an alert). Cabinet's **Microsoft**
preset asks for your **tenant id** and pins the issuer to
`https://login.microsoftonline.com/<tenant>/v2.0`; the shared `common`
endpoint does not work, since its issuer varies per sign-in and fails
Cabinet's discovery check. Entra's `sub` is pairwise per application and
stable across sign-ins; the free tier is enough. "Confirm at your sign-in
provider" falls back to the password with Entra: it returns `auth_time`
only as an optional claim, which Cabinet doesn't rely on being present.

*Verified in this build*: not against a live Entra tenant; the tenant
pinning rule was carried over from the researched quirk table (SPEC_0330
section 3).

#### 5. Google

Create an **OAuth client ID** of type **Web application** in the Google
Cloud console, with the redirect URI above, and configure the consent
screen. Cabinet preset: **Google**; no tenant to enter. "Confirm at your
sign-in provider" falls back to the password: Google supports neither
`prompt=login` nor `auth_time`. Turn on 2-Step Verification on the Google
account you link.

*Verified in this build*: not against a live Google account.

#### 6. GitHub

GitHub speaks OAuth 2.0, not OpenID Connect (no ID token, no discovery),
so Cabinet reads the identity from GitHub's profile endpoint instead
(SPEC_0330 section 5a). Under **Settings → Developer settings → OAuth
Apps**, create a new app with the **Authorization callback URL** set to
the redirect URI above (one app per origin: a second `PUBLIC_ORIGINS`
entry needs a second GitHub app, since GitHub takes one callback URL per
app). Cabinet's **GitHub** preset asks only for the client id and secret;
no scope is requested, since GitHub's public profile already includes the
numeric `id` Cabinet links by (a renamed GitHub account stays linked,
since the id never changes). Turn on two-factor authentication on the
GitHub account before linking it, or don't link it: the button is only as
safe as the GitHub account behind it. "Confirm at your sign-in provider"
never works with GitHub (there is no ID token to re-verify); a GitHub
session always confirms with the password. Cabinet reads GitHub's token
response as JSON and sends the client credentials as form fields, which is
GitHub's documented shape.

*Verified in this build*: the GitHub kind was exercised against
`tests/fake_idp.py`'s GitHub mode in pytest (form-encoded and JSON token
answers, the numeric `id`), not against the real `github.com` endpoints
and not through the compose stack (the preset's URLs are fixed to
github.com); see the build log.

#### 7. Any other OpenID Connect provider

Zitadel, Kanidm, PocketID, Dex, Okta, Auth0, GitLab, Forgejo, Synology SSO
Server, Nextcloud's OIDC app, and Amazon Cognito all work with Cabinet's
**Custom OpenID Connect** preset: enter the issuer, and Cabinet does the
rest through discovery. What Cabinet requires of any such provider: a
discovery document at `{issuer}/.well-known/openid-configuration` whose
own `issuer` field equals exactly what you typed, the `code` response
type, `response_mode=query`, PKCE with `S256` (Cabinet always sends it,
which is why Kanidm, which requires PKCE, works with no extra
configuration), an ID token signed RS256, PS256, ES256, or EdDSA, and
HTTPS (plain HTTP is accepted only beside `AUTH_INSECURE_HTTP`, for the
local stack and CI). The "Test" button on the Add form in Settings →
Sign-in runs discovery against the issuer you typed and reports whether "Confirm at your sign-in
provider" will be available. Amazon Cognito's issuer is the user-pool URL,
not the hosted UI domain. Kanidm requires PKCE, already covered.

**What does not work, and why**: Apple (requires `response_mode=form_post`,
a cross-site POST Cabinet's gate refuses by design, unless you omit the
`email`/`name` scopes, in which case its client secret is also a signed,
rotating JWT that needs its own maintenance, not supported in v0.33.0);
any OAuth 2.0-only provider besides GitHub, such as Discord, X, or
Facebook (no ID token or discovery; federate them through Authentik or
Keycloak, then use OpenID Connect to reach Cabinet); SAML 2.0 identity
providers, older ADFS setups, or Shibboleth (not planned; ADFS 2016 and
later speak OpenID Connect directly); LDAP, Active Directory, or FreeIPA
used directly (they are a directory, not a web sign-in; put Authentik,
Keycloak, or Authelia in front of the directory); and Tailscale's identity
headers (plain text, not a signed assertion Cabinet can verify: see the
trusted-header mode below).

### The trusted-header mode

The trusted-header mode is for a gateway that has already authenticated
the browser and can assert the identity to Cabinet as a **signed JWT** in
one header, never a plain-text header and a shared secret (SPEC_0330's
owner decision: a shared secret is just a second password on the wire).
Cabinet verifies the JWT's signature against the gateway's own published
keys, its issuer, and its audience, and offers a single button on the
sign-in page, "Continue with the proxy's sign-in", never automatic, so
signing out of Cabinet still means something while the gateway's own
session lives on.

Four environment variables configure it, all four or none:

| Variable | Meaning |
|---|---|
| `TRUSTED_ASSERTION_HEADER` | The header carrying the gateway's signed JWT (e.g. `X-authentik-jwt`). Set on **both** the backend and the proxy; unset, the mode is off and nginx blanks every identity header as always |
| `TRUSTED_ASSERTION_JWKS_URL` | Where the gateway's public keys are; must be `https://` unless `AUTH_INSECURE_HTTP` is set |
| `TRUSTED_ASSERTION_ISSUER` | The `iss` the assertion must carry |
| `TRUSTED_ASSERTION_AUDIENCE` | The `aud` the assertion must carry; never empty |

`SSO_CA_FILE` (a PEM file of extra CA certificates) is for a gateway or
provider behind a certificate from a local, private certificate authority.

The mode also has a **stored switch**, on by default once the four
variables are set: `disable-sso` in the container turns it off (along with
every provider), and only Settings → Sign-in turns it back on. Linking is
"Link the identity this proxy asserts" in Settings, enabled only when the
current request actually came through the gateway.

Per gateway:

- **Authentik proxy provider with Traefik forward-auth** (the owner's own
  deployment). Create a **proxy provider dedicated to Cabinet alone**, in
  single-application mode: a domain-level provider shared across several
  apps would give every co-hosted app an assertion carrying Cabinet's own
  `iss` and `aud`, and a compromised or merely curious co-hosted app could
  then present a working Cabinet assertion. Select an **asymmetric signing
  key** on the provider (an unset key makes Authentik sign with HS256 by
  the client secret, which Cabinet refuses, so the mode would simply never
  see a valid assertion). Make sure Traefik's forward-auth middleware lists
  `X-authentik-jwt` in `authResponseHeaders`, or Traefik never forwards it.
  Set `TRUSTED_ASSERTION_HEADER=X-authentik-jwt`,
  `TRUSTED_ASSERTION_JWKS_URL` to the provider's `jwks/` endpoint
  (`https://<authentik>/application/o/<slug>/jwks/`),
  `TRUSTED_ASSERTION_ISSUER` to the provider's issuer URL, and
  `TRUSTED_ASSERTION_AUDIENCE` to the provider's client id. The assertion
  is valid for the outpost session's whole lifetime, not minutes, so with
  this mode on **the proxy port must be reachable only from the gateway**
  (on a Swarm, don't publish it; under Compose, put it only on the
  gateway's network): the mode's whole safety rests on nothing but the
  gateway being able to present the header. The exact claims in Authentik's
  assertion aren't in its released documentation; confirm them against your
  own Authentik and see the build log in
  [SPEC_0330](specs/SPEC_0330.md#18-build-log) for what the owner recorded.
  The forward-auth exemption for the share paths (below) still applies.
- **Cloudflare Access.** Header `Cf-Access-Jwt-Assertion`, JWKS
  `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, issuer the
  team domain (`https://<team>.cloudflareaccess.com`), audience the
  application's AUD tag. Documented from Cloudflare's own reference, not
  exercised against a live Cloudflare Access application in this build.
- **Pomerium.** Header `X-Pomerium-Jwt-Assertion`, JWKS
  `https://<authenticate-service>/.well-known/pomerium/jwks.json`, issuer
  and audience per Pomerium's own documentation (typically the protected
  route's host as the audience). Documented, not exercised live.
- **Google Identity-Aware Proxy.** Header `X-Goog-IAP-JWT-Assertion`, JWKS
  `https://www.gstatic.com/iap/verify/public_key-jwk`, issuer
  `https://cloud.google.com/iap`, audience the backend service's
  `/projects/<number>/global/backendServices/<id>` string. Documented, not
  exercised live. IAP is a public-cloud product: the exposure warning above
  still applies in full: put a private network in front of the workload
  IAP protects, the same as any other deployment.

**When the gateway itself is down.** With a gateway in front, its sign-in
page sits in front of Cabinet's own, so if the gateway is unreachable you
need a way around it. "Just hit the proxy port from a LAN host" does not
work on an https deployment: Cabinet's nginx only ever speaks plain HTTP,
and the session cookie is `Secure`, which a browser only stores from a
plain-http page on `localhost`. Two things do work: an SSH port forward to
the proxy (`ssh -L 8080:<proxy host>:80 <a LAN host>`, with `localhost`
added to `ALLOWED_HOSTS` and `http://localhost:8080` added to
`PUBLIC_ORIGINS`, then browsing to `http://localhost:8080`, where browsers
do accept a `Secure` cookie set over `localhost`); or a second HTTPS route
at the edge proxy that skips the gateway entirely, reachable only from the
LAN. Either is the documented recovery for a gateway outage; for every
other kind of lockout, `reset-password` in the container is the recovery
(next subsection).

### Recovery

The **password always works**, on any kind of session, and is the
recovery credential: a forgotten password is `python -m app.cli
reset-password` in the container, whether or not single sign-on is
configured, by design: a provider account must never by itself be enough
to change the Cabinet password, so the browser never sets a new one
without the current one. `unlink-identity <id>` removes one linked
identity and ends the sessions that came through it; `disable-sso` turns
every provider and the trusted-header mode off in one step, for a
configuration that locks you out of the sign-in page itself (a
misconfigured redirect, a gateway stuck in a loop); `status` prints the
configured providers, the linked identities, and which sign-in methods are
currently on. All of the container commands take effect in the running
backend immediately, with no restart needed.

**After a suspected compromise of a provider account** (or of the gateway),
check the linked identities before anything else: `status` in the
container (or Settings → Sign-in) lists every identity, and anyone who held
the provider account could have linked a second identity at another
enabled provider, which survives `reset-password`, `sign-out-everywhere`,
and `disable-sso` (linked identities are kept so the mode can be switched
back on). Unlink every identity you don't recognise with `unlink-identity
<id>`, then reset the password. The `identity_linked` alert through the
webhook is the tripwire for that, so keep the webhook on. Switching the
trusted-header mode off in Settings, switching a provider off, unlinking,
and `disable-sso` each end the sessions that came through what was
removed, at once.

Provider ids and client secrets are **not included in a Cabinet backup**
(they live in the `cabinet_auth` schema, alongside the admin account
itself): restoring an archive onto a fresh machine means re-entering every
provider's client id and secret and relinking each identity, the same way
the password itself has to be re-set up. Renaming the domain
(`PUBLIC_ORIGINS`) means re-registering the redirect URI at every provider.
A user recreated at the provider (a new account, even with the same email)
is a new identity to Cabinet; sign in with the password and relink it.

### The operator acceptance checklist

Before relying on single sign-on or the trusted-header mode, confirm:

- The redirect URI is registered at the provider **exactly** as Settings →
  Sign-in shows it (scheme, host, and path).
- No wildcard callback URL is registered at GitHub (GitHub allows it; don't
  use it).
- The machine's clock is within 60 seconds of real time (Cabinet's
  allowed leeway on token timestamps).
- Multi-factor authentication is switched on at the provider for the
  account you link.
- The local admin password is saved in a password manager, not only
  remembered.
- `disable-sso` has been run once from the container, and the mode
  switched back on afterwards from Settings, so you know both directions
  work.
- The gateway-down bypass above has been exercised once, before you need
  it for real.
- A successful sign-in through each configured provider has been recorded
  (Settings → Sign-in, or the audit log).
- For the trusted-header mode: the live assertion's `alg`, `iss`, `aud`,
  and lifetime have been noted somewhere (the build log in
  [SPEC_0330](specs/SPEC_0330.md#18-build-log) asks for the same values from
  the owner's own gateway).

### Traefik + Authentik (forward-auth)

An authenticating gateway in front is now optional (above), but remains a
reasonable choice if you want a door before Cabinet's sign-in page is ever
shown, or if you want the trusted-header mode's one-click sign-in. With a
Traefik file provider:

```yaml
http:
  routers:
    cabinet:
      rule: "Host(`cabinet.example.com`)"
      entryPoints: [websecure]
      service: cabinet
      middlewares: [hsts@file, authentik@file]
      tls:
        certResolver: letsencrypt
  middlewares:
    hsts:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: false
        stsPreload: false
  services:
    cabinet:
      loadBalancer:
        servers:
          - url: "http://cabinet-proxy:80"
```

The `hsts` middleware is the `Strict-Transport-Security` header, which
Cabinet's own nginx cannot send: it only ever sees plain HTTP from Traefik
(it overwrites `X-Forwarded-Proto` by design, [security.md](security.md)),
and a browser ignores the header over plain HTTP anyway. Put it on every
router that serves the host (the share router below included), or once on
the `websecure` entrypoint. Start with a day (`stsSeconds: 86400`) and
raise it to a year once the certificate renews cleanly; leave
`stsIncludeSubdomains` off unless every subdomain is HTTPS only, and never
set `stsPreload`, which commits the whole domain to browser preload lists.
A self-signed certificate behind HSTS has no click-through in a browser, so
a LAN name with one should not send it.

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

### Sharing, and the forward-auth exemption

Sharing is meant only for people who can already reach Cabinet over your
own network or VPN (section 2); a forward-auth gateway kept inside that
network still has to be told not to guard the share paths, or it blocks
your own share links along with everything else.

Turning sharing on (Settings → Sharing, off by default) means a share link
(`/s/<token>`) and its API (`/api/share/...`) are meant to open for anyone
holding the link, without signing in and without going through Cabinet's
own gate. An authenticating reverse proxy in front doesn't know that: it
guards everything behind it by default, so it blocks your own share links
too unless you exempt those paths from its authentication middleware. The
share routes carry their own throttle (after 20 failed lookups from one
address, or 300 a minute from all of them, a failed lookup answers 429
rather than 404; it doesn't slow guessing, since every request is still
looked up and a live link always opens: the 256-bit token is what makes a
link unguessable) and mark themselves non-indexable (`X-Robots-Tag` and
a `noindex` meta tag on the page itself; `/robots.txt` no longer disallows
`/s/`, since a crawler has to fetch the page to see that tag), so there is
nothing else the edge proxy needs to add.

With the Traefik + Authentik example above, give the share paths their own
router without the Authentik middleware (the `hsts` one stays):

```yaml
http:
  routers:
    cabinet-share:
      rule: "Host(`cabinet.example.com`) && (PathPrefix(`/s/`) || PathPrefix(`/api/share/`) || Path(`/robots.txt`))"
      entryPoints: [websecure]
      service: cabinet
      middlewares: [hsts@file]
      tls:
        certResolver: letsencrypt
    cabinet:
      rule: "Host(`cabinet.example.com`)"
      entryPoints: [websecure]
      service: cabinet
      middlewares: [authentik@file]
      tls:
        certResolver: letsencrypt
```

No `priority` is set: Traefik ranks routers by rule length when priorities
tie, and the share rule is the longer one, so it already wins over the
general host rule without one; an explicit low number here would do the
opposite of what it looks like and lose to the general rule instead.

Any other forward-auth gateway needs the equivalent: whatever it offers for
excluding a path prefix from its own authentication check. Skipping this
doesn't fail loudly: a share link just shows the gateway's own sign-in page
instead of Cabinet's share page, since the request never reaches Cabinet.
The gateway also has to normalise the request path (collapse `..`
segments, decode encoded dots) before it matches its own rules, or a path
that only looks like it starts under `/s/` or `/api/share/` after
normalisation could ride the exemption to a route it was never meant to
cover. Traefik does this itself unless `sanitizePath` is turned off on the
entry point; check that a custom gateway does the equivalent before
trusting a prefix match on unnormalised input.

A share token is redacted from nginx's access log (and the backend's), but
not from the edge proxy's own logs: Traefik's or Authentik's access log
records `/s/<token>` in clear, so treat those as sensitive too. Nor from
nginx's error log: an upstream error on a share request, such as a 502
while the backend restarts during a deploy, can quote the full request line,
token included. Treat that log as sensitive wherever it is shipped or kept,
the same as you would the access log before it was redacted.

Sharing on, and the instance reachable from outside your network, means
exactly what a share link says: anyone holding the link can see what it
shares, without signing in. Keep the switch off unless you mean to hand a
link to someone; see [security.md](security.md#accounts-and-permissions)
for what a link can and can't show. This is not, and is never meant to be,
a way to expose Cabinet itself: see section 2 above.

<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->
Cabinet is designed for private networks (a home LAN, a homelab, or a VPN
you control), not the open internet. Do not expose it directly to the
internet, even behind TLS, single sign-on, or an authenticating gateway;
reach it from outside through your own network's remote access instead,
such as a VPN (WireGuard, Tailscale, or your router's own) or an
identity-aware tunnel that terminates before Cabinet. Cabinet has one
admin account and, by design, a password sign-in path with a single
factor, so that a provider outage or a lost phone can never lock you out;
exposing any self-hosted service that holds personal records invites
automated credential guessing and vulnerability scanning within hours of
the port opening. The project cannot see or control how Cabinet is
deployed and takes no responsibility for an exposed instance. If you
deploy it this way regardless, at minimum use TLS, single sign-on with
multi-factor authentication enforced at the provider, an authenticating
gateway in front, the alert webhook switched on, and a password no human
has memorised.
<!-- exposure-warning: copied verbatim; the source is docs/deployment.md -->

### Other proxies

Any proxy works: Caddy with `basicauth`, nginx with `auth_request`, or a
tunnel that requires identity. The requirements are: TLS, authentication, and
a body-size limit that permits photo uploads. HSTS belongs on that proxy too;
Cabinet's nginx sets the other security headers itself
([security.md](security.md)).

### Checking a gateway is wired up correctly

If you keep an authenticating gateway in front, confirm each of these
before relying on it:

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
- If you configured the trusted-header mode, "Continue with the proxy's
  sign-in" appears on the sign-in page only when the request actually came
  through the gateway.

## 5. Scheduled backups

A backup is only real once it's automatic. The simplest way: Settings →
Backups → **Schedule** daily or weekly, set how many to keep, and mount the
backup directory (`/data/backups`) on storage that isn't this host's disk
(see section 3). Click **Back up now** once to confirm the directory is
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

## 6. Upgrades

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

## 7. Operational notes

- **Run one backend replica.** The price-refresh and backup schedulers run
  in-process; additional replicas would duplicate refreshes and backups.
  The sharing switch is held in each process's memory too (v0.32.0), so a
  second replica could keep opening share links after the first was
  switched off.
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
  and `revoke-tokens [--name NAME]` revokes every token or one. From v0.33.0
  `status` also lists the sign-in providers, the linked identities, and which
  sign-in methods are on. `unlink-identity <id>` unlinks one single sign-on
  identity (its id is in `status`) and ends the sessions that came through
  it. `disable-sso` switches every provider and the trusted-header mode off
  and ends their sessions, for a configuration that keeps you from the
  sign-in page; the password still works, and the linked identities stay.
  Both take effect in the running backend at once, with no restart. There
  is deliberately no command that undoes the setup or deletes the admin.
  `strip-photo-metadata` (v0.32.0) re-encodes every stored photo and
  thumbnail without EXIF, GPS, and the rest, the pass the backend runs once
  by itself; `restore.sh` runs it after putting back an archive's photos,
  and the Swarm steps in backup-restore.md include it.
  On a Swarm, `docker exec -it` into the backend task instead.

## 8. Swarm / multi-host deployment

A single host running `docker compose up` (sections 1–6) is the primary,
best-tested path. To run Cabinet as a Swarm stack instead, use
[`deploy/docker-stack.yaml`](../deploy/docker-stack.yaml):

```bash
git clone https://github.com/jsaumer/cabinet-numismatics.git
cd cabinet-numismatics
cp .env.example .env        # edit secrets
set -a; . ./.env; set +a    # stack deploy reads the shell, not .env
TAG=0.32.0 CABINET_PORT=8080 docker stack deploy -c deploy/docker-stack.yaml cabinet
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
  the backend process; a second replica would run them twice, and would
  hold its own copy of the sharing switch.
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
  file), drop its `ports:` for Traefik's labels (see section 4), and keep
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
