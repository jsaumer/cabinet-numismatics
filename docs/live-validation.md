# Live validation of v0.33.0: single sign-on and a security scan

v0.33.0 shipped single sign-on with nothing checked against a real
identity provider or gateway: pytest's fake and CI's mock stood in for all
of them (the list of what is owed is in
[SPEC_0330](specs/SPEC_0330.md#owed-to-the-owners-live-check)). This is the
plan for closing that on the owner's own Swarm once the release is live,
plus a vulnerability scan of the running instance with the homelab's
OpenVAS (Greenbone) server. It was run on 24 September 2026 (see "The
first run" below); any operator can run it against their own instance.

## Rules

- **Nothing here is destructive to the live instance.** Every step below
  adds a provider, links an identity, signs in and out, or reads. The
  steps that change the account itself (`reset-password`,
  `sign-out-everywhere`) and the outage drills (a provider or gateway
  stopped) run on the local compose stack, not the Swarm; the plan says
  which is which.
- **Take a backup first** (Settings → Backups → Back up now) and confirm
  `GET /api/health` reports the version you deployed with `schema` and
  `auth_schema` both `ok` before anything else.
- **No secret leaves the console it was made in.** A client secret goes
  from the provider's console into Settings → Sign-in and nowhere else;
  none is pasted into a chat, a commit, an issue, or this document's
  results. `.env` is never read.
- **Results stay out of the repository except as a summary.** The
  summary (pass or fail per row, and the assertion's `alg`, `iss` form,
  `aud` form, and lifetime) goes into SPEC_0330's build log under "Owed to
  the owner's live check" and ticks the roadmap; raw scan reports, screen
  captures, and addresses and port numbers stay in
  `docs/live-validation-results/`, which is gitignored.
- **Expect alerts.** Failed sign-ins, rejected assertions, new browsers,
  new identities, and the scan's probing all fire the webhook and fill the
  audit log by design. Leave the webhook on and read the alerts as part of
  the results: a step that should alert and didn't is a failure too.

## Part A: the upgrade itself

Run in order after bumping the Swarm's image tags to `0.33.0`.

| # | Check | Expected |
|---|---|---|
| A1 | `docker service logs` of the backend during the first start | Both migration chains apply (`a0002` is the new one), no `ConfigError`, no critical line from the backup self-test |
| A2 | `GET /api/health` (signed in) | `version:` the version you deployed, `schema.status: ok`, `auth_schema.status: ok` |
| A3 | Sign in with the password | Works; the sign-in page shows the password form and no provider button yet |
| A4 | `python -m app.cli status` in the backend container | Prints the admin, no providers, no identities, the trusted-header mode off (the variables aren't set yet) |
| A5 | Settings → Sign-in | Opens, shows the exact redirect URI per `PUBLIC_ORIGINS` entry, the Add form, and no providers |
| A6 | The existing forward-auth gateway (Traefik + Authentik) still in front | A photo loads on an item page; the password dialog appears and succeeds on a settings change; the Homepage tile still reads its `metrics` token on the internal name; a share link still opens without signing in (the `/s/`, `/api/share/`, `/robots.txt` exemption held) |
| A7 | One of the alert events from the release (a new browser on the first sign-in from a fresh profile) | Arrives at the webhook |

## Part B: the sign-in providers

### The script every provider runs through

Each provider gets the same fourteen steps; the per-provider sections
below only add what is specific. Record pass or fail per step. B1 to B4
are the acceptance checklist in
[deployment.md](deployment.md#the-operator-acceptance-checklist) made
concrete.

| # | Step | Expected |
|---|---|---|
| B1 | Register the app at the provider with the redirect URI exactly as Settings → Sign-in shows it; multi-factor on for the account you'll link | Provider console accepts it; no wildcard URL |
| B2 | Settings → Sign-in → Add: preset, issuer (Custom only), client id, secret; press **Test** before saving | Discovery succeeds; the answer says whether "Confirm at your sign-in provider" will be offered |
| B3 | Save, then enable the provider | `provider_created` and `provider_enabled` audit rows; the first time any provider is ever enabled, `password_sign_in_alerts` switches on by itself (Settings shows it) |
| B4 | Sign out, open the sign-in page | One button for this provider, the password form still present |
| B5 | Press the button **before linking** | The provider authenticates you and sends you back to `/login?error=` with "This account is not linked to Cabinet"; an `sso_sign_in_rejected` audit row with `reason: unlinked`; no session; no new account |
| B6 | Sign in with the password, Settings → Sign-in → **Link** next to the provider | Round trip to the provider and back to `/settings/signin?linked=`; "Linked" shown; an `identity_linked` audit row and alert |
| B7 | Sign out, press the button | Signed in; `sign_in` audit row with `method: oidc` (GitHub too: the row records the flow, not the preset kind); Settings → Account shows the session as a provider session; `GET /api/auth/me` reports `auth_method` and `provider_id` |
| B8 | From a fresh browser profile, press the button | Signed in, plus a new-browser alert (no device cookie is issued for an external sign-in, so only the browser cookie decides whether a later sign-in from that profile alerts again) |
| B9 | Do a fresh action (download a backup): the confirm dialog | Offers "Confirm at your sign-in provider" only where B2 said it would; choosing it re-prompts at the provider (a real password or second-factor prompt, not a silent bounce), returns to the page, and the download proceeds; the password option works too |
| B10 | Sign out | With `logout_at_provider` on, the browser is sent to the provider's end-session page and back to `/login`; otherwise straight to `/login`. Provider off or GitHub: the plain path |
| B11 | Disable the provider in Settings while signed in through it | The session ends at once (the next request is 401, you land on `/login`); the button is gone; the password works |
| B12 | Re-enable it; sign in again through it; then **Unlink** in Settings | The session ends at once; `identity_unlinked` audit row; the button remains but leads to B5's refusal |
| B13 | Link again with a **different** account at the provider than the one B6 used, if you have one | Refused as unlinked on sign-in; a second identity at the same provider for the admin is refused as `already_linked` when linking |
| B14 | Wrong-credential check: change the client secret in Settings to a wrong value, press the button | `/login?error=` with a provider error; the `sso_provider_<id>` alert condition goes failing (Settings → Alerts lists it); fix the secret, sign in once, the condition recovers |

### Authentik (OpenID Connect, Custom preset)

The first provider to test, since the homelab already runs it and the
recovery commands are one `docker exec` away.

- Provider: OAuth2/OpenID, Confidential, an **asymmetric signing key
  selected** (unset means HS256 by the client secret, which Cabinet
  refuses; the symptom would be B7 failing with an algorithm error while
  B2's Test passes, since discovery says nothing about which key is
  used). Subject mode at its default (hashed user id).
- Issuer: the provider's OpenID configuration issuer, typically
  `https://<authentik>/application/o/<slug>/`, trailing slash included. If
  B2's Test fails, try it without the slash before anything else; record
  which form worked.
- If Authentik sits behind a private certificate authority, `SSO_CA_FILE`
  on the backend, and B2's Test is the check that it is read.
- Expected at B2: confirm offered (Authentik supports `prompt=login` and
  reports `auth_time`). **B9 is the owed check**: confirm that the
  provider really re-prompts rather than silently reusing the Authentik
  session. If it bounces silently and Cabinet refuses the confirm
  (`auth_time` older than 120 s), that is Cabinet doing its job and
  Authentik not honouring `prompt=login`; record it, and confirm with the
  password.
- Record for SPEC_0330's build log: the issuer form that worked, the
  signing algorithm shown on the provider's key page, and whether B9
  re-prompted.

### Google

- Console: a project, an OAuth consent screen (External, **Testing**
  status with your account as a test user is enough for one admin and
  avoids verification), an OAuth client of type Web application, the
  redirect URI from Settings. The redirect is a browser redirect, so
  Google never needs to reach Cabinet; Cabinet needs outbound HTTPS to
  `accounts.google.com` and `www.googleapis.com` for discovery and keys.
- Cabinet preset: **Google**. No issuer to type; both of Google's
  documented issuer forms (`https://accounts.google.com` and
  `accounts.google.com`) are accepted since stage 7.
- Expected at B2: confirm **not** offered (Google supports neither
  `prompt=login` nor `auth_time` the way Cabinet requires); B9 should show
  only the password option. If it offers the provider, that is a finding.
- B10: Google publishes no `end_session_endpoint`, so sign-out is the plain
  path.
- 2-Step Verification on the Google account is B1's multi-factor.

### GitHub

- Settings → Developer settings → OAuth Apps → New OAuth App; the
  callback URL exactly as shown; **no wildcard**. A GitHub App also works,
  but an OAuth App is the simpler fit.
- Cabinet preset: **GitHub** (the `oauth2_profile` kind: no ID token, the
  identity is the numeric account `id` from the profile call).
- **Owed checks** (record each): the code exchange succeeds although
  Cabinet always sends a PKCE `code_verifier` (GitHub's OAuth Apps predate
  PKCE); the token answer is JSON (Cabinet asks with `Accept:
  application/json` and refuses form-encoded); the profile's `id` is read
  as an integer.
- Expected: B2's Test reports confirm never available (GitHub never
  confirms, by rule); B9 shows only the password; B10 plain; the
  Settings page shows your GitHub `login` as the display name.
- B14 variant: GitHub's error code for a wrong secret is
  `incorrect_client_credentials`; the `sso_provider_<id>` condition should
  still go failing.

### Optional: the other presets, if you can reach an instance

Run the same fourteen steps and record the same things. What is worth
watching per platform (from deployment.md's setup notes):

- **Keycloak** (Custom): issuer `https://<host>/realms/<realm>`; confirm
  expected offered; B9 is the owed `prompt=login` and `auth_time` check,
  as for Authentik.
- **Authelia** (Custom): confirm depends on the version's `auth_time`
  support; take B2's answer as truth and check B9 agrees.
- **Microsoft Entra ID** (Microsoft preset, a tenant id): the owed check
  is that the tenant-pinned issuer works and that the shared `common`
  endpoint fails discovery as the quirk table says. Confirm is never
  offered for this preset (SR-04); B9 must show only the password.
- **Any other OpenID Connect provider** (Custom): B2's Test is the whole
  compatibility check; the known refusals (Apple's `form_post`, HS256-only
  providers) are listed in deployment.md.

### The trusted-header mode (Authentik proxy outpost)

Only after the Authentik provider above passes, and only if you want the
"Continue with the proxy's sign-in" button; it is an addition, not a
replacement. Set the four `TRUSTED_ASSERTION_*` variables on both the
backend and the proxy per
[deployment.md](deployment.md#the-trusted-header-mode) and redeploy.

| # | Step | Expected |
|---|---|---|
| T1 | Backend and proxy start | No `ConfigError`; the proxy's log says which header it passes and that the rest are blanked |
| T2 | Sign-in page **through the gateway** | The "Continue with the proxy's sign-in" button is shown |
| T3 | Sign-in page on the LAN, **around the gateway** (the proxy's own port, if reachable at all) | No proxy button, since the request carried no assertion |
| T4 | Press the button before linking | Refused as unlinked, `sso_sign_in_rejected` with `kind: trusted_header`; no session |
| T5 | Password sign-in, Settings → Sign-in → "Link the identity this proxy asserts" | Enabled only through the gateway; links; `identity_linked` |
| T6 | Sign out, press the button | Signed in, `method: trusted_header`; no device cookie set |
| T7 | Switch the mode off in Settings → Sign-in while signed in through it | The session ends at once (SR-01); the button is gone; the password works; switch it back on |
| T8 | `disable-sso` in the container, then re-enable from Settings | Both directions work (the acceptance checklist's step) |
| T9 | **Forged header, from outside the gateway**: from a container on the Swarm that is not the outpost, `curl -X POST -H "<header>: not.a.jwt" http://<proxy>:<port>/api/auth/trusted` | Preferably the connection fails (the port isn't reachable off the gateway's network). If it is reachable: a 4xx, an `sso_sign_in_rejected` row with `reason: assertion`, and never a session |
| T10 | **Forged header, through the gateway**: the same request through the public hostname with a garbage header, signed in at Authentik | The audit row, if any, must show the outpost's real assertion was what arrived (a success on the button, or `reason: unlinked`), never `reason: assertion` from your garbage value: that proves the outpost overwrites a client-sent header rather than appending to it |
| T11 | Record the live assertion's values | `alg`, `iss`, `aud`, `exp - iat`, the issuer mode and subject mode configured; a JWT decoder run locally on a copied token is fine, the token itself is never saved |
| T12 | Twenty wrong assertions from one address in a row, then one right one | The wrong ones are throttled (429 after the free allowance), the right one is **not** (SR-07: verify first, throttle only failures), and a `rejected_sso` burst alert arrives |

T9 to T11 are the owed items from SPEC_0330 section 18. T10 is the one
that matters most: if a forged header reaches the backend through the
gateway, the mode is unsafe on that gateway and should be switched off
until the outpost's header handling is understood.

### Recovery drills (local compose stack, not the Swarm)

Bring up the local stack with the CI mock provider (`COMPOSE_FILE`
including `docker-compose.ci.yml`; `bash scripts/ci/stack-smoke.sh sso`
does the setup) and, with a provider linked, run each command once so its
behaviour is known before it is needed on the Swarm:

- `status`: providers, identities, methods on or off.
- `unlink-identity <id>`: the provider session ends at once.
- `disable-sso`: the sign-in page loses every button; the password works;
  Settings switches the mode back on and the linked identities are still
  there.
- `reset-password`: every session and token ends; identities survive
  (SR-05: check them after a suspected compromise).
- `sign-out-everywhere`: every session ends, known devices and browsers
  are dropped, so the next sign-in alerts as a new browser.
- Provider outage: `docker compose stop mock_idp`, then the button gives a
  provider error within about ten seconds (the outbound timeout), the
  password still works, and `GET /api/auth/me` still answers (a failed
  discovery is remembered for a minute, so the page doesn't hang).

## Part C: the security scan with OpenVAS

The scan is the outside view of the running instance. It is
non-destructive as configured below, but it is noisy: it will trip the
sign-in throttles for the scanner's address, fill the audit log's capped
tables, and fire burst alerts. Run it when you don't need to sign in from
the scanner's address for an hour.

### Targets

Scan each of these as a separate target, since they are different attack
surfaces:

| Target | What it represents | How to address it |
|---|---|---|
| C-1 The Traefik entry point | What the LAN or VPN sees: TLS, the forward-auth gateway, then Cabinet | The public hostname, ports 443 and 80 |
| C-2 Cabinet's own proxy port | Cabinet with nothing in front, the way a deployment without a gateway would run it | The Swarm node's address and `CABINET_PORT`. If the port isn't published on the node at all, that is itself the desired result: record "unreachable" and skip |
| C-3 The Swarm node's other ports | Anything else the host offers on the same address (the Docker API, SSH, Postgres if it were ever published) | The node's address, full port range |

Never point the scanner at the identity provider or at the
internet-facing side of anything; Authentik and the provider consoles are
out of scope.

### Scan configuration

- **Scan config: "Full and fast."** Not "Full and very deep ultimate": the
  deep configs include denial-of-service and brute-force families, which
  the rules forbid against the live instance. "Full and fast" keeps
  Greenbone's safe-checks behaviour.
- **Port list**: "All IANA assigned TCP" for C-1 and C-2; "All TCP and
  Nmap top 100 UDP" for C-3.
- **Alive test**: "Consider Alive" for C-1 and C-2, since a target behind
  Traefik may not answer ICMP.
- **No credentials.** OpenVAS's web checks can't carry a Cabinet session
  or Bearer token in a useful way, so the scan covers the anonymous
  surface only: exactly what an attacker on the network gets. That is the
  right scope; the authenticated surface is what `tests/test_gate.py` and
  the `outside-in` smoke phase cover on the local stack.
- **One scanner address**, fixed, so the throttles and the audit rows
  attribute everything to it and it can be told apart from real use.

### What a clean result looks like

Expect these, and don't file them as findings:

- **C-1**: a TLS report on Traefik's certificate and cipher suites (that
  is Traefik's configuration, not Cabinet's); a "web application" section
  full of `401` and `404` answers from the gateway or the gate;
  `robots.txt` disallowing `/api/`; the security headers present on every
  page (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, a Content-Security-Policy on the app);
  `Server: nginx` with no version (`server_tokens off`).
- **C-2**: everything above minus TLS. "Missing HSTS" and "cookie without
  Secure" style findings on a plain-http port are expected here **only if
  the port is reachable at all**: Cabinet's own nginx terminates no TLS by
  design. A reachable C-2 is a deployment question (why is the port
  published on the node?), not a Cabinet defect.
- Requests with an unknown `Host` header get no response at all (nginx's
  `444`), which a scanner reports as a connection reset; expected.
- The sign-in, setup, and trusted endpoints answer `413` past 8 KiB and
  `429` once the scanner's address is throttled; also expected.

### What counts as a finding

- Any **High or Critical** result against C-1 or C-2 that names a Cabinet
  component (the nginx configuration, the frontend, an API answer), once
  you've confirmed it isn't a version-banner guess (OpenVAS infers
  versions; with `server_tokens off` it often can't and says so).
- Any **Medium** result that is about behaviour rather than a header
  policy you already understand: an information leak in an error body, a
  path that answers anonymously outside the gate's allowed routes and the
  share prefix, a photo served without the `auth_request` check.
- **Any open port on the node other than 80, 443, SSH, and the ones you
  put there** (C-3). Postgres or the Docker API reachable from the LAN
  would be the most serious result the whole exercise could produce, and
  it is a Swarm configuration matter, not Cabinet's.
- Anything OpenVAS flags in the nginx or Alpine layer that Trivy in
  `security.yml` didn't: compare against the latest CI run.

Triage each real finding into: **Cabinet defect** (a fix and a test, in a
patch release), **deployment** (a change to the stack file or the Swarm,
recorded in deployment.md if it is general advice), or **accepted** (with
the reason, in `docs/live-validation-results/`). A Cabinet defect that is
a security issue follows [SECURITY.md](../SECURITY.md); since the
repository is public, the fix lands before the finding is described in a
commit message.

### Complementary checks worth a few minutes

Not OpenVAS, but cheap and answering questions it can't:

- `testssl.sh` against C-1 for the TLS grade (Traefik's, again, but
  Cabinet's cookies depend on it).
- The Mozilla Observatory header check against C-1 for the CSP and the
  rest of the header set.
- `bash scripts/ci/stack-smoke.sh outside-in` against the live instance
  is **not** to be run: it mints tokens and creates items. Its
  local-stack run in CI is the authenticated coverage.

## The first run (24 September 2026)

Parts A and B ran the day of the release, against the owner's Swarm, in
the order above. Part A passed (A6 not applicable: no gateway in front). Authentik, Google, and GitHub
passed every step; B13 and the trusted-header mode were skipped (one user
per provider, no forward-auth gateway). Three Cabinet defects surfaced
and shipped as 0.33.2, 0.33.3, and 0.33.4 the same day; the details are in
[SPEC_0330](specs/SPEC_0330.md#owed-to-the-owners-live-check). Two things
the plan didn't say that the run taught:

- **Keep the reading session on the password.** A provider sign-in in the
  same browser replaces the session, and a disable or unlink then ends it
  mid-test; use a private window for every provider step.
- **Unlink and Remove use the browser's own confirm dialog**, which an
  embedded or automated browser may not show; do those two from an
  ordinary browser.

Part C ran the same evening from the homelab's Greenbone (26.7.0).
C-2 did not exist (the proxy port is published to nobody; only Traefik
reaches it), which is the result the plan hoped for. C-1
(`cabinet.saumer.cloud`, All IANA assigned TCP, Consider Alive, Full and
fast, 1 h 21 min) and C-3 (the four Swarm nodes, All TCP and Nmap top 100
UDP, Full and fast, about 1 h 30 min) both came back with **no Critical,
High, or Medium at Greenbone's default QoD and no finding against any
Cabinet component**: the application surface produced Log entries only
(the header set, the certificate, the gate's 401 and 429 answers). Three
web NVTs (the directory traversal, Log4Shell, and Shellshock active checks)
timed out against the throttle rather than finishing; expected, and worth
knowing they neither passed nor failed. Everything with a severity was the
nodes' own SSH (weak MAC algorithms on 22 and 222; Terrapin and a
username-enumeration CVE inferred below QoD 70) plus the timestamp noise
every Linux host shows. The open-port inventory held no surprise: SSH,
Swarm's own ports, Traefik's 80, 443, and 8080 on one node, rpcbind, and
two published services; nothing of the database or the Docker API. The
deployment items that fell out (an sshd `MACs` line, whether Traefik's
8080 and rpcbind's 111 need to listen at all) are the operator's, not
Cabinet's, and stay in the local results folder.

What the run taught about the scan itself:

- **Export with the filter cleared.** Greenbone exports the report through
  its current filter, so the default export holds only rows at QoD 70 and
  above with a severity; set the filter to `levels=hmlg min_qod=0` before
  exporting if the local copy should hold the Log rows and the low-QoD
  inferences.
- **The hostname target scans a node.** `cabinet.saumer.cloud` resolves to
  one Swarm node, so C-1 was that node's whole port range through the
  hostname; the Cabinet-specific part of it is only what answered on 80
  and 443. That is fine, and it is why C-3's per-node results duplicate
  C-1's SSH rows.

## Recording the outcome

1. SPEC_0330's build log, "Owed to the owner's live check": one line per
   owed item, closed or still open, with the T11 values.
2. `docs/roadmap.md`, "The road to v1.0.0": tick "v0.33.0 validated live"
   when Parts A and B (Authentik, Google, GitHub) pass and Part C has no
   open Cabinet defect.
3. `docs/deployment.md`: the "Verified in this build" line under each
   provider you tested changes from "against the mock only" to the date
   and what was checked; any console step that turned out different from
   the described intent is corrected.
4. Anything specific to the homelab (addresses, port numbers, the raw
   scan reports) stays in `docs/live-validation-results/`, gitignored.
