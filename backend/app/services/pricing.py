"""Price-source adapters (see docs/price-sources.md).

An adapter is `(db, item) -> EstimateResult`; it raises `NotApplicable` when
the item lacks a prerequisite and `SourceUnavailable` when the upstream fails.
Melt value lives here — spot price × weight × fineness × quantity,
deterministic and explainable, with the metal and spot price recorded in the
estimate's `source`. Other sources (numista, pcgs, comps) live in their own
modules and are resolved by `get_adapter`.

Money convention: estimates (like acquisition/sold prices) are per row — the
whole lot — so per-piece values are multiplied by quantity.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import EstimateAttempt, Item, PriceEstimate, SourceCache, SpotPrice
from app.services import alerts
from app.services.currency import Converter

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


class KeyRejected(SourceUnavailable):
    """The source refused the stored key or token, so every request will fail
    until it's replaced. Raises an alert, and stops a scheduled refresh."""


class QuotaExhausted(SourceUnavailable):
    """The source's request quota is used up. Raises an alert, and stops a
    scheduled refresh rather than spending the rest of the run on refusals."""


class SpotUnavailable(SourceUnavailable):
    """No fresh or cached spot price could be obtained."""


@dataclass
class EstimateResult:
    source: str
    estimated_value: Decimal
    currency: str
    confidence: Decimal
    sample_size: int | None = None
    # Provenance: what the source returned that produced this value. Must be
    # JSON-safe (floats, strings, ISO dates) — the column rejects Decimal.
    details: dict | None = None


def estimate_row(item_id: uuid.UUID, result: EstimateResult) -> PriceEstimate:
    return PriceEstimate(
        item_id=item_id,
        source=result.source,
        estimated_value=result.estimated_value,
        currency=result.currency,
        confidence=result.confidence,
        sample_size=result.sample_size,
        details=result.details,
    )


def freshness(fetched_at: datetime, ttl: timedelta) -> dict:
    """When upstream data was fetched, and whether it was already past its
    cache window — which is what gets served when a refresh fails."""
    fetched = _as_utc(fetched_at)
    return {
        "data_as_of": fetched.isoformat(),
        "stale": datetime.now(timezone.utc) - fetched >= ttl,
    }


def cached_fetch(
    db: Session, source: str, cache_key: str, ttl: timedelta, loader
) -> tuple[dict, datetime]:
    """Fetch an upstream response through the `source_cache` table. External
    sources have small free-tier quotas, so a cached entry within `ttl` beats
    spending a request, and a stale entry beats a failed one.

    `loader` is a zero-argument callable raising SourceUnavailable on failure.
    Returns the payload and when it was actually fetched.
    """
    row = db.get(SourceCache, (source, cache_key))
    now = datetime.now(timezone.utc)
    if row is not None and now - _as_utc(row.fetched_at) < ttl:
        return row.payload, row.fetched_at
    try:
        payload = loader()
    except SourceUnavailable as exc:
        # A refused key or quota alerts even when stale data covers for it.
        if isinstance(exc, (KeyRejected, QuotaExhausted)):
            kind = "key" if isinstance(exc, KeyRejected) else "quota"
            alerts.source_failed(db, source, kind, str(exc))
        if row is not None:
            return row.payload, row.fetched_at
        raise
    alerts.source_ok(db, source)
    if row is None:
        row = SourceCache(source=source, cache_key=cache_key)
        db.add(row)
    row.payload = payload
    row.fetched_at = now
    # Commit now so a request already spent survives an estimate that later
    # fails for a reason the response itself revealed.
    db.commit()
    return payload, now


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


def melt_prerequisite(db: Session, item: Item) -> str | None:
    """What the item lacks for a melt estimate, or None. No network."""
    if detect_metal(item.composition) is None:
        return "No precious metal found in composition — set it to e.g. '90% silver'"
    if item.weight_g is None:
        return "Set the item's weight to estimate melt value"
    if effective_fineness(item) is None:
        return "Set fineness (or a percentage in composition) to estimate melt value"
    return None


def melt_estimate(db: Session, item: Item) -> EstimateResult:
    """Melt value for a precious-metal item. Raises NotApplicable/SpotUnavailable."""
    reason = melt_prerequisite(db, item)
    if reason:
        raise NotApplicable(reason)
    metal = detect_metal(item.composition)
    fineness = effective_fineness(item)

    spot = get_spot_price(db, metal)
    per_piece = Decimal(item.weight_g) * fineness * Decimal(spot.price_per_gram)
    value = (per_piece * item.quantity).quantize(Decimal("0.01"))
    return EstimateResult(
        source=f"melt:{metal} @ {Decimal(spot.price_per_gram).quantize(Decimal('0.0001'))}/g",
        estimated_value=value,
        currency=spot.currency,
        confidence=Decimal("0.95"),
        details={
            "metal": metal,
            "weight_g": float(item.weight_g),
            "fineness": float(fineness),
            "fineness_from": "field" if item.fineness is not None else "composition",
            "quantity": item.quantity,
            "spot_per_gram": float(spot.price_per_gram),
            "spot_currency": spot.currency,
            "spot_source": spot.source,
            **freshness(spot.fetched_at, CACHE_TTL),
        },
    )


# Adapter registry. Sources are resolved lazily so each adapter module can
# import this one for the shared contract without a circular import.
ADAPTER_NAMES = ("melt", "numista", "pcgs", "comps")


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
    if name == "comps":
        from app.services.comps import comps_estimate

        return comps_estimate
    return None


def get_prerequisite(name: str):
    """The source's local eligibility check — `(db, item) -> reason | None` —
    which its adapter runs first. Used to explain gaps without a request."""
    if name == "melt":
        return melt_prerequisite
    if name == "numista":
        from app.services.numista import prerequisite

        return prerequisite
    if name == "pcgs":
        from app.services.pcgs import prerequisite

        return prerequisite
    if name == "comps":
        from app.services.comps import prerequisite

        return prerequisite
    return None


def run_adapter(db: Session, item: Item, source: str) -> EstimateResult:
    """Run one source's adapter and record the outcome as the item's latest
    attempt for that source. A failure is committed before it propagates, so
    it survives the caller's error handling; a success is committed along with
    the caller's estimate row."""
    adapter = get_adapter(source)
    try:
        result = adapter(db, item)
    except NotApplicable as exc:
        _record_attempt(db, item, source, "not_applicable", str(exc))
        db.commit()
        raise
    except SourceUnavailable as exc:
        _record_attempt(db, item, source, "unavailable", str(exc))
        db.commit()
        raise
    _record_attempt(db, item, source, "ok", None)
    return result


def _record_attempt(
    db: Session, item: Item, source: str, outcome: str, message: str | None
) -> None:
    row = db.get(EstimateAttempt, (item.id, source))
    if row is None:
        row = EstimateAttempt(item_id=item.id, source=source)
        db.add(row)
    row.outcome = outcome
    row.message = message[:500] if message else None
    row.attempted_at = datetime.now(timezone.utc)


AVERAGEABLE_SOURCES = ("melt", "numista", "pcgs", "comps")  # pluggable sources only;
# to include a manual source later, add its exact source string here.


def source_key(source: str) -> str:
    """Reduce a free-text estimate `source` (e.g. "numista:N#123 XF") to its
    adapter key ("numista"). Manual entries with no ":" pass through as-is."""
    return source.split(":", 1)[0]


def resolve_display_value(
    estimates: Sequence[PriceEstimate],
    strategy: str,
    preferred_source: str | None,
    converter: Converter | None = None,
) -> tuple[Decimal | float, str, str] | None:
    """The one blended value for an item's estimates (newest-first), per the
    `value_strategy` setting.

    - "latest": the most recent estimate overall (today's behavior).
    - "preferred_source": the most recent estimate from `preferred_source`;
      falls back to "latest" if the item has none from that source.
    - "average": the mean of the latest estimate from each distinct
      AVERAGEABLE_SOURCES key present, each converted via `converter` first
      (sources that fail to convert are skipped). Falls back to "latest" if
      `converter` is None or nothing converts.

    "latest"/"preferred_source" return the chosen estimate's own
    value/currency unconverted — this keeps the default "latest" path a true
    no-op. "average" always returns (mean, converter.display).

    Returns (value, currency, source_label): source_label is the winning
    estimate's source_key (e.g. "numista", "melt", or a manual entry's raw
    source string), or the literal "average" when blended across sources —
    lets callers show where a displayed value actually came from.
    """
    if not estimates:
        return None
    latest = estimates[0]
    fallback = (latest.estimated_value, latest.currency, source_key(latest.source))

    if strategy == "preferred_source" and preferred_source:
        for est in estimates:
            if source_key(est.source) == preferred_source:
                return (est.estimated_value, est.currency, source_key(est.source))
        return fallback

    if strategy == "average" and converter is not None:
        seen: set[str] = set()
        total = 0.0
        count = 0
        for est in estimates:
            key = source_key(est.source)
            if key not in AVERAGEABLE_SOURCES or key in seen:
                continue
            seen.add(key)
            converted = converter.convert(est.estimated_value, est.currency)
            if converted is not None:
                total += converted
                count += 1
        if count:
            return (total / count, converter.display, "average")
        return fallback

    return fallback


def refresh_melt_estimates(db: Session, max_age_days: int = 7) -> dict:
    """Re-run melt estimates for owned items whose LATEST estimate is a melt
    estimate older than max_age_days. Items whose latest estimate is manual are
    left alone — a fresh melt value must never bury the user's own number.
    An item that no longer qualifies (NotApplicable) counts as skipped.
    Returns {"updated": n, "skipped": n, "failed": n}, plus "error" (the last
    failure's message) when anything failed."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    updated = skipped = failed = 0
    error = None
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
            result = run_adapter(db, item, "melt")
        except NotApplicable:
            skipped += 1
            continue
        except SourceUnavailable as exc:
            failed += 1
            error = str(exc)
            continue
        db.add(estimate_row(item.id, result))
        updated += 1
    db.commit()
    return _refresh_outcome(updated, skipped, failed, error)


def _refresh_outcome(
    updated: int, skipped: int, failed: int, error: str | None, stopped: str | None = None
) -> dict:
    outcome = {"updated": updated, "skipped": skipped, "failed": failed}
    if error:
        outcome["error"] = error
    if stopped:
        outcome["stopped"] = stopped
    return outcome


def refresh_source_estimates(db: Session, source: str, max_age_days: int = 7) -> dict:
    """Re-run `source`'s own estimate for owned items whose most recent
    estimate FROM THIS SOURCE (not the item's overall-latest, which may
    belong to a different source or be manual) is missing or older than
    max_age_days. Keeps each source's own data current independent of what
    currently wins — needed because value_strategy can be "preferred_source"
    or "average". NotApplicable (not eligible) counts as skipped, not
    failed. A rejected key or exhausted quota stops the run (every remaining
    request would fail the same way) and is returned as "stopped". Never
    called for "melt" — that keeps its own separate, conservative behavior in
    refresh_melt_estimates.
    Returns {"updated": n, "skipped": n, "failed": n}, plus "error" and
    "stopped" when set."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    updated = skipped = failed = 0
    error = stopped = None
    items = (
        db.execute(
            select(Item)
            .where(Item.status == "owned")
            .options(selectinload(Item.estimates), selectinload(Item.catalog_refs))
        )
        .scalars()
        .all()
    )
    for item in items:
        own_latest = next((e for e in item.estimates if source_key(e.source) == source), None)
        if own_latest is not None and _as_utc(own_latest.fetched_at) > cutoff:
            skipped += 1
            continue
        try:
            result = run_adapter(db, item, source)
        except NotApplicable:
            skipped += 1
            continue
        except (KeyRejected, QuotaExhausted) as exc:
            failed += 1
            stopped = str(exc)
            break
        except SourceUnavailable as exc:
            failed += 1
            error = str(exc)
            continue
        db.add(estimate_row(item.id, result))
        updated += 1
    db.commit()
    return _refresh_outcome(updated, skipped, failed, error, stopped)
