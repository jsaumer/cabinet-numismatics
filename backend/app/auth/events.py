"""Audit (and optionally alert) something a route did, under the name of
whoever called it: downloads, exports, the backup-key tick, deleting old
archives. Nothing from the collection goes into the row or the message."""

from fastapi import Request
from sqlalchemy.orm import Session as DbSession

from app.auth import audit, notify
from app.auth.audit import Actor
from app.auth.permissions import Principal, principal


def actor_of(who: Principal | None) -> Actor:
    if who is None:
        return Actor.system()
    return Actor(who.kind, who.user_id, who.username, who.address, who.user_agent)


def record(
    db: DbSession,
    request: Request,
    action: str,
    *,
    target: str | None = None,
    detail: dict | None = None,
    alert: str | None = None,
) -> None:
    audit.record(db, action, actor_of(principal(request)), target=target, detail=detail)
    db.commit()
    if alert is not None:
        notify.send(db, action, alert)
