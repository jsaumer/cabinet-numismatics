"""Phase 3: melt estimates, spot cache, manual confidence, collection stats."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.services import pricing
from tests.conftest import COIN

SILVER = {
    **COIN,
    "denomination": "1 dollar",
    "series": "Morgan Dollar",
    "composition": "90% silver",
    "weight_g": 26.73,
    "fineness": 0.9,
}


@pytest.fixture()
def spot(monkeypatch):
    """Mock the upstream spot API: $1.00/g, counting calls."""
    calls = {"count": 0}

    def fake_fetch(metal):
        calls["count"] += 1
        return Decimal("1.0")

    monkeypatch.setattr(pricing, "fetch_spot_price", fake_fetch)
    return calls


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_melt_estimate(client, spot):
    item = _create(client, SILVER)
    resp = client.post(f"/api/items/{item['id']}/estimate")
    assert resp.status_code == 201
    body = resp.json()
    # 26.73 g × 0.9 × $1.00/g = 24.06
    assert body["estimated_value"] == 24.06
    assert body["currency"] == "USD"
    assert body["confidence"] == 0.95
    assert body["source"].startswith("melt:silver")

    # estimate is in the item's history like any other
    detail = client.get(f"/api/items/{item['id']}").json()
    assert len(detail["estimates"]) == 1


def test_melt_multiplies_by_quantity(client, spot):
    item = _create(client, {**SILVER, "quantity": 3})
    body = client.post(f"/api/items/{item['id']}/estimate").json()
    assert body["estimated_value"] == 72.17  # 24.057 × 3, rounded


def test_melt_percent_fallback_from_composition(client, spot):
    item = _create(client, {**SILVER, "fineness": None})
    body = client.post(f"/api/items/{item['id']}/estimate").json()
    assert body["estimated_value"] == 24.06  # "90% silver" → 0.90


def test_melt_not_applicable_reasons(client, spot):
    no_metal = _create(client, COIN)
    resp = client.post(f"/api/items/{no_metal['id']}/estimate")
    assert resp.status_code == 422 and "composition" in resp.json()["detail"]

    no_weight = _create(client, {**SILVER, "weight_g": None})
    resp = client.post(f"/api/items/{no_weight['id']}/estimate")
    assert resp.status_code == 422 and "weight" in resp.json()["detail"]

    no_fineness = _create(client, {**SILVER, "fineness": None, "composition": "silver"})
    resp = client.post(f"/api/items/{no_fineness['id']}/estimate")
    assert resp.status_code == 422 and "fineness" in resp.json()["detail"].lower()

    assert spot["count"] == 0  # no upstream call for inapplicable items


def test_spot_price_cached_within_ttl(client, spot):
    item = _create(client, SILVER)
    client.post(f"/api/items/{item['id']}/estimate")
    client.post(f"/api/items/{item['id']}/estimate")
    assert spot["count"] == 1  # second estimate reused the cache


def test_stale_cache_used_when_fetch_fails(client, spot, monkeypatch):
    item = _create(client, SILVER)
    assert client.post(f"/api/items/{item['id']}/estimate").status_code == 201

    # expire the cache and break the upstream
    monkeypatch.setattr(pricing, "CACHE_TTL", timedelta(0))

    def broken(metal):
        raise pricing.SpotUnavailable("upstream down")

    monkeypatch.setattr(pricing, "fetch_spot_price", broken)
    resp = client.post(f"/api/items/{item['id']}/estimate")
    assert resp.status_code == 201  # stale beats nothing


def test_spot_unavailable_without_cache_is_502(client, monkeypatch):
    def broken(metal):
        raise pricing.SpotUnavailable("upstream down")

    monkeypatch.setattr(pricing, "fetch_spot_price", broken)
    item = _create(client, SILVER)
    resp = client.post(f"/api/items/{item['id']}/estimate")
    assert resp.status_code == 502


def test_manual_estimate_confidence(client, coin):
    resp = client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "confidence": 0.6, "source": "dealer quote"},
    )
    assert resp.status_code == 201
    assert resp.json()["confidence"] == 0.6

    resp = client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 90.0})
    assert resp.json()["confidence"] is None  # still optional

    assert (
        client.post(
            f"/api/items/{coin['id']}/estimates",
            json={"estimated_value": 1, "confidence": 1.5},
        ).status_code
        == 422
    )


def test_collection_stats(client):
    owned = _create(client, {**COIN, "acquisition_price": 100.0})
    client.post(f"/api/items/{owned['id']}/estimates", json={"estimated_value": 150.0})

    _create(client, {**COIN, "acquisition_price": 50.0, "currency": "CAD"})  # excluded

    sold = _create(client, {**COIN, "acquisition_price": 80.0})
    client.patch(
        f"/api/items/{sold['id']}",
        json={"status": "sold", "sold_date": "2026-08-01", "sold_price": 120.0},
    )

    _create(client, {**COIN, "status": "wishlist", "acquisition_price": None})

    stats = client.get("/api/stats/collection").json()
    assert stats["currency"] == "USD"
    assert stats["counts"] == {
        "total": 4,
        "owned": 2,
        "sold": 1,
        "wishlist": 1,
        "coins": 4,
        "notes": 0,
    }
    assert stats["cost_basis"] == 100.0
    assert stats["estimated_value"] == 150.0
    assert stats["unrealized_gain"] == 50.0
    assert stats["realized_gain"] == 40.0
    assert stats["estimated_items"] == 1
    assert stats["excluded_other_currency"] == 1
