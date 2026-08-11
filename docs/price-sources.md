# Price Sources

Estimating the market value of coins and paper money is inherently imprecise:
value depends heavily on grade, eye appeal, variety, and current demand. This
document describes how the app produces estimates and the caveats involved.

## Approach

The backend produces estimates keyed by an item's catalog reference and grade.
Results are appended to the `price_estimates` table with a timestamp and a
confidence score, so value history is retained over time. Recent lookups can be
cached in a small database table to avoid repeated upstream requests.

Each estimate records:
- `source` — where the number came from
- `estimated_value` + `currency`
- `confidence` — 0.0–1.0, reflecting sample size and match quality
- `sample_size` — how many comparables informed the estimate

## Candidate sources

The following are options; which to enable depends on their current terms of
service and API availability. **Always review each source's ToS before
automating access — some prohibit scraping or require an API agreement.**

### Melt value (implemented — the first automatic source)
For precious-metal items, `weight × fineness × spot price × quantity` gives a
deterministic floor value with no terms-of-service concerns. Implemented in
`app/services/pricing.py`: the metal is detected from the `composition` text
(gold/silver/platinum/palladium), fineness falls back to a percentage in the
composition ("90% silver" → 0.900), and spot prices come from gold-api.com
(free, keyless, USD/oz) cached in the `spot_prices` table for 12 hours — a
stale cached price is used if the upstream is down. Estimates record the spot
price used in their `source` (e.g. `melt:silver @ 1.0562/g`) and carry
confidence 0.95.

### Numista (implemented — pricing program M2)
Numista catalogues coins, banknotes, and exonumia and quotes collector-swap
estimates per grade. Implemented in `app/services/numista.py`.

The chain an estimate follows:

1. The item's `numista` catalog reference gives the **type** id (`N#1234`,
   `N# 1234`, and a bare `1234` all parse).
2. `GET /types/{type}/issues` gives the type's issues; the one matching the
   item's **year** is chosen, preferring a matching mint letter when the item
   has a mint mark.
3. `GET /types/{type}/issues/{issue}/prices` gives prices per grade bucket, in
   the app's display currency.
4. The item's grade is mapped onto Numista's seven buckets by rank — Sheldon
   and PMG share the 1–70 scale, so one mapping serves coins and notes:
   `<8 → g`, `<12 → vg`, `<20 → f`, `<40 → vf`, `<50 → xf`, `<60 → au`,
   `≥60 → unc`.

If the exact bucket isn't priced, the nearest one is used — the lower of two
equally close buckets, so a substitution errs low. The estimate's `source`
always names the grade actually used (`numista:N#1234 XF (for UNC)`), and
confidence drops from 0.60 to 0.45 when a substitution happened. Prices are
per piece, so the value is multiplied by the item's quantity.

Requirements and limits:

- A free API key (numista.com), stored encrypted in Settings; the source is
  disabled until you switch it on.
- 2,000 requests a month, so every response is cached in `source_cache` —
  issues for 30 days, prices for 7 — and a stale entry is used when the
  upstream fails. An item missing its prerequisites (no ref, no grade) costs
  no request at all.
- Confidence is medium by design: these are collector estimates, not realized
  auction prices. Melt remains the higher-confidence floor for bullion.
- **Scheduled refresh** (off by default): a cadence of every 7, 14, or 30
  days in Settings, alongside the same 12h loop that refreshes melt. Each
  estimate costs 2 calls (issues + prices), so Settings shows the real
  projected monthly count for your collection's priceable-item count against
  the 2,000/month quota — weekly refresh only stays under budget for roughly
  the first ~230 priceable items. Refresh keeps Numista's own data current
  independent of whichever source currently wins an item's overall-latest
  estimate, since `value_strategy` (see [api.md](api.md)) may prefer or
  average a source that isn't "latest" right now.

A missing prerequisite answers 422 with what to fix; an upstream failure or an
exhausted quota answers 502.

### PCGS (implemented — pricing program M3)
PCGS CoinFacts returns a price-guide value *and* a list of auction sales in one
response, so a single request yields both numbers. Implemented in
`app/services/pcgs.py`.

Lookup is by **cert number** when the item has one and `cert_service` is PCGS —
that identifies the individual slab — and otherwise by **PCGS number + grade**
from a `pcgs` catalog reference (`GET /coindetail/GetCoinFactsByCertNo/{cert}`
or `GET /coindetail/GetCoinFactsByGrade`). PCGS grade numbers *are* Sheldon
numbers, so the grade's rank passes straight through; an item graded on the PMG
scale is refused rather than mistranslated.

Realized auction prices win when PCGS has any: the median of up to the ten most
recent lots, confidence 0.85 with five or more sales and 0.75 below that, with
`sample_size` recording how many informed it. With no sales, the price-guide
value is used at confidence 0.60. The estimate's `source` says which
(`pcgs:apr cert 12345678`, `pcgs:guide #5960 MS-65`). Values are USD.

**Coins only.** PCGS Banknote has its own endpoints, but their responses carry
no price fields, so there is nothing for notes to read.

Requirements and limits:

- An access token (pcgs.com/publicapi, OAuth against your PCGS login), stored
  encrypted in Settings; the source is disabled until you switch it on.
- 1,000 calls a day; responses are cached in `source_cache` for 7 days.
- PCGS signals failure in the body, not the status: `IsValidRequest: false`
  means the request values were malformed, and `"No data found"` means no such
  coin. Both surface as 422 with the reason. A 500 usually means the token has
  expired — that surfaces as 502 saying so.
- **Scheduled refresh** (off by default): a simple weekly on/off toggle in
  Settings, no cadence choice needed — 1 call per estimate against a
  1,000/day quota comfortably covers weekly refresh at any realistic
  collection size, so Settings shows no quota caveat here (unlike Numista's).

### Checking a source against the live API

Unit tests use canned responses, so they prove the parsing but not the
contract. `backend/scripts/check_sources.py` covers the other half: it runs one
adapter for one item and prints the upstream calls, the raw payload, and the
estimate parsed out of it, without writing anything to `price_estimates`.

```bash
docker compose exec backend python scripts/check_sources.py --list
docker compose exec backend python scripts/check_sources.py -s numista -i <item-id> --fresh
```

`--list` shows which items carry a handle a source could use. `--fresh`
ignores the cache TTL to force a real request (and so spends quota); without
it a cached response is reused and the run is free. `--full` prints untrimmed
payloads. Credentials come from Settings and are never printed.

### Sold-listing comparables
Marketplaces that expose *sold* prices give the closest thing to real market
value. Filter by catalog reference and grade, then aggregate (e.g. median of
recent sales) and derive confidence from the sample size and spread. Prefer an
official API over scraping where one exists.

### Price-guide references
Published guides (annual catalogs and grading-service price guides) give
book values by grade. These are stable references but can lag the live market
and may not be available via API — some may require manual entry of values.

### Manual / user-provided
The app should always allow manually recording a value the user researched
themselves — their own comps, a dealer quote, or an auction result. Manual
entries are first-class `price_estimates` rows with `source = "manual"` and a
confidence the user sets (optional — omitted confidence is stored as null).

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
  estimate — surface low confidence rather than a misleadingly precise number.
- Cached estimates age; the `fetched_at` timestamp shows how stale a value is.

## Implementation notes

- Keep each source behind a small adapter interface (`fetch(catalog_ref,
  grade) -> list[comparable]`) so sources can be added or disabled
  independently.
- Rate-limit and cache upstream calls; respect each source's limits.
- Store raw comparables (or a summary) alongside the estimate where possible so
  a value can be explained, not just asserted.
