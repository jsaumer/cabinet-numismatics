# Plan review brief: Cabinet v0.33.0, single sign-on (P8 A2)

You are reviewing a **plan before any code exists**: `docs/specs/SPEC_0330.md`
on the branch `p8-auth-a2` of C:\git\cabinet-numismatics (approved by the
owner on 24 September 2026; its section 15 records every decision). The
owner wants a second pair of eyes on the design before stage 1 is built.
Nothing in this release has been written yet, so you are reviewing the
contract, not a diff.

## Rules for the reviewer

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0330-codex-review.md`. Create or change no other file,
  create no branch, commit nothing, push nothing, run no migration.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud) or any identity provider.
- You may run read-only Python in `backend/.venv` against `app.main:app`
  with a throwaway database (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, `PUBLIC_ORIGINS=https://testserver`,
  `PHOTO_DIR` and `DOCUMENT_DIR` pointing at a temp folder), and the test
  suite with `.venv\Scripts\python.exe -m pytest -q`, to check how the
  gate, FastAPI, and Starlette behave today.
- Every claim about the repo needs a `file:line`. Every claim about a
  protocol or a library needs the RFC or spec section, or the library
  version and how you checked. Label anything you did not verify.
- No em dashes anywhere in your output (the owner's rule).
- Settled decisions (below) are not up for debate on taste. Raise one only
  with a concrete attack or defect it causes, and say plainly that you are
  doing so.

## What to read, in order

1. `docs/specs/SPEC_0330.md`, whole. Section 1 is the questions, section
   15 the answers; sections 5, 5a, 7, 8, and 9 are the design a review
   can attack.
2. `CLAUDE.md` (the project's standing rules), then `docs/security.md`
   "Accounts and permissions" (the A1 decisions table and the permission
   table).
3. `docs/specs/SPEC_0300.md` sections 3, 4, 5, and the appendix (the
   gate, CSRF, credentials, and the class of every route, which
   `backend/tests/test_gate.py` enforces), because A2 must fit inside it.
4. The code A2 extends: `backend/app/auth/gate.py`, `permissions.py`,
   `sessions.py`, `accounts.py`, `throttle.py`, `audit.py`, `notify.py`,
   `setup.py`, `backend/app/models/auth.py`, `backend/app/routers/auth.py`,
   `backend/app/main.py` (the log filter and middleware order),
   `backend/app/config.py` (`check_startup`, `normalize_origin`),
   `proxy/nginx.conf`, `proxy/cabinet-proxy.conf`, `proxy/40-cabinet-hosts.sh`,
   `frontend/src/App.tsx`, `frontend/src/auth/*`, `frontend/src/api/client.ts`,
   `frontend/src/pages/Login.tsx`.
5. `docs/deployment.md` section 3 and `docs/implementation-notes.md`
   "Authentication and encrypted backups (v0.30.0)" for the rules the
   last auth release left behind.

## The plan in one list

What v0.33.0 builds, as the spec has it. Section numbers refer to
SPEC_0330.

1. **Providers** (5, 5a, 8): an `auth_providers` table in `cabinet_auth`
   (kind `oidc` or `oauth2_profile`; presets `google`, `microsoft`,
   `github`, `custom`; client secret Fernet-encrypted; at most 8 rows;
   several enabled at once, one button each). OpenID Connect by
   discovery, authorization code with PKCE `S256`, `state` and `nonce` in
   an encrypted one-use flow cookie (`__Host-cabinet_oidc`,
   `SameSite=Lax`, `Path=/api/auth/oidc/`, 10 minutes), ID token verified
   with PyJWT against the provider's JWKS (RS256, PS256, ES256, EdDSA;
   never `none` or HMAC; `iss`, `aud`/`azp`, `exp`/`iat`/`nbf` with 60 s
   leeway, `nonce`). GitHub through the `oauth2_profile` kind: no ID
   token, the identity read from `GET https://api.github.com/user` as the
   numeric `id`, the access token used once and dropped.
2. **Linking** (4, 5): from Settings only, on a fresh session, one
   identity per provider plus one for the trusted-header mode, in an
   `identities` table keyed `(issuer, subject)`; never an email; no
   first-login claim; unlinking and provider deletion end the sessions
   that came through them.
3. **Sessions** (4): the same `cabinet_auth.sessions`, `auth_method`
   `password`, `oidc`, or `trusted_header`; the known-device cookie
   issued as today.
4. **Confirming a fresh action** (5, Q1, Q11): the password always; a
   provider re-authentication (`prompt=login&max_age=0`, `auth_time`
   within 120 s) only where discovery advertises `auth_time` and
   `prompt=login`; GitHub and trusted-header sessions have only the
   password.
5. **The trusted-header mode** (7): a signed JWT the gateway sets
   (Authentik `X-authentik-jwt`, Pomerium, Cloudflare Access, Google IAP),
   passed through nginx only when `TRUSTED_ASSERTION_HEADER` names it (a
   generated identity include replaces the fixed blank list), verified
   against `TRUSTED_ASSERTION_JWKS_URL` (https) with the configured `iss`
   and `aud`; consulted only by `GET /api/auth/state`, `POST
   /api/auth/trusted`, and the link route, only to start a session; one
   click, never automatic; no shared-secret mode.
6. **No second factor inside Cabinet** (6, Q2): the provider's MFA is the
   second factor; the password path is one factor, hardened as in A1; a
   `password_sign_in_alerts` switch, auto-on with the first provider.
7. **The gate** (9): three new anonymous pairs (`GET /api/auth/oidc/start`,
   `GET /api/auth/oidc/callback`, `POST /api/auth/trusted`), the POST in
   `SMALL_BODY`; no other layer-1 change; every new route declared in the
   spec's table, which `test_gate.py` will read alongside SPEC_0300's.
8. **Recovery** (4 item 5): the browser never sets a new password without
   the current one, on any session; container commands `reset-password`
   (unchanged), `unlink-identity`, `disable-sso`, `status`; provider
   config is not in backups and the docs say so.
9. **Audit and alerts** (4 item 8): new events and webhook alerts; a
   provider rejecting Cabinet's credentials is an alert condition with
   recovery.
10. **Logs** (5): the callback's query string redacted in uvicorn's access
    log and nginx's, like share tokens.
11. **Frontend** (10): buttons above the always-visible password form,
    never an automatic redirect; Settings → Sign-in; the exposure
    guidance linked from Settings and one dismissible setup-checklist
    line; no new dependency.
12. **CI** (11): an in-process fake provider that can misbehave, a stdlib
    mock provider in the compose stack, a `sso` smoke phase, a Playwright
    spec.
13. **Docs** (12): a hard "private networks only, do not expose to the
    internet" advisory; deployment.md section 3 rewritten; the usual set.
14. **Stages** (13): six, each pushed with a report; a draft pull request;
    a fresh-context security review before merge.

## Settled (challenge only with a concrete attack)

One admin, one collection; login always on; the deny-by-default gate and
the `@permission` classes; `cabinet_auth` never in a backup and never
restored; nginx trusts no forwarded header and blanks identity headers
except the one assertion header a deployment names; the local password
stays and cannot be switched off; no second factor inside Cabinet (the
provider's MFA); GitHub in scope through the profile kind; signed
assertions only for the header mode; provider config in `cabinet_auth`;
no first-login claim; the browser never sets a new password without the
current one; private networks only, as a documented hard recommendation.

## The review the owner wants

### 1. Could someone take control of the admin account?

- **The callback** (spec section 5) is the first cross-site navigation
  that sets a session cookie in an app whose gate refuses cross-site
  requests. Walk the flow as an attacker: login CSRF (the attacker's code
  completed in the victim's browser), a stolen or replayed code, a
  callback with no flow cookie, a flow cookie from another origin, a
  `state` reused, a `nonce` reused, a code redeemed at the wrong provider
  with several configured (the mix-up rule), an `iss` claim missing or
  wrong, an ID token for the right `sub` from the wrong provider, an
  `aud` list with the client id among others, `azp` games, an `alg`
  downgrade, a JWKS the attacker influences, a `kid` that forces a
  refetch loop, clock skew abuse at the 60 s leeway, `next` as an open
  redirect (`safeNext`'s rules, the `//` and `/\` cases), and the
  `Sec-Fetch-Mode`/`Sec-Fetch-Dest` checks when a browser sends neither.
  Say which of these the spec already closes, with the sentence that
  closes it, and which it does not.
- **`SameSite=Lax` on the flow cookie.** It has to be Lax to survive the
  redirect back. Is `Path=/api/auth/oidc/` plus Fernet plus one-use enough,
  or can a Lax cookie be made to do something on another path?
- **The GitHub path** (5a) has no `nonce` and no ID token. Is `state` in
  the one-use cookie enough there? Is the numeric `id` as `sub` safe
  against account renames, deletions, and GitHub's own id reuse rules
  (cite GitHub's documentation)? Is `read:user` the least scope?
- **Linking** is admin plus fresh. Can a link be completed by a session
  other than the one that started it (the flow cookie carries the session
  id; is that binding sound)? Can an identity linked to a deleted
  provider survive into a re-added one with the same issuer?
- **The trusted-header mode** (7). The header reaches the backend only
  when named. Can a client reach nginx with that header set itself (when
  the gateway is not in front, or through a second listener)? The
  assertion must verify against the gateway's JWKS with `iss` and `aud`:
  what does an attacker who controls DNS for the JWKS host, or who can
  make the JWKS URL answer, achieve, and does the https requirement plus
  certificate verification in httpx close it? Replay of a captured
  assertion within its `exp`: is the spec's acceptance honest? Is there
  any path on which the assertion authenticates a route directly?
- **The one factor.** With no second factor inside Cabinet, the password
  path is what an attacker on the private network attacks. Is A1's
  throttle design (the known-device cookie, the per-account delay that
  never locks, the global limit) still the right shape when the password
  is meant to be rare? Would you change anything in it for this release?

### 2. Could the collection or a secret leak?

- The client secret: Fernet at rest, write-only, masked; the token
  endpoint call; `dry_run`; the audit `detail` for `sso_configured`.
  Where could it appear (a log, an exception, a 4xx body, the OpenAPI
  document, a metric, the CLI's stdout)?
- The callback's `code` and `state` in access logs (uvicorn and nginx):
  is the redaction rule complete (query on a `HEAD`, a trailing slash, a
  different case, the `error` redirect's own query)?
- The assertion header in the header mode: does it reach any log?
- Discovery and JWKS fetches: what does the provider learn about the
  deployment (the redirect URI reveals the origin; anything else)?

### 3. Could the owner be locked out?

Walk each: provider down; provider deleted and recreated (new `sub`);
domain renamed (`PUBLIC_ORIGINS` changed, redirect URI stale at the
provider); clock skew beyond 60 s; an expired Entra client secret; a
misconfigured trusted header causing a loop; `disable-sso` run by
mistake; a restore onto a fresh machine (provider config gone); every
session revoked by a provider deletion while the owner is signed in
through it; a password forgotten while SSO works (the container command,
by design). For each, is the fallback the spec names actually reachable,
and does anything in the design make the password path itself depend on
provider code?

### 4. Is the header mode contract deployable?

Read `proxy/cabinet-proxy.conf` and `40-cabinet-hosts.sh`. The plan moves
the identity-header blank list into a generated include and passes one
header through. Check nginx's actual semantics: `proxy_set_header`
inheritance per location, what happens with two directives for one
header name, whether `$http_x_authentik_jwt` is the right variable form,
and whether the header can arrive twice. Check Authentik's forward-auth
documentation for what `X-authentik-jwt` contains (an access token? for
which audience? signed by which key, and is the JWKS the provider's
`jwks/` endpoint?), since the spec's `iss`/`aud` requirements have to be
satisfiable there. Say what you verified and what you could not.

### 5. Does the plan fit the existing contract?

- Every new route needs a class in the spec's table, and `test_gate.py`
  parses SPEC_0300's appendix today. Is extending the parser to a second
  file sound, or should SPEC_0300's appendix gain the rows?
- The three new anonymous pairs: does anything in layer 1 (the `%`
  refusal, `SMALL_BODY`, the token rules, the maintenance rule, the share
  prefix) interact badly with them?
- `GET /api/auth/state` grows: it is anonymous. Is anything it will now
  reveal (provider names and presets, whether the header mode sees an
  assertion) a problem?
- The spec drops two `users` columns and adds tables in `a0002`: check
  `alembic_auth/versions/a0001_initial.py` and `tests/test_auth_schema.py`
  for rules the migration must keep (no cross-schema key, no `public`
  in the file).
- The frontend: the share routes render outside `AuthProvider`; the OIDC
  start and callback are backend redirects, not pages. Does anything
  need to render outside the boot check?

### 6. What is missing, and what is more than it needs to be

- Missing: anything a competent operator would expect from single
  sign-on in a self-hosted app that the spec leaves out, with the harm
  its absence causes (not a feature wish).
- More than needed: anything the spec builds that a single-admin app on
  a private network does not need, with what cutting it saves and what
  it would cost.
- The exposure advisory (section 12): is it stated so that a reader
  cannot mistake it for a suggestion, and does anything else in the docs
  or the app contradict it?

### 7. CI and proof

- The in-process fake provider and the stdlib mock: list the negative
  cases the plan names, and the ones it should add.
- What can only be proven against a real provider, and how should the
  release notes say so (as SPEC_0320's build log did for the Numista
  shape)?

## Output

Write `docs/specs/SPEC_0330-codex-review.md`, in plain words:

1. **Verdict**: safe to build as written, safe with changes, or not safe,
   in three sentences at most.
2. **Findings**, most severe first, as a table: id, severity (critical,
   high, medium, low), which harm above it enables, the attack or defect
   in one or two sentences, evidence (`file:line`, spec section, RFC or
   documentation section, or library behaviour and how you checked), the
   exact rule to put in the contract, and the test that proves it.
3. **Add list** and **cut list**: one line each, with what it protects or
   costs.
4. **Not verified**: what you could not check, and why.

Only a critical or high finding reopens an approved decision; medium and
low findings are folded into the build stages.
