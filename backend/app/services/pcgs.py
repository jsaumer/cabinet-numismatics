"""PCGS price adapter (pricing program M3).

PCGS CoinFacts answers with both a price-guide value and a list of auction
sales in one response, so a single request yields the two numbers this adapter
chooses between. Realized auction prices win when there are any — they are
actual sales — and the price guide is the fallback.

An item is looked up by its PCGS **cert number** when it has one (exact: that
individual slab), otherwise by **PCGS number + grade** from a `pcgs` catalog
reference. PCGS grade numbers *are* Sheldon numbers, so the grade's rank maps
straight through.

Coins only. PCGS Banknote has its own endpoints, but their responses carry no
price fields at all, so notes have nothing to read here.

Daily limit is 1,000 calls; responses are cached in `source_cache` for 7 days.
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

import httpx
from sqlalchemy.orm import Session

from app.models import Item
from app.services import app_settings
from app.services.pricing import (
    EstimateResult,
    NotApplicable,
    SourceUnavailable,
    cached_response,
)

API_ROOT = "https://api.pcgs.com/publicapi"
CACHE_TTL = timedelta(days=7)
# Auction lots to aggregate: enough to smooth one odd sale, few enough that
# the answer still reflects the current market rather than a decade of it.
APR_WINDOW = 10
DATE_FORMATS = ("%m-%d-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def pcgs_number(item: Item) -> str | None:
    """The PCGS number from a `pcgs` catalog reference."""
    for ref in item.catalog_refs:
        if ref.catalog.strip().lower() == "pcgs":
            code = ref.ref_code.strip()
            if code:
                return code
    return None


def cert_number(item: Item) -> str | None:
    """The cert number, but only when PCGS is the grading service."""
    if (item.cert_service or "").strip().upper() != "PCGS":
        return None
    cert = (item.cert_number or "").strip()
    return cert or None


def _request(token: str, path: str, params: dict | None = None) -> dict:
    """One upstream call. Raises SourceUnavailable; PCGS reports 'no such
    coin' in the body rather than by status, so that is the caller's problem."""
    try:
        resp = httpx.get(
            f"{API_ROOT}/{path}",
            params=params or {},
            headers={"Authorization": f"bearer {token}"},
            timeout=10.0,
        )
        if resp.status_code == 204:  # documented as empty request data
            return {"IsValidRequest": False, "ServerMessage": "PCGS received an empty request"}
        if resp.status_code == 500:
            # PCGS documents 500 as usually meaning invalid credentials.
            raise SourceUnavailable(
                "PCGS returned a server error — usually an expired or invalid token; "
                "regenerate it and update Settings"
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"PCGS request failed: {exc}") from exc
    except ValueError as exc:
        raise SourceUnavailable(f"PCGS returned invalid JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def check_payload(payload: dict) -> None:
    """Raise NotApplicable for the two documented in-body failures."""
    message = str(payload.get("ServerMessage") or "").strip()
    if not payload.get("IsValidRequest"):
        raise NotApplicable(f"PCGS rejected the lookup: {message or 'invalid request'}")
    if message.lower().startswith("no data"):
        raise NotApplicable("PCGS has no record of this coin")


def _amount(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def _sale_date(sale: dict) -> datetime | None:
    raw = str(sale.get("Date") or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw[:19] if "T" in raw else raw, fmt)
        except ValueError:
            continue
    return None


def recent_sales(payload: dict) -> list[Decimal]:
    """Prices of the most recent auction lots, newest first. Undated lots keep
    the order PCGS returned them in, behind everything dated."""
    lots = payload.get("AuctionList") or payload.get("Auctions") or []
    priced = [(_sale_date(lot), _amount(lot.get("Price"))) for lot in lots if isinstance(lot, dict)]
    dated = sorted(
        [(d, p) for d, p in priced if d is not None and p is not None],
        key=lambda pair: pair[0],
        reverse=True,
    )
    undated = [p for d, p in priced if d is None and p is not None]
    return [p for _, p in dated][:APR_WINDOW] + undated[: max(0, APR_WINDOW - len(dated))]


def pcgs_estimate(db: Session, item: Item) -> EstimateResult:
    """Price a coin from PCGS. Raises NotApplicable/SourceUnavailable."""
    token = str(app_settings.get_setting(db, "pcgs_api_token"))
    if not token:
        raise NotApplicable("Add a PCGS API token in Settings to price items from PCGS")
    if item.type != "coin":
        raise NotApplicable("PCGS prices coins only — its banknote data carries no values")

    cert = cert_number(item)
    if cert is not None:
        path = f"coindetail/GetCoinFactsByCertNo/{cert}"
        params = {"retrieveAllData": "true"}
        cache_key = f"certfacts:{cert}"
        matched = f"cert {cert}"
    else:
        number = pcgs_number(item)
        if number is None:
            raise NotApplicable(
                "Add a PCGS cert number, or a 'pcgs' catalog reference, to price this item"
            )
        if item.grade is None:
            raise NotApplicable("Set the item's grade — PCGS quotes values per grade")
        if item.grade.scale != "sheldon":
            raise NotApplicable("PCGS values are quoted on the Sheldon scale — regrade to use it")
        path = "coindetail/GetCoinFactsByGrade"
        params = {"PCGSNo": number, "GradeNo": item.grade.rank, "PlusGrade": "false"}
        cache_key = f"gradefacts:{number}:{item.grade.rank}"
        matched = f"#{number} {item.grade.code}"

    payload = cached_response(
        db, "pcgs", cache_key, CACHE_TTL, lambda: _request(token, path, params)
    )
    check_payload(payload)

    sales = recent_sales(payload)
    if sales:
        per_piece = Decimal(median(sales))
        # Real sales beat a book value; more of them beat fewer.
        confidence = Decimal("0.85") if len(sales) >= 5 else Decimal("0.75")
        source = f"pcgs:apr {matched}"
        sample_size = len(sales)
    else:
        per_piece = _amount(payload.get("PriceGuideValue"))
        if per_piece is None:
            raise NotApplicable(f"PCGS has no auction sales or price-guide value for {matched}")
        confidence = Decimal("0.60")
        source = f"pcgs:guide {matched}"
        sample_size = None

    return EstimateResult(
        source=source,
        estimated_value=(per_piece * item.quantity).quantize(Decimal("0.01")),
        currency="USD",  # PCGS quotes US dollars
        confidence=confidence,
        sample_size=sample_size,
    )
