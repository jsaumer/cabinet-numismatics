"""The bullion stack (roadmap Phase 7, P7): fine ounces by metal, cost per
ounce (which is also the break-even spot price), the premium paid over spot at
purchase, and spot-price threshold alerts.

The stack is the owned, untrashed items with a detected precious metal, a
weight, and a fineness: exactly the pieces melt value can price
(`Item.fine_oz`). Money is converted into one currency the way
`/api/stats/collection` does it (cached daily rates; an amount with no rate is
left out and counted), but ounces always count, and a premium paid is worked
out in the item's own currency so nothing has to convert at all.

Purchase-day spot comes from the public-domain (CC0) fawazahmed0 currency-api,
which has XAU/XAG/XPT/XPD daily from 2024-03-02. LBMA's public series goes
back further but its terms need a licence for valuation, and gold-api.com's
history needs a key, so older purchases take a hand-typed figure. Only a date
and a metal code go upstream, never collection data.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Item
from app.services import alerts
from app.services import app_settings as store
from app.services.currency import get_rate
from app.services.pricing import (
    CACHE_TTL,
    METAL_SYMBOLS,
    TROY_OUNCE_G,
    NotApplicable,
    SourceUnavailable,
    cached_fetch,
    detect_metal,
    effective_fineness,
    freshness,
    get_spot_price,
    money,
)

logger = logging.getLogger(__name__)

# The metals, in the order the report and the item list use.
METALS = tuple(METAL_SYMBOLS)

HISTORY_START = date(2024, 3, 2)  # the first day the currency-api covers XAU
HISTORY_SOURCE = "spot_history"
HISTORY_LABEL = "fawazahmed0 currency-api"
# A past day's price never changes, so the cache entry never needs refreshing.
HISTORY_TTL = timedelta(days=3650)
HISTORY_HOSTS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{code}.json",
    "https://{date}.currency-api.pages.dev/v1/currencies/{code}.json",
)
METAL_CODES = {"gold": "xau", "silver": "xag", "platinum": "xpt", "palladium": "xpd"}

# How many items one hourly tick and one backfill request may look up.
HOURLY_BACKFILL = 20
BACKFILL_LIMIT = 50

MAX_SPOT_ALERTS = 12


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _f(value, places: int = 2) -> float | None:
    return None if value is None else round(float(value), places)


# --- purchase-day spot ------------------------------------------------------


def _fetch_history(code: str, on: date) -> dict:
    """One day's per-ounce prices, from the CDN or its fallback host."""
    problem = None
    for template in HISTORY_HOSTS:
        url = template.format(date=on.isoformat(), code=code)
        try:
            resp = httpx.get(url, timeout=8.0, follow_redirects=True)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            problem = exc
            continue
        rates = payload.get(code)
        if isinstance(rates, dict) and rates:
            return {"date": payload.get("date") or on.isoformat(), code: rates}
        problem = ValueError(f"no {code} prices in the response")
    raise SourceUnavailable(f"Spot price for {code} on {on} could not be fetched: {problem}")


def historic_spot(db: Session, metal: str, on: date, currency: str) -> Decimal:
    """The metal's spot price per troy ounce on `on`, in `currency`. Raises
    NotApplicable outside what the source covers, SourceUnavailable when both
    hosts fail."""
    code = METAL_CODES.get(metal)
    if code is None:
        raise NotApplicable(f"No spot price for {metal!r}")
    if on < HISTORY_START:
        raise NotApplicable(
            f"Purchase-day spot starts at {HISTORY_START.isoformat()}; "
            "type the figure in by hand for an earlier purchase"
        )
    if on >= _today():
        raise NotApplicable("A past day only; use the current spot price for today")
    payload, _ = cached_fetch(
        db,
        HISTORY_SOURCE,
        f"{code}:{on.isoformat()}",
        HISTORY_TTL,
        lambda: _fetch_history(code, on),
    )
    price = (payload.get(code) or {}).get(currency.lower())
    if price is None:
        raise NotApplicable(f"No {metal} price in {currency.upper()} on {on.isoformat()}")
    try:
        value = Decimal(str(price))
    except ArithmeticError as exc:
        raise SourceUnavailable(f"Spot price for {code} on {on} was {price!r}") from exc
    if value <= 0:
        raise NotApplicable(f"No {metal} price in {currency.upper()} on {on.isoformat()}")
    return value


# --- the figures ------------------------------------------------------------


class _Rates:
    """Conversion into one currency, as `/api/stats/collection` does it: cached
    daily rates, and an amount with no rate is left out and counted."""

    def __init__(self, db: Session, display: str):
        self.db = db
        self.display = display
        self.excluded = 0
        self._seen: dict[str, Decimal | None] = {}

    def rate(self, code: str) -> Decimal | None:
        if code == self.display:
            return Decimal(1)
        if code not in self._seen:
            self._seen[code] = get_rate(self.db, code, self.display)
        return self._seen[code]


@dataclass
class _Bucket:
    items: int = 0
    pieces: int = 0
    fine_oz: Decimal = Decimal(0)
    cost_basis: Decimal = Decimal(0)
    costed_oz: Decimal = Decimal(0)
    # The premium aggregate: cost and value-at-purchase-spot of the pieces
    # where the purchase-day spot is known, both in the report's currency.
    premium_cost: Decimal = Decimal(0)
    premium_at_spot: Decimal = Decimal(0)
    premium_oz: Decimal = Decimal(0)
    rows: list = field(default_factory=list)


def _spot_per_oz(db: Session, metal: str, rates: _Rates):
    """(price per troy ounce in the report's currency, when it was fetched,
    whether that was already stale), or (None, None, False)."""
    try:
        row = get_spot_price(db, metal)
    except SourceUnavailable:
        return None, None, False
    rate = rates.rate(row.currency)
    if rate is None:
        return None, None, False
    fresh = freshness(row.fetched_at, CACHE_TTL)
    return Decimal(row.price_per_gram) * TROY_OUNCE_G * rate, row.fetched_at, fresh["stale"]


def in_scope(item: Item, tag: str | None, set_id: int | None) -> bool:
    if tag is not None and not any(t.name == tag for t in item.tags):
        return False
    return not (set_id is not None and item.set_id != set_id)


def needs_spot(item: Item, today: date | None = None) -> bool:
    """Whether the purchase-day spot for this piece could be looked up: in the
    stack, no figure yet, a cost, and a purchase date the source covers."""
    today = today or _today()
    return (
        item.fine_oz is not None
        and item.spot_at_purchase is None
        and item.acquisition_date is not None
        and HISTORY_START <= item.acquisition_date < today
        and (item.cost_basis or 0) > 0
    )


def _owned(db: Session) -> list[Item]:
    return (
        db.execute(select(Item).where(Item.status == "owned").options(selectinload(Item.tags)))
        .scalars()
        .all()
    )


def stack_figures(
    db: Session, currency: str, tag: str | None = None, set_id: int | None = None
) -> dict:
    """The whole stack report. Spot prices come from the same cache melt uses
    (stale beats failed); a metal whose spot can't be had still lists its
    ounces, with the money-at-spot figures left empty."""
    rates = _Rates(db, currency)
    today = _today()
    buckets: dict[str, _Bucket] = {}
    skipped = missing_spot = 0
    skipped_items: list[dict] = []

    for item in _owned(db):
        metal = detect_metal(item.composition)
        if metal is None or not in_scope(item, tag, set_id):
            continue
        oz = item.fine_oz
        if oz is None:
            # A precious metal, but no weight or fineness (or neither).
            skipped += 1
            missing = []
            if item.weight_g is None:
                missing.append("weight")
            if effective_fineness(item) is None:
                missing.append("fineness")
            skipped_items.append(
                {"item_id": item.id, "label": item.label, "missing": " and ".join(missing)}
            )
            continue
        if needs_spot(item, today):
            missing_spot += 1
        bucket = buckets.setdefault(metal, _Bucket())
        bucket.items += 1
        bucket.pieces += item.quantity
        bucket.fine_oz += oz

        rate = rates.rate(item.currency)
        cost = item.cost_basis
        converted_cost = None
        if cost is not None and rate is not None:
            converted_cost = Decimal(cost) * rate
            bucket.cost_basis += converted_cost
            bucket.costed_oz += oz
        elif cost is not None:
            rates.excluded += 1
        premium = item.premium_paid_pct
        if premium is not None and rate is not None:
            bucket.premium_cost += Decimal(cost) * rate
            bucket.premium_at_spot += oz * Decimal(item.spot_at_purchase) * rate
            bucket.premium_oz += oz
        bucket.rows.append((item, oz, converted_cost, premium, rate is not None and rate != 1))

    metals = []
    rows = []
    total_melt = total_cost = total_gain = Decimal(0)
    for metal in METALS:
        bucket = buckets.get(metal)
        if bucket is None:
            continue
        spot, fetched_at, stale = _spot_per_oz(db, metal, rates)
        melt = bucket.fine_oz * spot if spot is not None else None
        # No costed piece means no gain to speak of, not a gain of zero.
        costed_melt = bucket.costed_oz * spot if spot is not None and bucket.costed_oz else None
        gain = costed_melt - bucket.cost_basis if costed_melt is not None else None
        metals.append(
            {
                "metal": metal,
                "items": bucket.items,
                "pieces": bucket.pieces,
                "fine_oz": _f(bucket.fine_oz, 3),
                "fine_g": _f(bucket.fine_oz * TROY_OUNCE_G),
                "spot_per_oz": _f(spot),
                "spot_fetched_at": fetched_at,
                "spot_stale": stale,
                "melt_value": _f(melt),
                "cost_basis": _f(bucket.cost_basis),
                "costed_oz": _f(bucket.costed_oz, 3),
                "cost_per_oz": (
                    _f(bucket.cost_basis / bucket.costed_oz) if bucket.costed_oz else None
                ),
                "gain": _f(gain),
                "gain_pct": (
                    _f(gain / bucket.cost_basis * 100)
                    if gain is not None and bucket.cost_basis
                    else None
                ),
                "premium_paid_pct": (
                    _f(
                        (bucket.premium_cost - bucket.premium_at_spot)
                        / bucket.premium_at_spot
                        * 100
                    )
                    if bucket.premium_at_spot
                    else None
                ),
                "premium_known_oz": _f(bucket.premium_oz, 3),
            }
        )
        total_melt += melt or 0
        total_cost += bucket.cost_basis
        total_gain += gain or 0
        # Within a metal, the biggest holdings first.
        for item, oz, cost, premium, was_converted in sorted(bucket.rows, key=lambda r: -r[1]):
            item_melt = oz * spot if spot is not None else None
            rows.append(
                {
                    "item_id": item.id,
                    "label": item.label,
                    "metal": metal,
                    "quantity": item.quantity,
                    "fine_oz": _f(oz, 3),
                    "cost_basis": _f(cost),
                    "cost_per_oz": _f(cost / oz) if cost is not None and oz else None,
                    "spot_at_purchase": _f(item.spot_at_purchase, 4),
                    "spot_at_purchase_source": item.spot_at_purchase_source,
                    "premium_paid_pct": _f(premium),
                    "melt_value": _f(item_melt),
                    "gain": (
                        _f(item_melt - cost) if item_melt is not None and cost is not None else None
                    ),
                    "currency": item.currency,
                    "converted": was_converted,
                }
            )

    return {
        "currency": currency,
        "metals": metals,
        "totals": {
            "melt_value": _f(total_melt),
            "cost_basis": _f(total_cost),
            "gain": _f(total_gain),
            "fine_oz_by_metal": {m["metal"]: m["fine_oz"] for m in metals},
        },
        "items": rows,
        "missing_spot": missing_spot,
        "skipped": skipped,
        "skipped_items": skipped_items,
        "excluded_other_currency": rates.excluded,
        "history_start": HISTORY_START,
    }


def fine_ounces_by_metal(db: Session) -> dict[str, float]:
    """Fine troy ounces of owned bullion per metal, for /api/metrics. No
    network: ounces need no spot price."""
    totals: dict[str, Decimal] = {}
    for item in db.execute(select(Item).where(Item.status == "owned")).scalars():
        metal = detect_metal(item.composition)
        oz = item.fine_oz if metal else None
        if oz is not None:
            totals[metal] = totals.get(metal, Decimal(0)) + oz
    return {metal: round(float(oz), 4) for metal, oz in totals.items()}


# --- backfilling the purchase-day spot --------------------------------------


def backfill(db: Session, limit: int = BACKFILL_LIMIT) -> dict:
    """Look up the purchase-day spot for pieces that qualify and have none.
    A value typed in by hand is never touched (it is not eligible). Returns
    {filled, failed, remaining}."""
    today = _today()
    pending = [item for item in _owned(db) if needs_spot(item, today)]
    filled = failed = 0
    for item in pending[:limit]:
        metal = detect_metal(item.composition)
        try:
            price = historic_spot(db, metal, item.acquisition_date, item.currency)
        except (NotApplicable, SourceUnavailable) as exc:
            failed += 1
            logger.info("Purchase-day spot for %s: %s", item.label, exc)
            continue
        item.spot_at_purchase = price
        item.spot_at_purchase_source = "auto"
        filled += 1
    db.commit()
    return {"filled": filled, "failed": failed, "remaining": len(pending) - filled}


# --- spot-price threshold alerts --------------------------------------------


def alert_key(threshold: dict) -> str:
    """A threshold's identity, so its state survives the list being reordered."""
    return (
        f"{threshold.get('metal')}:{threshold.get('direction')}:"
        f"{float(threshold.get('price') or 0):g}:{str(threshold.get('currency') or '').upper()}"
    )


def spot_alerts(db: Session) -> list[dict]:
    value = store.get_setting(db, "spot_alerts")
    return list(value) if isinstance(value, list) else []


def alert_state(db: Session) -> dict:
    value = store.get_setting(db, "spot_alert_state")
    return dict(value) if isinstance(value, dict) else {}


def prune_alert_state(db: Session) -> None:
    """Forget the state of thresholds that are no longer saved. The caller
    commits."""
    keys = {alert_key(t) for t in spot_alerts(db)}
    state = alert_state(db)
    kept = {key: met for key, met in state.items() if key in keys}
    if kept != state:
        store.set_setting(db, "spot_alert_state", kept)


def check_spot_alerts(db: Session) -> int:
    """Check each saved threshold against the current spot price. A threshold
    that has just started being met sends one event; when it stops being met it
    re-arms silently. Returns how many fired."""
    thresholds = spot_alerts(db)
    state = alert_state(db)
    kept: dict[str, bool] = {}
    fired = 0
    for threshold in thresholds:
        metal = str(threshold.get("metal") or "")
        code = str(threshold.get("currency") or "USD").upper()
        direction = str(threshold.get("direction") or "above")
        if metal not in METAL_SYMBOLS:
            continue
        try:
            price = Decimal(str(threshold["price"]))
        except (KeyError, ArithmeticError, TypeError):
            continue
        spot = _threshold_spot(db, metal, code)
        if spot is None:
            continue  # no spot and no rate: leave the state as it was
        key = alert_key(threshold)
        met = spot >= price if direction == "above" else spot <= price
        kept[key] = met
        if met and not state.get(key):
            fired += 1
            alerts.event(
                db,
                f"spot_{metal}",
                f"{metal.capitalize()} is {direction} {money(price, code)}",
                f"Spot is {money(spot, code)} per ounce (threshold {money(price, code)}).",
            )
    # Thresholds that were removed, or couldn't be checked, keep nothing.
    if kept != state:
        store.set_setting(db, "spot_alert_state", kept)
        db.commit()
    return fired


def _threshold_spot(db: Session, metal: str, code: str) -> Decimal | None:
    """The current spot price per troy ounce in `code`, or None."""
    try:
        row = get_spot_price(db, metal)
    except SourceUnavailable:
        return None
    rate = get_rate(db, row.currency, code) if row.currency != code else Decimal(1)
    if rate is None:
        return None
    return Decimal(row.price_per_gram) * TROY_OUNCE_G * rate
