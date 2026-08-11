"""Pricing program M1: settings API, secret masking, integrations."""

import json

from tests.conftest import COIN

SILVER = {**COIN, "composition": "90% silver", "weight_g": 26.73, "fineness": 0.9}


def test_defaults(client):
    body = client.get("/api/settings").json()
    assert body["display_currency"] == "USD"
    assert body["reestimate_days"] == 7  # env default
    assert body["reestimate_days_overridden"] is False
    melt = next(s for s in body["sources"] if s["key"] == "melt")
    assert melt["enabled"] is True and melt["available"] is True and melt["configured"] is True
    numista = next(s for s in body["sources"] if s["key"] == "numista")
    assert numista["configured"] is False and numista["available"] is True
    assert numista["enabled"] is False  # off until a key is configured
    pcgs = next(s for s in body["sources"] if s["key"] == "pcgs")
    assert pcgs["configured"] is False and pcgs["available"] is True
    assert body["value_strategy"] == "latest"
    assert body["preferred_source"] is None
    assert body["numista_refresh_days"] is None
    assert body["pcgs_auto_refresh"] is False
    assert body["numista_priceable_items"] == 0
    assert body["pcgs_priceable_items"] == 0


def test_value_strategy_update_and_validation(client):
    resp = client.put(
        "/api/settings", json={"value_strategy": "preferred_source", "preferred_source": "numista"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["value_strategy"] == "preferred_source"
    assert body["preferred_source"] == "numista"

    # persisted for subsequent reads
    body = client.get("/api/settings").json()
    assert body["value_strategy"] == "preferred_source"
    assert body["preferred_source"] == "numista"

    assert client.put("/api/settings", json={"value_strategy": "bogus"}).status_code == 422
    assert client.put("/api/settings", json={"preferred_source": "ebay"}).status_code == 422

    # explicit null clears it back
    resp = client.put("/api/settings", json={"value_strategy": "latest", "preferred_source": None})
    assert resp.json()["preferred_source"] is None


def test_numista_refresh_days_and_pcgs_auto_refresh(client):
    for days in (7, 14, 30):
        resp = client.put("/api/settings", json={"numista_refresh_days": days})
        assert resp.status_code == 200
        assert resp.json()["numista_refresh_days"] == days
    assert client.put("/api/settings", json={"numista_refresh_days": 15}).status_code == 422

    resp = client.put("/api/settings", json={"numista_refresh_days": None})
    assert resp.json()["numista_refresh_days"] is None

    resp = client.put("/api/settings", json={"pcgs_auto_refresh": True})
    assert resp.json()["pcgs_auto_refresh"] is True
    assert client.put("/api/settings", json={"pcgs_auto_refresh": []}).status_code == 422


def test_priceable_item_counts(client):
    body = client.get("/api/settings").json()
    assert body["numista_priceable_items"] == 0
    assert body["pcgs_priceable_items"] == 0

    client.post(
        "/api/items", json={**COIN, "catalog_refs": [{"catalog": "numista", "ref_code": "N#1234"}]}
    )
    client.post("/api/items", json={**COIN, "cert_service": "PCGS", "cert_number": "12345"})
    client.post(
        "/api/items", json={**COIN, "catalog_refs": [{"catalog": "pcgs", "ref_code": "PC1"}]}
    )

    body = client.get("/api/settings").json()
    assert body["numista_priceable_items"] == 1
    assert body["pcgs_priceable_items"] == 2


def test_update_and_persist(client):
    resp = client.put("/api/settings", json={"display_currency": "cad", "reestimate_days": 30})
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_currency"] == "CAD"
    assert body["reestimate_days"] == 30 and body["reestimate_days_overridden"] is True

    # persisted for subsequent reads
    body = client.get("/api/settings").json()
    assert body["display_currency"] == "CAD"

    assert client.put("/api/settings", json={"display_currency": "toolong"}).status_code == 422
    assert client.put("/api/settings", json={"reestimate_days": 9999}).status_code == 422


def test_display_currency_drives_stats_default(client):
    client.post("/api/items", json={**COIN, "acquisition_price": 50.0, "currency": "CAD"})
    client.put("/api/settings", json={"display_currency": "CAD"})

    stats = client.get("/api/stats/collection").json()  # no ?currency
    assert stats["currency"] == "CAD"
    assert stats["cost_basis"] == 50.0  # native currency now, no conversion needed

    # explicit override still wins
    assert (
        client.get("/api/stats/collection", params={"currency": "USD"}).json()["currency"] == "USD"
    )


def test_secrets_are_write_only(client):
    resp = client.put("/api/settings", json={"numista_api_key": "super-secret-key-1234"})
    assert resp.status_code == 200
    dumped = json.dumps(resp.json())
    assert "super-secret" not in dumped  # never echoed back

    numista = next(s for s in resp.json()["sources"] if s["key"] == "numista")
    assert numista["configured"] is True
    assert numista["secret_hint"] == "…1234"

    # clearing with an empty string
    resp = client.put("/api/settings", json={"numista_api_key": ""})
    numista = next(s for s in resp.json()["sources"] if s["key"] == "numista")
    assert numista["configured"] is False and numista["secret_hint"] is None


def test_melt_toggle_gates_estimation(client, monkeypatch):
    from decimal import Decimal

    from app.services import pricing

    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))
    item = client.post("/api/items", json=SILVER).json()

    client.put("/api/settings", json={"melt_enabled": False})
    resp = client.post(f"/api/items/{item['id']}/estimate")
    assert resp.status_code == 422 and "disabled" in resp.json()["detail"]
    assert client.post("/api/estimates/refresh-melt").status_code == 422

    client.put("/api/settings", json={"melt_enabled": True})
    assert client.post(f"/api/items/{item['id']}/estimate").status_code == 201


def test_cached_data_listed(client, monkeypatch):
    from decimal import Decimal

    from app.services import pricing

    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("2.0"))
    item = client.post("/api/items", json=SILVER).json()
    client.post(f"/api/items/{item['id']}/estimate")

    cached = client.get("/api/settings").json()["cached"]
    silver = next(c for c in cached if c["label"] == "silver spot")
    assert silver["value"].startswith("2.0000")
    assert silver["source"] == "gold-api.com"
