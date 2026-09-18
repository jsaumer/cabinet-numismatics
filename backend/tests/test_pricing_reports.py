"""Pricing program M5: coverage, stale estimates, per-source breakdown, accuracy."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db import get_db
from app.main import app
from app.models import EstimateAttempt, PriceEstimate
from app.services import numista, pricing
from tests.conftest import COIN

SILVER = {**COIN, "composition": "90% silver", "weight_g": 6.3, "fineness": 0.9}
NOW = datetime.now(timezone.utc)


@pytest.fixture()
def spot(monkeypatch):
    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))


@pytest.fixture()
def numista_api(monkeypatch):
    """Canned Numista responses; set `state["down"]` to make requests fail."""
    state = {"down": False}

    def fake(api_key, path, params=None):
        if state["down"]:
            raise pricing.SourceUnavailable("Numista request failed: timeout")
        if path.endswith("/prices"):
            return {"currency": "USD", "prices": [{"grade": "vf", "price": 30.0}]}
        return {"items": [{"id": 55, "year": 1932, "mint_letter": "D"}]}

    monkeypatch.setattr(numista, "_request", fake)
    return state


def _session():
    return next(app.dependency_overrides[get_db]())


def _create(client, **overrides):
    resp = client.post("/api/items", json={**COIN, **overrides})
    assert resp.status_code == 201
    return resp.json()


def _numista_item(client, ref="N#1234", **overrides):
    grades = client.get("/api/grades", params={"scale": "sheldon"}).json()
    vf = next(g["id"] for g in grades if g["code"] == "VF-20")
    refs = [{"catalog": "numista", "ref_code": ref}]
    return _create(client, catalog_refs=refs, grade_id=vf, **overrides)


def _enable_numista(client):
    body = {"numista_enabled": True, "numista_api_key": "numista-test-key"}
    assert client.put("/api/settings", json=body).status_code == 200


def _estimate(client, item, source="melt"):
    return client.post(f"/api/items/{item['id']}/estimate", params={"source": source})


def _manual(client, item, value, source="dealer quote", currency="USD"):
    body = {"estimated_value": value, "source": source, "currency": currency}
    resp = client.post(f"/api/items/{item['id']}/estimates", json=body)
    assert resp.status_code == 201


def _edit_estimates(item, source_prefix="", fetched_at=None, details=None):
    db = _session()
    rows = db.query(PriceEstimate).filter(
        PriceEstimate.item_id == uuid.UUID(item["id"]),
        PriceEstimate.source.like(f"{source_prefix}%"),
    )
    for est in rows:
        if fetched_at is not None:
            est.fetched_at = fetched_at
        if details is not None:
            est.details = details
    db.commit()
    db.close()


def _source(entry, source):
    return next(s for s in entry["sources"] if s["source"] == source)


def test_coverage_explains_every_gap(client, spot, numista_api):
    _enable_numista(client)
    melted = _create(client, **SILVER)
    assert _estimate(client, melted).status_code == 201
    plain = _create(client)
    ready = _numista_item(client)
    failing = _numista_item(client, ref="N#9")
    numista_api["down"] = True
    assert _estimate(client, failing, "numista").status_code == 502

    body = client.get("/api/pricing/coverage").json()
    assert (body["owned_items"], body["estimated_items"], body["manual_only_items"]) == (4, 1, 0)

    listed = {entry["item_id"]: entry for entry in body["items"]}
    assert melted["id"] not in listed  # priced, and nothing else outstanding
    assert set(listed) == {plain["id"], ready["id"], failing["id"]}

    assert _source(listed[plain["id"]], "melt")["status"] == "not_applicable"
    assert "composition" in _source(listed[plain["id"]], "melt")["reason"]
    assert "catalog reference" in _source(listed[plain["id"]], "numista")["reason"]
    assert _source(listed[plain["id"]], "pcgs")["status"] == "disabled"
    assert _source(listed[ready["id"]], "numista")["status"] == "not_tried"
    failed = _source(listed[failing["id"]], "numista")
    assert failed["status"] == "failed" and "timeout" in failed["reason"]
    assert failed["attempted_at"] is not None

    summary = {s["source"]: s for s in body["sources"]}
    assert summary["melt"]["priced"] == 1
    assert summary["numista"] == {
        "source": "numista",
        "enabled": True,
        "priced": 0,
        "not_applicable": 2,
        "failed": 1,
        "not_tried": 1,
    }
    assert summary["pcgs"]["enabled"] is False


def test_coverage_flags_a_source_that_stopped_pricing(client, numista_api):
    _enable_numista(client)
    item = _numista_item(client)
    assert _estimate(client, item, "numista").status_code == 201
    assert client.get("/api/pricing/coverage").json()["items"] == []

    # the item changes so Numista can no longer match it; the old estimate remains
    client.patch(f"/api/items/{item['id']}", json={"year": 1955})
    assert _estimate(client, item, "numista").status_code == 422

    [entry] = client.get("/api/pricing/coverage").json()["items"]
    status = _source(entry, "numista")
    assert status["status"] == "not_applicable" and "1955" in status["reason"]
    assert status["estimated_at"] is not None


def test_scheduled_refresh_records_attempts_and_deleting_the_item_clears_them(client, numista_api):
    _enable_numista(client)
    item = _create(client)  # no numista ref
    pricing.refresh_source_estimates(_session(), "numista", 7)

    db = _session()
    attempt = db.get(EstimateAttempt, (uuid.UUID(item["id"]), "numista"))
    assert attempt.outcome == "not_applicable" and "catalog reference" in attempt.message
    db.close()

    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    db = _session()
    assert db.query(EstimateAttempt).count() == 0
    db.close()


def test_stale_report(client, spot):
    item = _create(client, **SILVER)
    assert _estimate(client, item).status_code == 201
    _manual(client, item, 12.0)  # the newest estimate, so the one shown
    _edit_estimates(item, "melt", fetched_at=NOW - timedelta(days=40))

    body = client.get("/api/pricing/stale").json()
    assert (body["days"], body["checked"]) == (30, 2)
    [entry] = body["stale"]
    assert (entry["source"], entry["age_days"], entry["in_totals"]) == ("melt", 40, False)
    assert entry["upstream_stale"] is False

    _edit_estimates(item, "dealer", fetched_at=NOW - timedelta(days=10))
    stale = client.get("/api/pricing/stale", params={"days": 7}).json()["stale"]
    assert [e["source"] for e in stale] == ["melt", "manual"]
    assert stale[1]["source_label"] == "dealer quote" and stale[1]["in_totals"] is True

    # fresh, but built from spot data past its cache window
    _edit_estimates(item, "melt", fetched_at=NOW, details={"stale": True})
    stale = client.get("/api/pricing/stale").json()["stale"]
    assert [(e["source"], e["upstream_stale"]) for e in stale] == [("melt", True)]

    assert client.get("/api/pricing/stale", params={"days": 0}).status_code == 422


def test_sources_report(client, spot, numista_api):
    _enable_numista(client)
    both = _numista_item(client, **SILVER)
    assert _estimate(client, both).status_code == 201  # 6.3 g × 0.9 × $1 = 5.67
    assert _estimate(client, both, "numista").status_code == 201  # 30.00
    # SQLite timestamps have one-second resolution; make numista unambiguously newest
    _edit_estimates(both, "melt", fetched_at=NOW - timedelta(days=1))
    manual = _create(client)
    _manual(client, manual, 100.0)

    body = client.get("/api/pricing/sources").json()
    assert (body["currency"], body["strategy"], body["averaged_items"]) == ("USD", "latest", 0)
    rows = {r["source"]: r for r in body["sources"]}
    assert set(rows) == {"melt", "numista", "pcgs", "comps", "manual"}
    assert (rows["melt"]["items"], rows["melt"]["total_value"]) == (1, 5.67)
    assert (rows["numista"]["avg_confidence"], rows["numista"]["in_totals"]) == (0.6, 1)
    assert (rows["manual"]["total_value"], rows["manual"]["in_totals"]) == (100.0, 1)
    assert (rows["melt"]["in_totals"], rows["pcgs"]["items"]) == (0, 0)

    [spread] = body["disagreements"]
    assert spread["values"] == {"melt": 5.67, "numista": 30.0}
    assert spread["spread_pct"] == 429.1

    client.put("/api/settings", json={"value_strategy": "average"})
    body = client.get("/api/pricing/sources").json()
    assert body["averaged_items"] == 1
    assert {r["source"]: r["in_totals"] for r in body["sources"]}["numista"] == 0


def test_accuracy_report(client):
    sold = _create(client, acquisition_price=100.0)
    _manual(client, sold, 150.0)
    _edit_estimates(sold, fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    sale = {"status": "sold", "sold_price": 120.0, "sold_date": "2026-02-01"}
    client.patch(f"/api/items/{sold['id']}", json=sale)
    _manual(client, sold, 999.0, source="after the sale")  # recorded after: not a prediction

    _create(client, status="sold", sold_price=50.0, sold_date="2026-02-01")  # never estimated
    euro = _create(client, currency="EUR", status="sold", sold_price=40.0)
    _manual(client, euro, 45.0, currency="EUR")  # no EUR→USD rate offline: excluded
    owned = _create(client)
    _manual(client, owned, 10.0)  # owned items aren't part of this report

    body = client.get("/api/pricing/accuracy").json()
    assert (body["sold_items"], body["compared_items"]) == (3, 1)
    assert body["excluded_other_currency"] >= 1

    [entry] = body["items"]
    assert entry["sold_price"] == 120.0
    assert entry["blended"] == {
        "source": "manual",
        "value": 150.0,
        "error_pct": 25.0,
        "estimated_at": None,
    }
    assert [(e["source"], e["value"]) for e in entry["by_source"]] == [("manual", 150.0)]
    assert body["summary"] == [
        {
            "source": "blended",
            "sales": 1,
            "median_abs_error_pct": 25.0,
            "mean_error_pct": 25.0,
            "within_20_pct": 0,
        },
        {
            "source": "manual",
            "sales": 1,
            "median_abs_error_pct": 25.0,
            "mean_error_pct": 25.0,
            "within_20_pct": 0,
        },
    ]


def test_reports_are_empty_on_an_empty_collection(client):
    assert client.get("/api/pricing/coverage").json()["items"] == []
    assert client.get("/api/pricing/stale").json()["stale"] == []
    assert client.get("/api/pricing/sources").json()["disagreements"] == []
    assert client.get("/api/pricing/accuracy").json()["summary"] == []
