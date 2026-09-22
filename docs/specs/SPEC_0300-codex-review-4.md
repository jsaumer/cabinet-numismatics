# Codex adversarial review, round 4: final authentication contract review

## Verdict

**Approve, with rules to add during the build.** No critical or high finding
remains in the encrypted archive boundary within the stated operator-storage
scope. C1 is medium: the ledger needs an explicit archive binding and an
authenticated timestamp comparison so `RESTORE OLDER` cannot be bypassed by
renaming a genuine old archive.

## Round-3 items

| Item | Status | Reason |
| --- | --- | --- |
| B1, plaintext archive boundary | Closed | The archive is streamed into age, only ciphertext may be in BACKUP_DIR, and decryption is limited to `/data/staging`; both normal and failure paths, including startup recovery, are covered (docs/specs/SPEC_0300.md:170-171, docs/specs/SPEC_0300.md:193). `restore.sh` must use a private trapped temporary folder (docs/specs/SPEC_0300.md:178). |
| B2, MAC identity after rotation | Closed | The MAC-covered `mac_recipient` must select exactly one configured identity, rejecting none or duplicates (docs/specs/SPEC_0300.md:174-175). The rotation test covers old and new identities and a read-only secret (docs/specs/SPEC_0300.md:194). |
| B3, replay of a genuine older archive | Partially closed | The immutable auth-schema ledger and `RESTORE OLDER` landed (docs/specs/SPEC_0300.md:67, docs/specs/SPEC_0300.md:176, docs/specs/SPEC_0300.md:195), but C1 specifies the binding and comparison those rules require. |
| B4, legacy plain archives | Closed | Plain `.zip` archives are refused by every restore path, including genuine old ones (docs/specs/SPEC_0300.md:179, docs/specs/SPEC_0300.md:196). |
| B5, uncertain key location | Closed | The generated-key check has separate, shared, and not-verified states, while unreadable secret files stop startup before a backup (docs/specs/SPEC_0300.md:172, docs/specs/SPEC_0300.md:186-197). |
| B6, MAC conformance | Closed | The required test changes only the manifest, retains SHA256SUMS and the old MAC, re-encrypts to the public recipient, and requires both restore paths to refuse it (docs/specs/SPEC_0300.md:192). |
| Consistency: token revocation test | Closed | The credential test now requires both a password change and reset to revoke every token scope (docs/specs/SPEC_0300.md:368). |
| Consistency: BACKUP_KEY_FILE definition | Closed | The Settings table now defines the identity-file format, ownership, failure, selection, and rotation rules (docs/specs/SPEC_0300.md:434). |
| Consistency: backup staging documentation | Closed at the top-level rule | The planned security text names private staging and identifies the old `BACKUP_DIR` staging as pre-v0.30 behavior (docs/security.md:341-354). The detailed contract conflict below remains. |
| Consistency: Phase 5.6 archive history | Closed | The roadmap explicitly labels the old archive description as superseded in part by v0.30.0 (docs/roadmap.md:506-509). |
| Consistency: proxy trust wording and gateway checklist | Closed | The backend never trusts forwarded headers in A1, and the deployment work includes the concrete gateway checklist (docs/specs/SPEC_0300.md:424, docs/specs/SPEC_0300.md:473). |

## Findings

| ID | Severity | Harm | Attack | Evidence | Exact rule | Test |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | medium | Control of the collection record | A backup-share writer replaces a current archive with a genuine older archive, but changes its name and filesystem timestamp. The MAC passes. If implementation identifies the ledger row by `name`, or decides older from the file timestamp, it can call the archive "Not made by this Cabinet" or current and accept `RESTORE`, silently rolling the collection back. | The ledger stores `name`, `created_at`, `mac_recipient`, and a digest of the MAC (docs/specs/SPEC_0300.md:67), while the restore rule says only "older than the newest recorded" without defining the match or comparison source (docs/specs/SPEC_0300.md:176). The required test covers two genuine archives but not a renamed archive or a pruned non-latest row (docs/specs/SPEC_0300.md:195). | At write, store the exact MAC-covered manifest `created_at`, `mac_recipient`, and `SHA-256(mac)`. At inspect, identify an archive by the latter two values, never by filename or filesystem metadata; compare its verified manifest `created_at` to the newest retained ledger `created_at`. Any earlier value requires `RESTORE OLDER`, including an archive whose individual row was pruned. An empty ledger on a new machine must explicitly say rollback detection is unavailable. | Write A then B, rename A to B's name, set A's mtime newer, and inspect A. It identifies A by MAC identity and refuses plain `RESTORE` because A's authenticated `created_at` predates B. Repeat after pruning A's individual row while retaining B. On an empty new-machine ledger, the UI states that detection is unavailable. |

## Consistency problems

- `check_archive` still says it extracts `db.dump` into `.restore-staging/<id>.dump` ([SPEC_0300.md:112](SPEC_0300.md#L112)), whereas the encrypted-archive rules require all decrypted material in `/data/staging` and say `BACKUP_DIR/.restore-staging` holds ciphertext only ([SPEC_0300.md:171](SPEC_0300.md#L171)). Change the former to `/data/staging/<id>.dump` or define the path relative to `/data/staging`.
- The historical review table still says metrics tokens survive a password change ([SPEC_0300.md:650](SPEC_0300.md#L650)), while the live session rule and test revoke every scope ([SPEC_0300.md:295](SPEC_0300.md#L295), [SPEC_0300.md:368](SPEC_0300.md#L368)). Label the old table row superseded by the later owner decision so a builder does not copy its obsolete outcome.
- Stage 4 requires the table-of-contents inspection, which extracts `db.dump` ([SPEC_0300.md:112](SPEC_0300.md#L112)), but the private staging volume is scheduled only in stage 5 ([SPEC_0300.md:601](SPEC_0300.md#L601)). Build the `/data/staging` primitive in stage 4, or defer that extraction until stage 5, so no intermediate implementation puts a plain dump in BACKUP_DIR.

## Not verified

- v0.30.0 code does not exist yet. I inspected the current pre-auth backup and restore paths, which still stage under the backup directory (backend/app/services/restore.py:112-115), only to compare the planned changes. I did not execute them because the current scripts load `.env` (scripts/backup.sh:8, scripts/restore.sh:14).
- I did not run the Debian age binary, Docker secret mounts, PostgreSQL restore, nginx, or a gateway. The age assessment remains an unexecuted design review against the primary [age v1 specification](https://age-encryption.org/v1), which I checked directly.
- I did not inspect the live stack, any `.env` file, the backup share, Docker API, or the live Cabinet instance. Crash cleanup of `/data/staging` and the host temporary folder must be verified by the specified stage-5 tests.
