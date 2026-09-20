"""Prometheus metrics for /api/metrics, computed from the database when
scraped and cached for a minute: Prometheus typically scrapes every 15s, and
collection value walks every item's estimates.

Timestamps are Unix seconds, so an age is `time() - <metric>` in PromQL.
"""

import threading
import time
from datetime import datetime

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.models import Document, EstimateAttempt, Item, ItemPhoto
from app.services import alerts, schema
from app.services import app_settings as store
from app.services import backup as backups

CACHE_SECONDS = 60
_cache: dict = {"at": 0.0, "body": b""}
_lock = threading.Lock()


def _ts(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso).timestamp() if iso else None


def _gauge(name: str, doc: str, value: float | None = None, labels=()) -> GaugeMetricFamily:
    family = GaugeMetricFamily(name, doc, labels=list(labels))
    if value is not None and not labels:
        family.add_metric([], value)
    return family


def collect(db: Session) -> list:
    from app.routers.stats import collection_stats  # the dashboard's own totals

    families = []
    revision = None
    try:
        revision = schema.current_revision(db.connection())
    except Exception:
        pass
    expected, _ = schema.script_revisions()
    info = InfoMetricFamily("cabinet", "Cabinet version and schema revision")
    info.add_metric([], {"version": __version__, "schema": revision or "unknown"})
    families.append(info)
    families.append(
        _gauge(
            "cabinet_schema_up_to_date",
            "1 when the database is at the revision this build expects",
            1.0 if revision is not None and revision == expected else 0.0,
        )
    )

    items = _gauge(
        "cabinet_items", "Items by status and type, trash excluded", labels=("status", "type")
    )
    rows = db.execute(
        select(Item.status, Item.type, func.count())
        .where(Item.deleted_at.is_(None))
        .group_by(Item.status, Item.type)
    ).all()
    for status, kind, count in rows:
        items.add_metric([status, kind], count)
    families.append(items)
    trashed = db.execute(
        select(func.count())
        .select_from(Item)
        .where(Item.deleted_at.is_not(None))
        .execution_options(include_deleted=True)
    ).scalar_one()
    families.append(_gauge("cabinet_items_in_trash", "Items in the trash", trashed))
    families.append(
        _gauge(
            "cabinet_photos",
            "Photos, trash included",
            db.execute(select(func.count()).select_from(ItemPhoto)).scalar_one(),
        )
    )
    families.append(
        _gauge(
            "cabinet_documents",
            "Attached documents",
            db.execute(select(func.count()).select_from(Document)).scalar_one(),
        )
    )

    stats = collection_stats(currency=None, db=db)
    labels = ("currency",)
    for name, doc, value in (
        (
            "cabinet_collection_value",
            "Owned items' value, per the value strategy",
            stats.estimated_value,
        ),
        (
            "cabinet_collection_cost_basis",
            "Owned items' cost basis, fees included",
            stats.cost_basis,
        ),
        (
            "cabinet_unrealized_gain",
            "Owned items' value less cost, where both exist",
            stats.unrealized_gain,
        ),
        ("cabinet_realized_gain", "Sold items' proceeds less cost", stats.realized_gain),
    ):
        family = GaugeMetricFamily(name, doc, labels=list(labels))
        family.add_metric([stats.currency], value)
        families.append(family)
    families.append(
        _gauge("cabinet_items_valued", "Owned items with a value", stats.estimated_items)
    )
    families.append(
        _gauge(
            "cabinet_amounts_unconverted",
            "Amounts left out of the totals for lack of an exchange rate",
            stats.excluded_other_currency,
        )
    )

    families.extend(_backup_families(db))
    families.extend(_refresh_families(db))

    attempts = _gauge(
        "cabinet_estimate_attempts",
        "Each item's latest automatic estimate attempt per source, by outcome",
        labels=("source", "outcome"),
    )
    for source, outcome, count in db.execute(
        select(EstimateAttempt.source, EstimateAttempt.outcome, func.count())
        .join(Item, Item.id == EstimateAttempt.item_id)
        .where(Item.deleted_at.is_(None))
        .group_by(EstimateAttempt.source, EstimateAttempt.outcome)
    ).all():
        attempts.add_metric([source, outcome], count)
    families.append(attempts)

    failing = alerts.failing(db)
    alert = _gauge(
        "cabinet_alert_failing", "1 while an alert condition is failing", labels=("alert",)
    )
    for key in alerts.CONDITIONS:
        alert.add_metric([key], 1.0 if key in failing else 0.0)
    families.append(alert)
    for name, outcome in (
        ("cabinet_alert_delivery_success", alerts.last_delivery()),
        ("cabinet_heartbeat_success", alerts.last_heartbeat()),
    ):
        if outcome:
            families.append(
                _gauge(name, "1 if the last attempt succeeded", 1.0 if outcome["ok"] else 0.0)
            )
    return families


def _backup_families(db: Session) -> list:
    families = [
        _gauge(
            "cabinet_backup_scheduled",
            "1 when scheduled backups are on",
            1.0 if store.get_setting(db, "backup_schedule") else 0.0,
        )
    ]
    last = store.get_setting(db, "backup_last_run")
    if last:
        families.append(
            _gauge("cabinet_backup_last_run_timestamp_seconds", "Last backup run", _ts(last["at"]))
        )
        families.append(
            _gauge(
                "cabinet_backup_last_run_success",
                "1 if the last backup run succeeded",
                1.0 if last.get("ok") else 0.0,
            )
        )
    try:
        stored = backups.stored_backups(backups.backup_dir())
    except (backups.BackupError, OSError):
        stored = None
    if stored is not None:
        families.append(
            _gauge("cabinet_backup_archives", "Archives in the backup directory", len(stored))
        )
        if stored:
            newest = stored[0].stat()
            families.append(
                _gauge(
                    "cabinet_backup_newest_timestamp_seconds",
                    "When the newest stored archive was written",
                    newest.st_mtime,
                )
            )
            families.append(
                _gauge(
                    "cabinet_backup_newest_size_bytes",
                    "Size of the newest stored archive",
                    newest.st_size,
                )
            )
    return families


def _refresh_families(db: Session) -> list:
    last = store.get_setting(db, "refresh_last_run") or {}
    at = _gauge(
        "cabinet_refresh_last_run_timestamp_seconds",
        "Last scheduled refresh per source",
        labels=("source",),
    )
    counts = _gauge(
        "cabinet_refresh_last_run_items",
        "Items in the last scheduled refresh per source, by outcome",
        labels=("source", "outcome"),
    )
    for source, run in last.items():
        at.add_metric([source], _ts(run["at"]))
        for outcome in ("updated", "skipped", "failed"):
            counts.add_metric([source, outcome], run.get(outcome, 0))
    return [at, counts]


class _Snapshot:
    def __init__(self, families: list):
        self.families = families

    def collect(self):
        return iter(self.families)


def render(db: Session) -> bytes:
    """The exposition text, rebuilt at most once a minute."""
    with _lock:
        now = time.monotonic()
        if _cache["body"] and now - _cache["at"] < CACHE_SECONDS:
            return _cache["body"]
        registry = CollectorRegistry(auto_describe=False)
        registry.register(_Snapshot(collect(db)))
        body = generate_latest(registry)
        _cache.update(at=now, body=body)
        return body


def reset_cache() -> None:
    _cache.update(at=0.0, body=b"")
