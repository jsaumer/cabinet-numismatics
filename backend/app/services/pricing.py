"""Price-source adapters (see docs/price-sources.md).

Phase 3 ships one adapter: melt value — spot price × weight × fineness ×
quantity. Deterministic and explainable; the estimate's `source` records the
metal and the spot price used.

Money convention: estimates (like acquisition/sold prices) are per row — the
whole lot — so melt multiplies per-piece value by quantity.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import Item, SpotPrice

TROY_OUNCE_G = Decimal("31.1034768")
CACHE_TTL = timedelta(hours=12)

# gold-api.com: free, keyless, USD per troy ounce.
SPOT_API = "https://api.gold-api.com/price/{symbol}"
METAL_SYMBOLS = {"gold": "XAU", "silver": "XAG", "platinum": "XPT", "palladium": "XPD"}

_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


class NotApplicable(Exception):
    """The adapter cannot price this item; the message says what's missing."""


class SpotUnavailable(Exception):
    """No fresh or cached spot price could be obtained."""


@dataclass
class EstimateResult:
    source: str
    estimated_value: Decimal
    currency: str
    confidence: Decimal
    sample_size: int | None = None


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


# Adapter registry: later sources (sold comps, price guides) append here.
ADAPTERS = {"melt": melt_estimate}
