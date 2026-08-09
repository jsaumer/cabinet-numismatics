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

### Melt value (first automatic source)
For precious-metal items, `weight × fineness × spot price` gives a
deterministic floor value with near-1.0 confidence and no terms-of-service
concerns — spot prices are available from free APIs. Requires the structured
composition/weight/fineness fields (Phase 2). This ships *before* the harder
sources below: it is trivial to compute, always explainable, and covers the
bullion floor of most collections.

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
confidence the user sets. *(Implementation status: manual entry exists as of
Phase 1 and stores `confidence = null`; the optional user-set confidence field
arrives with the Phase 3 valuation work.)*

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
