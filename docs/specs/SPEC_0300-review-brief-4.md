# Review brief, round 4 (final): SPEC_0300

The last review of the v0.30.0 authentication contract before the owner
approves it and the build starts. Cabinet catalogues a private coin and
banknote collection, including **where each piece is kept**; a read-only
copy of that data is the worst case, because it can lead to physical theft.

This round is deliberately **narrow**. Three rounds have converged: your
third review (`docs/specs/SPEC_0300-codex-review-3.md`) confirmed every
round-2 fix closed and found problems only in the encrypted-archive design.
All six of its findings and all five consistency problems were taken;
section 14 of the contract records each verdict. The owner has set a
stopping rule: **if this round finds nothing critical or high, the contract
is approved**, and anything medium or lower becomes a rule added during the
build rather than another round. So please grade severity carefully and say
plainly when something is not worth a finding.

## Rules

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0300-codex-review-4.md`. Change no other file, create no
  branch, commit nothing, push nothing, run no migration.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud).
- You may run read-only Python in `backend/.venv` with a throwaway database
  (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, temp `PHOTO_DIR` and `DOCUMENT_DIR`), and
  reason from the age v1 specification and the `cryptography` package.
- Every repo claim needs a `file:line`; every library or format claim its
  source and how you checked it. Label anything unverified.
- No em dashes anywhere in your output (the owner's rule).
- Out of scope by the owner's decision: protecting the database, photo,
  document, and staging volumes (the operator's storage), and restoring
  archives made before v0.30.0 (dropped entirely).
- Settled decisions are challenged only with a concrete attack.

## What to read

1. `docs/specs/SPEC_0300.md`: section 2 ("Encrypted, tamper-evident
   archives", the key-location paragraph, and its tests), section 1's
   `backup_ledger` table, section 7's settings and networks tables, the
   stage 5 row in section 10, and section 14.
2. `docs/specs/SPEC_0300-how-it-works.md`, section 6.
3. Your third review.
4. The code the design changes: `backend/app/services/backup.py`,
   `backend/app/services/restore.py` (`staging_dir`, `check_archive`,
   `inspect`, `_run`, `recover`), `scripts/backup.sh`, `scripts/restore.sh`.

## What to check

### 1. Did the round-3 fixes land?

One line each, closed or not, with the reason: B1 (streamed writes, no
plain text in `BACKUP_DIR`, decryption only in `/data/staging`,
`restore.sh` in a private temporary folder with a cleanup trap), B2
(`mac_recipient` selecting exactly one identity), B3 (the archive record in
`cabinet_auth` and `RESTORE OLDER`), B4 (plain archives never restorable),
B5 (separate, shared, or not verified), B6 (the byte-exact MAC conformance
test), and the five consistency fixes.

### 2. Try once more to break the archive boundary

Only the design as it now stands, for example:

- Is there any remaining path (download, scheduled, run-now, safety backup,
  upload, inspect, restore, `recover()`, `backup.sh`, `restore.sh`, an
  exception half-way) that could leave plain archive bytes, a plain member,
  or the decrypted `db.dump` in `BACKUP_DIR`?
- Can `mac_recipient` selection be confused (two identities with the same
  recipient, an identity file with junk lines, a recipient string that
  parses loosely)?
- Can the archive record be used against the owner: a forged archive that
  claims to be newer, an old archive renamed, the ledger after a restore
  onto a new machine, pruning?
- Does `RESTORE OLDER` compare the right thing (the archive's MAC-covered
  `created_at` against the newest recorded archive, not the file name or
  modification time)?
- Is the staging volume's clean-up complete across a crash mid-decrypt and
  a crash mid-restore, given `recover()`'s journal phases in the same
  section?

### 3. Final consistency sweep

Read the contract, the walkthrough, `docs/security.md`, the P8 entry and the
Phase 5.6 note in `docs/roadmap.md`, and the route appendix together. List
any rule stated two different ways, and any stage in section 10 that needs
something a later stage builds.

## Output

Write `docs/specs/SPEC_0300-codex-review-4.md`:

1. **Verdict**, one of: **approve**; **approve, with rules to add during the
   build** (only medium or lower findings); or **not safe** (any critical or
   high finding). Three sentences at most.
2. **Round-3 items**: one line each.
3. **Findings**, most severe first, as a table: id, severity, harm, attack,
   evidence, exact rule, test. Leave it empty if there are none.
4. **Consistency problems**, each with both locations.
5. **Not verified**, and why.
