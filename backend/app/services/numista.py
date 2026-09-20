"""Numista price adapter (pricing program M2).

Numista prices an *issue* (a catalogue type narrowed to a year and mint) and
quotes it per grade bucket. The adapter resolves that chain: the item's
`numista` catalog ref gives the type, the type's issues are matched against the
item's year (and mint mark), and the item's grade is mapped onto Numista's
seven buckets.

Free API keys allow 2,000 requests a month, so every upstream response is
cached in `source_cache` (catalogue data and prices for 7 days, the longest
Numista's API licence (§8.3) allows for catalogue data), and a stale entry is
preferred over a failed request, the same discipline spot prices and exchange
rates use.

Confidence is medium: these are collector-swap-derived estimates, not realized
auction prices. Money is per row, so the per-piece price is multiplied by the
item's quantity.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

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
    detect_metal,
    freshness,
)

API_ROOT = "https://api.numista.com/api/v3"
CATALOG_TTL = timedelta(days=7)  # the licence caps catalogue caching at 7 days
PRICE_TTL = timedelta(days=7)

# Numista's grade buckets, worst to best.
GRADE_BUCKETS = ("g", "vg", "f", "vf", "xf", "au", "unc")
# Cabinet grade ranks (Sheldon and PMG share the 1–70 scale) → bucket.
_RANK_CUTOFFS = ((8, "g"), (12, "vg"), (20, "f"), (40, "vf"), (50, "xf"), (60, "au"))


class _NotFound(Exception):
    """Upstream 404: the catalogue has no such type or issue."""


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


def _request(
    api_key: str, path: str, params: dict | None = None, forbidden: str | None = None
) -> dict:
    """One upstream call. Raises _NotFound or SourceUnavailable; a 403 raises
    `NotApplicable(forbidden)` when given (an endpoint the key's plan lacks)."""
    try:
        resp = httpx.get(
            f"{API_ROOT}/{path}",
            params=params or {},
            headers={"Numista-API-Key": api_key},
            timeout=10.0,
        )
        if resp.status_code == 404:
            raise _NotFound()
        if resp.status_code == 403 and forbidden:
            raise NotApplicable(forbidden)
        if resp.status_code in (401, 403):
            raise KeyRejected("Numista rejected the API key. Check it in Settings")
        if resp.status_code == 429:
            raise QuotaExhausted("Numista request quota exhausted. Try again later")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"Numista request failed: {exc}") from exc
    except ValueError as exc:
        raise SourceUnavailable(f"Numista returned invalid JSON: {exc}") from exc
    # A bare list (the issues endpoint) is wrapped so the cache column stays a dict.
    return data if isinstance(data, dict) else {"items": data}


def _cached(
    db: Session, cache_key: str, ttl: timedelta, api_key: str, path: str, params=None
) -> tuple[dict, datetime]:
    return cached_fetch(db, "numista", cache_key, ttl, lambda: _request(api_key, path, params))


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
    """The wanted bucket if priced, else the nearest one, preferring the
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


def prerequisite(db: Session, item: Item) -> str | None:
    """What stops Numista pricing this item before any request, or None."""
    if not str(app_settings.get_setting(db, "numista_api_key")):
        return "Add a Numista API key in Settings to price items from Numista"
    if type_id_for(item) is None:
        return "Add a 'numista' catalog reference (e.g. N#1234) to price this item"
    if item.grade is None:
        return "Set the item's grade: Numista quotes prices per grade"
    if item.strike != "business":
        return "Numista prices circulation strikes by grade, not proofs or specimens"
    if item.grade_details:
        return "Numista prices problem-free pieces, and this one has a details grade"
    return None


def numista_estimate(db: Session, item: Item) -> EstimateResult:
    """Price an item from Numista. Raises NotApplicable/SourceUnavailable."""
    reason = prerequisite(db, item)
    if reason:
        raise NotApplicable(reason)
    api_key = str(app_settings.get_setting(db, "numista_api_key"))
    type_id = type_id_for(item)

    wanted = bucket_for_rank(item.grade.rank)
    currency = app_settings.display_currency(db)

    try:
        issues_payload, _ = _cached(
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
        payload, prices_fetched_at = _cached(
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
    quoted_currency = _currency_of(payload, currency)
    mint_letter = issue.get("mint_letter")
    return EstimateResult(
        source=source,
        estimated_value=value,
        currency=quoted_currency,
        confidence=Decimal("0.60") if exact else Decimal("0.45"),
        details={
            "type_id": type_id,
            "issue_id": issue_id,
            "issue_year": _issue_year(issue),
            "mint_letter": str(mint_letter) if mint_letter else None,
            "grade_wanted": wanted,
            "grade_used": used,
            "prices": {g: float(prices[g]) for g in GRADE_BUCKETS if g in prices},
            "currency": quoted_currency,
            "quantity": item.quantity,
            **freshness(prices_fetched_at, PRICE_TTL),
        },
    )


# ---------------------------------------------------------------- catalogue lookup
# Filling an item in from the catalogue (roadmap Phase 5.7 C5). Same key, cache,
# and quota as pricing; a type's issues share their cache entry with pricing.

SEARCH_RESULTS = 20

# Longest values the item schema accepts, so a filled form always saves.
_LIMITS = {"country": 100, "denomination": 100, "series": 200, "composition": 100,
           "edge": 100, "shape": 50, "issuer": 200}  # fmt: skip

_FINENESS_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_FINENESS_DECIMAL = re.compile(r"(?<![\d.])0?\.(\d{3,4})(?!\d)")
_FINENESS_MILLESIMAL = re.compile(r"(?<![\d.,])(\d{3}(?:\.\d+)?)(?![\d%])")


class CatalogueNotFound(LookupError):
    """Numista has no such type."""


def _lookup_key(db: Session) -> str:
    api_key = str(app_settings.get_setting(db, "numista_api_key"))
    if not api_key:
        raise NotApplicable("Add a Numista API key in Settings to look items up on Numista")
    return api_key


def _clean(value, limit: int | None = None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())
    return text[:limit] if limit else text


def _number(value, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 < value <= maximum else None


def fineness_from_composition(text: str | None) -> float | None:
    """Fineness written into a composition, for precious metals only: "Silver
    (.900)", "90% silver", "Gold 916.7", "Silver 999"."""
    if not text or detect_metal(text) is None:
        return None
    candidates = []
    if match := _FINENESS_PERCENT.search(text):
        candidates.append(float(match.group(1)) / 100)
    if match := _FINENESS_DECIMAL.search(text):
        candidates.append(float(f"0.{match.group(1)}"))
    if match := _FINENESS_MILLESIMAL.search(text):
        candidates.append(float(match.group(1)) / 1000)
    for value in candidates:
        if 0 < value <= 1:
            return round(value, 4)
    return None


def search_types(db: Session, query: str, category: str | None = None) -> dict:
    """Catalogue search: types matching `query`, optionally one category."""
    api_key = _lookup_key(db)
    q = " ".join(query.split())
    params = {"q": q, "count": SEARCH_RESULTS}
    if category:
        params["category"] = category
    payload, _ = _cached(
        db, f"search:{category or 'all'}:{q.lower()}", CATALOG_TTL, api_key, "types", params
    )
    results = []
    for found in payload.get("types") or []:
        if not isinstance(found, dict) or not isinstance(found.get("id"), int):
            continue
        issuer = found.get("issuer") if isinstance(found.get("issuer"), dict) else {}
        results.append(
            {
                "type_id": found["id"],
                "title": _clean(found.get("title")) or f"N#{found['id']}",
                "category": _clean(found.get("category")),
                "issuer": _clean(issuer.get("name")),
                "min_year": found.get("min_year")
                if isinstance(found.get("min_year"), int)
                else None,
                "max_year": found.get("max_year")
                if isinstance(found.get("max_year"), int)
                else None,
                "thumbnail": _clean(found.get("obverse_thumbnail")),
            }
        )
    count = payload.get("count")
    return {"count": int(count) if str(count).isdigit() else len(results), "results": results}


def catalogue_fields(payload: dict) -> dict:
    """Item fields a catalogue type fills in, keyed like the item schema.
    Only values Numista actually has are included."""
    note = payload.get("category") == "banknote"
    issuer = payload.get("issuer") if isinstance(payload.get("issuer"), dict) else {}
    value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
    composition = payload.get("composition")
    composition_text = composition.get("text") if isinstance(composition, dict) else None
    min_year, max_year = payload.get("min_year"), payload.get("max_year")
    fields = {
        "type": "note" if note else "coin",
        "country": _clean(issuer.get("name"), _LIMITS["country"]),
        "denomination": _clean(value.get("text"), _LIMITS["denomination"]),
        "year": min_year if isinstance(min_year, int) and min_year == max_year else None,
        "series": _clean(payload.get("series"), _LIMITS["series"]),
        "composition": _clean(composition_text, _LIMITS["composition"]),
        "fineness": fineness_from_composition(composition_text),
    }
    if note:
        entity = payload.get("issuing_entity")
        fields["issuer"] = (
            _clean(entity.get("name"), _LIMITS["issuer"]) if isinstance(entity, dict) else None
        )
    else:
        edge = payload.get("edge")
        fields.update(
            weight_g=_number(payload.get("weight"), 100_000),
            diameter_mm=_number(payload.get("size"), 1000),
            thickness_mm=_number(payload.get("thickness"), 100),
            shape=_clean(payload.get("shape"), _LIMITS["shape"]),
            edge=_clean(edge.get("description"), _LIMITS["edge"])
            if isinstance(edge, dict)
            else None,
        )
    return {key: value for key, value in fields.items() if value is not None}


def catalogue_refs(type_id: int, payload: dict) -> list[dict]:
    """The Numista number plus the type's references in other catalogues."""
    refs = [{"catalog": "numista", "ref_code": f"N#{type_id}"}]
    for ref in payload.get("references") or []:
        catalogue = ref.get("catalogue") if isinstance(ref, dict) else None
        code = _clean(catalogue.get("code")) if isinstance(catalogue, dict) else None
        number = _clean(ref.get("number")) if isinstance(ref, dict) else None
        if code and number:
            refs.append({"catalog": code.lower()[:50], "ref_code": f"{code}#{number}"[:100]})
    return refs


def catalogue_type(db: Session, type_id: int) -> dict:
    """One catalogue type, as fields ready to fill into an item, plus its
    issues (year, mint letter, mintage) for picking the exact one."""
    api_key = _lookup_key(db)
    try:
        payload, _ = _cached(db, f"type:{type_id}", CATALOG_TTL, api_key, f"types/{type_id}")
    except _NotFound:
        raise CatalogueNotFound(f"Numista has no type N#{type_id}") from None
    try:
        issues_payload, _ = _cached(
            db, f"issues:{type_id}", CATALOG_TTL, api_key, f"types/{type_id}/issues"
        )
        issues = issues_payload.get("issues") or issues_payload.get("items") or []
    except (_NotFound, SourceUnavailable):
        issues = []  # the type alone is enough to fill the form
    return {
        "type_id": type_id,
        "title": _clean(payload.get("title")) or f"N#{type_id}",
        "url": _clean(payload.get("url")),
        "category": _clean(payload.get("category")),
        "fields": catalogue_fields(payload),
        "catalog_refs": catalogue_refs(type_id, payload),
        "issues": [
            {
                "year": _issue_year(issue),
                "mint_letter": _clean(issue.get("mint_letter")),
                "mintage": issue["mintage"]
                if isinstance(issue.get("mintage"), int) and issue["mintage"] >= 0
                else None,
                "comment": _clean(issue.get("comment")),
            }
            for issue in issues
            if isinstance(issue, dict)
        ],
    }


# ---------------------------------------------------------------- auction sales
# Numista's record of past auction sales, fed into the item's sales log for the
# `comps` estimate (v0.17.0). The endpoint is part of Numista's *paid* API plan
# (€0.01 a request, after an activation fee and a monthly minimum); a free key
# gets 403 "Permission denied". So it sits behind its own setting, off by
# default, and runs only when asked, never on the refresh schedule.

SALES_TTL = timedelta(days=1)  # a second click the same day costs nothing
SALES_COUNT = 100
PAID_PLAN = (
    "Numista refused the auction-sales request. Sales records need Numista's paid "
    'API plan: a free key gets "Permission denied". See Settings → Price sources.'
)


def sales_prerequisite(db: Session, item: Item) -> str | None:
    """What stops fetching auction sales for this item, or None. No network."""
    if not app_settings.get_setting(db, "numista_sales_enabled"):
        return (
            "Numista auction sales are switched off in Settings (they need Numista's paid API plan)"
        )
    if not str(app_settings.get_setting(db, "numista_api_key")):
        return "Add a Numista API key in Settings to fetch auction sales"
    if type_id_for(item) is None:
        return "Add a 'numista' catalog reference (e.g. N#1234) to fetch auction sales"
    return None


def _money(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def sale_rows(payload: dict) -> list[dict]:
    """Numista sales records as sales-log fields. Records without a date, a
    house, or a positive price are skipped; pictures are not kept (they carry
    the auction house's copyright)."""
    rows = []
    for record in payload.get("sales_records") or []:
        if not isinstance(record, dict):
            continue
        house = record.get("auction_house") if isinstance(record.get("auction_house"), dict) else {}
        price = record.get("price") if isinstance(record.get("price"), dict) else {}
        amount = _money(price.get("amount"))
        currency = price.get("currency")
        venue = _clean(house.get("name"), 200)
        try:
            sold_on = datetime.strptime(str(record.get("auction_date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if amount is None or not venue or not isinstance(currency, str) or len(currency) != 3:
            continue
        grade = record.get("grade") if record.get("grade") in GRADE_BUCKETS else None
        lot = _clean(record.get("lot_number"), 50)
        url = _clean(record.get("lot_url"), 1000)
        premium = price.get("premium_included")
        rows.append(
            {
                "sold_on": sold_on,
                "venue": venue,
                "title": _clean(record.get("auction_title"), 300),
                "lot": lot,
                "url": url,
                "grade": _clean(record.get("grade_details"), 100) or (grade or "").upper() or None,
                "grade_bucket": grade,
                "price": amount,
                "currency": currency.upper(),
                "premium_included": premium if isinstance(premium, bool) else None,
                "external_id": (url or f"{house.get('id')}:{sold_on.isoformat()}:{lot}")[:300],
            }
        )
    return rows


def fetch_sales(db: Session, item: Item) -> tuple[list[dict], int | None]:
    """The item's issue's auction sales from Numista, as sales-log fields, and
    the matched issue id. Raises NotApplicable/SourceUnavailable."""
    reason = sales_prerequisite(db, item)
    if reason:
        raise NotApplicable(reason)
    api_key = str(app_settings.get_setting(db, "numista_api_key"))
    type_id = type_id_for(item)
    try:
        issues_payload, _ = _cached(
            db, f"issues:{type_id}", CATALOG_TTL, api_key, f"types/{type_id}/issues"
        )
    except _NotFound:
        raise NotApplicable(f"Numista has no type N#{type_id}") from None
    issue = pick_issue(issues_payload.get("issues") or issues_payload.get("items") or [], item)
    if issue is None or issue.get("id") is None:
        raise NotApplicable(f"Numista lists no {item.year} issue for N#{type_id}")
    issue_id = issue["id"]
    params = {"issue_id": issue_id, "count": SALES_COUNT}
    try:
        payload, _ = cached_fetch(
            db,
            "numista",
            f"sales:{type_id}:{issue_id}",
            SALES_TTL,
            lambda: _request(
                api_key, f"types/{type_id}/sales_records", params, forbidden=PAID_PLAN
            ),
        )
    except _NotFound:
        raise NotApplicable(f"Numista has no type N#{type_id}") from None
    return sale_rows(payload), issue_id


# ---------------------------------------------------------------- the user's collection
# Importing the collection on the user's own Numista account (v0.18.0). The API
# key authenticates as its owner through OAuth's client-credentials grant
# (scope `view_collection`), then one request returns every collected item.
# The collection is cached for an hour, so a preview and the import that
# follows it cost one fetch; catalogue details come from the same 7-day type
# cache as the item form's lookup, one request per type not already cached.

COLLECTION_TTL = timedelta(hours=1)


def _account_request(path: str, api_key: str, params: dict, token: str | None = None) -> dict:
    headers = {"Numista-API-Key": api_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(f"{API_ROOT}/{path}", params=params, headers=headers, timeout=30.0)
        if resp.status_code == 501:
            raise NotApplicable("This Numista API key isn't linked to a Numista account")
        if resp.status_code in (401, 403):
            raise KeyRejected(
                "Numista refused access to the collection. Check the API key in Settings"
            )
        if resp.status_code == 429:
            raise QuotaExhausted("Numista request quota exhausted. Try again later")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"Numista request failed: {exc}") from exc
    except ValueError as exc:
        raise SourceUnavailable(f"Numista returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceUnavailable("Numista returned an unexpected response")
    return data


def _load_collection(api_key: str) -> dict:
    grant = _account_request(
        "oauth_token", api_key, {"grant_type": "client_credentials", "scope": "view_collection"}
    )
    token, user_id = grant.get("access_token"), grant.get("user_id")
    if not token or not isinstance(user_id, int):
        raise SourceUnavailable("Numista didn't return an access token")
    payload = _account_request(f"users/{user_id}/collected_items", api_key, {}, token)
    items = payload.get("items")
    return {"user_id": user_id, "items": items if isinstance(items, list) else []}


def fetch_collection(db: Session) -> tuple[list[dict], datetime]:
    """The items in the key owner's Numista collection, and when they were
    fetched. Raises NotApplicable/SourceUnavailable."""
    api_key = str(app_settings.get_setting(db, "numista_api_key"))
    if not api_key:
        raise NotApplicable("Add your Numista API key in Settings to import your collection")
    owner = hashlib.sha256(api_key.encode()).hexdigest()[:16]  # a new key, a new collection
    payload, fetched_at = cached_fetch(
        db, "numista", f"collection:{owner}", COLLECTION_TTL, lambda: _load_collection(api_key)
    )
    return payload.get("items") or [], fetched_at


def cached_type_ids(db: Session, type_ids: set[int]) -> set[int]:
    """Which of these types have fresh catalogue data cached (no request needed)."""
    from app.models import SourceCache

    now = datetime.now(timezone.utc)
    fresh = set()
    for type_id in type_ids:
        row = db.get(SourceCache, ("numista", f"type:{type_id}"))
        if row is not None:
            fetched = (
                row.fetched_at
                if row.fetched_at.tzinfo
                else row.fetched_at.replace(tzinfo=timezone.utc)
            )
            if now - fetched < CATALOG_TTL:
                fresh.add(type_id)
    return fresh


def type_fields(db: Session, type_ids: set[int], fetch: bool) -> tuple[dict[int, dict], int]:
    """Item fields per catalogue type (`catalogue_fields`, plus the type's
    references as `catalog_refs`), from the cache, or fetched when `fetch`
    (one request per uncached type). Returns the fields found and how many
    types couldn't be looked up."""
    api_key = _lookup_key(db)
    fresh = cached_type_ids(db, type_ids)
    found: dict[int, dict] = {}
    missed = 0
    for type_id in sorted(type_ids):
        if type_id not in fresh and not fetch:
            missed += 1
            continue
        try:
            payload, _ = _cached(db, f"type:{type_id}", CATALOG_TTL, api_key, f"types/{type_id}")
        except (_NotFound, SourceUnavailable):
            missed += 1
            continue
        found[type_id] = {
            **catalogue_fields(payload),
            "catalog_refs": catalogue_refs(type_id, payload),
        }
    return found, missed
