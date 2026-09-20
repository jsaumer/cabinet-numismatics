# Price Sources

Estimating the market value of coins and paper money is inherently imprecise:
value depends heavily on grade, eye appeal, variety, and current demand. This
document describes how the app produces estimates and the caveats involved.

## Approach

The backend has four automatic sources (`melt`, `numista`, `pcgs`, `comps`)
and manual entry. Each automatic source is an adapter chosen with
`POST /api/items/{id}/estimate?source=`; it reads the item (catalog
reference, grade, cert number, composition, or sales log, depending on the
source) and returns one estimate. Results are appended to the
`price_estimates` table with a timestamp and a confidence score, so value
history is retained over time. Upstream responses are cached in the
`source_cache` table (spot prices in `spot_prices`), so a repeat lookup
spends no request and a stale copy covers for a failed one. No source is
ever sent collection data: a lookup carries a catalogue or cert number and a
grade, nothing else.

Each estimate records:
- `source`: where the number came from
- `estimated_value` + `currency`
- `confidence`: 0.0–1.0, reflecting sample size and match quality
- `sample_size`: how many comparables informed the estimate
- `details`: provenance, so a value can be explained rather than just
  asserted (pricing program M4). Each automatic source records what produced
  its number, plus `data_as_of` (when the upstream data was actually
  fetched) and `stale` (true when a cached copy was served because a refresh
  failed):
  - **melt**: metal, weight, fineness and whether it came from the field or
    the composition text, quantity, the spot price per gram, its currency and
    source.
  - **numista**: type and matched issue (id, year, mint letter), the grade
    bucket wanted and the one actually priced, and the full per-grade price
    list.
  - **pcgs**: lookup (cert, or PCGS number + grade), basis (`apr`, `guide`,
    or `apr_old`), the auction lots behind the median (date, price, auctioneer,
    sale, lot URL), older or undated lots that were recorded but not
    counted (`older_lots`), the median, the price-guide value (recorded even
    when sales won), the CoinFacts link, and the population at this grade and
    higher.
  - **comps**: the median and its currency, the sales used (date, venue,
    grade, price as recorded and converted, link, manual or Numista), the
    spread, the grade bucket they were matched on, and whether sales older
    than the window were needed.

  The item page shows this under each value-history row. Rows recorded before
  it existed have no details.

## Sources

Melt, Numista, PCGS, and comps are implemented; the rest of this section
records what was researched and why it isn't. **Always review a source's ToS
before automating access: some prohibit scraping or require an API
agreement.**

### Melt value (implemented, the first automatic source)
For precious-metal items, `weight × fineness × spot price × quantity` gives a
deterministic floor value with no terms-of-service concerns. Implemented in
`app/services/pricing.py`: the metal is detected from the `composition` text
(gold/silver/platinum/palladium), fineness falls back to a percentage in the
composition ("90% silver" → 0.900), and spot prices come from gold-api.com
(free, keyless, USD/oz) cached in the `spot_prices` table for 12 hours. A
stale cached price is used if the upstream is down. Estimates record the spot
price used in their `source` (e.g. `melt:silver @ 1.0562/g`) and carry
confidence 0.95.

### Purchase-day spot for the bullion stack (implemented, v0.28.0, roadmap Phase 7 P7)
The bullion stack (see [api.md](api.md#bullion-stack)) also wants the metal's
spot price on the day a piece was *bought*, not just its current value, to
work out the premium paid over spot. This isn't a `price_estimates` source
(there's no adapter, no confidence, no `POST .../estimate`): it fills one
item field, `spot_at_purchase`.

Researched and rejected:

- **LBMA's public JSON price series** goes back to 1968, well past what
  anything else offers, but the LBMA/ICE Benchmark Administration terms say a
  licence is needed to use benchmark data, including for valuation. Cabinet
  does not use it, and it must not gain an LBMA adapter without one.
- **gold-api.com's `/history` endpoint** needs an API key (its free tier is
  rate-limited to ten requests an hour); only its current-price endpoint
  (already used for melt, above) is keyless.
- **Stooq** now serves a bot-detection challenge page instead of CSV.
- **Nasdaq Data Link and FRED** both need a free API key, which is one more
  credential to manage for a single field most purchases won't use.
- **datahub.io and the World Bank** publish monthly series only, too coarse
  for a specific purchase date.
- **Yahoo Finance's chart API** is unofficial and undocumented.

Implemented instead with the public-domain (CC0) **fawazahmed0 currency-api**
(`services/stack.py`, `historic_spot`), which has published daily
XAU/XAG/XPT/XPD rates since **2024-03-02**:

```
https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{YYYY-MM-DD}/v1/currencies/{xau|xag|xpt|xpd}.json
```

with a fallback host if the CDN is unreachable:

```
https://{YYYY-MM-DD}.currency-api.pages.dev/v1/currencies/{code}.json
```

Each response is `{"date": "...", "xau": {"usd": ..., "eur": ..., ...}}`:
units of the requested currency per one troy ounce, a cross-rate rather than
a benchmark fixing. Only a date and a metal code are sent, never collection
data. A past day's price never changes, so a fetched day is cached
(`source_cache`, source `spot_history`) for ten years; today or a future
date is refused (422: use the current spot price for today instead), so
nothing that could still change is ever cached. A purchase before
2024-03-02 needs a hand-typed figure; there is no free, keyless, cleanly
licensed source that reaches further back.

Confirmed against the live feed on 20 September 2026: silver on 2025-01-15
was USD 29.81/oz, gold on 2024-06-03 was EUR 2145.62/oz, and a 2020 date was
refused with 422.

### Numista (implemented, pricing program M2)
Numista catalogues coins, banknotes, and exonumia and quotes collector-swap
estimates per grade. Implemented in `app/services/numista.py`.

The chain an estimate follows:

1. The item's `numista` catalog reference gives the **type** id (`N#1234`,
   `N# 1234`, and a bare `1234` all parse).
2. `GET /types/{type}/issues` gives the type's issues. The pool is the ones
   matching the item's **year** (an ND item with no year pools Numista's own
   undated issues); if nothing pools and the type has exactly one issue,
   that issue stands in anyway (recorded as a year mismatch). The pool is
   then ranked, best first: a matching mint letter, then replacement
   agreement (does the issue look like a replacement note, the same way the
   item's own `replacement_note` flag does), then a match on the item's
   catalogue reference, variety, or signatures, then ND agreement, then
   Numista's own order. A type can list more than one issue for the same
   year, a replacement note beside the regular one being the case that
   prompted this: the ranking is what tells them apart.
3. `GET /types/{type}/issues/{issue}/prices` gives prices per grade bucket, in
   the app's display currency. The ranked issues are tried in turn, up to
   four, until one has a priced grade; an issue with no prices at all (a 404, or an empty list) costs one
   request and moves on to the next; one priced in another grade is used,
   with the nearest grade standing in as before.
4. The item's grade is mapped onto Numista's seven buckets by rank (Sheldon
   and PMG share the 1–70 scale, so one mapping serves coins and notes):
   `<8 → g`, `<12 → vg`, `<20 → f`, `<40 → vf`, `<50 → xf`, `<60 → au`,
   `≥60 → unc`.

The estimate's `details` record which issue was used (`issue_comment`,
`issue_reference`, `issue_nd`, `candidates_tried`, and `year_mismatch` when
the year had to be given up on), shown on the item page as "Priced as:
{reference}, {comment}".

If the exact bucket isn't priced, the nearest one is used: the lower of two
equally close buckets, so a substitution errs low. The estimate's `source`
always names the grade actually used (`numista:N#1234 XF (for UNC)`), and
confidence drops from 0.60 to 0.45 when a substitution happened. Prices are
per piece, so the value is multiplied by the item's quantity.

Numista's per-grade prices describe problem-free circulation strikes, so a
proof, a specimen, or an item with a details grade is refused (422) rather
than priced as something it isn't.

Requirements and limits:

- A free API key (numista.com), stored encrypted in Settings; the source is
  disabled until you switch it on.
- 2,000 requests a month, so every response is cached in `source_cache`:
  issues and prices for 7 days. The licence forbids storing its data (§8.1)
  apart from identifiers (§8.2), catalogue metadata for seven days (§8.3),
  and an individual's personal project (§8.4); §8.4 is what covers a
  self-hosted Cabinet, and it keeps §8.3's seven days for everything. It
  does not cover publishing the data or running a public service. A stale
  entry is used when the upstream fails. An item missing its prerequisites
  (no ref, no grade) costs no request at all.
- Confidence is medium by design: these are collector estimates, not realized
  auction prices. Melt remains the higher-confidence floor for bullion.
- **Scheduled refresh** (off by default): a cadence of every 7, 14, or 30
  days in Settings, alongside the same 12h loop that refreshes melt. Each
  estimate costs 2 calls (issues + prices), so Settings shows the real
  projected monthly count for your collection's priceable-item count against
  the 2,000/month quota. Weekly refresh only stays under budget for roughly
  the first ~230 priceable items. Refresh keeps Numista's own data current
  independent of whichever source currently wins an item's overall-latest
  estimate, since `value_strategy` (see [api.md](api.md)) may prefer or
  average a source that isn't "latest" right now.

A missing prerequisite answers 422 with what to fix; an upstream failure or an
exhausted quota answers 502.

**Catalogue lookup.** The same key also fills items in: the item form looks a
type up by Numista number or name search (`GET /types/{id}` and
`GET /types?q=`) and pre-fills identity, composition, and physical fields,
catalogue references, and the issue list with mintages. It needs only the
key, not the pricing toggle, and spends from the same quota: one request per
search or type, cached 7 days; a type's issues are the same cache entry the
estimates use, so pricing an item you just filled in costs one request fewer.

### PCGS (implemented, pricing program M3)
PCGS CoinFacts returns a price-guide value *and* a list of auction sales in one
response, so a single request yields both numbers. Implemented in
`app/services/pcgs.py`.

Lookup is by **cert number** when the item has one and `cert_service` is PCGS
(that identifies the individual slab) and otherwise by **PCGS number + grade**
from a `pcgs` catalog reference (`GET /coindetail/GetCoinFactsByCertNo/{cert}`
or `GET /coindetail/GetCoinFactsByGrade`). PCGS grade numbers *are* Sheldon
numbers, so the grade's rank passes straight through; an item graded on the PMG
scale is refused rather than mistranslated. A plus grade is sent as
`PlusGrade=true`. PCGS numbers are strike-specific (a proof has its own),
so the `pcgs` reference must be the proof's number for a proof; the grade
number is the same, and the source reads `PR-65`. A details-graded coin is
priced only by its cert number, since a grade lookup would return the
problem-free value.

The same cert response fills an item in (`GET /api/pcgs/cert/{cert}`,
`pcgs.cert_facts`): identity, physical fields, the grade parsed from PCGS's
`Grade`/`Designation` strings (`pcgs.parse_grade`: `MS64+`, `PR-65 DCAM`,
`AU58` + `FB`), and the PCGS number as a `pcgs` reference; denominations
are translated from label form (`25C` → `25 cents`). Two answers are
brought into line with hand entry, because filters, checklists, and the
duplicate check match text as written: the country is written "United
States" however PCGS spells it, and PCGS's "P" mint mark is kept only where
the coin carries it (wartime nickels, the 1979 dollar, everything but the
cent from 1980, and the 2017 cent). The fill also reports the population and
the guide value, and costs nothing extra when an estimate follows: both read
the same cached response.

From v0.25.0 the population is kept with the item (`pcgs_population`,
`pcgs_pop_higher`) and shown beside the grade: the fill carries both figures
into the form, and every PCGS estimate, scheduled ones included, rewrites
them from the response it priced from, at no extra request, dated by when
that response was fetched (so figures served from the 7-day cache carry the
cache's date, not today's). A response without a population leaves the
item's figures as they were. They can also be typed in by hand, for a coin
looked up on PCGS's site.

Realized auction prices win when PCGS has recent ones: the median of up to the
ten most recent lots from the last five years, at confidence 0.85 with five or
more sales, 0.75 with three or four, and 0.65 with one or two, with
`sample_size` recording how many informed it. Older and undated lots are kept
in the estimate's details (`older_lots`) but not counted: the first real cert
looked up returned a single 2003 sale at $43,700 against a $160,000 guide
value. With no recent sales, the price-guide value is used at confidence 0.60;
with no guide value either, the median of the old lots at 0.35
(`pcgs:apr-old`). The live API dates a lot by month (`07-2003`), read as
the first of that month. The estimate's `source` says which
(`pcgs:apr cert 12345678`, `pcgs:guide #5960 MS-65`). Values are USD, per
piece, multiplied by the item's quantity.

**Coins only.** PCGS Banknote has its own endpoints, but their responses carry
no price fields, so there is nothing for notes to read.

Requirements and limits:

- An access token (pcgs.com/publicapi, OAuth against your PCGS login), stored
  encrypted in Settings; the source is disabled until you switch it on.
- 100 calls a day by default (PCGS's documentation said 1,000 until it was
  cut; a larger limit is available by emailing apis@pcgs.com); responses are
  cached in `source_cache` for 7 days. PCGS documents no usage endpoint, no
  quota headers, and no reset time.
- PCGS signals failure in the body, not the status: `IsValidRequest: false`
  means the request values were malformed, and `"No data found"` means no such
  coin. Both surface as 422 with the reason. A 401, or a 500 (which usually
  means the token has expired), surfaces as 502 saying so and raises the
  PCGS token alert; a 429 raises the quota alert
  (see [monitoring.md](monitoring.md)).
- **Scheduled refresh** (off by default): a simple weekly on/off toggle in
  Settings, no cadence choice needed. One call per estimate: with more
  than about 100 priceable items a refresh reaches the default daily limit,
  stops there, and raises the quota alert, and Settings says so.

### Checking a source against the live API

Unit tests use canned responses, so they prove the parsing but not the
contract. `backend/scripts/check_sources.py` covers the other half: it runs one
adapter for one item and prints the upstream calls, the raw payload, and the
estimate parsed out of it, without writing anything to `price_estimates`.

```bash
docker compose exec backend python scripts/check_sources.py --list
docker compose exec backend python scripts/check_sources.py -s numista -i <item-id> --fresh
docker compose exec backend python scripts/check_sources.py -s pcgs -i <cert-number>
docker compose exec backend python scripts/check_sources.py -s numista-sales -i <item-id>
```

`--list` shows which items carry a handle a source could use (a `numista` or
`pcgs` reference, or a PCGS cert). `-s` takes `melt`, `numista`, `pcgs`,
`comps`, or `numista-sales`, which fetches the item's Numista auction sales
without adding them to its sales log (billed per uncached request on the
paid plan). `-i` takes an item id or, failing that, the cert number of an
item already in the collection. `--fresh` ignores the cache TTL to force a
real request (and so spends quota); without it a cached response is reused,
shown as such, and the run is free. `--full` prints untrimmed payloads.
Credentials come from Settings and are never printed. A lookup that reaches
the upstream still updates `source_cache` and the source's key and quota
alerts, as any lookup does.

### Sold-listing comparables (implemented, v0.17.0)
Sold prices are the closest thing to real market value, and almost nobody
will hand them to a self-hosted app. Research in September 2026 found:

- **eBay**: sold data is only in the Marketplace Insights API, closed to new
  applicants (2025–26 applications are refused); the Finding API's
  `findCompletedItems` was decommissioned in February 2025; the open Browse
  API returns asking prices on active listings only, and eBay's API licence
  forbids using its content to model prices. Scraping is against the user
  agreement.
- **Auction houses and aggregators** (Heritage, GreatCollections, Stack's
  Bowers, Spink, CoinArchives, acsearch, WorthPoint): no public API or data
  licence for individuals, and their terms forbid automated collection.
  Their archives are free or cheap to *read*.
- **Price guides with APIs**: Greysheet/CDN needs a dealer subscription plus
  $95–287 a month and is wholesale guide data, not sales; PriceCharting
  derives values from eBay sales of US coins for $49 a month. Neither is
  planned. NGC, PMG, and Colnect offer no usable price API.
- **Numista** records past auction sales per type and issue
  (`GET /types/{id}/sales_records`), but only on its paid API plan (€0.01 a
  request, after a €100 activation fee and a €100 monthly minimum); a free
  key gets 403 "Permission denied".

So the source is a **sales log per item**, filled by hand from those
archives, with Numista's sales as an optional paid feed into the same log.
Implemented in `app/services/comps.py`:

- A sale counts when it's included and, if its grade bucket is known, matches
  the item's (hand-logged sales carry no bucket: choosing them was the
  match).
- Recent sales win: the last three years, falling back to every sale when
  fewer than three are that recent; at most twenty, newest first.
- Each sale's price plus any fees on top is converted into the display
  currency at the cached daily rate (today's rate, not the sale day's);
  sales that can't convert are left out and counted.
- The estimate is the median × quantity. Confidence: 0.30 for one sale,
  0.40 for two, 0.50 for three or four, 0.60 for five to nine, 0.70 for ten or
  more; less 0.08 when the median absolute deviation exceeds 25% of the
  median and 0.15 above 50%; less 0.05 with no item grade; less 0.10 when
  older sales were needed; kept between 0.15 and 0.80.
- Numista's sales (`numista.fetch_sales`, `POST
  /api/items/{id}/comparables/numista`) sit behind `numista_sales_enabled`,
  off by default, and run only on request, never on the refresh schedule,
  since each one is billed. A same-day repeat comes from `source_cache`
  (one-day TTL); known lots are skipped by URL. Pictures are not kept (they
  carry the auction houses' copyright), and Numista is shown as the source.

### Price-guide references
Published guides (annual catalogs and grading-service price guides) give
book values by grade. These are stable references but can lag the live market
and may not be available via API, so some may require manual entry of values.

### Manual / user-provided
The app should always allow manually recording a value the user researched
themselves: their own comps, a dealer quote, or an auction result. Manual
entries are first-class `price_estimates` rows with `source = "manual"` and a
confidence the user sets (optional: omitted confidence is stored as null).
An optional note (up to 500 characters: the lot, the dealer, raw or slabbed)
is kept in `details` and shown the same way as an automatic source's
provenance.

## Confidence scoring

A simple, transparent heuristic works better than false precision:

- Larger sample of recent, well-matched comparables → higher confidence.
- Exact catalog + grade match → higher confidence than an approximate match.
- Book-value-only or single-data-point sources → lower confidence.
- Manual entries carry whatever confidence the user assigns.

## Caveats

- Estimates are **guidance, not appraisals.** For insurance or sale, get a
  professional appraisal or grading-service valuation.
- Grade dominates value; an estimate is only as good as the grade it assumes.
- Thin markets (scarce items) may have too few comparables for a meaningful
  estimate, so surface low confidence rather than a misleadingly precise number.
- Cached estimates age; the `fetched_at` timestamp shows how stale a value is.

## Implementation notes

- Each source is one adapter, `(db, item) -> EstimateResult`, registered in
  `pricing.get_adapter` (names in `pricing.ADAPTER_NAMES`) and raising
  `NotApplicable` (422) or `SourceUnavailable` (502), so sources can be added
  or disabled independently.
- Cache upstream calls through `pricing.cached_fetch` and respect each
  source's limits: a fresh entry spends no request, and a stale one beats a
  failed fetch. `KeyRejected` and `QuotaExhausted` (kinds of
  `SourceUnavailable`) raise alerts and stop a scheduled refresh at the
  first one.
- Store raw comparables (or a summary) alongside the estimate where possible so
  a value can be explained, not just asserted (done as `details`, above).
  Adapters build it as JSON-safe values (floats, strings, ISO dates; never
  `Decimal`), and every row goes through `pricing.estimate_row` so the
  on-demand and scheduled paths can't drift apart.

## Pricing reports

The Pricing page (`/api/pricing/*`, see [api.md](api.md#pricing-reports))
reports on estimate quality rather than producing estimates: coverage, stale
estimates, a per-source breakdown, and accuracy against realized sale prices.

Two pieces of the adapter contract exist for it:

- **Prerequisites.** Each source's local checks (credentials, catalog ref,
  grade, weight and fineness, coin vs note) are a `prerequisite(db, item)`
  function returning the reason or `None`. The adapter runs it first and
  raises `NotApplicable` with that reason; the coverage report runs it
  directly, so explaining a gap never spends a request. New adapters should
  follow the same split: anything decidable without the network goes in the
  prerequisite.
- **Attempts.** `pricing.run_adapter` wraps every automatic estimate, item
  page and scheduled refresh alike, and records the outcome per item and
  source in `estimate_attempts`: `ok`, `not_applicable` (with what the source
  said, e.g. "Numista lists no 1955 issue"), or `unavailable` (the fetch
  error). Only the latest attempt is kept.

Accuracy compares the estimates that stood on the sale date (recorded on or
before `sold_date`) with the sold price, so an estimate added after marking
an item sold never counts as a prediction.
