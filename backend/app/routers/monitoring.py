from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import alerts, metrics
from app.services import app_settings as store

router = APIRouter(prefix="/api", tags=["monitoring"])


class Outcome(BaseModel):
    at: datetime
    ok: bool
    detail: str


class AlertStatus(BaseModel):
    key: str
    label: str
    failing: bool
    since: datetime | None = None  # when it started failing, or recovered
    message: str | None = None


def alert_statuses(db: Session) -> list[AlertStatus]:
    """Every condition that has ever alerted, failing ones first."""
    rows = [
        AlertStatus(key=key, label=alerts.CONDITIONS.get(key, key), **state)
        for key, state in alerts.states(db).items()
        if key in alerts.CONDITIONS
    ]
    return sorted(rows, key=lambda r: (not r.failing, r.label))


@router.post("/alerts/test", response_model=Outcome)
def send_test_alert(
    target: Literal["webhook", "heartbeat"] = "webhook", db: Session = Depends(get_db)
):
    """Send a test alert through the saved webhook, or push the heartbeat now.
    Answers 200 either way; `ok` says whether it arrived."""
    if target == "heartbeat":
        outcome = alerts.ping_heartbeat(db, test=True)
        if outcome is None:
            return Outcome(
                at=datetime.now(timezone.utc), ok=False, detail="No heartbeat URL is saved"
            )
        return outcome
    return alerts.send_test(db)


@router.get("/metrics", response_class=Response)
def prometheus_metrics(db: Session = Depends(get_db)):
    """Prometheus exposition format. Off until turned on in Settings."""
    if not store.get_setting(db, "metrics_enabled"):
        raise HTTPException(404, "Metrics are off — turn them on in Settings → Alerts & metrics")
    return Response(metrics.render(db), media_type=CONTENT_TYPE_LATEST)
