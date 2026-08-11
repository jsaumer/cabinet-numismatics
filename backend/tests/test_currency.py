"""Phase 5A: currency conversion, value history, melt refresh."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db import get_db
from app.main import app
from app.models import PriceEstimate
from app.services import currency, pricing
from tests.conftest import COIN

SILVER = {
    **COIN,
    "denomination": "1 dollar",
    "composition": "90% silver",
    "weight_g": 26.73,
    "fineness": 0.9,
}


@pytest.fixture()
def cad_rate(monkeypatch):
    """CAD→USD at 0.5, counting upstream calls."""
    calls = {"count": 0}

    def fake(base, quote):
        calls["count"] += 1
        assert (base, quote) == ("CAD", "USD")
        return Decimal("0.5")

    monkeypatch.setattr(currency, "fetch_rate", fake)
    return calls


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _session():
    """A DB session on the test engine (via the client's dependency override)."""
    return next(app.dependency_overrides[get_db]())


def test_stats_convert_other_currencies(client, cad_rate):
    usd = _create(client, {**COIN, "acquisition_price": 100.0})
    client.post(f"/api/items/{usd['id']}/estimates", json={"estimated_value": 150.0})
    _create(client, {**COIN, "acquisition_price": 50.0, "currency": "CAD"})

    stats = client.get("/api/stats/collection").json()
    assert stats["cost_basis"] == 125.0  # 100 USD + 50 CAD × 0.5
    assert stats["converted_other_currency"] == 1
    assert stats["excluded_other_currency"] == 0

    gains = client.get("/api/stats/gains").json()
    assert len(gains["unrealized"]) == 1  # CAD item has no estimate → not a gains row


def test_unconvertible_currency_still_excluded(client):
    # autouse fixture makes every rate fetch fail
    _create(client, {**COIN, "acquisition_price": 50.0, "currency": "CAD"})
    stats = client.get("/api/stats/collection").json()
    assert stats["cost_basis"] == 0.0
    assert stats["converted_other_currency"] == 0
    assert stats["excluded_other_currency"] == 1


def test_rate_cached_and_stale_fallback(client, cad_rate, monkeypatch):
    _create(client, {**COIN, "acquisition_price": 50.0, "currency": "CAD"})
    client.get("/api/stats/collection")
    client.get("/api/stats/collection")
    assert cad_rate["count"] == 1  # second call used the 24h cache

    # expire the cache and break the upstream: stale rate still converts
    monkeypatch.setattr(currency, "CACHE_TTL", timedelta(0))

    def broken(base, quote):
        raise currency.RateUnavailable("down")

    monkeypatch.setattr(currency, "fetch_rate", broken)
    stats = client.get("/api/stats/collection").json()
    assert stats["cost_basis"] == 25.0


def test_value_history(client):
    a = _create(client, COIN)
    client.post(f"/api/items/{a['id']}/estimates", json={"estimated_value": 100.0})
    b = _create(client, COIN)
    client.post(f"/api/items/{b['id']}/estimates", json={"estimated_value": 50.0})

    body = client.get("/api/stats/value-history", params={"months": 6}).json()
    assert len(body["points"]) >= 1  # leading empty months dropped
    last = body["points"][-1]
    assert last["value"] == 150.0
    assert last["estimated_items"] == 2


def test_value_history_strategy_aware(client):
    a = _create(client, COIN)
    client.post(
        f"/api/items/{a['id']}/estimates",
        json={"estimated_value": 100.0, "source": "numista:N#1 XF"},
    )
    client.post(
        f"/api/items/{a['id']}/estimates",
        json={"estimated_value": 200.0, "source": "manual"},  # newer, but not preferred
    )
    client.put(
        "/api/settings", json={"value_strategy": "preferred_source", "preferred_source": "numista"}
    )

    body = client.get("/api/stats/value-history", params={"months": 6}).json()
    last = body["points"][-1]
    assert last["value"] == 100.0  # preferred source, not the newer manual entry


def test_refresh_melt_updates_only_stale_melt_estimates(client, monkeypatch):
    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))

    fresh = _create(client, SILVER)
    client.post(f"/api/items/{fresh['id']}/estimate")  # fresh melt → skipped

    stale = _create(client, SILVER)
    client.post(f"/api/items/{stale['id']}/estimate")

    manual = _create(client, SILVER)
    client.post(f"/api/items/{manual['id']}/estimates", json={"estimated_value": 99.0})

    # backdate the second item's melt estimate past the refresh window
    db = _session()
    stale_id = uuid.UUID(stale["id"])
    for est in db.query(PriceEstimate).filter(PriceEstimate.item_id == stale_id).all():
        est.fetched_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    db.close()

    result = client.post("/api/estimates/refresh-melt").json()
    assert result == {"updated": 1, "skipped": 2, "failed": 0}

    history = client.get(f"/api/items/{stale['id']}/estimates").json()
    assert len(history) == 2  # append-only: old melt estimate retained

    # the manual item was left alone — a melt refresh never buries a manual value
    manual_history = client.get(f"/api/items/{manual['id']}/estimates").json()
    assert len(manual_history) == 1 and manual_history[0]["source"] == "manual"
