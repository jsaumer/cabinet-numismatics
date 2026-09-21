"""Roadmap Phase 7, P10 "group C" dashboard widgets: quality, value spread,
data health, and the showcase pieces. Split out of routers/stats.py so that
router stays a thin layer over these computations.
"""

import hashlib
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Item
from app.services.currency import Converter
from app.services.pricing import detect_metal, effective_fineness, resolve_display_value


def _owned(db: Session) -> list[Item]:
    return (
        db.execute(
            select(Item)
            .where(Item.status == "owned")
            .options(selectinload(Item.estimates), selectinload(Item.photos))
        )
        .scalars()
        .all()
    )


def quality_stats(db: Session, currency: str, strategy: str, preferred_source: str | None) -> dict:
    """Certified vs. raw counts and value, and a breakdown by grading
    service, for owned items. "Certified" means a cert service or number."""
    conv = Converter(db, currency)
    owned = _owned(db)
    certified = {"items": 0, "value": 0.0}
    raw = {"items": 0, "value": 0.0}
    by_service: dict[str, dict] = defaultdict(lambda: {"count": 0, "estimated_value": 0.0})
    graded = 0

    for item in owned:
        resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)
        value = (conv.convert(resolved[0], resolved[1]) if resolved else None) or 0.0
        is_certified = bool(item.cert_service or item.cert_number)
        bucket = certified if is_certified else raw
        bucket["items"] += 1
        bucket["value"] += value
        if is_certified and item.cert_service:
            entry = by_service[item.cert_service]
            entry["count"] += 1
            entry["estimated_value"] += value
        if item.grade_id is not None:
            graded += 1

    return {
        "currency": currency,
        "owned": len(owned),
        "certified": {"items": certified["items"], "value": round(certified["value"], 2)},
        "raw": {"items": raw["items"], "value": round(raw["value"], 2)},
        "by_service": [
            {"key": key, "count": v["count"], "estimated_value": round(v["estimated_value"], 2)}
            for key, v in sorted(by_service.items(), key=lambda kv: -kv[1]["estimated_value"])
        ],
        "graded": graded,
        "ungraded": len(owned) - graded,
    }


def value_spread(db: Session, currency: str, strategy: str, preferred_source: str | None) -> dict:
    """Distribution of owned items' shown values: min/median/max/mean, and
    the share of total value held by the top 10% (at least one item)."""
    conv = Converter(db, currency)
    values = []
    for item in _owned(db):
        resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)
        value = conv.convert(resolved[0], resolved[1]) if resolved else None
        if value is not None:
            values.append(value)

    if not values:
        return {
            "currency": currency,
            "items": 0,
            "min": None,
            "median": None,
            "max": None,
            "mean": None,
            "top_share_pct": None,
        }

    ordered = sorted(values, reverse=True)
    total = sum(ordered)
    top_n = max(1, round(len(ordered) * 0.1))
    top_share = (sum(ordered[:top_n]) / total * 100) if total > 0 else None
    return {
        "currency": currency,
        "items": len(values),
        "min": round(min(values), 2),
        "median": round(median(values), 2),
        "max": round(max(values), 2),
        "mean": round(mean(values), 2),
        "top_share_pct": round(top_share, 2) if top_share is not None else None,
    }


# key, label, and a predicate (item) -> bool for each data-health check.
_CHECKS = [
    ("no_photo", "No photo", lambda i: not i.photos),
    ("no_grade", "No grade", lambda i: i.grade_id is None),
    ("no_cost", "No cost basis", lambda i: i.cost_basis is None),
    ("no_value", "No value estimate", lambda i: not i.estimates),
    (
        "no_weight",
        "No weight or fineness for a precious metal",
        lambda i: (
            detect_metal(i.composition) is not None
            and (i.weight_g is None or effective_fineness(i) is None)
        ),
    ),
    ("no_storage", "No storage location", lambda i: not i.storage_location),
    ("no_reference", "No catalogue reference", lambda i: not i.catalog_refs),
]


def data_health(db: Session) -> dict:
    """Owned items missing something worth having: a photo, a grade, a cost,
    a value estimate, weight/fineness for a precious metal, storage, or a
    catalogue reference. Each check lists the first 5 items."""
    owned = (
        db.execute(
            select(Item)
            .where(Item.status == "owned")
            .options(
                selectinload(Item.estimates),
                selectinload(Item.photos),
                selectinload(Item.catalog_refs),
            )
        )
        .scalars()
        .all()
    )
    checks = []
    for key, label, predicate in _CHECKS:
        matches = [item for item in owned if predicate(item)]
        checks.append(
            {
                "key": key,
                "label": label,
                "count": len(matches),
                "items": [{"id": i.id, "label": i.label} for i in matches[:5]],
            }
        )
    return {"owned": len(owned), "checks": checks}


def _piece(
    item: Item | None, strategy: str, preferred_source: str | None, conv: Converter
) -> dict | None:
    if item is None:
        return None
    primary = next((p for p in item.photos if p.is_primary), None)
    if primary is None and item.photos:
        primary = item.photos[0]
    resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)
    value = conv.convert(resolved[0], resolved[1]) if resolved else None
    return {
        "id": item.id,
        "label": item.label,
        "year_label": item.year_label,
        "thumb_key": (primary.thumb_key or primary.file_key) if primary else None,
        "photo_key": primary.file_key if primary else None,
        "value": value,
        "currency": conv.display if value is not None else None,
        "acquisition_date": item.acquisition_date,
    }


def showcase(db: Session, currency: str, strategy: str, preferred_source: str | None) -> dict:
    """Piece of the day (deterministic per calendar day, preferring a
    photographed piece), the oldest and newest pieces, and pieces acquired on
    this day in an earlier year. Owned items only, trashed items already
    hidden by the ORM."""
    conv = Converter(db, currency)
    owned = _owned(db)
    today = datetime.now(timezone.utc).date()

    photographed = sorted((i for i in owned if i.photos), key=lambda i: str(i.id))
    pool = photographed or sorted(owned, key=lambda i: str(i.id))
    piece_of_the_day = None
    if pool:
        seed = int(hashlib.sha256(today.isoformat().encode()).hexdigest(), 16)
        piece_of_the_day = pool[seed % len(pool)]

    dated = [i for i in owned if i.year is not None]
    oldest = min(dated, key=lambda i: (i.year, str(i.id))) if dated else None

    def _acquired_key(item: Item) -> date:
        return item.acquisition_date or item.created_at.date()

    newest = max(owned, key=lambda i: (_acquired_key(i), i.created_at)) if owned else None

    on_this_day = sorted(
        (
            i
            for i in owned
            if i.acquisition_date is not None
            and i.acquisition_date.year < today.year
            and (i.acquisition_date.month, i.acquisition_date.day) == (today.month, today.day)
        ),
        key=lambda i: i.acquisition_date.year,
    )

    return {
        "piece_of_the_day": _piece(piece_of_the_day, strategy, preferred_source, conv),
        "oldest": _piece(oldest, strategy, preferred_source, conv),
        "newest": _piece(newest, strategy, preferred_source, conv),
        "on_this_day": [_piece(i, strategy, preferred_source, conv) for i in on_this_day],
    }
