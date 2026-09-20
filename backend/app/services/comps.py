"""Sold-listing comparables (v0.17.0): the `comps` price source.

The estimate is the median of recent sales in the item's sales log: sales the
user recorded by hand (eBay sold listings, auction archives, dealer sales) or
fetched from Numista's auction records (`numista.fetch_sales`, paid API plan).
No network: everything comes from the `comparables` table, converted into the
display currency at the cached daily rates.

Which sales count:
- only those marked `included` (the user can leave out an odd lot);
- a sale whose grade bucket is known (Numista's g…unc) must match the item's
  bucket (hand-logged sales carry no bucket, since choosing them was the match);
- the last `WINDOW_YEARS`, falling back to every sale when fewer than
  `MIN_RECENT` are that recent;
- at most `MAX_SALES`, newest first.

Confidence rises with the number of sales and falls with their spread (the
median absolute deviation relative to the median) and with fallbacks. Money is
per row, so the per-piece median is multiplied by quantity.
"""

from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.models import Comparable, Item
from app.services import app_settings
from app.services.currency import Converter
from app.services.numista import bucket_for_rank
from app.services.pricing import EstimateResult, NotApplicable

WINDOW_YEARS = 3
MIN_RECENT = 3
MAX_SALES = 20


def item_bucket(item: Item) -> str | None:
    """The item's grade as one of Numista's buckets, when it has a grade."""
    return bucket_for_rank(item.grade.rank) if item.grade is not None else None


def matching_sales(item: Item) -> tuple[list[Comparable], bool]:
    """The sales that count for this item, newest first, and whether sales
    older than the window had to be used."""
    bucket = item_bucket(item)
    usable = [
        c
        for c in item.comparables
        if c.included and (bucket is None or c.grade_bucket is None or c.grade_bucket == bucket)
    ]
    usable.sort(key=lambda c: (c.sold_on, c.id), reverse=True)
    cutoff = date.today() - timedelta(days=365 * WINDOW_YEARS)
    recent = [c for c in usable if c.sold_on >= cutoff]
    if len(recent) >= MIN_RECENT or len(recent) == len(usable):
        return recent[:MAX_SALES], False
    return usable[:MAX_SALES], True


def prerequisite(db: Session, item: Item) -> str | None:
    """What stops a comps estimate, or None. No network."""
    if not item.comparables:
        return "Log sales of comparable pieces in the item's sales log to estimate from comps"
    if not any(c.included for c in item.comparables):
        return "Every sale in the sales log is left out. Include at least one"
    if not matching_sales(item)[0]:
        bucket = item_bucket(item)
        return f"None of the logged sales match this item's grade ({(bucket or '').upper()})"
    return None


def _confidence(count: int, spread: float, graded: bool, older: bool) -> Decimal:
    if count >= 10:
        score = 0.70
    elif count >= 5:
        score = 0.60
    elif count >= 3:
        score = 0.50
    elif count == 2:
        score = 0.40
    else:
        score = 0.30
    if spread > 0.5:
        score -= 0.15
    elif spread > 0.25:
        score -= 0.08
    if not graded:
        score -= 0.05  # no grade to hold the sales against
    if older:
        score -= 0.10
    return Decimal(str(round(min(max(score, 0.15), 0.80), 2)))


def comps_estimate(db: Session, item: Item) -> EstimateResult:
    """Median of the item's matching logged sales. Raises NotApplicable."""
    reason = prerequisite(db, item)
    if reason:
        raise NotApplicable(reason)
    sales, older = matching_sales(item)
    currency = app_settings.display_currency(db)
    conv = Converter(db, currency)

    used: list[tuple[Comparable, float]] = []
    for sale in sales:
        value = conv.convert(sale.total, sale.currency)
        if value is not None and value > 0:
            used.append((sale, value))
    if not used:
        raise NotApplicable(
            f"No exchange rate to {currency} for the logged sales' currencies. Try again later"
        )

    values = [v for _, v in used]
    mid = median(values)
    spread = median(abs(v - mid) for v in values) / mid if mid else 0.0
    per_piece = Decimal(str(mid)).quantize(Decimal("0.01"))
    count = len(used)
    return EstimateResult(
        source=f"comps:{count} sale{'s' if count != 1 else ''}",
        estimated_value=(per_piece * item.quantity).quantize(Decimal("0.01")),
        currency=currency,
        confidence=_confidence(count, spread, item.grade is not None, older),
        sample_size=count,
        details={
            "median": float(per_piece),
            "currency": currency,
            "quantity": item.quantity,
            "spread_pct": round(spread * 100, 1),
            "grade_bucket": item_bucket(item),
            "window_years": WINDOW_YEARS,
            "older_sales_used": older,
            "excluded_other_currency": conv.excluded,
            "sales": [
                {
                    "date": sale.sold_on.isoformat(),
                    "venue": sale.venue,
                    "grade": sale.grade,
                    "price": float(sale.total),
                    "currency": sale.currency,
                    "converted": round(value, 2),
                    "premium_included": sale.premium_included,
                    "url": sale.url,
                    "source": sale.source,
                }
                for sale, value in used
            ],
        },
    )
