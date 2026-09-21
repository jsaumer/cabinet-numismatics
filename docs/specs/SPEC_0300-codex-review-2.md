# Codex adversarial review, round 2: SPEC_0300

## Verdict

**Safe with changes.** The revised gate, credential-free archive boundary,
exact restore-marker comparison, and recent-password window close the major
first-round leaks, but the plan still leaves a public request-body denial of
service and lets a live stolen session erase recovery access without a password.
The owner should also decide whether a 90-day inventory-reading token and an
unsigned, writable backup mount meet the stated physical-security bar.

## First-round findings

| Finding | Status | Reason |
| --- | --- | --- |
| C1, password changes left durable tokens | Partly closed | `read` and `write` tokens are revoked on both paths, but a metrics token deliberately survives and can retain collection totals indefinitely (`docs/specs/SPEC_0300.md:253`, `docs/specs/SPEC_0300.md:260-263`). |
| C2, archive-controlled restore marker | Closed | Recovery compares the marker to the 128-bit journal value and treats a different archive-supplied value as restored, so a backup-share writer cannot choose the branch without the state-volume journal (`docs/specs/SPEC_0300.md:120`, `docs/specs/SPEC_0300.md:133-136`). |
| C3, claimed setup-code entropy | Closed | The supplied-code check is now honestly a mistake check and `SETUP_CODE_FILE` is preferred (`docs/specs/SPEC_0300.md:334-337`). |
| C4, global login flood | Closed for the network-flood attack | A matching per-user known-device cookie receives a separately reserved Argon2 slot and skips the public limits (`docs/specs/SPEC_0300.md:244`, `docs/specs/SPEC_0300.md:267-280`). |
| C5, failed sign-ins fill audit logs or disks | Closed | Failures have a separate on-write cap, stdout is sampled, and both examples require bounded Docker logs (`docs/specs/SPEC_0300.md:286-290`). |
| H1, a read token is a collection map | Partly closed | Expiry, fresh creation, an alert, and no documents or bulk endpoint reduce duration and convenience, but a script can still page through every item, location, value, and photo (`docs/specs/SPEC_0300.md:207`, `docs/specs/SPEC_0300.md:260-262`). See pushback below. |
| H2, unlocked live session can take the collection | Partly closed | The fresh matrix covers backups, exports, restores, tokens, secrets, and permanent deletion, but not the account-destructive routes in A2 below (`docs/specs/SPEC_0300.md:208`). |
| H3, setup flood blocks the owner | Closed | The secret is checked before the wrong-code bucket and a correct value bypasses that bucket only (`docs/specs/SPEC_0300.md:280`, `docs/specs/SPEC_0300.md:341`). |
| M1, browser cache after sign-out | Closed | Default API responses and the named file classes are `private, no-store`; logout clears cache and the frontend discards collection state (`docs/specs/SPEC_0300.md:185`, `docs/specs/SPEC_0300.md:254`, `docs/specs/SPEC_0300.md:401-402`). |
| M2, modified archive changes settings | Partly closed | A new plaintext secret cannot become usable, but the archive remains unsigned and can still alter collection records, non-secret settings, or replay an old valid ciphertext (`docs/specs/SPEC_0300.md:123`, `docs/specs/SPEC_0300.md:144-145`). |
| M3, restart clears throttles | Not taken, with corrected evidence | The Swarm example does have a 1024M backend limit at `deploy/docker-stack.yaml:56-60`. Compose has no corresponding limit at `docker-compose.yaml:1-75`, which matters with A1 below. |
| L1, forwarded-header trust | Closed | The planned `--no-proxy-headers`, overwritten proxy headers, and removal of proxy allow-list settings eliminate header-based identity trust in A1 (`docs/specs/SPEC_0300.md:391`, `docs/specs/SPEC_0300.md:399`, `docs/specs/SPEC_0300.md:411-413`). |
| L2, encoded path routing | Partly closed | Raw-byte refusal is the right boundary, but the existing PCGS frontend route still constructs encoded path segments. See A4 below (`docs/specs/SPEC_0300.md:178`). |

## New findings

| ID | Severity | Harm enabled | Attack | Evidence | Exact contract rule | Test that proves it |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | high | Availability | Before any account exists, a remote client can repeatedly send 25 MiB bodies to the two public credential endpoints. The generic proxy allowance is 25 MiB, and the planned routes must parse the body to learn that it is not a valid login or setup payload. Enough concurrent requests can exhaust backend memory or make the owner unable to claim or sign in. | `proxy/nginx.conf:7` sets `client_max_body_size 25M`; its generic API proxy is at `proxy/nginx.conf:55-61`. The only anonymous POSTs are setup and login in `docs/specs/SPEC_0300.md:181` and `docs/specs/SPEC_0300.md:308-309`. The proposed 1024M bound applies only to the Swarm example today, `deploy/docker-stack.yaml:56-60`; Compose has no memory limit, `docker-compose.yaml:1-75`. | Set an 8 KiB maximum body for `POST /api/auth/setup` and `POST /api/auth/login` at nginx, and reject a declared body above that limit in the ASGI gate before routing. The body cap must also apply to chunked requests. Set an explicit backend memory limit in the Compose deployment example, matching the capacity calculation in section 5. | Through real nginx, send valid small setup and login bodies, then a 8193-byte Content-Length body and a larger chunked body to both routes. Each large request is 413, never reaches the handler, and parallel attempts cannot prevent a valid known-device login. |
| A2 | medium | Availability | A person holding an unlocked browser with a live session cannot export or restore without the password again, but can list and revoke every token, end every other session, or call sign-out-everywhere. That can remove monitoring and sign the owner out of all devices, making recovery during an incident harder. | The fresh list omits account-destruction routes at `docs/specs/SPEC_0300.md:208`; `DELETE /api/auth/sessions`, `DELETE /api/auth/sessions/{id}`, and `DELETE /api/auth/tokens/{id}` are ordinary admin routes at `docs/specs/SPEC_0300.md:315-320`. Sign-out-everywhere also deletes known devices, `docs/specs/SPEC_0300.md:317`. | Keep ordinary logout passwordless, but require recent-password confirmation for sign-out-everywhere, ending a different session, and revoking a token. A current-session logout may remain immediate. | A stale session can log itself out, but receives the defined `reauth_required` 403 when it tries to end another session, sign out everywhere, or revoke a token. The same actions succeed after confirmation; every token still receives 403. |
| A3 | medium | Control of the deployment; availability | An upgrade from a database containing a legacy plaintext secret will silently lose its price-source key, webhook, or heartbeat when the self-heal is removed. That is an existing supported state, not a hypothetical row, and losing the alert webhook can hide the very authentication events this release adds. Automatically encrypting that value during an upgrade is unsafe, because a pre-A1 archive restored later could use the same path to plant a secret. | The current self-heal accepts and encrypts plaintext at `backend/app/services/app_settings.py:71-76`, and `crypto.decrypt` returns unprefixed input at `backend/app/services/crypto.py:91-96`. Its current behavior is covered by `backend/tests/test_crypto.py:116-127`. The new contract removes it, `docs/specs/SPEC_0300.md:144-145` and `docs/specs/SPEC_0300.md:539`, but the upgrade warning at `docs/specs/SPEC_0300.md:527-529` does not mention the consequence. | Make this an explicit fail-safe migration rule: on v0.30 startup and after restore, clear every nonempty, unprefixed value for the four `SECRET_KEYS`, report only their names, and never auto-encrypt them. Add the required re-entry to the release warning, setup/upgrade screen, and restore outcome. | Start from a v0.29.1-shaped database holding plaintext values for all four secret keys. Upgrade and assert each is unset, named once without its value, and never used. Restore a pre-A1 archive containing a plaintext webhook and assert it remains unset after collection migration. |
| A4 | low | Availability | The blanket percent rule conflicts with an existing frontend URL builder: it applies `encodeURIComponent` to the PCGS certificate path segment. The backend currently accepts any 1 to 20 character `cert`, so whitespace or a slash produces a path the planned gate will intentionally reject. | `frontend/src/api/calls.ts:180` builds `/api/pcgs/cert/${encodeURIComponent(cert)}`. The route accepts `cert: str` with only length validation at `backend/app/routers/catalogue.py:18-24`. The proposed gate rejects every percent in an API raw path, `docs/specs/SPEC_0300.md:178`. | Preserve the raw-path rejection. Before A1 ships, define the PCGS certificate identifier as its actual ASCII grammar, validate it in the frontend before building the URL and in the backend route, and ensure no supported value encodes to `%`. | The route matrix includes every supported certificate form and proves it has no percent-encoded raw path. Inputs outside that grammar are rejected by the frontend and with a documented backend 422, while encoded anonymous and authenticated paths remain 400. |

## Pushback on the pushback

**Read tokens.** I still disagree that the current H1 treatment is enough for
this product. A 100 to 500 item collection is easy to copy by pagination: a
`read` token gets every item, storage location, value, and photo
(`docs/specs/SPEC_0300.md:207`; photo authorization is also read at
`docs/specs/SPEC_0300.md:405-407`). No bulk route changes transfer speed, not
the physical-security outcome; a 90-day expiry is a long exposure window and
there is no alert when a stolen token is used. This is not a request for
partial redaction. Do not offer UI issuance of the broad `read` scope in
v0.30.0, because the listed integrations need `metrics` or `write`; retain
the implementation and introduce an explicitly named, short-lived inventory
scope only when a real automation need is approved.

**Metrics after a password change or reset.** I also disagree with retaining
metrics tokens by default. Someone who learned the password can satisfy the
fresh-password check, mint a non-expiring metrics token, and retain collection
value and cost totals after the owner changes the password
(`docs/specs/SPEC_0300.md:253`, `docs/specs/SPEC_0300.md:260-263`). It is less
harmful than locations, but it is still valuable targeting information. Revoke
all token scopes on password change and reset. The operational cost is
replacing a Homepage or Prometheus secret, which is the appropriate response
to a suspected password compromise.

**Unsigned archives.** I still disagree with leaving archive signing out of
the release if a writable NAS share remains a supported backup target. The
new secret rule stops one specific deployment takeover, but it cannot detect
changed values, locations, receipts, or non-secret settings in an archive;
the contract itself says the checksums live inside that archive
(`docs/security.md:328-335`). A writer can also replay a ciphertext copied
from an earlier backup that was encrypted under the current key. Add optional
archive signing in v0.30.0, with a verification key or public key outside
`BACKUP_DIR`, and make both the in-app and `restore.sh` paths verify it. If
that cannot ship, the release documentation should say a writable backup
mount is not a trustworthy restore source and require an immutable or
separately protected copy for integrity.

## Not verified

- No v0.30.0 code exists, so gate ordering, CSRF, fresh-route enforcement,
  migration behavior, alert payloads, and known-device reservation were
  reviewed as contract rules rather than executed behavior.
- I did not run Postgres restore experiments. The marker conclusion depends
  on the planned `pg_restore --schema=public --clean` behavior, which needs
  the specified real-Postgres tests before release.
- I did not run nginx or browser tests. The current proxy is pre-auth
  (`proxy/nginx.conf:1-86`), so percent-path, `auth_request`, host handling,
  request-body limits, and cache behavior remain implementation checks.
- No `.env` file, live instance, Docker API, NAS mount, or live Swarm
  configuration was read or contacted. The actual network rule that only
  nginx can reach the backend remains an operator verification.
