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

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

import httpx
from sqlalchemy.orm import Session

from app.models import Item
from app.services import app_settings
from app.services.pricing import (
    EstimateResult,
    KeyRejected,
    NotApplicable,
    QuotaExhausted,
    SourceUnavailable,
    cached_fetch,
    freshness,
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
        if resp.status_code == 401:
            raise KeyRejected("PCGS rejected the API token — check it in Settings")
        if resp.status_code == 429:
            raise QuotaExhausted("PCGS request quota exhausted — try again tomorrow")
        if resp.status_code == 500:
            # PCGS documents 500 as usually meaning invalid credentials.
            raise KeyRejected(
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


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def recent_lots(payload: dict) -> list[dict]:
    """The most recent priced auction lots, newest first. Undated lots keep
    the order PCGS returned them in, behind everything dated."""
    lots = []
    for lot in payload.get("AuctionList") or payload.get("Auctions") or []:
        if not isinstance(lot, dict):
            continue
        price = _amount(lot.get("Price"))
        if price is None:
            continue
        lots.append(
            {
                "date": _sale_date(lot),
                "price": price,
                "auctioneer": _text(lot.get("Auctioneer")),
                "sale": _text(lot.get("SaleName")),
                "url": _text(lot.get("AuctionLotUrl")),
            }
        )
    dated = sorted(
        (lot for lot in lots if lot["date"] is not None), key=lambda lot: lot["date"], reverse=True
    )
    undated = [lot for lot in lots if lot["date"] is None]
    return dated[:APR_WINDOW] + undated[: max(0, APR_WINDOW - len(dated))]


def recent_sales(payload: dict) -> list[Decimal]:
    """Prices of the most recent auction lots, newest first."""
    return [lot["price"] for lot in recent_lots(payload)]


def prerequisite(db: Session, item: Item) -> str | None:
    """What stops PCGS pricing this item before any request, or None."""
    if not str(app_settings.get_setting(db, "pcgs_api_token")):
        return "Add a PCGS API token in Settings to price items from PCGS"
    if item.type != "coin":
        return "PCGS prices coins only — its banknote data carries no values"
    if cert_number(item) is not None:
        return None
    if pcgs_number(item) is None:
        return "Add a PCGS cert number, or a 'pcgs' catalog reference, to price this item"
    if item.grade is None:
        return "Set the item's grade — PCGS quotes values per grade"
    if item.grade.scale != "sheldon":
        return "PCGS values are quoted on the Sheldon scale — regrade to use it"
    if item.grade_details:
        return (
            "PCGS prices problem-free coins by grade, and this one has a details grade "
            "— a PCGS cert number still works"
        )
    return None


def pcgs_estimate(db: Session, item: Item) -> EstimateResult:
    """Price a coin from PCGS. Raises NotApplicable/SourceUnavailable."""
    reason = prerequisite(db, item)
    if reason:
        raise NotApplicable(reason)
    token = str(app_settings.get_setting(db, "pcgs_api_token"))

    cert = cert_number(item)
    if cert is not None:
        path = f"coindetail/GetCoinFactsByCertNo/{cert}"
        params = {"retrieveAllData": "true"}
        cache_key = f"certfacts:{cert}"
        matched = f"cert {cert}"
        lookup = {"lookup": "cert", "cert": cert}
    else:
        number = pcgs_number(item)  # present: prerequisite() checked it
        path = "coindetail/GetCoinFactsByGrade"
        # The PCGS number is strike-specific (proofs have their own), so the
        # grade number is the same one a business strike would use.
        plus = "true" if item.grade_plus else "false"
        params = {"PCGSNo": number, "GradeNo": item.grade.rank, "PlusGrade": plus}
        cache_key = f"gradefacts:{number}:{item.grade.rank}{'+' if item.grade_plus else ''}"
        matched = f"#{number} {item.grade_code}"
        lookup = {"lookup": "grade", "pcgs_number": number, "grade": item.grade_code}

    payload, fetched_at = cached_fetch(
        db, "pcgs", cache_key, CACHE_TTL, lambda: _request(token, path, params)
    )
    check_payload(payload)

    lots = recent_lots(payload)
    guide = _amount(payload.get("PriceGuideValue"))
    if lots:
        per_piece = Decimal(median(lot["price"] for lot in lots))
        # Real sales beat a book value; more of them beat fewer.
        confidence = Decimal("0.85") if len(lots) >= 5 else Decimal("0.75")
        source = f"pcgs:apr {matched}"
        sample_size = len(lots)
    else:
        per_piece = guide
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
        details={
            **lookup,
            "basis": "apr" if lots else "guide",
            "lots": [
                {
                    **lot,
                    "date": lot["date"].date().isoformat() if lot["date"] else None,
                    "price": float(lot["price"]),
                }
                for lot in lots
            ],
            "median": float(per_piece) if lots else None,
            "price_guide_value": float(guide) if guide is not None else None,
            "coinfacts_url": _text(payload.get("CoinFactsLink")),
            "quantity": item.quantity,
            **freshness(fetched_at, CACHE_TTL),
        },
    )


# --- Filling an item in from a cert (roadmap Phase 5.9, v0.22.0) ------------
#
# GetCoinFactsByCertNo answers the coin's identity as well as its price:
# PCGSNo, Name, Year, Denomination, MintMark, SeriesName, MetalContent,
# Weight, Diameter, Edge, Mintage, Grade, Designation, the varieties, and
# the population. The same cached response later prices the item, so a fill
# followed by an estimate costs one request.

# PCGS writes denominations as it prints them on labels.
DENOMINATIONS = {
    "1/2C": "half cent",
    "1C": "1 cent",
    "2C": "2 cents",
    "3CS": "3 cents (silver)",
    "3CN": "3 cents (nickel)",
    "5C": "5 cents",
    "H10C": "half dime",
    "10C": "10 cents",
    "20C": "20 cents",
    "25C": "25 cents",
    "50C": "50 cents",
    "$1": "1 dollar",
    "G$1": "1 dollar (gold)",
    "$2.50": "2.5 dollars",
    "$3": "3 dollars",
    "$4": "4 dollars",
    "$5": "5 dollars",
    "$10": "10 dollars",
    "$20": "20 dollars",
    "$25": "25 dollars",
    "$50": "50 dollars",
    "$100": "100 dollars",
}

# Designation codes Cabinet keeps (schemas.DESIGNATIONS); anything else PCGS
# prints stays in the grade's details text.
_DESIGNATION_CODES = {
    "PL",
    "DMPL",
    "CAM",
    "DCAM",
    "UCAM",
    "RD",
    "RB",
    "BN",
    "FB",
    "FBL",
    "FH",
    "FS",
    "FT",
}
_GRADE_RE = re.compile(
    r"^\s*(?P<prefix>PO|FR|AG|G|VG|F|VF|XF|EF|AU|MS|PR|PF|SP|SPL)?\s*-?\s*(?P<number>\d{1,2})"
    r"\s*(?P<plus>\+)?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


def parse_grade(grade: str | None, designation: str | None = None) -> dict | None:
    """ "MS64+", "PR-65 DCAM", "AU58" (with "FB" in Designation) → the Sheldon
    rank, strike, plus flag, and Cabinet's designation codes."""
    match = _GRADE_RE.match(str(grade or ""))
    if not match:
        return None
    rank = int(match.group("number"))
    if not 1 <= rank <= 70:
        return None
    prefix = (match.group("prefix") or "").upper()
    strike = (
        "proof" if prefix in ("PR", "PF") else "specimen" if prefix in ("SP", "SPL") else "business"
    )
    words = re.split(r"[\s,/]+", f"{match.group('rest')} {designation or ''}".upper())
    plus = bool(match.group("plus")) or "+" in words
    codes = [w for w in words if w in _DESIGNATION_CODES]
    return {
        "rank": rank,
        "strike": strike,
        "plus": plus,
        "designations": list(dict.fromkeys(codes)),
    }


def _mintage(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    digits = re.sub(r"[^\d]", "", str(value or ""))
    return int(digits) if digits else None


def _clean(value, limit: int) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit] if text else None


def cert_fields(cert: str, payload: dict) -> dict:
    """Item fields a cert lookup fills in, keyed like the item schema, plus
    the grade and what else PCGS knows about the coin."""
    denomination = _clean(payload.get("Denomination"), 100)
    varieties = [
        _clean(payload.get(key), 200) for key in ("MajorVariety", "MinorVariety", "DieVariety")
    ]
    variety = " · ".join(dict.fromkeys(v for v in varieties if v))
    fields = {
        "type": "coin",
        "country": _clean(payload.get("Country"), 100) or "United States",
        "denomination": DENOMINATIONS.get(denomination or "", denomination),
        "year": payload.get("Year") if isinstance(payload.get("Year"), int) else None,
        "mint_mark": _clean(payload.get("MintMark"), 10),
        "series": _clean(payload.get("SeriesName"), 200),
        "variety": variety[:200] or None,
        "composition": _clean(payload.get("MetalContent"), 100),
        "weight_g": _amount(payload.get("Weight")),
        "diameter_mm": _amount(payload.get("Diameter")),
        "edge": _clean(payload.get("Edge"), 100),
        "mintage": _mintage(payload.get("Mintage")),
        "cert_service": "PCGS",
        "cert_number": cert,
    }
    fields = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in fields.items() if v}
    number = _text(payload.get("PCGSNo"))
    return {
        "cert": cert,
        "pcgs_number": number,
        "name": _text(payload.get("Name")),
        "fields": fields,
        "grade": parse_grade(_text(payload.get("Grade")), _text(payload.get("Designation"))),
        "catalog_refs": [{"catalog": "pcgs", "ref_code": number}] if number else [],
        "population": payload.get("Population")
        if isinstance(payload.get("Population"), int)
        else None,
        "pop_higher": payload.get("PopHigher")
        if isinstance(payload.get("PopHigher"), int)
        else None,
        "price_guide_value": float(_amount(payload.get("PriceGuideValue")) or 0) or None,
        "coinfacts_url": _text(payload.get("CoinFactsLink")),
    }


def cert_facts(db: Session, cert: str) -> dict:
    """Look a PCGS cert up and describe the coin. Raises NotApplicable
    without a token or when PCGS has no such cert, SourceUnavailable when
    PCGS can't be reached."""
    token = str(app_settings.get_setting(db, "pcgs_api_token"))
    if not token:
        raise NotApplicable("Add a PCGS API token in Settings to fill items in from a cert")
    cert = re.sub(r"\D", "", cert)
    if not cert:
        raise NotApplicable("A PCGS cert number is digits only")
    payload, _ = cached_fetch(
        db,
        "pcgs",
        f"certfacts:{cert}",
        CACHE_TTL,
        lambda: _request(
            token, f"coindetail/GetCoinFactsByCertNo/{cert}", {"retrieveAllData": "true"}
        ),
    )
    check_payload(payload)
    return cert_fields(cert, payload)
