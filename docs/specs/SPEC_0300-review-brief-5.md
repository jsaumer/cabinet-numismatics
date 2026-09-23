# Review brief, round 5: the v0.30.0 build

The four earlier rounds reviewed the contract. This one reviews **the code
that implements it**, before the owner tags v0.30.0 and it reaches the live
instance. Cabinet catalogues a private coin and banknote collection,
including **where each piece is kept**; a read-only copy of that data is the
worst case, because it can lead to physical theft. v0.30.0 is the release
that closes the app: before it, anyone who could reach Cabinet could read
and change everything.

The same brief goes to two reviewers working independently, Fable and
Codex. Please be thorough: comb the diff with a fine-toothed comb. The
owner's rule for what follows: **a critical or high finding reopens the
contract**; anything medium or lower is fixed or recorded as a rule. So
please grade severity carefully and say plainly when something is not worth
a finding.

## Rules

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0300-review-5-<you>.md` (`-fable` or `-codex`). Change no
  other file, create no branch, commit nothing, push nothing, run no
  migration against anything but a throwaway database.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud). Don't run Docker: the owner's local stack is not
  yours to change.
- You may run the test suite (`backend/`: `.venv/Scripts/python.exe -m pytest
  -q -p no:cacheprovider`, about three minutes; tests use in-memory SQLite and
  mock every outbound call) and read-only Python in `backend/.venv` with a
  throwaway database (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, `PUBLIC_ORIGINS=https://testserver`, temp
  `PHOTO_DIR`, `DOCUMENT_DIR`, `STAGING_DIR`, and `SECRET_KEY_FILE`). A
  throwaway script in a temp folder is fine; delete it afterwards.
- Every repo claim needs a `file:line`; every library or format claim its
  source and how you checked it. Label anything unverified. Where you can,
  prove a finding with a failing test or a short reproduction and include it.
- No em dashes anywhere in your output (the owner's rule).
- **Out of scope by the owner's decision:** protecting the database, photo,
  document, and staging volumes (the operator's storage); restoring archives
  made before v0.30.0; trusting forwarded headers (`TRUSTED_PROXIES`); pinned
  Docker networks; an interactive `/api/docs` page; an API call counter.
- Settled decisions are challenged only with a concrete attack.

## What to read

1. `docs/specs/SPEC_0300.md`, the contract: sections 1 to 7, 9, and the
   appendix of route permissions. Sections 12 to 15 record what the earlier
   reviews found and what was taken.
2. `docs/specs/SPEC_0300-how-it-works.md`, the same in plain words.
3. `docs/implementation-notes.md`, "Authentication and encrypted backups
   (v0.30.0)": the rules the build settled on, including every departure
   from the contract.
4. The diff: `git diff v0.29.1..HEAD` on branch `p8-auth-a1` (PR #21).
   The heart of it:
   - `backend/app/auth/`: `gate.py` (layer 1, before routing),
     `permissions.py` (layer 2, `@permission` on every route), `accounts.py`,
     `passwords.py`, `sessions.py`, `tokens.py`, `devices.py`,
     `throttle.py`, `audit.py`, `notify.py`, `setup.py`, `events.py`,
     `common.py`.
   - `backend/app/routers/auth.py` and every `@permission` line in
     `backend/app/routers/`.
   - `backend/app/services/archive_keys.py`, `backup.py`, `restore.py`,
     `backend/app/cli.py`, `scripts/backup.sh`, `scripts/restore.sh`.
   - `backend/app/config.py`, `backend/app/main.py`,
     `backend/docker-entrypoint.sh`, `backend/Dockerfile`.
   - `proxy/nginx.conf`, `proxy/cabinet-proxy.conf`,
     `proxy/cabinet-headers.conf`, `proxy/40-cabinet-hosts.sh`,
     `frontend/Dockerfile`, `docker-compose.yaml`, `deploy/docker-stack.yaml`.
   - `frontend/src/auth/`, `frontend/src/api/client.ts`,
     `frontend/src/pages/Login.tsx`, `Setup.tsx`,
     `frontend/src/components/account.tsx`.
   - The tests that pin it: `backend/tests/test_gate.py`,
     `test_auth_routes.py`, `test_credentials.py`, `test_cli_accounts.py`,
     `test_archives.py`, `test_restore.py`, `test_auth_schema.py`, and the
     outside-in checks in `scripts/ci/stack-smoke.sh` and
     `scripts/ci/upgrade-test.sh`.

## Deliberate departures (already decided; challenge only with an attack)

- `POST /api/auth/password` and `/api/auth/username` are not marked fresh:
  the current password in their body is the confirmation.
- A wrong password on confirm, password change, or username change answers
  403, not 401, so a signed-in page isn't mistaken for a signed-out one.
- nginx forwards the raw request URI (`proxy_pass` with no path), so the
  gate's "any `%` is 400" rule sees what the client sent.
- Sign-in and setup also refuse `Sec-Fetch-Site: cross-site` and
  `same-site`, and require `Content-Type: application/json` (stricter than
  the contract).
- The in-memory throttles are cleared by `reset-password` through a flag
  file that every throttle check reads (the contract said the gate reads it).
- The archive commands (`decrypt-archive`, `verify-archive`,
  `write-archive`) work before setup, for `restore.sh` and `backup.sh` on a
  fresh machine; the account and `backup-key` commands refuse until claimed.
- Live token names are unique (the CLI revokes by name); audit events
  `backup_key_saved` and `unencrypted_deleted` were added.
- A multipart upload to `/api/imports` is read before the permission check
  (FastAPI parses the body first), so a `read` token can make it read up to
  nginx's 1 GB cap before its 403. Restore uploads stream after the check.
- The setup throttle cannot slow a brute force, because a right code always
  passes; the code's length (128 bits or more) is the protection.
- Photos: the `auth_request` check costs about 3.5 ms a photo; no cache.
- A failed restore's alert carries no error text (pg_restore can quote rows).
- Accepted lows from the stage 5 review: `restore.sh` has no `RESTORE OLDER`
  gate (it is the break-glass path and prints the archive's date), and a
  second archive written in the same second takes over the ledger row by
  name.

## What to check

Anything that is exploitable or fails open, and anything where the code
does not do what the contract or the notes say. In particular:

1. **Getting past the gate.** Any route, path form (encoding, dot segments,
   double slashes, `;`, case, trailing slash), method (HEAD, OPTIONS),
   header, or maintenance-mode path that reaches data without the right
   credential. Token scope escalation. A stale session on a fresh route.
   The OpenAPI route. The restore grant. Nested routers.
2. **Cross-site requests.** `Sec-Fetch-Site` and Origin or Referer
   handling, the two `none` exceptions, the photo check, sign-in CSRF, the
   frontend's `next` redirect, cookie attributes, `AUTH_INSECURE_HTTP`.
3. **Credentials.** Generation, storage (hashes only), comparison, idle and
   absolute expiry, rotation, revocation (password change and reset revoke
   every token of every scope), the known-device cookie and the reserved
   check slot, throttle bypasses, timing, the setup code and the claim race,
   the claimed marker.
4. **Leaks.** Any password, setup code, token secret, backup key, or piece
   of collection data in a log line, error, audit row, alert, validation
   echo, or cached response.
5. **Backups and restore.** The MAC (what it covers, canonical form, zip
   quirks, duplicate or extra members), `age` invocation, staging
   permissions and clean-up, tar and zip path traversal, the restore marker
   and `recover()`, `restore.sh` and `backup.sh` quoting and traps, the key
   file (generated once, never overwritten), and any plain text written
   where it must not be.
6. **The container commands.** Privilege drop, argv, output.
7. **nginx.** Every location includes what it must; forwarded and identity
   headers; the 444 default server; body caps; `auth_request` on every
   path that serves a photo, and nothing else served from disk that should
   not be.
8. **The frontend.** XSS sinks, anything sensitive in `localStorage` or
   `sessionStorage`, the token shown once, the reauth retry.
9. **Tests that could pass while the behaviour is wrong.**

## Output

Findings first, most severe first: severity, `file:line`, what is wrong, a
concrete failure scenario, and the fix you'd make. Then what you checked and
found sound, briefly. Then anything you could not verify.
