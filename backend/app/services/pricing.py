"""Price-source adapters (see docs/price-sources.md).

An adapter is `(db, item) -> EstimateResult`; it raises `NotApplicable` when
the item lacks a prerequisite and `SourceUnavailable` when the upstream fails.
Melt value lives here — spot price × weight × fineness × quantity,
deterministic and explainable, with the metal and spot price recorded in the
estimate's `source`. Other sources live in their own modules and are resolved
by `get_adapter`.

Money convention: estimates (like acquisition/sold prices) are per row — the
whole lot — so per-piece values are multiplied by quantity.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import Item, SourceCache, SpotPrice

TROY_OUNCE_G = Decimal("31.1034768")
CACHE_TTL = timedelta(hours=12)

# gold-api.com: free, keyless, USD per troy ounce.
SPOT_API = "https://api.gold-api.com/price/{symbol}"
METAL_SYMBOLS = {"gold": "XAU", "silver": "XAG", "platinum": "XPT", "palladium": "XPD"}

_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


class NotApplicable(Exception):
    """The adapter cannot price this item; the message says what's missing."""


class SourceUnavailable(Exception):
    """An upstream price source could not be reached."""


class SpotUnavailable(SourceUnavailable):
    """No fresh or cached spot price could be obtained."""


@dataclass
class EstimateResult:
    source: str
    estimated_value: Decimal
    currency: str
    confidence: Decimal
    sample_size: int | None = None


def cached_response(db: Session, source: str, cache_key: str, ttl: timedelta, loader) -> dict:
    """Fetch an upstream response through the `source_cache` table. External
    sources have small free-tier quotas, so a cached entry within `ttl` beats
    spending a request, and a stale entry beats a failed one.

    `loader` is a zero-argument callable raising SourceUnavailable on failure.
    """
    row = db.get(SourceCache, (source, cache_key))
    now = datetime.now(timezone.utc)
    if row is not None and now - _as_utc(row.fetched_at) < ttl:
        return row.payload
    try:
        payload = loader()
    except SourceUnavailable:
        if row is not None:
            return row.payload
        raise
    if row is None:
        row = SourceCache(source=source, cache_key=cache_key)
        db.add(row)
    row.payload = payload
    row.fetched_at = now
    # Commit now so a request already spent survives an estimate that later
    # fails for a reason the response itself revealed.
    db.commit()
    return payload


def detect_metal(composition: str | None) -> str | None:
    if not composition:
        return None
    text = composition.lower()
    for metal in METAL_SYMBOLS:
        if metal in text:
            return metal
    return None


def effective_fineness(item: Item) -> Decimal | None:
    """The fineness field, falling back to a percentage in the composition
    text (e.g. "90% silver" → 0.900)."""
    if item.fineness is not None:
        return Decimal(item.fineness)
    match = _PERCENT_RE.search(item.composition or "")
    if match:
        percent = Decimal(match.group(1))
        if 0 < percent <= 100:
            return percent / 100
    return None


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def fetch_spot_price(metal: str) -> Decimal:
    """Fetch the current spot price in USD per gram. Raises SpotUnavailable."""
    symbol = METAL_SYMBOLS[metal]
    try:
        resp = httpx.get(SPOT_API.format(symbol=symbol), timeout=5.0)
        resp.raise_for_status()
        per_ounce = Decimal(str(resp.json()["price"]))
    except (httpx.HTTPError, KeyError, ValueError, ArithmeticError) as exc:
        raise SpotUnavailable(f"Spot price fetch for {metal} failed: {exc}") from exc
    if per_ounce <= 0:
        raise SpotUnavailable(f"Spot price fetch for {metal} returned {per_ounce}")
    return per_ounce / TROY_OUNCE_G


def get_spot_price(db: Session, metal: str) -> SpotPrice:
    """Cached spot price for a metal, refreshed when older than CACHE_TTL.
    A stale cache entry is used if the upstream fetch fails."""
    cached = db.get(SpotPrice, metal)
    now = datetime.now(timezone.utc)
    if cached is not None and now - _as_utc(cached.fetched_at) < CACHE_TTL:
        return cached
    try:
        price = fetch_spot_price(metal)
    except SpotUnavailable:
        if cached is not None:
            return cached  # stale beats nothing
        raise
    if cached is None:
        cached = SpotPrice(metal=metal, currency="USD", source="gold-api.com")
        db.add(cached)
    cached.price_per_gram = price
    cached.source = "gold-api.com"
    cached.fetched_at = now
    db.flush()
    return cached


def melt_estimate(db: Session, item: Item) -> EstimateResult:
    """Melt value for a precious-metal item. Raises NotApplicable/SpotUnavailable."""
    metal = detect_metal(item.composition)
    if metal is None:
        raise NotApplicable("No precious metal found in composition — set it to e.g. '90% silver'")
    if item.weight_g is None:
        raise NotApplicable("Set the item's weight to estimate melt value")
    fineness = effective_fineness(item)
    if fineness is None:
        raise NotApplicable("Set fineness (or a percentage in composition) to estimate melt value")

    spot = get_spot_price(db, metal)
    per_piece = Decimal(item.weight_g) * fineness * Decimal(spot.price_per_gram)
    value = (per_piece * item.quantity).quantize(Decimal("0.01"))
    return EstimateResult(
        source=f"melt:{metal} @ {Decimal(spot.price_per_gram).quantize(Decimal('0.0001'))}/g",
        estimated_value=value,
        currency=spot.currency,
        confidence=Decimal("0.95"),
    )


# Adapter registry. Sources are resolved lazily so each adapter module can
# import this one for the shared contract without a circular import.
ADAPTER_NAMES = ("melt", "numista", "pcgs")


def get_adapter(name: str):
    """The adapter callable for a source name, or None if there isn't one."""
    if name == "melt":
        return melt_estimate
    if name == "numista":
        from app.services.numista import numista_estimate

        return numista_estimate
    if name == "pcgs":
        from app.services.pcgs import pcgs_estimate

        return pcgs_estimate
    return None


def refresh_melt_estimates(db: Session, max_age_days: int = 7) -> dict:
    """Re-run melt estimates for owned items whose LATEST estimate is a melt
    estimate older than max_age_days. Items whose latest estimate is manual are
    left alone — a fresh melt value must never bury the user's own number.
    Returns {"updated": n, "skipped": n, "failed": n}."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import PriceEstimate

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    updated = skipped = failed = 0
    items = (
        db.execute(select(Item).where(Item.status == "owned").options(selectinload(Item.estimates)))
        .scalars()
        .all()
    )
    for item in items:
        latest = item.estimates[0] if item.estimates else None
        if (
            latest is None
            or not latest.source.startswith("melt:")
            or _as_utc(latest.fetched_at) > cutoff
        ):
            skipped += 1
            continue
        try:
            result = melt_estimate(db, item)
        except (NotApplicable, SpotUnavailable):
            failed += 1
            continue
        db.add(
            PriceEstimate(
                item_id=item.id,
                source=result.source,
                estimated_value=result.estimated_value,
                currency=result.currency,
                confidence=result.confidence,
            )
        )
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped, "failed": failed}
