"""Phase 3: melt estimates, spot cache, manual confidence, collection stats."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.db import get_db
from app.main import app
from app.models import EstimateAttempt
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
    resp = client.post(f"/api/items/{item['id']}/estimates/auto")
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
    body = client.post(f"/api/items/{item['id']}/estimates/auto").json()
    assert body["estimated_value"] == 72.17  # 24.057 × 3, rounded


def test_melt_percent_fallback_from_composition(client, spot):
    item = _create(client, {**SILVER, "fineness": None})
    body = client.post(f"/api/items/{item['id']}/estimates/auto").json()
    assert body["estimated_value"] == 24.06  # "90% silver" → 0.90


def test_melt_records_provenance(client, spot):
    item = _create(client, SILVER)
    details = client.post(f"/api/items/{item['id']}/estimates/auto").json()["details"]
    assert details["metal"] == "silver"
    assert details["weight_g"] == 26.73
    assert details["fineness"] == 0.9
    assert details["fineness_from"] == "field"
    assert details["quantity"] == 1
    assert details["spot_per_gram"] == 1.0
    assert details["spot_source"] == "gold-api.com"
    assert details["stale"] is False

    derived = _create(client, {**SILVER, "fineness": None})
    details = client.post(f"/api/items/{derived['id']}/estimates/auto").json()["details"]
    assert details["fineness_from"] == "composition"


def test_melt_not_applicable_reasons(client, spot):
    no_metal = _create(client, COIN)
    resp = client.post(f"/api/items/{no_metal['id']}/estimates/auto")
    assert resp.status_code == 422 and "composition" in resp.json()["detail"]

    no_weight = _create(client, {**SILVER, "weight_g": None})
    resp = client.post(f"/api/items/{no_weight['id']}/estimates/auto")
    assert resp.status_code == 422 and "weight" in resp.json()["detail"]

    no_fineness = _create(client, {**SILVER, "fineness": None, "composition": "silver"})
    resp = client.post(f"/api/items/{no_fineness['id']}/estimates/auto")
    assert resp.status_code == 422 and "fineness" in resp.json()["detail"].lower()

    assert spot["count"] == 0  # no upstream call for inapplicable items


def test_spot_price_cached_within_ttl(client, spot):
    item = _create(client, SILVER)
    client.post(f"/api/items/{item['id']}/estimates/auto")
    client.post(f"/api/items/{item['id']}/estimates/auto")
    assert spot["count"] == 1  # second estimate reused the cache


def test_stale_cache_used_when_fetch_fails(client, spot, monkeypatch):
    item = _create(client, SILVER)
    assert client.post(f"/api/items/{item['id']}/estimates/auto").status_code == 201

    # expire the cache and break the upstream
    monkeypatch.setattr(pricing, "CACHE_TTL", timedelta(0))

    def broken(metal):
        raise pricing.SpotUnavailable("upstream down")

    monkeypatch.setattr(pricing, "fetch_spot_price", broken)
    resp = client.post(f"/api/items/{item['id']}/estimates/auto")
    assert resp.status_code == 201  # stale beats nothing
    assert resp.json()["details"]["stale"] is True  # ...and says so


def test_spot_unavailable_without_cache_is_502(client, monkeypatch):
    def broken(metal):
        raise pricing.SpotUnavailable("upstream down")

    monkeypatch.setattr(pricing, "fetch_spot_price", broken)
    item = _create(client, SILVER)
    resp = client.post(f"/api/items/{item['id']}/estimates/auto")
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
        "coins": 2,  # owned only: the split describes current holdings
        "notes": 0,
        "bullion": 0,
    }
    assert stats["cost_basis"] == 100.0
    assert stats["estimated_value"] == 150.0
    assert stats["unrealized_gain"] == 50.0
    assert stats["realized_gain"] == 40.0
    assert stats["estimated_items"] == 1
    assert stats["excluded_other_currency"] == 1


def test_old_auto_estimate_path_is_gone(client):
    item = client.post("/api/items", json=COIN).json()
    assert client.post(f"/api/items/{item['id']}/estimate").status_code in (404, 405)


# --- melt at save time (P11, v0.31.0, stage 4) -------------------------------


def _session():
    """A DB session on the test engine (via the client's dependency override)."""
    return next(app.dependency_overrides[get_db]())


def _warm_cache(client, spot):
    """Prime the melt spot-price cache by pricing a throwaway item."""
    seed = _create(client, SILVER)
    client.post(f"/api/items/{seed['id']}/estimates/auto")
    assert spot["count"] == 1


def test_melt_on_save_with_no_cache_makes_no_network_call(client, spot):
    _create(client, SILVER)  # nothing cached yet: nothing added, nothing fetched
    assert spot["count"] == 0


def test_melt_on_save_adds_an_estimate_from_a_fresh_cache(client, spot):
    _warm_cache(client, spot)
    item = _create(client, {**SILVER, "denomination": "1/2 dollar"})
    assert spot["count"] == 1  # only the seed item's fetch; the save read the cache

    history = client.get(f"/api/items/{item['id']}").json()["estimates"]
    assert len(history) == 1
    row = history[0]
    assert row["source"].startswith("melt:silver")
    assert row["estimated_value"] == pytest.approx(26.73 * 0.9, abs=0.01)
    json.dumps(row["details"])  # JSON-safe: no Decimal leaked through

    db = _session()
    try:
        attempt = db.get(EstimateAttempt, (uuid.UUID(item["id"]), "melt"))
        assert attempt is not None and attempt.outcome == "ok"
    finally:
        db.close()


def test_melt_on_save_skips_a_missing_or_stale_cache(client, spot, monkeypatch):
    empty = _create(client, SILVER)  # no cache at all yet
    assert client.get(f"/api/items/{empty['id']}").json()["estimates"] == []

    _warm_cache(client, spot)
    monkeypatch.setattr(pricing, "CACHE_TTL", timedelta(0))  # the cache is now stale
    stale = _create(client, {**SILVER, "denomination": "1/2 dollar"})
    assert client.get(f"/api/items/{stale['id']}").json()["estimates"] == []


def test_melt_on_save_no_duplicate_on_an_unrelated_edit(client, spot):
    _warm_cache(client, spot)
    item = _create(client, {**SILVER, "denomination": "1/2 dollar"})
    assert len(client.get(f"/api/items/{item['id']}").json()["estimates"]) == 1

    unrelated = client.patch(f"/api/items/{item['id']}", json={"notes": "album 3"})
    assert unrelated.status_code == 200
    assert len(client.get(f"/api/items/{item['id']}").json()["estimates"]) == 1  # no duplicate

    reweighed = client.patch(f"/api/items/{item['id']}", json={"weight_g": 30.0})
    assert reweighed.status_code == 200
    assert len(client.get(f"/api/items/{item['id']}").json()["estimates"]) == 2  # inputs changed


def test_melt_on_save_is_owned_pieces_only(client, spot):
    _warm_cache(client, spot)
    wishlist = _create(client, {**SILVER, "status": "wishlist"})
    assert client.get(f"/api/items/{wishlist['id']}").json()["estimates"] == []


def test_refresh_melt_takes_an_owned_piece_with_no_estimate(client, monkeypatch):
    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))
    item = _create(client, SILVER)  # cache empty: no save-time estimate yet
    assert client.get(f"/api/items/{item['id']}").json()["estimates"] == []

    result = client.post("/api/estimates/refresh?source=melt").json()
    assert result == {"updated": 1, "skipped": 0, "failed": 0}
    history = client.get(f"/api/items/{item['id']}").json()["estimates"]
    assert len(history) == 1 and history[0]["source"].startswith("melt:silver")


def test_refresh_melt_leaves_a_manual_latest_item_alone(client, monkeypatch):
    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))
    item = _create(client, SILVER)
    client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": 99.0})

    result = client.post("/api/estimates/refresh?source=melt").json()
    assert result == {"updated": 0, "skipped": 1, "failed": 0}
    history = client.get(f"/api/items/{item['id']}").json()["estimates"]
    assert len(history) == 1 and history[0]["source"] == "manual"
