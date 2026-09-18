"""Pricing reports (pricing program M5): where estimates are missing, old,
disagreeing, or wrong. Read-only views over estimates, recorded pricing
attempts, and settings — nothing here calls an upstream source.

Every report groups estimates by source key: `melt`, `numista`, `pcgs`, and
`manual` for anything entered by hand (whatever its free-text source).
"""

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import EstimateAttempt, Item, PriceEstimate
from app.schemas import (
    AccuracyEstimate,
    AccuracyItem,
    AccuracyReport,
    AccuracySummary,
    CoverageItem,
    Disagreement,
    PricingCoverage,
    SourceBreakdown,
    SourceCoverage,
    SourceCoverageSummary,
    SourcesReport,
    StaleEstimate,
    StaleReport,
)
from app.services import pricing
from app.services.app_settings import get_setting
from app.services.currency import Converter

REPORT_SOURCES = (*pricing.ADAPTER_NAMES, "manual")
DISAGREEMENT_LIMIT = 10


def report_key(source: str) -> str:
    key = pricing.source_key(source)
    return key if key in pricing.ADAPTER_NAMES else "manual"


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load(db: Session, status: str) -> list[Item]:
    return (
        db.execute(
            select(Item)
            .where(Item.status == status)
            .options(
                selectinload(Item.estimates),
                selectinload(Item.catalog_refs),
                selectinload(Item.comparables),
            )
        )
        .scalars()
        .all()
    )


def _latest_by_key(estimates: list[PriceEstimate]) -> dict[str, PriceEstimate]:
    """Each source's most recent estimate (input is newest-first)."""
    latest: dict[str, PriceEstimate] = {}
    for est in estimates:
        latest.setdefault(report_key(est.source), est)
    return latest


def _strategy(db: Session) -> tuple[str, str | None]:
    return str(get_setting(db, "value_strategy")), get_setting(db, "preferred_source")


def _display_ids(estimates: list[PriceEstimate], strategy: str, preferred: str | None) -> set:
    """Which estimates feed the item's shown value — the same choice
    `pricing.resolve_display_value` makes, minus currency conversion."""
    if not estimates:
        return set()
    if strategy == "preferred_source" and preferred:
        for est in estimates:
            if pricing.source_key(est.source) == preferred:
                return {est.id}
    elif strategy == "average":
        chosen: dict[str, object] = {}
        for est in estimates:
            key = pricing.source_key(est.source)
            if key in pricing.AVERAGEABLE_SOURCES:
                chosen.setdefault(key, est.id)
        if chosen:
            return set(chosen.values())
    return {estimates[0].id}


# ---------------------------------------------------------------- coverage


def _source_status(
    db: Session,
    item: Item,
    source: str,
    enabled: bool,
    estimate: PriceEstimate | None,
    attempt: EstimateAttempt | None,
) -> SourceCoverage:
    estimated_at = estimate.fetched_at if estimate else None
    attempted_at = attempt.attempted_at if attempt else None

    def status(name: str, reason: str | None = None) -> SourceCoverage:
        return SourceCoverage(
            source=source,
            status=name,
            reason=reason,
            estimated_at=estimated_at,
            attempted_at=attempted_at,
        )

    if estimate is not None:
        # An estimate exists, but a later attempt may not have produced a new one.
        if (
            attempt is not None
            and attempt.outcome != "ok"
            and _utc(attempt.attempted_at) > _utc(estimate.fetched_at)
        ):
            name = "failed" if attempt.outcome == "unavailable" else "not_applicable"
            return status(name, attempt.message)
        return status("priced")
    if not enabled:
        return status("disabled", "Turned off in Settings")
    reason = pricing.get_prerequisite(source)(db, item)
    if reason:
        return status("not_applicable", reason)
    if attempt is not None and attempt.outcome == "unavailable":
        return status("failed", attempt.message)
    if attempt is not None and attempt.outcome == "not_applicable":
        return status("not_applicable", attempt.message)
    return status("not_tried", "Ready to price — no attempt recorded yet")


def coverage(db: Session) -> PricingCoverage:
    """Owned items and, per automatic source, whether each is priced — and if
    not, why: switched off, a missing prerequisite, what the source said, a
    failed fetch, or simply never tried."""
    items = _load(db, "owned")
    attempts = {(a.item_id, a.source): a for a in db.execute(select(EstimateAttempt)).scalars()}
    enabled = {s: bool(get_setting(db, f"{s}_enabled")) for s in pricing.ADAPTER_NAMES}
    counts = {s: defaultdict(int) for s in pricing.ADAPTER_NAMES}
    estimated = manual_only = 0
    listed: list[CoverageItem] = []

    for item in items:
        latest = _latest_by_key(item.estimates)
        if latest:
            estimated += 1
            if set(latest) == {"manual"}:
                manual_only += 1
        statuses = [
            _source_status(db, item, s, enabled[s], latest.get(s), attempts.get((item.id, s)))
            for s in pricing.ADAPTER_NAMES
        ]
        for sc in statuses:
            counts[sc.source][sc.status] += 1
        needs_attention = not latest or any(
            sc.status in ("failed", "not_tried")
            or (sc.estimated_at is not None and sc.status != "priced")
            for sc in statuses
        )
        if needs_attention:
            listed.append(
                CoverageItem(
                    item_id=item.id, label=item.label, has_estimate=bool(latest), sources=statuses
                )
            )

    listed.sort(key=lambda entry: (entry.has_estimate, entry.label))
    return PricingCoverage(
        owned_items=len(items),
        estimated_items=estimated,
        manual_only_items=manual_only,
        sources=[
            SourceCoverageSummary(
                source=s,
                enabled=enabled[s],
                priced=counts[s]["priced"],
                not_applicable=counts[s]["not_applicable"],
                failed=counts[s]["failed"],
                not_tried=counts[s]["not_tried"],
            )
            for s in pricing.ADAPTER_NAMES
        ],
        items=listed,
    )


# ---------------------------------------------------------------- stale


def stale(db: Session, days: int) -> StaleReport:
    """Each owned item's latest estimate per source that is `days` old or more,
    or that was produced from upstream data already past its cache window."""
    now = datetime.now(timezone.utc)
    strategy, preferred = _strategy(db)
    checked = 0
    entries: list[StaleEstimate] = []

    for item in _load(db, "owned"):
        shown = _display_ids(item.estimates, strategy, preferred)
        for key, est in _latest_by_key(item.estimates).items():
            checked += 1
            age = now - _utc(est.fetched_at)
            upstream_stale = bool((est.details or {}).get("stale"))
            if age.days < days and not upstream_stale:
                continue
            entries.append(
                StaleEstimate(
                    item_id=item.id,
                    label=item.label,
                    source=key,
                    source_label=est.source,
                    estimated_value=float(est.estimated_value),
                    currency=est.currency,
                    fetched_at=est.fetched_at,
                    age_days=age.days,
                    upstream_stale=upstream_stale,
                    in_totals=est.id in shown,
                )
            )

    entries.sort(key=lambda e: (-e.age_days, e.label))
    return StaleReport(days=days, checked=checked, stale=entries)


# ---------------------------------------------------------------- sources


def sources(db: Session, currency: str) -> SourcesReport:
    """Per source: how many owned items it prices, what those latest
    estimates add up to, how confident and how old they are, and how many
    items' shown value it supplies. Plus the items whose sources disagree most."""
    now = datetime.now(timezone.utc)
    conv = Converter(db, currency)
    strategy, preferred = _strategy(db)
    acc = {
        s: {"items": 0, "total": 0.0, "confidence": [], "ages": [], "in_totals": 0}
        for s in REPORT_SOURCES
    }
    averaged = 0
    disagreements: list[Disagreement] = []

    for item in _load(db, "owned"):
        values: dict[str, float] = {}
        for key, est in _latest_by_key(item.estimates).items():
            row = acc[key]
            row["items"] += 1
            value = conv.convert(est.estimated_value, est.currency)
            if value is not None:
                row["total"] += value
                values[key] = value
            if est.confidence is not None:
                row["confidence"].append(float(est.confidence))
            row["ages"].append((now - _utc(est.fetched_at)).total_seconds() / 86400)

        resolved = pricing.resolve_display_value(item.estimates, strategy, preferred, conv)
        if resolved is not None:
            if resolved[2] == "average":
                averaged += 1
            else:
                acc[report_key(resolved[2])]["in_totals"] += 1

        if len(values) >= 2 and min(values.values()) > 0:
            low, high = min(values.values()), max(values.values())
            disagreements.append(
                Disagreement(
                    item_id=item.id,
                    label=item.label,
                    values={k: round(v, 2) for k, v in values.items()},
                    spread_pct=round((high - low) / low * 100, 1),
                )
            )

    disagreements.sort(key=lambda d: -d.spread_pct)
    return SourcesReport(
        currency=currency,
        strategy=strategy,
        preferred_source=preferred,
        sources=[
            SourceBreakdown(
                source=s,
                items=row["items"],
                total_value=round(row["total"], 2),
                avg_confidence=round(mean(row["confidence"]), 2) if row["confidence"] else None,
                median_age_days=round(median(row["ages"]), 1) if row["ages"] else None,
                in_totals=row["in_totals"],
            )
            for s, row in acc.items()
            if s in pricing.ADAPTER_NAMES or row["items"]
        ],
        averaged_items=averaged,
        disagreements=disagreements[:DISAGREEMENT_LIMIT],
        excluded_other_currency=conv.excluded,
    )


# ---------------------------------------------------------------- accuracy


def _error_pct(estimate: float, sold: float) -> float:
    return round((estimate - sold) / sold * 100, 1)


def accuracy(db: Session, currency: str) -> AccuracyReport:
    """Sold items: the estimates that stood on the sale date (the latest per
    source, and the shown value) against the realized price. Estimates
    recorded after the sale date are ignored — they aren't predictions."""
    conv = Converter(db, currency)
    strategy, preferred = _strategy(db)
    errors: dict[str, list[float]] = defaultdict(list)
    sold_items = 0
    compared: list[AccuracyItem] = []

    for item in _load(db, "sold"):
        if item.sold_price is None:
            continue
        sold_items += 1
        sold = conv.convert(item.sold_price, item.currency)
        if sold is None or sold <= 0:
            continue
        before = [
            e
            for e in item.estimates
            if item.sold_date is None or _utc(e.fetched_at).date() <= item.sold_date
        ]
        by_source: list[AccuracyEstimate] = []
        for key, est in _latest_by_key(before).items():
            value = conv.convert(est.estimated_value, est.currency)
            if value is None:
                continue
            entry = AccuracyEstimate(
                source=key,
                value=round(value, 2),
                error_pct=_error_pct(value, sold),
                estimated_at=est.fetched_at,
            )
            by_source.append(entry)
            errors[key].append(entry.error_pct)

        blended = None
        resolved = pricing.resolve_display_value(before, strategy, preferred, conv)
        value = conv.convert(resolved[0], resolved[1]) if resolved else None
        if value is not None:
            label = resolved[2] if resolved[2] == "average" else report_key(resolved[2])
            blended = AccuracyEstimate(
                source=label, value=round(value, 2), error_pct=_error_pct(value, sold)
            )
            errors["blended"].append(blended.error_pct)

        if blended is not None or by_source:
            compared.append(
                AccuracyItem(
                    item_id=item.id,
                    label=item.label,
                    sold_date=item.sold_date,
                    sold_price=round(sold, 2),
                    blended=blended,
                    by_source=by_source,
                )
            )

    compared.sort(key=lambda i: -abs(i.blended.error_pct) if i.blended else 0)
    return AccuracyReport(
        currency=currency,
        sold_items=sold_items,
        compared_items=len(compared),
        summary=[
            AccuracySummary(
                source=key,
                sales=len(values),
                median_abs_error_pct=round(median(abs(v) for v in values), 1),
                mean_error_pct=round(mean(values), 1),
                within_20_pct=sum(1 for v in values if abs(v) <= 20),
            )
            for key in ("blended", *REPORT_SOURCES)
            if (values := errors.get(key))
        ],
        items=compared,
        excluded_other_currency=conv.excluded,
    )
