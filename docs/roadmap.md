# Cabinet: Roadmap

What is left before 1.0, what might come after, what was set aside or cut
and why, and a short record of what shipped when.

This page is deliberately short. What Cabinet does today is in
[features.md](features.md); what each release changed is in the
[changelog](../CHANGELOG.md); the rules each release left behind for the
code are in [implementation-notes.md](implementation-notes.md).

## Status

**v0.44.0 is the latest release (November 2026).** Versioned images are
published to GHCR from every tagged release, for amd64 and arm64.

Everything planned through Phase 7 (the parity plan the owner chose on 20
September 2026 from a survey of other collection tools) has shipped. Cabinet
is in use on its author's own collection, and what is left before 1.0
is checking and polish, not new capability.

## The road to v1.0.0

1.0 means the HTTP API is stable: the
[stability policy](api.md#stability-policy) says what that covers, and a
check in the test suite compares every build with the last release's
schema. Each item below is a patch or minor release of its own, and 1.0.0
is cut when the list is done.

Left, in order:

1. **"Add a run" confirmed against live Numista.** It was built and tested
   against recorded answers; it needs one run with a real key.
2. **The Numista banknote mapping confirmed against the live API** (size,
   printer, watermark, demonetization, added in v0.29.0). It was written
   without a key, so it reads every shape defensively and has never met a
   real answer.
3. **A README and quick-start pass**, read as a stranger installing for the
   first time, with the screenshots retaken. Last, so it describes the 1.0
   build.
4. **v1.0.0 itself**: the version, a changelog entry stating the stability
   promise, a release page, and the `1` and `1.0` image tags. No code
   change of its own.

Two questions are the owner's to send, and neither blocks 1.0: to Numista,
whether catalog facts may appear on a share link, and to PCGS, whether a
private collection is a use its API agreement covers. Until they are
answered Cabinet takes the careful reading of both
([data-sources.md](data-sources.md)).

Done on the way here:

| What | Release |
|---|---|
| PCGS cert fill, grade parsing, and pricing confirmed against the live API | v0.24.5, v0.24.6 |
| Sign-in: one admin, sessions, scoped API tokens, every route denied by default | v0.30.0 |
| An API consistency pass and a written stability policy | v0.30.0 |
| An upgrade test in CI, from the last release before sign-in | v0.30.0 |
| Single sign-on (OpenID Connect, GitHub, a gateway's signed assertion), validated live against three providers | v0.33.0 |
| A check that fails the build on a breaking API change, and the last input rules tightened | v0.38.0 |
| Four contract decisions: what an item embeds, what today's fields will mean, the wider promise, third-party terms | v0.39.0 |
| Images for arm64, build provenance, and an SBOM | v0.40.0 |
| A one-file install from the published images, tested in CI as the README says it | v0.41.0 |
| Upgrades from older releases tested with their own archives restored; the page says when it and the server are different releases | v0.42.0 |
| The first-run pass: a welcome state, a demo collection from one button, a form that keeps your work | v0.43.0 |
| Accessibility basics: dialogs that hold focus, announced errors, field outlines that can be seen, a title on every page, and an automated scan kept in the browser tests | v0.44.0 |

## After 1.0

Nothing here is scheduled. One is pulled when real use asks for it, and
friction found while entering a real collection outranks all of it.

**Candidates**

- **Phone entry**: a quick add made for a phone camera, and scanning a
  slab's barcode or QR code into the cert fill. Cabinet already installs as
  an app; nothing works offline.
- **Storage that knows where things are**: nested locations (safe, box,
  row), a "last verified" date, and printable 2×2 inserts and slab or box
  labels with a QR code back to the piece.
- **A trash for photos and documents.** Deleting either is for good today;
  pieces already have a trash with restore.
- **Saved views** and a choice of list columns; print or export any view.
- **Paperwork**: an insurance schedule with the insurer's own fields and a
  flag above the scheduling threshold, appraisal records, an estate packet,
  and variety references by scheme (FS, VAM, Overton) with links.
- **Portability**: Excel export with thumbnails, and an
  OpenNumismat-compatible export with its photos.
- **A user guide.** Today's documents are for the person running Cabinet
  and the person changing it, not for the person using it day to day.
- **Off-site backups** pushed to S3, WebDAV, or SFTP. A mounted path,
  including a NAS, covers this today without a new dependency.
- **Purchase-day spot prices before March 2024**, from an optional keyed
  source. The free lookup starts there; older purchases take a typed
  figure.
- **More accounts**: the admin adding editors and viewers, with single
  sign-on creating them. It would still be one shared collection; the
  permission table for it is already written in
  [security.md](security.md#accounts-and-permissions).

**Parked.** Real features for a collector this owner isn't, revisited only
if that changes:

- Statuses beyond owned, sold, and wish list (watching, bidding, ordered,
  for sale) with auction fields. The owner mostly holds.
- Tax lots, partial sales, and realized gains by year with a Form
  8949-style export. Nothing has been sold; cost basis with fees exists.
- Grading submissions (service, tier, fees, dates, old and new cert).
  Nothing is being submitted.

**Tabled.** A counter of calls made to Numista and PCGS against their
limits, with a cost preview before a run. Neither service reports usage, so
it could only count Cabinet's own calls; set aside on 20 September 2026
until real use shows quota pressure.

## Not planned, and why

- **Identifying or grading a coin from a photo.** It needs a hosted model
  or a paid API, and the ANA's review disputes the grading and pricing of
  the best-known app that does it.
- **Swap matching, a marketplace, rankings, feeds.** They need a community;
  Cabinet is one person's records.
- **Competitive registries with awards.** Checklists give the completion
  view without the competition.
- **Several collections, or separate collections per user.** Tags and sets
  divide one collection. More accounts, if they come, share it.
- **Cloud sync.** Backups go to a mount you choose.
- **A bundled price database sold as updates.** The sources Cabinet reads
  are free with your own key, and current.
- **A report designer.** Print styles, and saved views if they come, cover
  it.
- **Dealers, buyers, and loans as records of their own.** A text field for
  where a piece came from has been enough.
- **A second factor built into Cabinet.** Your identity provider's own
  multi-factor check is the second factor; the local password stays a
  recovery credential the container can always reset.
- **Running on the open internet.** Cabinet is for private networks,
  whatever sits in front of it; see
  [deployment.md](deployment.md#2-exposure-cabinet-is-for-private-networks).
- **Redis, object storage, a job queue.** One user doesn't need them: photos
  are files on a volume, and background work runs in the backend process.
- **A server-side PDF library.** Reports are print-ready pages; the
  browser's own Print to PDF does the rest.
- **LBMA prices.** Its series reaches back further than the free sources,
  and its terms need a license to use it for valuation.
- **Working offline.** A page cached in the browser is exactly what has to
  come fresh from the server.

## What shipped

Specifications, tests, and notes elsewhere in the repository refer to these
phases by name, so the names are kept. The detail is in the changelog.

| Phase | What | Release |
|---|---|---|
| 0 to 4 | Foundations, a usable catalog, the fields a whole collection needs, melt value and totals, the dashboard and reports | through v0.9.0 |
| 5 | Currency conversion, value over time, sets, custom fields, bulk edit, checklists, dark mode, edit history | through v0.9.0 |
| 6 | Open-source release: license, contributor docs, CI, a demo collection | v0.9.0 (public from v0.10.1, images from v0.10.2) |
| 5.5 M1 to M3 | Settings, the Numista and PCGS price sources, a value per source and a blended one, scheduled refresh | v0.10.0 |
| 5.5 M4 | Where each value came from, kept with it | v0.11.0 |
| 5.6 B1, B2 | Backups from inside the app, on a schedule | v0.12.0 |
| 5.5 M5 | Pricing reports: coverage, stale values, sources, accuracy | v0.13.0 |
| 5.7 C1 to C4 | Grading depth, physical and note fields, costs in the gain, cert lookup links | v0.14.0 |
| 5.7 C5 | Fill a piece from the Numista catalog | v0.15.0 |
| 5 | Photo tools: crop, straighten, zoom, drop, paste, URL, webcam | v0.16.0 |
| 3 | Comparable sales, logged by hand or from Numista | v0.17.0 |
| – | Import from Numista, OpenNumismat, and any spreadsheet | v0.18.0 |
| 5.8 | Documents attached to pieces | v0.19.0 |
| 5.8 | A trash with restore | v0.20.0 |
| 5.8 | Alerts, a heartbeat, and metrics | v0.21.0 |
| 5.9 | Hardening: a setup checklist, browser tests in CI, a Swarm stack file | v0.21.1 |
| 5.9 | Fill a piece from its PCGS cert number; duplicate warnings | v0.22.0 |
| 5.9 | Add a run; checklists generated and matched to what's owned | v0.23.0 |
| 5.9 | From the first weeks of real data entry: the look, the logo, money shown as money, PCGS fixes | v0.23.2 to v0.24.9 |
| 7 P1, P3 to P6 | PCGS population, wish-list targets, paper money depth, fancy serials, die axis and other calendars | v0.25.0 |
| 7 P2 (5.6 B3) | Restore from inside the app | v0.26.0 |
| 7 P10 | A customizable dashboard | v0.27.0 |
| 5.9 | Undated pieces; Numista varieties of one year | v0.27.1 |
| 7 P7 | Bullion stack figures and spot-price alerts | v0.28.0 |
| 5.9, 7 P10 | Note details, the item page regrouped, ten more dashboard widgets | v0.29.0 |
| 7 P8 A1 | Sign-in and encrypted backups ([SPEC_0300](specs/SPEC_0300.md)) | v0.30.0 |
| 7 P11 | Bars and rounds ([SPEC_0310](specs/SPEC_0310.md)) | v0.31.0 |
| 7 P9 | Share links ([SPEC_0320](specs/SPEC_0320.md)) | v0.32.0 |
| 7 P8 A2 | Single sign-on ([SPEC_0330](specs/SPEC_0330.md)) | v0.33.0 |
| 5.9 | The workbench layout: a sidebar, list and inspector, edit in place, quick add | v0.34.0 |
| 5.9 | Four color themes | v0.35.0 |
| 5.9 | Photos for the demo collection | v0.36.0 |
| 5.9 | Proof and mint sets ([SPEC_0370](specs/SPEC_0370.md)) | v0.37.0 |
| Road to 1.0 | Fixes from a full review, in two batches | v0.37.3, v0.37.5 |
| Road to 1.0 | See the table under "The road to v1.0.0" | v0.38.0 to v0.44.0 |

## How the order was decided

- **Friction from real use comes first.** The owner has been entering a
  real collection since 20 September 2026, and what that turned up has
  outranked every plan made before it.
- **Fields before data.** Adding a column is cheap before a collection is
  entered and tedious after, so the catalog's fields were filled out early.
- **The easiest honest price first.** Melt value is arithmetic, needs no
  agreement with anyone, and is the floor of most collections; sold-price
  comparables came last, because no sold-price API is open to individuals.
- **Sign-in before a public page, and before 1.0.** A share link is a
  deliberately open door, so everything else had to be closed first, and
  sign-in touches every route, so it had to land before the API was called
  stable.
- **Every schema change is a migration.** Alembic from the first commit,
  applied by the backend itself on startup since v0.11.1.
- **Outside services are kept at arm's length.** Keyless where possible,
  cached in the database, tolerant of a stale answer, and never sent
  anything about the collection.
