"""The work the background loops in main.py run: the 12-hourly price refresh,
and the hourly tick (stored secrets checked, the sharing switch reread,
scheduled backup, trash clear-out, purchase-day spot backfill, spot-price
alerts, heartbeat). Kept
here so it can be tested without the loops."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth import accounts, audit
from app.services import alerts, maintenance, pricing, stack, trash
from app.services import app_settings as store
from app.services import backup as backups

logger = logging.getLogger(__name__)

SOURCE_NAMES = {"melt": "Melt", "numista": "Numista", "pcgs": "PCGS"}


def refresh(db: Session) -> dict:
    """Run each enabled source's scheduled refresh, record its outcome in
    `refresh_last_run`, and raise or clear its alert. Returns the outcomes.
    Sits out while a restore is replacing the database."""
    with maintenance.scheduled_task() as go:
        if not go:
            logger.info("Scheduled refresh skipped: a restore is running")
            return {}
        return _refresh(db)


def _refresh(db: Session) -> dict:
    runs = {}
    days = store.effective_reestimate_days(db)
    if days > 0 and store.get_setting(db, "melt_enabled"):
        runs["melt"] = lambda: pricing.refresh_melt_estimates(db, days)
    else:
        logger.info("Scheduled melt refresh disabled (days=%s)", days)
    numista_days = store.get_setting(db, "numista_refresh_days")
    if numista_days and store.get_setting(db, "numista_enabled"):
        runs["numista"] = lambda: pricing.refresh_source_estimates(db, "numista", int(numista_days))
    if store.get_setting(db, "pcgs_auto_refresh") and store.get_setting(db, "pcgs_enabled"):
        runs["pcgs"] = lambda: pricing.refresh_source_estimates(db, "pcgs", 7)

    outcomes = {}
    for source, run in runs.items():
        outcome = run()
        logger.info("Scheduled %s refresh: %s", source, outcome)
        _record(db, source, outcome)
        outcomes[source] = outcome
    return outcomes


def _record(db: Session, source: str, outcome: dict) -> None:
    last = dict(store.get_setting(db, "refresh_last_run") or {})
    last[source] = {"at": datetime.now(timezone.utc).isoformat(), **outcome}
    store.set_setting(db, "refresh_last_run", last)
    db.commit()
    key = f"refresh_{source}"
    if outcome["failed"]:
        message = f"{outcome['failed']} item(s) failed"
        if outcome.get("stopped"):
            message += f"; stopped early: {outcome['stopped']}"
        elif outcome.get("error"):
            message += f" ({outcome['error']})"
        alerts.fail(db, key, f"{SOURCE_NAMES[source]} refresh: {message}")
    else:
        alerts.recover(db, key)


def clear_secrets(db: Session, undecryptable: bool = False) -> list[str]:
    """Clear stored secrets this deployment won't use (plain text, and with
    `undecryptable` any it can't decrypt), commit, and say so by name through
    the webhook if one is still saved. Run at startup, after a restore, and
    hourly, which also catches a database restored by `restore.sh`."""
    cleared = store.clear_unusable_secrets(db, undecryptable)
    if cleared:
        audit.record(db, "secrets_cleared", audit.Actor.system(), detail={"names": cleared})
    db.commit()
    if cleared:
        names = ", ".join(store.SECRET_LABELS[key] for key in cleared)
        alerts.event(
            db,
            "secrets_cleared",
            "Cabinet cleared stored secrets",
            f"Not encrypted with this deployment's key, so never used: {names}. "
            "Enter them again in Settings.",
        )
    return cleared


def hourly(db: Session) -> None:
    """Back up if one is due, empty the trash of expired items, fill in
    purchase-day spot prices, check the spot-price thresholds, then push the
    heartbeat (last, so it reports what this tick found). Sits out while a
    restore is replacing the database."""
    with maintenance.scheduled_task() as go:
        if not go:
            logger.info("Hourly tasks skipped: a restore is running")
            return
        _hourly(db)


def _hourly(db: Session) -> None:
    try:
        clear_secrets(db)
    except Exception:
        db.rollback()
        logger.exception("Checking stored secrets failed")
    try:
        # The gate holds the sharing switch in memory; a database put back by
        # restore.sh (or edited by hand) is picked up here.
        from app.services import share

        share.load(db)
    except Exception:
        db.rollback()
        logger.exception("Reading whether sharing is on failed")
    try:
        if outcome := backups.run_scheduled(db):
            logger.info("Scheduled backup: %s", outcome)
    except backups.BackupError as exc:
        logger.error("Scheduled backup failed: %s", exc)
    except Exception:  # keep the rest of the tick, and the heartbeat, going
        db.rollback()
        logger.exception("Scheduled backup failed")
        alerts.fail(db, "backup", "Scheduled backup failed unexpectedly. See the log")
    try:
        accounts.prune(db)
    except Exception:
        db.rollback()
        logger.exception("Pruning ended sessions and old audit rows failed")
    if purged := trash.purge_expired(db):
        logger.info("Emptied %s item(s) from the trash (past retention)", purged)
    # Both are best-effort: a missing purchase-day price or spot price is not
    # worth an alert, so they only reach the log.
    try:
        outcome = stack.backfill(db, stack.HOURLY_BACKFILL)
        if outcome["filled"] or outcome["failed"]:
            logger.info("Purchase-day spot backfill: %s", outcome)
    except Exception:
        db.rollback()
        logger.exception("Purchase-day spot backfill failed")
    try:
        if fired := stack.check_spot_alerts(db):
            logger.info("Spot price alerts: %s threshold(s) crossed", fired)
    except Exception:
        db.rollback()
        logger.exception("Spot price alert check failed")
    alerts.ping_heartbeat(db)
