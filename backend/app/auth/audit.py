"""The audit log: one row per event in `cabinet_auth.audit_log`, and one JSON
line on stdout (logger `cabinet.audit`).

Failed sign-ins have a cap of their own (FAILED_CAP rows), and so do
rejected single sign-ons (REJECTED_SSO_CAP, v0.33.0: anyone with a Google
or GitHub account can finish the flow as an unlinked identity), so a flood
of either can never push out the evidence of anything else; every other
event is kept 180 days or KEEP_ROWS rows. The caps are enforced as rows
are written. On stdout, both kinds are sampled: at most one line per event
and name (or `unknown`) per 15 minutes, carrying how many there were.

Nothing from the collection (item names, locations, documents) and no
secret ever goes into a row, a line, or a webhook.
"""

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.auth import common
from app.models.auth import AuditEntry

logger = logging.getLogger("cabinet.audit")

EVENTS = frozenset(
    {
        "setup",
        "setup_failed",
        "sign_in",
        "sign_in_failed",
        "sign_out",
        "reauth",
        "password_changed",
        "username_changed",
        "password_reset",
        "sessions_revoked_all",
        "tokens_revoked_all",
        "session_revoked",
        "token_created",
        "token_revoked",
        "backup_downloaded",
        "export_downloaded",
        "restore_started",
        "restore_finished",
        "secrets_cleared",
        "backup_key_shown",
        "backup_key_rotated",
        "backup_key_saved",
        "backup_deleted",
        "sharing_switched",
        "share_link_created",
        "share_link_regenerated",
        "share_link_revoked",
        "share_link_changed",
        "restore_sharing",
        "identity_linked",
        "identity_unlinked",
        "sso_configured",
        "sso_disabled",
        "sso_sign_in_rejected",
    }
)
FAILED = "sign_in_failed"
FAILED_CAP = 10_000
REJECTED_SSO = "sso_sign_in_rejected"
REJECTED_SSO_CAP = 10_000
KEEP = timedelta(days=180)
KEEP_ROWS = 50_000
SAMPLE_WINDOW = 15 * 60
SAMPLE_KEYS = 10_000
# Keys a detail may never carry, whatever the caller meant.
FORBIDDEN_DETAIL = ("password", "secret", "code", "token_value")
# Bulk deletes find their rows with a query rather than evaluating the
# condition in Python: SQLite hands times back naive.
FETCH = {"synchronize_session": "fetch"}


@dataclass(frozen=True)
class Actor:
    kind: str  # session | token | anonymous | cli | system
    user_id: int | None = None
    label: str | None = None
    address: str | None = None
    user_agent: str | None = None

    @classmethod
    def cli(cls, user=None) -> "Actor":
        return cls("cli", getattr(user, "id", None), "cli")

    @classmethod
    def system(cls) -> "Actor":
        return cls("system", None, "system")


def _check_detail(detail: dict | None) -> None:
    for key in detail or {}:
        if any(word in key.lower() for word in FORBIDDEN_DETAIL):
            raise ValueError(f"audit detail may not carry {key!r}")


def record(
    db: DbSession,
    action: str,
    actor: Actor,
    *,
    target: str | None = None,
    detail: dict | None = None,
) -> AuditEntry:
    """Add the row (the caller commits) and print its line."""
    if action not in EVENTS:
        raise ValueError(f"unknown audit event {action!r}")
    _check_detail(detail)
    row = AuditEntry(
        at=common.now(),
        actor_user_id=actor.user_id,
        actor_label=common.clip(actor.label, 64),
        actor_kind=actor.kind,
        action=action,
        target=common.clip(target, 200),
        detail=detail or None,
        address=common.clip(actor.address, 45),
        user_agent=common.clip(actor.user_agent, 256),
    )
    db.add(row)
    db.flush()
    _enforce_caps(db, action)
    _print(row)
    return row


def _trim(db: DbSession, where, keep: int) -> None:
    """Delete every row matching `where` older than the newest `keep`."""
    cutoff = db.scalar(
        select(AuditEntry.id).where(where).order_by(AuditEntry.id.desc()).offset(keep).limit(1)
    )
    if cutoff is not None:
        db.execute(
            delete(AuditEntry).where(where, AuditEntry.id <= cutoff), execution_options=FETCH
        )


def _own_caps() -> dict[str, int]:
    """The events capped apart from the rest, read at call time."""
    return {FAILED: FAILED_CAP, REJECTED_SSO: REJECTED_SSO_CAP}


def _enforce_caps(db: DbSession, action: str) -> None:
    caps = _own_caps()
    if action in caps:
        _trim(db, AuditEntry.action == action, caps[action])
        return
    others = AuditEntry.action.not_in(list(caps))
    db.execute(
        delete(AuditEntry).where(others, AuditEntry.at < common.now() - KEEP),
        execution_options=FETCH,
    )
    _trim(db, others, KEEP_ROWS)


def prune(db: DbSession) -> None:
    """For the hourly tick: age out old rows even when nothing is written."""
    _enforce_caps(db, "sign_in")


# --- stdout -----------------------------------------------------------------------

_sample_lock = threading.Lock()
_sampled: OrderedDict[str, list] = OrderedDict()  # event:label -> [printed_at, since]


def _print(row: AuditEntry) -> None:
    line = {
        "at": common.aware(row.at).isoformat(),
        "event": row.action,
        "actor": row.actor_kind,
        "user": row.actor_label,
        "target": row.target,
        "address": row.address,
        "detail": row.detail,
    }
    if row.action in _own_caps():
        label = f"{row.action}:{row.actor_label or 'unknown'}"
        t = common.monotonic()
        with _sample_lock:
            entry = _sampled.get(label)
            if entry is not None and t - entry[0] < SAMPLE_WINDOW:
                entry[1] += 1
                return
            line["count"] = 1 + (entry[1] if entry else 0)
            _sampled[label] = [t, 0]
            _sampled.move_to_end(label)
            while len(_sampled) > SAMPLE_KEYS:
                _sampled.popitem(last=False)
    logger.info(json.dumps({k: v for k, v in line.items() if v is not None}, default=str))


def reset_memory() -> None:
    with _sample_lock:
        _sampled.clear()


# --- reading ----------------------------------------------------------------------


def page(db: DbSession, before: int | None = None, limit: int = 50) -> list[AuditEntry]:
    limit = max(1, min(200, limit))
    query = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    if before is not None:
        query = query.where(AuditEntry.id < before)
    return list(db.scalars(query).all())


def count(db: DbSession, action: str, *, label: str | None = None, since=None) -> int:
    query = select(func.count()).select_from(AuditEntry).where(AuditEntry.action == action)
    if label is not None:
        query = query.where(AuditEntry.actor_label == label)
    if since is not None:
        query = query.where(AuditEntry.at > since)
    return db.scalar(query) or 0
