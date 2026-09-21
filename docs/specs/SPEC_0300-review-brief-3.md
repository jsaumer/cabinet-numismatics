# Review brief, round 3: SPEC_0300 with encrypted backups

The third and, if nothing structural turns up, final adversarial review of
the v0.30.0 authentication contract before the owner approves it and the
build starts. Cabinet catalogues a private coin and banknote collection:
what each piece is, what it is worth, receipts with names and addresses,
and **where each piece is kept**. A read-only copy of that data is the worst
case, because it can lead to physical theft.

Your second review (`docs/specs/SPEC_0300-codex-review-2.md`) found four
gaps and pushed back on three decisions. The owner took all of it on
21 September 2026, including one large addition: **every backup archive is
now encrypted and authenticated** (section 2 of the contract, "Encrypted,
tamper-evident archives"). That is new cryptographic design, which is where
mistakes are most expensive, so it is the main target of this round.
Section 13 of the contract records a verdict on each of your round-2 points.

## Rules

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0300-codex-review-3.md`. Change no other file, create no
  branch, commit nothing, push nothing, run no migration.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud).
- You may run read-only Python in `backend/.venv` with a throwaway database
  (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, temp `PHOTO_DIR` and `DOCUMENT_DIR`), and
  you may reason from the age specification (age-encryption.org/v1) and the
  `cryptography` package already in `backend/requirements.txt`.
- Every repo claim needs a `file:line`; every library or format claim its
  source and how you checked it. Label anything unverified.
- No em dashes anywhere in your output (the owner's rule).
- Settled decisions are challenged only with a concrete attack.

## What to read

1. `docs/specs/SPEC_0300-how-it-works.md`, especially section 6, "Backups
   and the backup key", and section 5, "When something goes wrong".
2. `docs/specs/SPEC_0300.md`: section 2 (archives, the marker, secrets),
   section 3 (the fresh list), sections 5 to 7, the stage table in
   section 10, section 13, and the route appendix.
3. Your first two reviews, and the round-2 brief for context.
4. `docs/security.md` and the P8 entry in `docs/roadmap.md`, updated to
   match.
5. The code the archive design changes: `backend/app/services/backup.py`
   (`dump_database`, `write_archive`, `verify_archive`, `NAME_RE`, `prune`,
   `write_prerestore`), `backend/app/services/restore.py` (`check_archive`,
   `inspect`, `_run`, `recover`), `backend/app/routers/backup.py`,
   `scripts/backup.sh`, `scripts/restore.sh`, `backend/Dockerfile`, and
   `backend/app/services/crypto.py`.

## What the owner wants from this round

### 1. Attack the encrypted-archive design

The design in one paragraph: archives are age v1 files encrypted to one
X25519 recipient, made by the Debian `age` binary run as a streaming
subprocess. The identity comes from `BACKUP_KEY_FILE` (a Docker secret) or
is generated at first start into `backup.key` (0600) on the state volume.
Because anyone with the public recipient could make a new archive, the
manifest inside carries `mac`, an HMAC-SHA256 over `SHA256SUMS` keyed by
HKDF-SHA256(identity, info `cabinet-backup-mac-v1`); restore decrypts,
verifies `mac`, and only then reads anything else. The key is shown only by
`python -m app.cli backup-key show`; rotation prepends a new identity; old
plain `.zip` archives are flagged, deletable, and restorable only after a
typed `RESTORE UNENCRYPTED`. Startup warns when the generated key shares a
mount source with `BACKUP_DIR`.

Please try to break it:

- **Forgery and substitution.** Can someone with write access to the share
  but not the key produce an archive that restores? Consider: replaying an
  older genuine archive (is a rollback to an old but authentic archive a
  risk worth a rule, for example a warning when the archive is older than
  the newest one seen?); swapping members between two genuine archives;
  truncation; the `mac` covering `SHA256SUMS` but not `manifest.json` itself
  (the manifest is not in `SHA256SUMS` today, see implementation notes);
  what exactly the MAC must cover.
- **Key handling.** HKDF input (the identity's bech32 text or its raw
  scalar?), domain separation, comparison in constant time, multiple
  identities during rotation (which key's MAC is expected?), the key file's
  permissions and ownership under the entrypoint's `setpriv` hand-off, and
  whether `backup-key show` from `docker exec` as root leaks anything
  (terminal scrollback, `docker logs`, audit).
- **The `age` subprocess.** Streaming large archives, error handling so a
  failed encryption never leaves a plain partial file in `BACKUP_DIR`,
  temporary files (the current code writes `.partial` and `.download-`
  files, backup.py:275-310: are any of them ever plain on the share?),
  and what the in-app download streams to the browser.
- **The `RESTORE UNENCRYPTED` path.** Is keeping it a hole? An attacker who
  can write to the share could drop a plain `.zip` and wait for the owner to
  restore it. Would you remove it, time-limit it, or keep it?
- **Key location.** Is the mount-source comparison sound on Docker, NFS
  binds, and named volumes? What should happen when it cannot tell?
- **Disaster recovery.** Walk through a lost machine: new host, v0.30.0,
  claim, `BACKUP_KEY_FILE` with the saved key, restore in-app and with
  `restore.sh`, and opening an archive with the plain `age` tool. Is any
  step missing or impossible as written?
- **Upgrade.** An install upgrading from v0.29.1 has plain archives on its
  share and scheduled backups running. What exactly happens on the first
  start, and is there any window where a new plain archive is written?

### 2. Check the round-2 fixes landed

One line each: A1 (8 KiB anonymous bodies and the compose memory limit),
A2 (every settings change, token revocation, ending another session, and
sign-out-everywhere now fresh), A3 (plain secrets cleared at upgrade and
restore, named, never auto-encrypted), A4 (the PCGS cert grammar), the
7-day `read` and `write` tokens, and every token revoked on a password
change or reset.

### 3. Consistency

The contract, the walkthrough, `docs/security.md`, and the roadmap were
edited separately. List any rule that two of them state differently, any
route in the appendix whose class disagrees with section 3, and any stage
in section 10 that needs something a later stage builds.

### 4. Anything still missing

With encrypted backups in, is there anything else a single-admin tool for
valuables should have in v0.30.0 rather than v0.31.0 (single sign-on and
two-factor sign-in)? And is there now anything that is more than it needs
to be? Be specific about cost and benefit either way.

## Output

Write `docs/specs/SPEC_0300-codex-review-3.md`:

1. **Verdict**: safe to build as written, safe with changes, or not safe,
   in three sentences at most. Say explicitly whether anything you found is
   structural (changes the design) or a rule to add (changes the text).
2. **Round-2 items**: one line each, closed or not, with the reason.
3. **Findings**, most severe first, as a table: id, severity, which harm it
   enables (knowing what is where and its value; personal data; control of
   the collection record; control of the deployment; availability), the
   attack, evidence, the exact rule for the contract, and the test that
   proves it.
4. **Consistency problems**, each with both locations.
5. **Missing or excess**, one line each, with the release it belongs in.
6. **Not verified**, and why.
