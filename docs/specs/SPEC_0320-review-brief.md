# Security review brief: Cabinet v0.32.0, the share and showcase view (P9)

You are reviewing, in a fresh context, the branch `p9-share` of
C:\git\cabinet-numismatics against `main`, before it is merged and tagged as
v0.32.0. This is a **read-only review**: do not edit, commit, push, run
Docker, read `.env` files, or contact any live instance. Run only read-only
commands (`git diff`, `git log`, `grep`, reading files) and, if useful, the
backend test suite in `backend/` with `.venv\Scripts\python.exe -m pytest -q`
(SQLite, everything outbound mocked).

## What v0.32.0 adds

The first deliberately public surface of an app that has been closed behind
sign-in since v0.30.0: a read-only page behind an unguessable link, for the
collection, a set, or a checklist, switched on by the admin and off by
default. The contract is `docs/specs/SPEC_0320.md` (approved by the owner
on 23 September 2026); the rules the build follows are the "Share and
showcase view (v0.32.0)" section of `docs/implementation-notes.md`, and the
model it sits inside is `docs/security.md` ("Accounts and permissions",
the threat table) and `docs/specs/SPEC_0300.md` (the gate, the permission
classes, the appendix of every route's class, which `tests/test_gate.py`
enforces).

Read the diff: `git diff main...p9-share --stat`, then the code:
`backend/app/auth/gate.py`, `permissions.py`, `throttle.py`,
`backend/app/services/share.py`, `routers/share.py`, `routers/share_links.py`,
`backend/app/main.py` (the log filter), `services/currency.py`
(`fetch=False`), `alembic/versions/0022_share_links.py`, `tests/test_share.py`,
`tests/test_gate.py`; `proxy/nginx.conf` and `proxy/*.conf`;
`frontend/src/App.tsx`, `frontend/src/pages/share/*`, `pages/settings/Sharing.tsx`,
`frontend/src/api/calls.ts`; `scripts/ci/stack-smoke.sh` (the `share` phase);
`frontend/e2e/share.spec.ts`.

## What to attack

Try to falsify each of these claims; each is a rule the build says it keeps.

1. **Nothing leaks past the allowlist.** `share.item_view` is the only way
   an item reaches a share; its keys are pinned by a test. Find any path
   (the manifest, the items page, one item, the checklist slots, the photo
   route, an error body, a header, a log line, a metric, the audit log)
   that reveals a cost, price, gain, acquisition or sale detail, storage
   location, document, serial number, custom field, population, wish-list
   field, timestamp, edit history, or anything about pieces outside the
   share (a set's non-owned or trashed pieces, a checklist's unfilled slots,
   a photo of an item not in the share, a photo's original path).
2. **The gate.** A `GET`/`HEAD` under `/api/share/` passes with no
   credential lookup. Can that prefix rule be abused to reach anything else
   (path tricks the `%` refusal doesn't catch, `HEAD` on an admin route,
   a share route with a method the gate treats differently, `/api/share`
   without the trailing slash, case, dot segments that nginx or Starlette
   normalise differently)? Does a session cookie on a share request ever
   touch `last_seen_at` or the confirm window? Can a `share`-class route
   be reached with sharing off in any way that differs from 404?
3. **The single 404.** Is there any observable difference (status, body,
   headers, timing you can reason about, the throttle's behaviour) between
   sharing off, an unknown token, a revoked token, a malformed token, and a
   target that was deleted?
4. **Tokens.** 32 random bytes, `secrets.token_urlsafe`, stored as SHA-256
   only, shown once. Does the token ever reach a log (uvicorn's access log
   is filtered, nginx's is rewritten by a `map`), an audit row, an alert, an
   exception, `argv`, a `Referer` (the page sets `no-referrer`), a URL
   query, or the response of any admin route? Is the redaction complete
   (query strings, `HEAD`, the `/s/` page, error paths)?
5. **Throttle.** A failed lookup counts per address (`X-Real-IP`, which
   nginx overwrites). Can a scanner enumerate cheaply anyway? Can a
   legitimate viewer be locked out by someone else on the same address, or
   by the viewer's own page (a resolved share's 404s don't count; is that
   true on every route)? Is the address ever taken from a header the client
   controls?
6. **No network on a public route.** Values convert at cached rates only
   (`Converter(fetch=False)`); photos are local files. Find any code path a
   share route can reach that fetches (spot prices, exchange rates, Numista,
   PCGS, alerts).
7. **Photos.** The share photo route streams `thumb_key`/`file_key` from the
   photo directory after checking the photo belongs to a shared item. Path
   traversal? A key that points outside the directory? A photo whose item
   moved out of the share (sold, trashed, removed from the set) after the
   page loaded? The headers (`nosniff`, a `default-src 'none'; sandbox`
   CSP, `noindex`)? nginx's `/photos/` is untouched: confirm a share viewer
   can't reach it.
8. **The admin side.** Create, rename, regenerate, revoke: `admin` class
   and `fresh` where the spec says; the appendix rows exist and the class
   counts in `test_gate.py` are right; a write token can't make a link; the
   20-link cap; a set's or checklist's deletion cascades; the URL is built
   from `PUBLIC_ORIGINS[0]` (is that the right origin for an instance that
   lists several?).
9. **The switch.** `share_enabled` is one settings key, admin and fresh to
   change, audited and alerted. Can a restore, a backup from another
   instance, or `restore.sh` flip it on unnoticed? (Settings are collection
   data and travel in archives; the roadmap accepted that, but say whether
   an archive from a stack with sharing on would switch it on here and what
   the owner would see.)
10. **The page.** `/s/*` renders before the auth `Gate` and never calls
    `/api/auth/*`; the calls use `raw`. Does any share page component import
    something that fires the 401 redirect or reads the signed-in state? Does
    the page link into the app anywhere? Is the CSP (now an include shared
    with `location /`) the same as the app's? Does `robots.txt` and
    `X-Robots-Tag` cover the page and the API?
11. **Deployment.** A forward-auth proxy in front blocks share viewers
    unless it exempts `/s/`, `/api/share/`, and `/robots.txt`; the docs say
    so with a Traefik example. Is the exemption safe as written (does it
    open more than those paths), and is there anything else an operator
    must do?

## Report

`docs/specs/SPEC_0320-review-opus.md` is where the owner will keep your
report; write it to that path only if you are told you may write, otherwise
return it as your answer. For each finding: severity (critical, high,
medium, low, info), the claim it falsifies, file and line, how to reproduce
or the reasoning, and a recommended fix. Then a verdict: is this safe to
release as the first public page of an otherwise closed app, and what, if
anything, must change first. Be adversarial: the previous reviews of this
project found real defects; assume this one has some too.
