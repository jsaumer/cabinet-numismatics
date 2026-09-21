# Review brief, round 2: SPEC_0300 after your first review

This is the second adversarial review of the v0.30.0 authentication contract
for Cabinet, a self-hosted catalogue of a private coin and banknote
collection: what each piece is, what it cost, what it is worth, receipts
with names and addresses, and **where each piece is kept**. A read-only leak
can lead to physical theft, so it is the worst case here, not the mildest.
Nothing has been built. The owner approves the contract only after this
round.

Your first review is `docs/specs/SPEC_0300-codex-review.md`. The contract
was changed in response; section 12 of `docs/specs/SPEC_0300.md` records a
verdict on every one of your findings, two problems found while checking
them, and a pushback table of what was deliberately not done.

## Rules

- **Read-only, with one exception:** write your review to
  `docs/specs/SPEC_0300-codex-review-2.md`. Create or change no other file,
  create no branch, commit nothing, push nothing, run no migration.
- Never read a `.env` file. Never contact the live instance
  (cabinet.saumer.cloud).
- You may run read-only Python in `backend/.venv` against `app.main:app` with
  a throwaway database (`DATABASE_URL=sqlite://`, `AUTO_MIGRATE=false`,
  `REQUIRE_DOCUMENT_MOUNT=false`, `PHOTO_DIR` and `DOCUMENT_DIR` pointing at a
  temp folder) to check how FastAPI 0.141.1 and Starlette 1.6.0 behave.
- Every repo claim needs a `file:line`; every library claim its version and
  how you checked it. Label anything unverified.
- No em dashes anywhere in your output (the owner's rule).
- Settled decisions (section 11 of the contract, and the list in the first
  brief, `docs/specs/SPEC_0300-review-brief.md`) are challenged only with a
  concrete attack. The pushback table is fair game: if you think a rejection
  is wrong, say why with evidence.

## What to read

1. `docs/specs/SPEC_0300-how-it-works.md`: the plain-language walkthrough of
   setup, sign-in, everyday use, changing the password, and the break-glass
   reset.
2. `docs/specs/SPEC_0300.md`: the contract, especially sections 2, 3, 5, 6,
   7, and 12, and the route appendix.
3. Your first review, for what you asked for.
4. `docs/security.md` ("Next: accounts and permissions") and the P8 entry in
   `docs/roadmap.md`, which were updated to match.
5. The code the contract changes (list in the first brief), plus
   `backend/app/services/app_settings.py` and `backend/app/services/crypto.py`
   for the secrets change.

## What the owner wants from this round

### 1. Did the fixes land correctly?

For each finding you raised, check that the contract's rule actually closes
the attack you described, and that the test named for it would fail if the
rule were broken. Pay particular attention to the two places where your fix
was replaced by a different one:

- **C2, the restore marker.** The marker stays in `public.app_settings`, and
  recovery compares the exact random value recorded in the journal. Is there
  any archive, crash timing, or journal state where recovery still takes the
  wrong branch?
- **H1, the scope of `read` tokens.** Instead of hiding fields, tokens stay
  honest (they see everything else, storage locations included) but must
  expire within 90 days, need the password to create, send an alert, and
  cannot export, download backups, or read document files. Is that enough
  for a tool like this? If not, what exactly would you change, and can it be
  done without the false comfort of partial redaction?

### 2. Attack the new mechanisms

These did not exist when you last looked:

- **The recent-password window** (`POST /api/auth/confirm`, the `fresh`
  flag, `sessions.confirmed_until`, 5 minutes, the 403 `reauth_required`
  retry in the frontend, and plain-link downloads that check
  `confirmed_until` before navigating). Can a session outside the window
  reach a fresh route? Can the confirmation itself be abused (brute force,
  CSRF, a token)? Is the list of fresh routes complete for this data?
- **The reserved verification slot** for a valid known device. Can an
  attacker obtain or starve it?
- **Password change and reset revoking `read` and `write` tokens** but
  keeping `metrics` ones. Any path that changes the password without
  revoking?
- **Refusing any `/api/` path containing `%` (400)**, and all comparisons on
  `scope["raw_path"]`. Does anything legitimate break (check every route's
  path parameters and the frontend's URL building)? Is there a bypass that
  doesn't use `%`?
- **Secrets that don't decrypt with the deployment's key are never used**
  (the plain-text self-heal in `get_setting` removed, and restores clearing
  them). Check `crypto.py`: can a value be crafted that passes as encrypted
  without the key? Does removing the self-heal break any existing install?
- **`--no-proxy-headers` and `X-Real-IP`** recorded for information only. Is
  any allow or deny decision still influenced by a client-controlled header?
- **Audit changes:** the separate 10,000-row cap for failed sign-ins, caps
  enforced on write, sampled stdout, and "nothing from the collection in any
  audit row, log line, or webhook". Can the evidence of a real intrusion
  still be erased or drowned?
- **Webhook alerts** for sign-in events, tokens, downloads, and restores.
  Could an alert itself leak something, or be triggered to flood the owner?
- **`SETUP_CODE_FILE`** and the rule that a supplied code must be at least 32
  characters with no character over a quarter of it.

### 3. The three flows the owner cares about most

Read the walkthrough as an attacker and as the owner:

- **Initialising the admin**: first start, the code's three sources, the
  claim, the claimed marker, upgrading an open install, and a fresh machine
  after a lost database.
- **Changing the password** in the app.
- **Breaking the glass** with `python -m app.cli reset-password` and the
  other three container commands.

For each: is there a window where someone other than the owner wins? Is
there a state the owner can get stuck in with no way out? Does the
walkthrough promise anything the contract does not require, or the other
way round?

### 4. Is it now right-sized?

The owner wants "the most secure basic sign-in and single-user maintenance
tools", with security paramount, without overbuilding. After this round of
additions, is anything now more than it needs to be? Is anything still
missing that belongs in v0.30.0 rather than v0.31.0 (which brings single
sign-on and two-factor sign-in)?

## Output

Write `docs/specs/SPEC_0300-codex-review-2.md`:

1. **Verdict**: safe to build as written, safe with changes, or not safe,
   in three sentences at most.
2. **Your first-round findings**: one line each, closed, partly closed, or
   not closed, with the reason.
3. **New findings**, most severe first, as a table: id, severity, which harm
   it enables (knowing what is where and its value; personal data; control
   of the collection record; control of the deployment; availability), the
   attack, evidence, the exact rule for the contract, and the test that
   proves it.
4. **Pushback on the pushback**: any rejection you still disagree with, and
   why.
5. **Not verified**, and why.
