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
