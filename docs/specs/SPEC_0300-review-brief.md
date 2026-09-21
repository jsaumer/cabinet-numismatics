# Review brief: SPEC_0300, authentication for a tool about valuables

This brief is for an outside reviewer (Codex, run locally in this repo). It
asks for an adversarial review of the v0.30.0 authentication contract,
`docs/specs/SPEC_0300.md`, with one question above all others: **if this is
built exactly as written, can someone who should not see or control this
collection do so?** Nothing has been built yet. The owner will not approve
the contract until this review is answered.

## Rules for the reviewer

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0300-codex-review.md`. Create or change no other file,
  create no branch, commit nothing, push nothing, run no migration.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud).
- You may run read-only Python in `backend/.venv` against `app.main:app` with
  a throwaway database (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, `PHOTO_DIR` and `DOCUMENT_DIR` pointing at a
  temp folder) to check how FastAPI and Starlette really behave.
- Every claim about the repo needs a `file:line`. Every claim about a library
  needs its version and how you checked it. Label anything you did not verify.
- No em dashes anywhere in your output (the owner's rule).
- Settled decisions (listed below) are not up for debate on taste. Raise one
  only with a concrete attack or defect it causes, and say plainly that you
  are doing so.

## Why this is not an ordinary login

Cabinet catalogues a private coin and banknote collection. The database holds
what each piece is, what it cost, what it is worth now, certificate numbers,
photos, receipts with names and addresses, and **where each piece is stored**
(a free-text location such as "safe, top shelf" or "bank box 12"). Put
together, that is a burglar's shopping list with a map. The owner's words:
"valuables + auth is big for me."

So judge every finding by what it gives an attacker, in this order of harm:

1. **Knowing what is where and what it is worth**: the item list with
   storage locations, values, and photos. A read-only leak is the worst case
   here, not the mildest, because it can lead to physical theft or targeting
   of a person.
2. **Personal data**: receipts and documents with names and addresses.
3. **Control of the collection record**: deleting, altering, or restoring
   over it (an insurance claim depends on it).
4. **Control of the deployment**: settings, stored API keys for Numista and
   PCGS, the alert webhook (which could be pointed somewhere else), backups.
5. **Availability**: locking the owner out.

Attackers to consider, most likely first:

- Someone on the same home network: a guest, a contractor, a compromised
  smart device or another container on the homelab.
- Someone who knows the owner collects and targets them: a visitor, an
  acquaintance, a former partner, someone who saw a post.
- An internet scanner, if the instance is ever exposed (it sits behind
  Traefik, sometimes with Authentik forward-auth, sometimes without).
- A thief holding an unlocked laptop or phone with a live session.
- Anyone who can read the backup mount (often a NAS share) or the Docker API
  (Portainer, Dozzle, `docker service inspect`).
- A compromised dependency or browser extension in the signed-in page.

## What to read

1. `docs/specs/SPEC_0300.md`: the contract. Section 11 has the owner's
   decisions. The appendix lists every route and its permission.
2. `docs/security.md` ("Authentication & network exposure" and "Next:
   accounts and permissions"), the P8 entry in `docs/roadmap.md`, `CLAUDE.md`.
3. The code the contract changes: `backend/app/main.py`,
   `backend/app/services/{maintenance,restore,backup,schema,app_settings}.py`,
   `backend/app/routers/{health,restore,items,estimates,documents,settings,backup}.py`,
   `backend/app/models/item.py`, `backend/tests/conftest.py`,
   `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `proxy/nginx.conf`,
   `frontend/Dockerfile`, `docker-compose.yaml`, `deploy/docker-stack.yaml`,
   `.github/workflows/ci.yml`, `scripts/backup.sh`, `scripts/restore.sh`,
   `frontend/src/api/client.ts`.

Repo state: `main` is v0.29.1 code plus docs-only commits. Pinned versions:
FastAPI 0.141.1, Starlette 1.6.0, uvicorn 0.53.0, SQLAlchemy 2.0.54, Alembic
1.20.0, nginx 1.31-alpine, Postgres 16.

## How the contract was made

- Base decisions with the owner on 20 and 21 September 2026.
- Four outside reviews the same day, each overriding the ones before where
  they differed. The last (yours, Codex, in an earlier session) produced the
  separate `cabinet_auth` schema, credential-free backups, the two-layer gate,
  fail-closed CSRF, the stored device cookie, `ALLOWED_HOSTS`, the restore
  marker row, and the two-route metrics scope.
- Every plan claim was then checked against the code by read-only agents;
  nine mismatches are listed in the spec's "Plan versus code" section.
- The owner then **simplified**: no pinned network ranges; no
  `TRUSTED_PROXIES` (nginx believes no forwarded header); throttle counters in
  memory; no audit merging; the `/api/docs` page turned off. The owner **added**
  account tools: four container commands (`reset-password`,
  `sign-out-everywhere`, `revoke-tokens`, `status`), a username change, and a
  "failed sign-ins since your last visit" notice.
- The build is ten stages, each with tests and an exit check judged by exit
  status.

## Settled (challenge only with a concrete attack)

One admin; a setup code of at least 128 bits, claimed once; login always on,
no switch; Argon2id (t=3, m=64 MiB, p=4, two at a time); passwords 12 to 256
characters; database sessions, one day idle and seven days absolute; tokens
`read`, `write` (includes read), and `metrics`, one scope each, never reaching
an admin route; `cabinet_auth` never in a backup and never restored; photos
checked by nginx `auth_request` with no cache; `PUBLIC_ORIGINS` required;
`ALLOWED_HOSTS` with 444 for any other Host; no pinned networks; no
`TRUSTED_PROXIES`; no docs page; single sign-on is the next release, not this
one.

## The review the owner wants

### 1. Could the collection leak?

Trace every way to read item data, photos, documents, or storage locations
without the admin's session or a proper token, and every way a legitimate
credential could read more than it should:

- **The gate.** Layer 1 matches the raw method and path; layer 2 checks each
  route's declared permission after routing. Try percent-encoding, `//`,
  `..`, `;` parameters, case, trailing slashes, `root_path`, HEAD, OPTIONS,
  and anything else that could make Starlette route to a handler while layer
  1 believes the path was allow-listed, or unknown and harmless.
- **Photos.** nginx serves `/photos/` after an `auth_request` subrequest.
  Are there paths, encodings, aliases, or error codes that serve a photo
  without the check, or leak which photos exist?
- **Tokens.** A `read` token reaches the whole inventory, storage locations
  included. Is that acceptable for a tool like this, or should locations,
  documents, or costs sit behind something stricter? Say what you would do
  and what it costs.
- **Bulk exfiltration in one request**: `GET /api/backup.zip`, the CSV and
  XLSX exports, `GET /api/items` with a large page. Should any of these
  require the password again, notify the owner, or be limited?
- **Caching**: can anything sensitive stay in a browser cache, a proxy
  cache, or Traefik after sign-out? Check the contract's `Cache-Control`
  rules against every response type (JSON, photos, documents, exports,
  backups).
- **Side channels**: health (anonymous gets only a status word), the setup
  state endpoint, error messages, timing on sign-in, the 401 versus 404
  split for unknown paths.
- **Logs and alerts**: could an item name, a storage location, a document,
  a setup code, or a password (typed into the username box) end up in the
  audit log, stdout, the alert webhook, or a Prometheus label?

### 2. Could someone take control?

- **Setup.** The code printed in the log, `SETUP_CODE` in the environment,
  the claimed marker on the state volume, the `claim` singleton row. What
  happens on an upgrade of an open install, a fresh machine, a lost state
  volume, a restore onto an empty database? Is there any window where
  whoever arrives first wins?
- **Sessions.** Fixation, rotation, the `__Host-` prefix being conditional
  on `Secure`, `AUTH_INSECURE_HTTP` and its guard (every origin must be
  `http`), logout, sign-out everywhere, a stolen laptop.
- **CSRF.** The fail-closed rule, its two `none` exceptions
  (`/api/openapi.json`, a document file), the photo check that refuses only
  `cross-site`, `Origin: null`, requests with no `Sec-Fetch-Site`, and
  sibling subdomains under the same parent domain.
- **Brute force and lockout.** In-memory throttles, the known-device cookie
  (the only thing separating the owner from an attacker when every client
  shares the Swarm ingress address), the global limit, and the CLI clearing
  throttles through a flag file on the state volume. Can an attacker lock
  the owner out, or guess faster than intended?
- **The account tools.** Username change (enumeration?), the failed-attempts
  notice, `reset-password` (does anything leak through argv, the process
  list, shell history, or container logs?), `revoke-tokens`, `status`.
- **Restore.** A restore replaces the whole collection. Check the restore
  grant, the marker row and `recover()` (section 2's table, including
  "database unreachable, stay in maintenance"), the refusal of archives
  holding `cabinet_auth` objects, and whether
  `pg_restore --schema=public --clean` on Postgres 16 really leaves
  `cabinet_auth` untouched (the schema itself, sequences, ownership,
  extensions). Could a tampered archive on the backup mount plant anything
  that matters, such as a webhook URL in settings?
- **Secrets.** Price-source keys and the webhook URL are Fernet-encrypted
  and write-only today. Does anything in the contract weaken that?

### 3. What is missing for valuables

The owner asked earlier whether the plan is "overcooked". Answer the other
side too: what would you expect a tool guarding this kind of data to have
that the contract lacks? Consider at least:

- a second factor for the admin (TOTP or WebAuthn passkeys), in this release
  or the next;
- asking for the password again before a restore, a backup download, a
  token creation, or a settings change that touches secrets;
- a webhook alert on a new sign-in, a new device, a new token, a backup
  download, or repeated failures;
- shorter sessions, or sign-in bound to one device;
- anything about storage locations specifically (for example, hiding them
  from tokens, or keeping them out of exports and backups by choice).

For each, say which release it belongs in (v0.30.0 now, v0.31.0 with single
sign-on, or never), what it protects against, and roughly what it costs.

### 4. What is more than it needs to be

Anything in the contract that adds complexity or risk without protecting
the collection. Say what would be lost by cutting it.

### 5. The process

Briefly: is the stage order safe (could any intermediate stage ship
something weaker than today's "trusted network only" stance)? Are the exit
checks strong enough to catch each stage's most likely mistake? Does the
test plan (OpenAPI-driven anonymous, completeness, and scope matrices;
source lint; ordering tests; outside-in CI against real nginx and Postgres)
leave any class of bug uncaught?

## Output

Write `docs/specs/SPEC_0300-codex-review.md`, in plain words:

1. **Verdict**: safe to build as written, safe with changes, or not safe,
   in three sentences at most.
2. **Findings**, most severe first, as a table: id, severity (critical,
   high, medium, low), which harm from the list above it enables, the
   attack in one or two sentences, evidence (`file:line`, spec section, or
   library behaviour and how you checked), the exact rule to put in the
   contract, and the test that proves it.
3. **Add list** and **cut list**: one line each, with the release it belongs
   in and what it protects or costs.
4. **Not verified**: what you could not check, and why.
