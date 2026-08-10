"""Numista price adapter (pricing program M2).

Numista prices an *issue* — a catalogue type narrowed to a year and mint — and
quotes it per grade bucket. The adapter resolves that chain: the item's
`numista` catalog ref gives the type, the type's issues are matched against the
item's year (and mint mark), and the item's grade is mapped onto Numista's
seven buckets.

Free API keys allow 2,000 requests a month, so every upstream response is
cached in `source_cache` — catalogue data for 30 days, prices for 7 — and a
stale entry is preferred over a failed request, the same discipline spot prices
and exchange rates use.

Confidence is medium: these are collector-swap-derived estimates, not realized
auction prices. Money is per row, so the per-piece price is multiplied by the
item's quantity.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.orm import Session

from app.models import Item, SourceCache
from app.services import app_settings
from app.services.pricing import EstimateResult, NotApplicable, SourceUnavailable

API_ROOT = "https://api.numista.com/api/v3"
CATALOG_TTL = timedelta(days=30)  # issues barely change
PRICE_TTL = timedelta(days=7)

# Numista's grade buckets, worst to best.
GRADE_BUCKETS = ("g", "vg", "f", "vf", "xf", "au", "unc")
# Cabinet grade ranks (Sheldon and PMG share the 1–70 scale) → bucket.
_RANK_CUTOFFS = ((8, "g"), (12, "vg"), (20, "f"), (40, "vf"), (50, "xf"), (60, "au"))


class _NotFound(Exception):
    """Upstream 404 — the catalogue has no such type or issue."""


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def bucket_for_rank(rank: int) -> str:
    for cutoff, bucket in _RANK_CUTOFFS:
        if rank < cutoff:
            return bucket
    return "unc"


def type_id_for(item: Item) -> str | None:
    """The numeric Numista type id from the item's `numista` catalog ref.
    Accepts `1234`, `N#1234`, and `N# 1234`."""
    for ref in item.catalog_refs:
        if ref.catalog.strip().lower() != "numista":
            continue
        digits = "".join(ch for ch in ref.ref_code if ch.isdigit())
        if digits:
            return digits
    return None


def _request(api_key: str, path: str, params: dict | None = None) -> dict:
    """One upstream call. Raises _NotFound or SourceUnavailable."""
    try:
        resp = httpx.get(
            f"{API_ROOT}/{path}",
            params=params or {},
            headers={"Numista-API-Key": api_key},
            timeout=10.0,
        )
        if resp.status_code == 404:
            raise _NotFound()
        if resp.status_code in (401, 403):
            raise SourceUnavailable("Numista rejected the API key — check it in Settings")
        if resp.status_code == 429:
            raise SourceUnavailable("Numista request quota exhausted — try again later")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"Numista request failed: {exc}") from exc
    except ValueError as exc:
        raise SourceUnavailable(f"Numista returned invalid JSON: {exc}") from exc
    # A bare list (the issues endpoint) is wrapped so the cache column stays a dict.
    return data if isinstance(data, dict) else {"items": data}


def _cached(db: Session, cache_key: str, ttl: timedelta, api_key: str, path: str, params=None):
    """Fetch through the `source_cache` table. A stale entry beats spending a
    request; a stale entry also beats a failed one."""
    row = db.get(SourceCache, ("numista", cache_key))
    now = datetime.now(timezone.utc)
    if row is not None and now - _as_utc(row.fetched_at) < ttl:
        return row.payload
    try:
        payload = _request(api_key, path, params)
    except SourceUnavailable:
        if row is not None:
            return row.payload
        raise
    if row is None:
        row = SourceCache(source="numista", cache_key=cache_key)
        db.add(row)
    row.payload = payload
    row.fetched_at = now
    # Commit now so a request already spent survives an estimate that later
    # fails (no matching issue, no price for the grade).
    db.commit()
    return payload


def pick_issue(issues: list[dict], item: Item) -> dict | None:
    """The issue matching the item's year, preferring one whose mint letter
    matches too."""
    same_year = [i for i in issues if isinstance(i, dict) and _issue_year(i) == item.year]
    if not same_year:
        return None
    if item.mint_mark:
        mark = item.mint_mark.strip().lower()
        exact = [i for i in same_year if str(i.get("mint_letter") or "").strip().lower() == mark]
        if exact:
            return exact[0]
    return same_year[0]


def _issue_year(issue: dict) -> int | None:
    for field in ("year", "min_year", "gregorian_year"):
        value = issue.get(field)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return None


def price_map(payload: dict) -> dict[str, Decimal]:
    """Grade bucket → price, from either shape Numista returns: a list of
    `{grade, price}` objects or a grade-keyed object. Unknown keys (currency
    and friends) and non-positive prices are dropped."""
    prices = payload.get("prices", payload)
    if isinstance(prices, dict):
        pairs = list(prices.items())
    elif isinstance(prices, list):
        pairs = [
            (p.get("grade"), p.get("price", p.get("value"))) for p in prices if isinstance(p, dict)
        ]
    else:
        return {}

    out: dict[str, Decimal] = {}
    for grade, value in pairs:
        if not isinstance(grade, str) or grade.strip().lower() not in GRADE_BUCKETS:
            continue
        if isinstance(value, dict):  # {"value": 12.5, "currency": "USD"}
            value = value.get("value", value.get("price"))
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if amount > 0:
            out[grade.strip().lower()] = amount
    return out


def resolve_grade(prices: dict[str, Decimal], wanted: str) -> str | None:
    """The wanted bucket if priced, else the nearest one — preferring the
    lower (more conservative) bucket when two are equally close."""
    if wanted in prices:
        return wanted
    target = GRADE_BUCKETS.index(wanted)
    ranked = sorted(
        prices,
        key=lambda g: (abs(GRADE_BUCKETS.index(g) - target), GRADE_BUCKETS.index(g) > target),
    )
    return ranked[0] if ranked else None


def _currency_of(payload: dict, fallback: str) -> str:
    value = payload.get("currency")
    return value.upper() if isinstance(value, str) and len(value) == 3 else fallback


def numista_estimate(db: Session, item: Item) -> EstimateResult:
    """Price an item from Numista. Raises NotApplicable/SourceUnavailable."""
    api_key = str(app_settings.get_setting(db, "numista_api_key"))
    if not api_key:
        raise NotApplicable("Add a Numista API key in Settings to price items from Numista")

    type_id = type_id_for(item)
    if type_id is None:
        raise NotApplicable("Add a 'numista' catalog reference (e.g. N#1234) to price this item")
    if item.grade is None:
        raise NotApplicable("Set the item's grade — Numista quotes prices per grade")

    wanted = bucket_for_rank(item.grade.rank)
    currency = app_settings.display_currency(db)

    try:
        issues_payload = _cached(
            db, f"issues:{type_id}", CATALOG_TTL, api_key, f"types/{type_id}/issues"
        )
    except _NotFound:
        raise NotApplicable(f"Numista has no type N#{type_id}") from None
    issues = issues_payload.get("issues") or issues_payload.get("items") or []

    issue = pick_issue(issues, item)
    if issue is None or issue.get("id") is None:
        raise NotApplicable(f"Numista lists no {item.year} issue for N#{type_id}")
    issue_id = issue["id"]

    try:
        payload = _cached(
            db,
            f"prices:{type_id}:{issue_id}:{currency}",
            PRICE_TTL,
            api_key,
            f"types/{type_id}/issues/{issue_id}/prices",
            {"currency": currency},
        )
    except _NotFound:
        raise NotApplicable(
            f"Numista has no prices for the {item.year} issue of N#{type_id}"
        ) from None

    prices = price_map(payload)
    used = resolve_grade(prices, wanted)
    if used is None:
        raise NotApplicable(f"Numista has no priced grade for the {item.year} issue of N#{type_id}")

    value = (prices[used] * item.quantity).quantize(Decimal("0.01"))
    exact = used == wanted
    source = f"numista:N#{type_id} {used.upper()}"
    if not exact:
        source += f" (for {wanted.upper()})"
    return EstimateResult(
        source=source,
        estimated_value=value,
        currency=_currency_of(payload, currency),
        confidence=Decimal("0.60") if exact else Decimal("0.45"),
    )
