# Features

Everything Cabinet does, in detail. The [README](../README.md) has the short
version; this page is the long one, followed by
[how Cabinet compares](#how-cabinet-compares) with the tools collectors
most often use instead.

- [Cataloging](#cataloging)
- [Photos](#photos)
- [Valuation](#valuation)
- [Insights & reporting](#insights--reporting)
- [Platform](#platform)
- [How Cabinet compares](#how-cabinet-compares)

## Cataloging
- Coins and notes with full numismatic detail: country, denomination, year
  (or ND, with an optional attributed year, for an undated piece), mint
  mark, series, variety/sub-type, strike (business, proof, specimen),
  composition, weight, fineness, diameter, thickness, edge, shape, die axis,
  mintage, quantity, and free-text notes (banknotes add serial number,
  prefix/block, signatures, issuer, and replacement notes), plus up to 20
  custom fields per item.
- **Bars and rounds**: a third item type alongside coins and notes, with no
  year required. A Metal select (gold, silver, platinum, palladium) fills
  the composition and defaults the fineness to .999; weight can be entered
  in grams or troy ounces; the product name is suggested from weight,
  metal, and shape until you type your own. Filled in from Numista's
  bullion catalog too.
- **Proof and mint sets**: a fourth item type for a set as the mint issued
  it (proof, uncirculated, or specimen), kept as one piece: the issuing
  mint, the year, a set name suggested from its kind and metal, how many
  pieces it holds, and its packaging (sealed, complete, or incomplete, with
  or without the box and certificate). The silver or gold in it gives it a
  melt value, and it counts in the bullion stack only if you tick it. Enter
  a set either as one set or as its coins, never both, or its coins count
  twice.
- **Dates as struck**: a coin dated in another calendar (Islamic, Persian,
  Thai Buddhist, Hebrew, Japanese eras, Vikram Samvat, Saka, Minguo, Chula
  Sakarat, Rattanakosin, Ethiopian) keeps the year as written, and the
  Gregorian year is worked out for you unless you type one.
- **Paper money depth**: National Bank Note charter number, bank city and
  state, and plate position; Pick and Friedberg catalog references with a
  web-search link; and fancy serial numbers (solid, ladder, radar, repeater,
  binary, low and high numbers, dates, star notes, and more) badged on the
  item and in the list, with a filter for any of them.
- **Note details**: width and height for anything not round (coins keep
  diameter), printer, watermark, and a demonetization date for coins and
  notes alike, filled in from Numista along with everything else.
- **Grading** on seeded Sheldon (coins) and PMG (notes) scales, with proof
  and specimen strikes, plus grades, stars, designations (CAM/DCAM, PL/DMPL,
  RD/RB/BN, EPQ…), CAC stickers, and details grades, shown the way the holder
  reads, e.g. `PR-69 DCAM ★`. Certification tracking (service + cert number)
  links to the grading service's verification. A PCGS coin keeps its
  population (graded at this grade, and higher) with the date it was read.
- **Provenance & location**: acquisition date, price and fees, source
  (dealer, show, auction, inheritance), and storage location (album, slab
  box, safe).
- **Lifecycle**: `owned` / `sold` / `wishlist` status with sold date and
  realized price; sets/lots for pieces held or sold together; catalog
  references (Krause, Numista, Red Book…); free-form tags.
- **Wish list**: a target price and a priority per piece, the gap between
  the newest estimate and the target, a "target reached" filter, and one
  webhook message when an estimate first reaches the target.
- **Working at scale**: search across notes/series/variety/certs/refs/tags,
  combined filters (type, status, country, year ranges, grade ranges,
  latest-value ranges, tag, set, fancy serials, targets reached), sortable
  columns, clone-item, bulk edit, per-item edit history, and completeness
  checklists for target sets (e.g. a date/mint run), written by hand or
  generated, with progress tracking.
- List filters and paging persist in the URL, so back-navigation keeps your
  place.
- **A workbench layout**: a sidebar holds every way into the collection
  (owned, wish list, sold, the trash), each checklist with its progress, and
  the insights pages, with the dashboard (the home page) first; the header
  has a search box (`/` to focus it) and Add piece. The Piece, Grade, and
  Value headings sort the list either way. On a wide screen the collection
  is a compact list with the selected piece open beside it, its sections
  behind Overview, Value, Photos and files, and History tabs, and the
  keyboard moves through it (J and K, Enter to open the full page, E to
  edit, N for a new piece, Esc to close).
- **Edit in place**: on the item page and beside the list, a fact (grade,
  series, mint mark, weight, fineness, paid, storage, and two dozen more)
  turns into a field on click; Enter or leaving it saves, Esc puts it back.
- **Quick add**: Add piece opens one lookup box that takes a name (a Numista
  search), a Numista number, or a PCGS cert number, fills the piece from it,
  offers the type's issues (owned ones struck through), and then asks only
  for what's yours: grade, price, quantity, date, seller, storage, tags.
  "Save and add another" keeps the date, seller, storage, and tags for the
  next piece and lists what was added this visit; the full form is a link
  away.
- **The item page leads with the piece**: a large primary photo beside the
  title, grade, certification, and value, then the rest of what's known
  grouped into titled facts (identity, grade and certification, physical,
  acquisition) that only show fields with something in them, with a
  "Show empty fields" toggle for the full sheet.
- **Fill from Numista**: enter a Numista number or search by name, and the
  item form fills in country, denomination, composition, fineness, weight,
  dimensions, catalog references, and the issue's year, mint, and mintage.
  Needs a free Numista API key in Settings.
- **Fill from a PCGS cert number**: a slabbed coin's type, date, mint,
  denomination, grade, designations, variety, PCGS number, and population
  come from the cert lookup (needs a free PCGS API token). Only empty fields
  are filled.
- **Duplicate warning** while entering anything already here: by cert,
  catalog reference, or country, denomination, year, and mint. The trash
  is checked too, and the importer notes lookalikes in its preview.
- **Add a run**: pick a type on Numista, tick the dates and mints you have,
  and get one item each, with the shared fields typed once. Issues you
  already own are marked and skipped.
- **Generated checklists**: slots come from a Numista type's issues or a
  year and mint range, and fill themselves from the owned items that match,
  with a completion percentage and a "needed to complete" list. A slot can
  still be ticked by hand.

## Photos
- Multiple photos per item with angle designation (obverse/reverse/edge/
  other), a primary image, and reordering.
- Uploads are validated as real JPEG/PNG/WebP images, EXIF orientation is
  corrected, and thumbnails are generated automatically. Every stored photo
  is re-encoded with its EXIF, XMP, and IPTC metadata stripped (the color
  profile is kept), so nothing but the image itself, no camera, location,
  or timestamp data, ever leaves the app, shared or not. Files live on a
  plain Docker volume served directly by nginx, with no object store.
- Add photos by file picker, drag and drop, pasting an image, a URL, or a
  webcam or phone camera; view them full size in a zoomable lightbox; and
  crop, turn, or straighten them in the browser.
- Attach documents, such as receipts, invoices, certificates of
  authenticity, and grading labels (PDF or image), with a first-page
  thumbnail; share one lot's invoice across every coin in it. Kept off the
  public photo path and included in backups.

## Valuation
- **Manual estimates**: record researched values (dealer quote, auction
  result, price guide) with source and optional confidence, kept as
  append-only history, never overwritten (a value typed in by mistake can be
  deleted; what a source said is kept).
- **Pluggable price sources**: melt value (spot price × weight × fineness ×
  quantity, keyless; metal detection skips named alloys like nickel silver
  and surface coatings like plating, and fineness parsing reads the
  percentage attached to the detected metal), Numista (coins, notes, and
  bars/rounds, priced by catalog ref + grade), and PCGS (US coins, by cert
  number or catalog ref + grade, preferring auction prices realized in the
  last five years over the price guide; the same answer keeps the coin's
  population current). One-click and scheduled refresh for all three, with
  Numista and PCGS off by default, Numista's cadence (7/14/30 days) shown
  against its 2,000/month quota, and PCGS weekly within its 100 calls a day.
- **Sold comparables**: log what pieces like yours actually sold for (eBay
  sold listings, auction archives, dealer sales) and get a comps estimate:
  the median of recent sales in your currency, with confidence from how many
  there are and how much they agree. Numista's auction records can fill the
  log at a click, with any Numista key (each fetch spends a request).
- **Value differentiation**: the item page shows every configured source's
  own latest value side by side (never blended), each with a "time since"
  label. A `value_strategy` setting picks the single blended number shown
  in the items list, export, and dashboard totals: latest estimate,
  a preferred source, or an average, with a `SOURCE` column on the list
  showing which one produced it.
- **Multi-currency**: totals are shown in one display currency; other
  currencies convert at cached daily ECB rates, and anything unconvertible
  is excluded and counted, never silently mixed.
- **Value over time**: month-end collection value and per-item estimate
  charts.
- **Pricing reports**: a Pricing page showing which items lack estimates and
  why (source off, missing catalog ref or grade, what the source said, a
  failed fetch), which estimates are stale, how the sources compare and
  disagree, and how estimates held up against actual sale prices.
- **Bullion stack**: a Stack page with fine troy ounces, melt value, cost per
  ounce (also the break-even spot price), gain or loss, and the premium paid
  over spot at purchase, by metal and per item, scopeable by tag, listing
  what it leaves out and why (no weight, no fineness); a proof or mint set
  counts only when ticked. Purchase-day spot is
  looked up automatically for purchases from 2 March 2024 and can be typed
  in for older ones; spot-price threshold alerts fire through the existing
  webhook.

## Insights & reporting
- Customizable dashboard (the home page): 32 widgets (value, breakdowns by
  country/decade/grade/tag/metal or one tag/set, acquisitions by year,
  top-movers tables, owned notes by series and signature pair, wish list,
  fancy serials, checklists, the bullion stack, pricing coverage, operations
  status, and a "group C" of showcase widgets: most valuable, piece of the
  day, oldest and newest pieces, on this day, a photo mosaic, certified
  share, value spread, population highlights, and data health) added,
  removed, resized, retitled, and arranged by drag or keyboard, saved on the
  server so it follows the collection; the default layout is today's fixed
  page (the group C widgets are opt-in), and a setup checklist widget says
  what is still off (scheduled backups, the alert webhook, a price-source
  key).
- Export to CSV or Excel; CSV import round-trips the export format (including
  grades, tags, refs, sets, and custom fields) with per-row error reporting.
- Deleting is recoverable: items go to a trash with their photos, documents,
  values, and history, and restore exactly as they were; the trash empties
  itself after 30 days (adjustable).
- Import from other tools, with a preview first: your Numista collection
  (straight from your account), Numista's export file, OpenNumismat
  collections with their photos, or any spreadsheet with its columns matched
  to Cabinet's fields. The sets in Numista's export come in as one proof or
  mint set each, with their coins listed in the notes, or as their coins if
  you choose. Re-importing skips what's already here.
- Printable insurance report with photos, certs, provenance, and totals,
  exported to PDF via the browser's print dialog.

## Platform
- Three-container Compose stack, also published as versioned images on GHCR
  with a [Swarm stack file](../deploy/docker-stack.yaml); an OpenAPI schema at
  `/api/openapi.json`. The backend applies its own migrations on startup.
- Responsive UI for phone/tablet, **dark by default** with a light theme on
  the header toggle, and **four color themes** (Bronze, the default;
  Silver; Album; Ledger) chosen in Settings → General, saved on the server
  so the choice follows you to every device, the logo and the browser-tab
  icon with it. Each was checked for WCAG AA contrast in light and dark. System fonts and inline SVG icons only: the
  page loads nothing from outside the app.
- **Backups from the app**: download the collection as one encrypted,
  tamper-evident archive (database + photos + documents + manifest, `.zip.age`,
  encrypted with a backup key you keep a copy of) from Settings, or schedule
  daily or weekly archives with retention by age (7 days to a year, or
  forever) into a directory you can point at a NAS, and delete any archive
  from the same page. Nothing unencrypted ever lands there.
- **Restore from the app**: pick a stored archive or upload one in
  Settings. It is decrypted in private staging, its MAC checked, compared
  with what is there now (an older archive needs `RESTORE OLDER`), and restored
  only after an automatic safety backup and a typed confirmation; a failure
  before the database is replaced changes nothing. `RESTORE_ENABLED=false`
  switches it off. `scripts/restore.sh` remains for when the app won't
  start, and CI rehearses both routes on every push (see
  [docs/backup-restore.md](backup-restore.md)).
- **Configurable pricing**: a Settings page for display currency, the
  blended-value strategy, per-source refresh cadence, and price-source
  credentials, stored **encrypted at rest** and never readable back
  through the API (see [docs/security.md](security.md)).
- **Alerts and metrics**: a webhook (n8n, ntfy, Discord, Slack, Gotify) when
  a backup fails, a price source rejects its key or runs out of quota, or a
  refresh fails, and when it recovers, and when a wish-list target is
  reached; an Uptime Kuma heartbeat;
  Prometheus metrics; and a recipe for a [Homepage](https://gethomepage.dev)
  tile. See [docs/monitoring.md](monitoring.md).
- **Sign-in**: one admin, claimed with a one-time setup code on first start,
  database-backed sessions, and scoped API tokens (`read`, `write`,
  `metrics`) for scripts and dashboards. Every route is denied by default;
  sensitive actions (backups, exports, restore, settings, tokens) ask for
  the password again. Photos go through the same check as the API. No
  interactive API docs page; the OpenAPI schema stays at
  `/api/openapi.json` for a signed-in session. See
  [docs/security.md](security.md).
- **Single sign-on**: sign in as the same admin through an OpenID Connect
  provider (Authentik, Keycloak, Authelia, Entra ID, Google, and more), a
  GitHub button, or a gateway's signed assertion (a trusted-header mode for
  Authentik, Cloudflare Access, Pomerium, or Google IAP), one button per
  configured provider. The identity provider's own multi-factor check is
  the second factor; the local password stays as a one-factor recovery
  credential the container can always reset. See
  [docs/deployment.md](deployment.md) for provider setup and
  [docs/security.md](security.md) for the model.
- **Share and showcase view**: a read-only link to the collection, a set, or
  a checklist, opened without signing in. Off by default; while off, no
  link can be made and every link answers not found. Each link chooses what
  it shows (photos, grades, tags, notes, the estimated value, and the cert
  number, each its own toggle); never a cost, gain, storage location,
  document, serial number, or custom field. Shared photos carry no
  metadata, the same as every stored photo. The token is shown once and
  stored only as its hash, with a Regenerate for a lost link and a Revoke
  that kills it at once. See [docs/security.md](security.md).
- **Hardened by default**: the backend container drops to an unprivileged
  user (`PUID`/`PGID`), the image installs a hash-pinned lockfile, nginx
  sets a Content-Security-Policy and the usual security headers, and a
  security workflow runs pip-audit, npm audit, and Trivy image scans on
  every change and weekly.

## How Cabinet compares

Three tools cover most of what collectors use to keep a collection on a
computer: OpenNumismat (the open-source desktop program), CoinManage (a
commercial one, sold since 1997), and Numista (the online catalog and
collector community). The table was checked in November 2026 against each
product's own pages, listed under it. If something here is out of date or
unfair, please [open an issue](https://github.com/jsaumer/cabinet-numismatics/issues).

| | Cabinet | OpenNumismat | CoinManage | Numista |
|---|---|---|---|---|
| **What it is** | A web app you host yourself | An open-source desktop program | A commercial desktop program | An online catalog and collector community |
| **Price** | Free (MIT) | Free (GPL-3.0) | $39.95 to $59.95, with optional paid yearly upgrades | Free |
| **Runs on** | A Docker host (amd64), used from any browser | Windows, macOS, Linux | Windows 10 or 11; a separate, smaller Mac app | Any browser |
| **Where your collection lives** | On your own server | In a file on your computer | In a file on your PC, with the vendor's cloud storage as a backup option | On Numista's servers |
| **From a phone** | Yes, in the browser | To view only, through its web viewer; the Android companion is archived | No | Yes, in the browser |
| **What it catalogs** | Coins, paper money, bars and rounds, and proof or mint sets, each as its own type | Coins, with 80+ customizable fields | Coins; paper money is a separate product (CurrencyManage) | Coins, banknotes, and exonumia |
| **Catalog data** | Filled in from Numista and PCGS with your own free API keys; nothing bundled | Imported from Numista and Colnect with your own keys; nothing bundled | Built in: every US coin from 1793, with Canada and UK editions | Its own catalog, the reason most people use it |
| **Values** | Melt, Numista, PCGS, comparable sales, and your own, side by side, each with its source and history | Values you enter, and precious-metal prices | A bundled value guide updated once a year, bullion from spot, and an eBay sold-price search | Numista's own estimates by grade |
| **Adding a slabbed coin** | Type its PCGS cert number | Scan the holder's barcode with a webcam | Scan a PCGS barcode or type the cert number | Not offered |
| **Wants and gaps** | A wish list with target prices and alerts; checklists that fill themselves from what you own | Wish and selling lists | A "Needed to Complete" list per type | A wish list by type, matched against other members' swap lists |
| **Export and reports** | CSV and Excel, an insurance report, and a full encrypted archive with photos and documents | Excel (with thumbnails), HTML, and CSV; reports as HTML, PDF, or Word | PDF, Excel, CSV, and HTML; a report and label designer | Excel |
| **Server and API** | Sign-in, optional single sign-on, and a REST API with scoped tokens | Desktop only; a remote database is a long-standing request | Desktop only, one user at a time | Hosted, with a public API (free up to 2,000 requests a month) |
| **Community** | None: it is private, with read-only share links when you want them | None | None | Swapping with ratings, and a forum |

### Where the others are ahead

- **A catalog and values in the box.** CoinManage, and the other
  commercial Windows programs like it (EzCoin, Coin Elite, Collector's
  Assistant), ship a US type catalog with values. Cabinet bundles neither; it looks pieces up through your own Numista and PCGS
  keys.
- **Scanning a holder.** OpenNumismat and CoinManage read a slab's barcode
  with a camera, and the PCGS and NGC apps add a coin by barcode (PCGS also
  by tapping the holder's NFC chip). In Cabinet you type the cert number.
- **Labels.** CoinManage prints labels of any size, with images or
  barcodes. Cabinet prints an insurance report and nothing for a flip or a
  box.
- **Languages.** OpenNumismat's interface comes in 17 languages. Cabinet is
  English only.
- **Moving in from other tools.** OpenNumismat imports from eight other
  programs and sites. Cabinet imports from Numista, OpenNumismat, and any
  spreadsheet.
- **Other collectors.** Numista matches your duplicates against what other
  members want. The PCGS and NGC registries rank graded sets against other
  collectors' and give awards. Cabinet has no community and isn't trying to
  have one.

### Where Cabinet stands apart

- **A value you can explain.** Every estimate keeps where it came from and
  what went into it, every source is shown beside the others, and the
  history is charted. The Pricing page says which pieces have no value and
  why.
- **Paper money, bullion, and sets as first-class pieces.** Fancy serial
  numbers spotted for you, National Bank Note fields, a bullion stack with
  premium over spot, and a proof or mint set kept as the one thing it is.
- **The paperwork with the piece.** Receipts, invoices, and certificates
  attached to one coin or shared across a lot, and carried in every backup.
- **Backups you can trust.** Encrypted, checked against tampering,
  scheduled, and restored from inside the app after an automatic safety
  backup. CI rehearses a restore on every change.
- **Yours, on your own server.** Sign-in with optional single sign-on, an
  API for your own scripts, alerts when something fails, and no company
  whose pricing or shutdown decides what happens to your records.

Cabinet does not identify or grade a coin from a photo. The apps that do
are useful for naming a common coin; the ANA's and CoinWeek's reviews
found their grades and values unreliable.

Sources, read in November 2026:
OpenNumismat's [home page](https://opennumismat.github.io/open-numismat/),
[release history](https://opennumismat.github.io/open-numismat/history.html),
and [issue 73](https://github.com/OpenNumismat/open-numismat/issues/73);
Liberty Street's [CoinManage page](https://www.libertystreet.com/Coin-Collecting-Software.htm),
[prices](https://www.libertystreet.com/coinmanage_purchasing_options.htm),
and [FAQ](https://www.libertystreet.com/CoinManage_FAQ.htm);
[Numista](https://en.numista.com/) and its
[API plans](https://en.numista.com/api/pricing.php);
the [PCGS apps](https://www.pcgs.com/apps) and the
[NGC Registry](https://www.ngccoin.com/Registry);
the ANA's [review of CoinSnap](https://readingroom.money.org/mind-the-app-coinsnaps-pros-cons/)
and [CoinWeek's test](https://coinweek.com/ai-collecting-app-identify-grade-coins/).
