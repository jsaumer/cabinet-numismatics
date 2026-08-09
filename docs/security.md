# Security

Cabinet is a single-user, self-hosted application. The design assumes the
stack runs on a network you control, and that the operator is the only user.
This document records what that means concretely, what is protected and how,
and what you must do before exposing the app more widely.

## Secrets at rest

Price-source credentials (Numista API key, PCGS token) are **encrypted before
they reach the database**, using [Fernet](https://cryptography.io/en/latest/fernet/)
from the `cryptography` library — AES-128-CBC with an HMAC-SHA256
authentication tag. Encryption is authenticated, so a tampered value fails to
decrypt rather than yielding garbage, and each write uses a fresh random IV,
so storing the same key twice produces different ciphertext.

Stored values carry an `enc:v1:` prefix identifying the scheme, which leaves
room for future algorithm changes without ambiguity.

**These credentials are also write-only through the API.** `GET /api/settings`
returns whether a secret is configured plus a last-4 hint (`…abcd`) — never
the value. There is no endpoint that reveals a stored secret, and secrets are
never written to logs, error messages, or URLs (they travel only in `PUT`
request bodies).

If a secret cannot be decrypted — the key was rotated away or lost — the app
reports that source as *not configured* rather than failing. Re-enter the key
in Settings.

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

The collection data itself — items, photos, estimates — is stored unencrypted
in postgres and on the photo volume. For a personal catalog on your own
hardware this is the appropriate trade-off: it keeps backup, restore, and
inspection simple. If the host is untrusted or portable, use full-disk or
volume-level encryption underneath the stack rather than application-level
encryption.

Backups (`scripts/backup.sh`) contain the database, so they contain the
**encrypted** credentials — but not the key, which lives in `.env` or on the
state volume. A backup restored without the matching key works fine; you just
re-enter the source API keys. Treat `.env` as sensitive: it holds the database
password and the encryption key.

## Authentication & network exposure

There is **no application-level authentication**, by design — see the roadmap's
sequencing notes. Cabinet is safe to run on a trusted LAN. Before exposing it
beyond that:

- Put it behind an authenticating reverse proxy (Traefik + Authentik
  forward-auth is the intended path) — this requires no application changes.
- Terminate TLS at the proxy so credentials entered in Settings and photos are
  not transmitted in the clear.
- Application-level login is only necessary for direct public exposure; it is
  tracked with the open-source release work.

Do not port-forward the stack to the internet as-is.

## Input handling

- **Uploads** are validated as real JPEG/PNG/WebP images by decoding them with
  Pillow; the client-declared content type is not trusted. Images are
  re-encoded for thumbnails, and originals are stored under generated UUID
  filenames, so user-supplied filenames never reach the filesystem or a URL.
- **Database access** goes exclusively through SQLAlchemy's parameter binding;
  there is no string-built SQL.
- **Custom fields** are bounded (20 keys, 50-char names, 500-char string
  values) so arbitrary payloads can't be stashed in the JSON column.
- **Outbound requests** go only to the two documented price/rate APIs, with
  timeouts and cached fallbacks. No collection data is ever sent outward.

## Dependencies

Runtime dependencies are pinned by minimum version and installed fresh at
image build. Rebuild periodically (`docker compose build --pull`) to pick up
security fixes in the base images and Python packages.
