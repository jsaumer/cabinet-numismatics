<!-- Fresh-context, read-only review by Claude Opus 5.5 of branch p9-share at 5877fa5, 23 September 2026, against SPEC_0320-review-brief.md. Kept verbatim; what was done about each finding is in section 5 of SPEC_0320. -->

# Security review of SPEC_0320 (v0.32.0, the share view), branch `p9-share` at 5877fa5

I reviewed it read-only against `main`: the diff (64 files), the code, the nginx config, the frontend and the docs. `tests/test_share.py` and `tests/test_gate.py` pass (84 passed). I checked one claim with a script in the scratchpad that imports `app.auth.throttle` and nothing else; no repository file was changed.

## Findings

### 1. HIGH: the full-size photo route serves the original upload bytes, EXIF and GPS included
- **Claim falsified:** 1 and 7, "never storage location, never timestamps".
- **Where:** `backend/app/services/photos.py:67` (`path.write_bytes(data)` stores the upload as-is) and `backend/app/routers/share.py:145-149` (`variant == "full"` streams `photo.file_key`). `frontend/src/pages/share/SharePiece.tsx:54` asks for `full` in the lightbox, and `show_photos` is on by default.
- **Reasoning:** `open_validated` fixes orientation only on the in-memory image used for the thumbnail. The original file keeps every EXIF, XMP and PNG text block it arrived with. That includes GPS coordinates (for a phone or camera photo taken at home, that is where the collection lives), `DateTimeOriginal`, and the camera's make, model, serial and owner name. Before v0.32.0 only the signed-in owner could fetch originals. Now anyone holding a link can. Thumbnails are clean: Pillow's `save` writes no EXIF unless it is passed one.
- **Reproduce:** upload a JPEG carrying GPS EXIF, share it, then `GET /api/share/{token}/photos/{id}/full` and read the EXIF.
- **Fix:** never serve untouched originals on a public route. Either:
  - at upload, keep a sanitised "display" copy (re-encoded, ICC profile kept, all EXIF, XMP and text chunks dropped) and serve that as `full`; or
  - strip metadata from every original at upload, which also covers backups.

  Add a test: a JPEG with a GPS IFD comes back from the share route with no EXIF.

### 2. MEDIUM: one anonymous client can hold every share link at 429, in the recommended deployment
- **Claim falsified:** 5, "can a legitimate viewer be locked out by someone else on the same address".
- **Where:** `backend/app/routers/share.py:45-53`. `throttle.wait` is checked before `resolve`, and a valid token never lifts it. `tests/test_share.py:265` asserts exactly this (a valid token from the throttled address gets 429).
- **Reasoning:** nginx writes `X-Real-IP $remote_addr` and trusts no forwarded header. Behind any authenticating reverse proxy (the documented Traefik + Authentik setup) or Swarm ingress mode, every viewer arrives with the proxy's address, so there is one `share:` bucket for the whole internet.
  - 20 bad lookups start the curve. After that, one bad lookup each time the wait expires (at most 60 s) keeps it closed.
  - Requests refused during the wait don't count, and a success never resets the bucket. A viewer's page (manifest, items, up to 100 thumbnails, each checked separately) therefore gets 429s indefinitely for about one request a minute.
  - Ordinary traffic does it too: people reopening revoked or regenerated links.
- **Fix:** resolve first. A valid link is never throttled. Apply the wait only to a lookup that failed: answer 429 instead of 404 while the bucket is over. This gives a scanner no new signal and makes the viewer lock-out impossible. Update the test.

### 3. MEDIUM: failed share lookups evict the sign-in throttle, and this is reachable with sharing off (the default)
- **Claim falsified:** 5 and 2; it also reopens the v0.30.0 rule that password guessing must never fall back to only the global limit.
- **Where:** `backend/app/routers/share.py:59` calls `throttle.fail("share", address)`. Those entries go into the one shared map, which holds at most 10,000 entries and drops the oldest first (`backend/app/auth/throttle.py:33`, `143-144`). The sign-in buckets `user:<name>` and `addr:<ip>` live in the same map (`backend/app/auth/accounts.py:179`).
- **Reasoning:** share failures cost nothing:
  - no Argon2 check;
  - no global cap;
  - no credential needed;
  - counted even while `share_enabled` is false.

  An attacker with 10,000 source addresses (one IPv6 /64, or a small botnet) flushes the admin's `user:` bucket and their own `addr:` buckets between guesses. Password guessing goes from about one per 60 s to the global 60 a minute, roughly 86,000 a day, the figure the v0.30.0 review called unacceptable.
- **Verified:** after 30 failures, `wait("user","admin")` is 60. After 10,000 `fail("share", <distinct v6>)` calls it is 0.0.
- **Fix:** give share failures their own bounded map, or at least never let `share:` entries push out `user:`, `addr:` or `setup:`. Key IPv6 addresses by /64. Add a global cap on share failures. Cache `share_enabled` in memory so that with sharing off a request is answered before any DB or throttle work.

### 4. MEDIUM: a restore silently brings back revoked or regenerated links and can switch sharing on
- **Claim falsified:** 9 (asked directly by the brief).
- **Where:** `backend/app/services/restore.py:879` (`_after_database` does nothing about sharing). `backend/app/routers/settings.py:285-294` (the `sharing_switched` audit and alert fire only on `PUT /api/settings`).
- **Reasoning:** `share_links` and `share_enabled` are in `public`, so every archive carries them.
  - A link leaks, and the owner revokes or regenerates it.
  - Later the owner restores last night's archive, or undoes a restore from the `-prerestore` safety archive, which by definition holds the older state.
  - The leaked token hash is back and works. A regenerated link returns to its old leaked token, and the new one dies.
  - An archive from a stack with sharing on switches sharing on here.

  None of this is audited or alerted. The owner would only find out by opening Settings → Sharing.
- **Fix:** before the database step, take a snapshot of `share_links` and `share_enabled`, and put them back after (treat links as access grants, like `cabinet_auth`). At minimum:
  - force `share_enabled` back to its pre-restore value;
  - audit and alert when the archive's value or link set differs;
  - name the difference in the restore outcome.

  `scripts/restore.sh` needs the same, or a documented warning.

### 5. LOW: the photo response's `Last-Modified` and `ETag` reveal when each photo was uploaded
- **Claim falsified:** 1, "never timestamps".
- **Where:** `backend/app/routers/share.py:149`. Starlette's `FileResponse` sets `last-modified` from the file's mtime and an `etag` built from mtime and size.
- **Reasoning:** the upload time is usually close to the acquisition time.
- **Fix:** send the photo without `last-modified` and `etag` (delete them after building the response, or stream it yourself). Test that neither header is present.

### 6. LOW: the token still reaches nginx logs on paths the redaction misses
- **Claim falsified:** 4.
- **Where:** `proxy/nginx.conf:7-11` and `21-26`, plus the image's default `error_log`.
  - **Error log:** upstream errors log the full `request: "GET /api/share/<token> HTTP/1.1"`. The backend restarts and migrates on every deploy, so any viewer who hits a 502 in that window leaves a token in the proxy's log, which may be shipped to a log aggregator.
  - **Default server:** the 444 server has no `access_log` of its own, so it uses the image's `main` format with the raw `$request`. That only happens when a request arrives under an unrecognised Host.
  - **Map regex:** it is anchored at `^/api/share/` and `^/s/`, so `//api/share/<token>` is logged in clear. The backend's filter, which is not anchored, does catch it.
- **Fix:**
  - Loosen the anchors to `^/+api/share/` and `^/+s/`.
  - Set `access_log off` (or the `cabinet` format) in the default server.
  - Document that the nginx error log can carry a token, or raise its level to `crit`.

### 7. LOW: `robots.txt` blocking `/s/` stops crawlers from seeing `noindex`
- **Claim falsified:** 10.
- **Where:** `proxy/nginx.conf:193`.
- **Reasoning:** a crawler that obeys `Disallow: /s/` never fetches the page, so it never sees `X-Robots-Tag` or the `<meta name="robots">`. Google documents that a blocked URL linked from elsewhere can still be listed as a bare URL. A share URL posted on a forum can therefore land in search results, and the URL is the token.
- **Fix:** drop `Disallow: /s/` and let the `noindex` header do its job. Keeping `/api/` blocked is fine.

### 8. LOW: the Traefik example in the docs doesn't work (it fails closed)
- **Claim falsified:** 11.
- **Where:** `docs/deployment.md:286` (`priority: 10`).
- **Reasoning:** Traefik's default priority is the length of the rule. The catch-all rule `Host(`cabinet.example.com`)` scores 27, which beats an explicit 10, so the Authentik router wins and share links land on the gateway's sign-in page. The text says the share router should have "a higher priority than the general rule". The longer share rule already wins without any priority set.
- **Fix:** remove `priority`, or use something like 1000.
- **Also:** the exemption makes these paths skip the second door. Tell operators to check that their gateway normalises `..` and encoded dots before matching (Traefik's `sanitizePath`). Otherwise `/s/../api/auth/login` bypasses the forward-auth for any path. Cabinet's own gate still refuses it (checked below).

### 9. LOW: `PATCH /api/share-links/{id}` widens a live link without the password, audit, or alert
- **Claim falsified:** 8 (it matches the spec, but the spec misses this case).
- **Where:** `backend/app/routers/share_links.py:297-312`.
- **Reasoning:** someone with a stolen session but not the password can't make, regenerate or revoke a link. They can, however, silently turn on `show_notes` and `show_values` for every existing recipient. Notes are where the owner types what doesn't fit elsewhere, such as prices paid.
- **Fix:** audit and alert whenever an option goes from off to on, and ask for the password again for turning on notes or values.

### 10. LOW: `cert_number` sits behind `show_grades`, which is on by default
- **Claim falsified:** 1, in effect ("never an acquisition detail").
- **Where:** `backend/app/services/share.py:53`.
- **Reasoning:** a cert number is a lookup key into public auction archives (Heritage, and PCGS's auction records by cert). Those give a slab's sale price and date, which is often the owner's own purchase. Cert numbers are also what slab counterfeiters copy, and collectors routinely blur them.
- **Fix:** give the cert number its own toggle, off by default. Update the allowlist test at the same time.

### 11. LOW: the link URL always uses `PUBLIC_ORIGINS[0]`
- **Where:** `backend/app/services/share.py:85-86`.
- **Reasoning:** the list keeps the operator's order. With `http://cabinet.lan,https://cabinet.example.com`, every link is built on the LAN name: unreachable from outside, or sent over plain http, which carries the token in the clear.
- **Fix:** use the request's Origin when it is in the list, else the first https origin. Or build the URL in the browser from `window.location.origin` and the token. Document the rule.

### 12. INFO: smaller points
- **Off isn't invisible.** With sharing off, `/api/share/*` still reaches the backend anonymously and does a settings read on every request. It answers 404 where every other unknown anonymous path answers 401, so it identifies v0.32+ and isn't quite "as if they didn't exist". Timing also differs: with sharing off `resolve` returns before the hash lookup, a sub-millisecond gap that says only whether sharing is on. The in-memory flag from finding 3 fixes both.
- **Framing policy doesn't match the spec.** `proxy/cabinet-csp.conf` says `frame-ancestors 'self'` and the headers say `X-Frame-Options: SAMEORIGIN`, while SPEC_0320 ("Out of scope") says `'none'` stays. Fix the docs or the header.
- **Huge offsets give a 500.** `offset` has no upper bound (`routers/share.py:87`), so a value past bigint range is a Postgres error and a 500. Only someone holding a valid token can trigger it. Bound it.
- **Metal value can be worked out with values off.** Composition, weight, fineness and quantity are always shown, so anyone can compute a collection link's precious-metal worth from spot price. Consider saying so beside the values toggle.
- **One path into the app.** `ShareRoutes`' `*` route sends `/s` or `/s/x/y` to `/`, which is the sign-in page. That is the only way from a share page into the app.

## Checked and holding
- **The gate's prefix rule.**
  - Uvicorn and Starlette don't normalise `..`, so `/api/share/../settings` matches no route. A non-share route reached with no principal would still get 401 from layer 2.
  - `/api/share` without the slash gets 401.
  - `%` is refused.
  - Other methods under the prefix go through the normal checks.
  - A cookie on a share request never updates `last_seen_at`.
- **The one 404.** Sharing off, and malformed, unknown, revoked and target-gone tokens, all give the same body and headers.
- **What reaches a share.** The allowlist is enforced, checklists show filled slots only, photo ownership is re-checked on every request, nginx's `/photos/` still asks for a session, and documents have no share route.
- **The page.** The share routes are handled before `AuthProvider` mounts, every call is `raw`, and the CSP comes from the same include as the app's.
- **Network.** No share route fetches anything: rates are read from the cache only, and checklists and `display_currency` touch the database only.
- **Admin routes.** Permission classes and fresh flags match the SPEC_0300 appendix, the class counts are 127 operations in all with 41 admin and 5 share, set and checklist deletions cascade, and the token never appears in the admin list, audit rows or alerts.
- **Logs.** The `uvicorn.access` filter handles query strings, and the Referrer-Policy override works as intended.

## Verdict
Not yet safe to release as the first public page of an otherwise closed app.
- **Must change before tagging:**
  - **Finding 1:** a shared photo gives away the owner's home coordinates and timestamps, with photos on by default.
  - **Findings 2 and 3:** the throttle as built lets one anonymous client break every share link in the recommended proxied deployment. It also weakens sign-in's per-account limit on every v0.32.0 install, including those that never turn sharing on.
- **Strongly recommended in the same release:** finding 4 (a restore bringing back a revoked, leaked link is exactly the failure revocation exists to prevent), plus findings 5 and 8, which are small.
- **Can follow in a patch:** findings 6, 7, and 9 to 12.
