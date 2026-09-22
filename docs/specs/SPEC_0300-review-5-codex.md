# Codex implementation review, round 5: v0.30.0

## Verdict

**Approve for the stated scope.** I found no critical, high, medium, or
low-severity implementation finding in `git diff v0.29.1..HEAD` that gives an
unauthenticated or insufficiently scoped party a practical way to read the
collection or its storage locations, alter it, obtain a credential, or bypass
the encrypted archive boundary. The contract does not need to reopen.

## Findings

None.

I considered, but did not record as findings, the deliberate low-risk items
listed in the brief: the break-glass `restore.sh` path has no `RESTORE OLDER`
prompt, same-second ledger names can replace a ledger row, setup-code
throttling cannot slow a correct 128-bit-or-better code, and an authenticated
but under-scoped import upload can be parsed before FastAPI returns its 403.
Each either requires an already privileged actor or is covered by the stated
design decision. I found no concrete attack that changes that assessment.

## Checked and found sound

- **Default-deny gate and route coverage.** The ASGI gate rejects encoded
  paths before routing, admits only the four anonymous method/path pairs, and
  returns 401 for every other anonymous or unknown request
  (`backend/app/auth/gate.py:36-45`, `backend/app/auth/gate.py:172-234`).
  It treats an invalid Cabinet bearer token as invalid rather than falling
  back to a session cookie (`backend/app/auth/gate.py:201-218`). Layer 2
  refuses any matched handler lacking `@permission`, including in production
  (`backend/app/auth/permissions.py:124-135`). The route-matrix test derives
  operations from OpenAPI and checks the registered endpoint declarations
  (`backend/tests/test_gate.py:20-42`).

- **Scopes, fresh actions, and maintenance.** Token access is constrained to
  read, write, or the explicit `metrics_ok` exception; tokens cannot satisfy
  admin or fresh requirements (`backend/app/auth/permissions.py:95-113`). A
  password confirmation belongs to an individual session and expires after
  five minutes (`backend/app/auth/sessions.py:13-18`,
  `backend/app/auth/sessions.py:77-80`). During restore, the status exception
  compares the holder's session-secret digest with the short-lived in-memory
  grant and does no database lookup while the database is being replaced
  (`backend/app/services/restore.py:246-276`,
  `backend/app/auth/gate.py:185-199`).

- **CSRF and browser credentials.** Cookie requests require a same-origin
  fetch signal, or an exact configured Origin or Referer fallback. The only
  `Sec-Fetch-Site: none` exceptions are the session-only OpenAPI and document
  download paths, plus the deliberately narrower photo check
  (`backend/app/auth/gate.py:144-156`). Setup and login additionally reject
  same-site and cross-site posts (`backend/app/auth/gate.py:220-228`). Normal
  deployments use host-only, Secure, HttpOnly session cookies and Lax or
  Strict SameSite attributes (`backend/app/auth/sessions.py:59-87`).

- **Credential lifecycle and throttling.** Session, device, and token values
  are 256-bit random secrets represented as base64url and stored only as
  SHA-256 digests (`backend/app/auth/common.py:12-40`,
  `backend/app/auth/tokens.py:65-100`). Password checks use Argon2id with two
  bounded verification slots (`backend/app/auth/passwords.py:17-29`,
  `backend/app/auth/passwords.py:74-101`). Account, address, and global
  throttles count before Argon2 work; a known device merely reserves one
  bounded slot and never authenticates a route (`backend/app/auth/accounts.py:137-181`,
  `backend/app/auth/devices.py:48-82`). Password change and command-line reset
  both revoke every scope of API token, all sessions, and all known devices
  (`backend/app/auth/accounts.py:266-295`, `backend/app/auth/accounts.py:317-335`).

- **Secret and collection-data exposure.** The audit layer rejects detail
  keys that could carry credentials, samples failed-login stdout messages,
  and states that collection fields and secrets never enter rows, lines, or
  webhooks (`backend/app/auth/audit.py:1-9`, `backend/app/auth/audit.py:56-116`).
  The global response wrapper adds `Cache-Control: private, no-store` unless
  a route supplied a policy, and static photos explicitly receive the same
  policy (`backend/app/auth/gate.py:237-247`, `proxy/nginx.conf:89-96`). The
  frontend stores only a failed-login notice and cosmetic preferences, not a
  credential or collection value (`frontend/src/auth/failedNotice.ts:1-33`,
  `frontend/src/components/theme.ts:1-10`). The login redirect validates that
  `next` remains same-origin (`frontend/src/pages/Login.tsx:8-22`).

- **Encrypted archives and restoration.** The MAC covers canonical manifest
  bytes without `mac`, followed by `SHA256SUMS`, using HKDF-SHA256 from the
  exact 32-byte identity secret (`backend/app/services/archive_keys.py:283-313`).
  Verification requires the named configured identity, rejects duplicate or
  unexpected zip members, verifies the MAC before payload checks, and hashes
  every declared member (`backend/app/services/archive_keys.py:304-313`,
  `backend/app/services/backup.py:490-533`). New archives are streamed into
  age and only the ciphertext partial is renamed into the backup directory
  (`backend/app/services/backup.py:620-632`). Decryption and dump extraction
  are limited to the configured private staging directory, which is checked
  not to nest with the backup, photo, document, or state locations
  (`backend/app/services/backup.py:429-473`,
  `backend/app/services/backup.py:536-550`).

- **Restore safety.** A restore refuses a non-age input before decrypting,
  verifies the archive before extraction, blocks tar links, absolute paths,
  traversal, and restore work-directory names, then rechecks the archive and
  its authentication-schema exclusion immediately before use
  (`backend/app/services/restore.py:297-389`,
  `backend/app/services/restore.py:1017-1058`). Archive provenance is bound
  to the verified MAC digest and recipient, while rollback age comes from the
  authenticated manifest timestamp rather than the filename or mtime
  (`backend/app/services/restore.py:431-479`). Cleanup runs on every outcome
  and restore alerts intentionally omit error text that might quote database
  rows (`backend/app/services/restore.py:1130-1163`).

- **Proxy and frontend boundary.** nginx answers an unlisted Host with 444,
  clears forwarded and common gateway identity headers for every proxied
  backend location, and keeps the photo directory behind an auth subrequest
  (`proxy/nginx.conf:1-12`, `proxy/nginx.conf:21-85`,
  `proxy/cabinet-proxy.conf:1-38`). The configured host generator rejects
  schemes, ports, paths, and malformed host names before nginx starts
  (`proxy/40-cabinet-hosts.sh:17-43`). The frontend fetch wrapper does not add
  credential persistence, and retries a fresh action at most once after the
  confirmation dialog (`frontend/src/api/client.ts:63-103`).

## Verification performed

- Confirmed branch `p8-auth-a1`; reviewed `git diff v0.29.1..HEAD` and the
  contract, plain-language guide, implementation notes, and prior four
  contract reviews.
- Ran `git diff --check v0.29.1..HEAD`: pass.
- Ran the allowed isolated backend tests with `-p no:cacheprovider`:
  `test_gate.py`, `test_auth_routes.py`, `test_credentials.py`, and
  `test_auth_schema.py`: **148 passed**. `test_archives.py`: **49 passed**.
  `test_restore.py`: **48 passed, 1 skipped**. All three commands exited 0.

## Not verified

- I did not run Docker, nginx, PostgreSQL, the real `age` binary, shell
  backup or restore scripts, Playwright, CI smoke tests, an SSO or
  forward-auth gateway, or a live deployment. Those require the release
  environment and are outside this read-only review.
- The frontend lint command could not run because `npm` is not available in
  this review environment. I performed a source inspection of the changed
  frontend authentication paths instead.
- I did not inspect any `.env` file, Docker state, volume, secret, backup,
  database, or live endpoint.
