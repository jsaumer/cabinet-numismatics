<!-- Second fresh-context, read-only review by Claude Opus 5.5, of stage 4 (5877fa5..064a6bc) on p9-share, 23 September 2026, against the same brief as SPEC_0320-review-brief.md pointed at the stage 4 diff. Kept verbatim; what was done about each finding is in SPEC_0320's build log (stage 5). -->

# Second security review of SPEC_0320 stage 4 (v0.32.0), branch `p9-share` at 064a6bc

This was a read-only review of `git diff 5877fa5..064a6bc`, the code it touches, nginx, the frontend and the docs.

- **Tests:** `test_share.py`, `test_gate.py`, `test_photo_metadata.py` and `test_restore.py` pass (165 passed, 2 skipped). The skips are the symlink test, which can't run on this Windows machine, and one test of POSIX file modes. `tests/test_auth_throttle.py`, named in the brief, doesn't exist.
- **Probes:** I ran two probes from the scratchpad, never inside the repository:
  - `p1.py` puts crafted JPEG, PNG and WebP files through `clean_bytes` and `carries_metadata` (Pillow 12.3.0).
  - `test_probe.py` ran against conftest's fixtures with `-p tests.conftest`.
- **Not run:** Docker, Postgres and real nginx. Every restore finding below comes from reading the code.

## The first review's twelve findings

### 1. HIGH, photo metadata: fixed for new photos, partly fixed for photos already stored
- **New photos:** `backend/app/services/photos.py:96-112` (`clean_bytes`) and `:115-141` (`save_photo`). Upload, URL import, the editor and import photos all go through `save_photo`, and nothing else writes to `PHOTO_DIR`.
- **Checked empirically, output clean:**
  - A JPEG carrying EXIF (GPS, make, orientation 6), a COM comment, XMP, APP13 (Photoshop/IPTC), APP12 and APP4 comes out with only JFIF APP0 and the image segments. Orientation is applied and the image comes out 20x40 from 40x20.
  - PNG `zTXt`, `iTXt`, `eXIf` and `tIME` are gone.
  - WebP EXIF and XMP are gone.
- **What the fix doesn't cover:** the pass that cleans existing files has gaps, and the share route trusts that every stored original is clean. See N1 to N3.
- **Tests:** they cover upload, orientation, the replaced image, palette transparency, the pass, the marker and the CLI.

### 2. MEDIUM, a live link could be held at 429: fixed
`routers/share.py:55-75` resolves the link first. Only `share.NotFound` reaches `throttle.share_failure`, and a 404 inside a resolved share isn't counted. A live link can't be 429'd by anything.

**Side effect (info):** because every request is resolved first, the throttle no longer slows token guessing at all. A throttled scanner still gets each guess checked; it just sees 429 in place of 404, and 200 on a hit. The 256-bit token is now the whole defence, which is enough. But `deployment.md` ("an unknown or wrong token is slowed") and security.md overstate what the throttle does.

### 3. MEDIUM, share failures evicting sign-in buckets: fixed
- `throttle.py:63-65, 72-73, 166-205`: share failures have their own map and their own global deque.
  - `attempt` writes only the sign-in buckets.
  - `_apply_reset_flag` clears only the sign-in buckets.
  - `size()` and `share_size()` are split.
- **Tests:** `test_share_failures_never_push_out_sign_in_buckets` runs the review's script the other way round. `/64` keying is checked, IPv4-mapped addresses fold to IPv4, and nothing unparseable raises.
- **/64 keying:** it can't hurt a legitimate viewer, because only failed lookups are throttled.
- **Global cap:** 300 a minute. At worst, someone with a dead link sees 429 instead of 404, and `SharePage` renders both the same way.
- **Switch off:** verified that an anonymous `/api/share/*` request and an unlisted path get identical status, body and headers (401, `{"detail":"Sign in to continue."}`, `no-store`), with no database read. There is one race in the in-memory switch: see N7.

### 4. MEDIUM, a restore brought back revoked links: mostly fixed
`restore.py:965-1033` (`_put_back_sharing`), plus the snapshot at `:1216` and the journal at `:1238, :1266`. The normal in-app path is right, and the snapshot holds hashes only.

Three paths let the archive's links or switch survive, or lose the live ones (N5, N6, N8):
- a restart in the `swapping` phase with the database unreachable;
- a failed state-volume write right after `pg_restore`;
- a put-back failure, which leaves the archive's rows in the table.

**Checked and holding:**
- **Journal:** it now keeps token hashes, link names and set names on the state volume while a restore runs. A SHA-256 of a 256-bit token can't be reversed or presented, so this matters little.
- **Id plus name:** because set ids are integers (sequence reset), a link is only ever re-attached to the same set as restored.

### 5. LOW, `Last-Modified` and `ETag` on the photo: fixed, with a regression
`routers/share.py:42-47`. Both headers are gone, and a test checks it. Removing them breaks Starlette's `If-Range` handling: see N4.

### 6. LOW, tokens in nginx logs: fixed
- `proxy/nginx.conf:9-10` accepts leading slashes, `:25` has `access_log off` on the default server, and the error log is documented in `deployment.md`.
- **Residual (info):** the map still logs in clear a path it doesn't recognise, such as `/./api/share/<t>` or `/%61pi/share/<t>`. Only the token's holder can send one: the gate refuses `%`, and neither form resolves a link. That isn't a leak to anyone new.

### 7. LOW, `robots.txt` blocking `/s/`: fixed
`nginx.conf:191-195` disallows only `/api/`, and `@share_index` sends `X-Robots-Tag`. The `<meta name="robots">` tag is added by JavaScript in `SharePage.tsx`, so it is weaker than the header, but the header is enough.

### 8. LOW, the Traefik example: fixed
`priority` is gone, and the text explaining why is accurate: Traefik's default priority is the rule's length. The `sanitizePath` and path-normalisation note and the error-log note are correct.

### 9. LOW, `PATCH` widening a link silently: fixed
`share_links.py:155-199`.
- The route is `admin, fresh`.
- `exclude_none` makes `null` a no-op.
- Two options at once, or a rename plus an option, are all recorded in `changed`.
- `widened` lists every one of notes, values and cert number that goes from off to on.

**Optional:** turning photos back on after they were off is audited but not alerted.

### 10. LOW, `cert_number` behind `show_grades`: fixed in the data
`share.py:62, 328-329`. The number isn't reachable by any other route: the items list, one item, the manifest and the checklist slots carry no cert fields, and the allowlist test pins it.

**Info:** a slab photo shows the cert number and barcode on the label, and photos are on by default. The same goes for a bar's stamped serial. The toggle's help text in `Sharing.tsx` should say that switching it off doesn't hide a number visible in a photo.

### 11. LOW, the link's origin: fixed
`share.py:97-110`. The request's Origin is used only after `normalize_origin` puts it inside `PUBLIC_ORIGINS`, so no outside origin can be used. Otherwise the first https origin is used, else the first origin. It is tested.

### 12. INFO, the smaller points: fixed
- `offset` is bounded, and a huge value gets 404 or 422, not 500.
- The frame-ancestors wording in the spec is corrected.
- The melt note is beside the values toggle.

**Info:** the security.md permission row says links can be created, changed and revoked "only while sharing is on". In fact `PATCH` and `DELETE` work while it is off; only create and regenerate answer 409.

## New findings

### N1. MEDIUM: photos stored before v0.32.0 are never cleaned when `AUTO_MIGRATE=false`
- **Where:** `backend/app/main.py:193` and `:210`. The only automatic startup pass, `photo_files.clean_in_background()`, sits inside `if config.auto_migrate:`.
- **Effect:**
  - An install that runs migrations by hand (a documented option, `deployment.md:109`) never cleans its existing originals.
  - The same holds after `recover()` removes the marker.
  - Once the owner turns sharing on, those originals, GPS included, are served by the share route.
  - CHANGELOG ("cleaned once, in the background, on the first start after upgrading") and security.md promise otherwise.
- **Fix:** run the pass regardless of `AUTO_MIGRATE`. It needs no database. Tests can patch `photos._spawn`, as they already do elsewhere.

### N2. LOW-MEDIUM: an archive's photos are served, metadata included, before a pass cleans them
There are three windows:
- **After an in-app restore** (`restore.py:1299-1300`): `clean_in_background(force=True)` starts a background thread, and `_finish` then leaves maintenance at once. At roughly 0.3 to 0.5 s per re-encoded 12 MP JPEG, a few hundred originals from an archive made before v0.32.0 are served with EXIF and GPS for minutes, to every live share link.
- **After `restore.sh`:**
  - The marker on the state volume isn't touched, so no restart cleans anything.
  - The script prints nothing about it. The reminder is a header comment (`scripts/restore.sh:15-20`) plus docs.
  - The script already runs `docker compose exec backend` commands, so it could run the pass itself.
- **When a rewrite fails or a file is unreadable:** those files stay as they are and are still served (a failure retries on the next start; an unreadable file never does).

**Fix, defence in depth:** make the share photo route never trust the disk.
- **Option A:** while `photos.marker_exists()` is false, serve `clean_bytes(open_validated(file))` instead of the file.
- **Option B:** always re-encode `full` on that route, with a small cache.

Also, either run the pass synchronously before `maintenance.leave()` for restored photos, or keep sharing suspended in memory until the pass writes the marker. And have `restore.sh` run `python -m app.cli strip-photo-metadata` and print the Settings → Sharing reminder.

### N3. LOW: the pass misreads some dirty files as clean, and old thumbnails aren't clean
- **Where:** `carries_metadata` (`photos.py:169-172`) looks only at Pillow's `info` keys, against a whitelist (`:44-66`).
- **Verified misses:** these files come back `carries_metadata == False`, so the pass leaves them alone. New uploads are unaffected, because `save_photo` always re-encodes.
  - a JPEG whose only metadata is in APP segments Pillow keeps in `applist` but not in `info` (APP12 "Ducky", APP4 vendor blocks, APP6 GoPro GPMF);
  - a PNG `tIME` chunk;
  - a PNG `tEXt` whose keyword happens to be a whitelisted name (`timestamp`, `dpi`).
- **Thumbnails ("thumbnails were always clean", backup-restore.md and spec 1):** not true. Pillow 12.3's JPEG encoder defaults `comment` from `im.info` (`JpegImagePlugin._save`: `comment = info.get("comment", im.info.get("comment"))`). The old `save_photo` built the thumbnail from the image with its `info` intact. Verified: a thumbnail made the pre-v0.32.0 way carries the source's COM segment ("owner Jayson" in the probe). The pass skips `*_thumb.jpg`, and the share grid serves thumbnails.
- **Fix:**
  - For JPEG, also treat any `applist` entry other than APP0 JFIF, APP2 ICC_PROFILE or APP14 Adobe, and any COM, as metadata.
  - For PNG, check for any ancillary chunk outside a known-harmless set.
  - Include thumbnails in the one-time pass.
  - Or simply re-encode every original once: the marker already stops repeats.
- **Info:** the kept ICC profile can carry a device model and a profile creation date. It is usually a standard profile. Acceptable, but worth a line in security.md.

### N4. LOW: `Range` plus `If-Range` on a share photo is now a 500
- **Where:** `routers/share.py:42-47`. The override drops `last-modified` and `etag`, but Starlette 1.6's `FileResponse._should_use_range` reads `self.headers["last-modified"]` and `self.headers["etag"]` directly.
- **Reproduce:** `GET /api/share/<valid>/photos/<id>/full` with `Range: bytes=0-9` and `If-Range: "x"` raises `KeyError: 'last-modified'` (verified with TestClient). `Range` alone works (206).
- **Who can trigger it:** only someone holding a valid link. A browser does send `If-Range` when resuming a partial download.
- **Fix:** also override `_should_use_range` to return False (the full body, which RFC 9110 allows), or send a constant, content-derived ETag. Add a test.

### N5. LOW: two restore paths drop the snapshot, leaving the archive's links and switch live
- **Restart in the `swapping` phase:** `recover()` (`restore.py:1455-1456`) calls `_recover_sharing`, which ignores a failed `schema.wait_for_database` (`:1484-1486`).
  1. `_put_back_sharing` fails, and so does its switch-off write.
  2. `recover` still marks the restore ok and deletes the journal (`:1472`), so the snapshot is gone.
  3. When the database comes back, the archive's links and `share_enabled` are in force: exactly what finding 4 was about.

  The trigger is plausible: a crash during migrations or the swap, then a host reboot where Postgres on NFS is slow. The `database` phase already handles this correctly: it stays in maintenance and keeps the journal.
- **In-run:** if `_write_json(... "swapping" ...)` (`:1266`) raises (for example, the state volume is full), the exception skips `_put_back_sharing` (`:1281`), and `_finish` deletes the journal (`:1333`). The database is the archive's, and nothing puts the links back.
- **Fix:**
  - In `recover`, when the put-back reports an error, keep the journal (or the snapshot in its own file) and enter maintenance, as the `database` phase does.
  - In `_run`, run the put-back whenever `database_restored` is true and it hasn't run yet (a `finally`), before anything else that can raise.

### N6. LOW: a failed put-back only switches sharing off
- **Where:** `restore.py:1014-1026`.
- **What happens:**
  - The transaction rolls back, so the archive's `share_links` rows, possibly revoked or leaked ones, stay in the table behind a switch that is off.
  - When the owner switches sharing back on, they are live.
  - If `_finish`'s tidy-up raises before `_reload_sharing` (`:1327-1338`), memory keeps the pre-restore value (possibly True) while the database has those rows. Resolving a link uses memory, so they would open straight away.
- **Fix:** on failure, also delete every `share_links` row (in a separate transaction) and call `share.set_enabled(False)` directly, whatever the database read says.

### N7. LOW: the in-memory switch can be overwritten by a stale read, leaving sharing on after the owner switched it off
- **Where:** `share.load` reads the setting (`share.py:143`) and then calls `set_enabled` (`:144`) without holding a lock across both. The same pattern is in `GET /api/settings` (`routers/settings.py:274`), the hourly tick (`scheduled.py:116`) and the gate's lazy load.
- **Interleaving:**
  1. The tick reads True.
  2. `PUT /api/settings` commits False and sets memory False.
  3. The tick then sets True.
- **Effect:** the gate and `resolve` keep serving links until the next hourly tick or the next time Settings is opened, even though the database says off. The window is milliseconds, but the result is the unsafe direction.
- **Fix:** a generation counter. `load` snapshots it before reading and writes only if no `set_enabled` ran in between. Or hold `_enabled_lock` across the read and the write, with the PUT's set after its commit, as it is now.
- **Related (info):** the switch is now a security control held per process. The one-replica assumption (docs, stack file) matters more than before, so state it in security.md.

### N8. INFO: after a restart, the owner's links are lost with an archive older than 0022
`recover()` puts the links back before startup migrations (`restore.py:1447`, `:1456`). For an archive older than migration 0022, `has_links` is false, so every live link is counted as dropped. The in-run path waits for migrations and keeps them. This fails safe (no leak), but the owner's links are lost.

**Fix:** defer the recover put-back until after startup migrations, for example by leaving the snapshot for the lifespan to apply.

### Checked and holding
- Symlinks are never followed.
- Temporary files stay in the same folder.
- Only `.strip-*` files older than ten minutes are deleted.
- A concurrent delete isn't resurrected, apart from a harmless orphan when a replace races.
- `.restore-*` folders are skipped.
- A race with the swap only fails closed (counted as failed, marker unwritten).
- `_pass_lock` serialises passes.
- The CLI pass runs as `PUID`.
- The gate's lazy load is idempotent and reads as off on a database error. One cost: while memory is `None` and the database is down, each anonymous share request makes a connection attempt in a worker thread. This happens only after a failed startup load or a failed reload.
- No new log line, audit row or alert carries a token.
- The admin routes' permission classes match the appendix.
- `HEAD` under the prefix gives 405.
- The frontend treats 404, 401 and 429 alike.

## Verdict

v0.32.0 is close. The HIGH and both MEDIUM findings are fixed where they bit hardest: new uploads carry no metadata, a live link can't be 429'd, and the sign-in buckets can't be evicted. But the fix for finding 1 isn't complete for photos already on disk. The share route still trusts that every stored original is clean, and three things make that untrue: N1 (`AUTO_MIGRATE=false`), N2 (the window after a restore, and `restore.sh`) and N3 (misclassified files and old thumbnails).

**Must change before tagging:**
- **N1:** run the pass regardless of `AUTO_MIGRATE`.
- **N2:** make the share photo route clean on the fly while the marker is absent, or always re-encode `full`. This also covers N3's leftovers.
- **N4:** a one-line fix to `_should_use_range`.

**Strongly recommended in the same release:**
- **N5 and N6:** these are the remaining ways finding 4's failure (a revoked link coming back) can still happen.
- **N7:** the generation counter.
- **Docs:** make `restore.sh` run the strip command and print the sharing reminder, and correct the docs' "thumbnails were always clean" and "wrong tokens are slowed".

**Can follow in a patch:** N3's `carries_metadata` improvements (once the share route cleans on the fly), N8, the note that slab photos show the cert number, and the security.md wording.
