"""Pricing program M2: the Numista adapter."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db import get_db
from app.main import app
from app.models import PriceEstimate
from app.services import numista, pricing
from app.services.pricing import SourceUnavailable
from tests.conftest import COIN


def _session():
    """A DB session on the test engine (via the client's dependency override)."""
    return next(app.dependency_overrides[get_db]())


# COIN is a 1932-D quarter; the canned catalogue matches it.
ISSUES = {"items": [{"id": 55, "year": 1932, "mint_letter": "D"}, {"id": 56, "year": 1933}]}
PRICES = {
    "currency": "USD",
    "prices": [{"grade": "vf", "price": 30.0}, {"grade": "xf", "price": 45.0}],
}


@pytest.fixture()
def upstream(monkeypatch):
    """Stand in for the Numista API, counting calls per path."""
    calls: list[str] = []

    def fake_request(api_key, path, params=None):
        calls.append(path)
        if path.endswith("/prices"):
            return PRICES
        if path.endswith("/issues"):
            return ISSUES
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(numista, "_request", fake_request)
    return calls


def configure(client, key="numista-test-key"):
    resp = client.put("/api/settings", json={"numista_enabled": True, "numista_api_key": key})
    assert resp.status_code == 200


def grade_id(client, scale, code):
    grades = client.get("/api/grades", params={"scale": scale}).json()
    return next(g["id"] for g in grades if g["code"] == code)


def make_item(client, grade="VF-20", ref="N#1234", **overrides):
    payload = {**COIN, "catalog_refs": [{"catalog": "numista", "ref_code": ref}], **overrides}
    if grade is not None:
        payload["grade_id"] = grade_id(client, "sheldon", grade)
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def estimate(client, item):
    return client.post(f"/api/items/{item['id']}/estimate", params={"source": "numista"})


def test_estimate_by_ref_and_grade(client, upstream):
    configure(client)
    item = make_item(client)

    resp = estimate(client, item)
    assert resp.status_code == 201
    body = resp.json()
    assert body["estimated_value"] == 30.0  # the "vf" bucket, exactly
    assert body["currency"] == "USD"
    assert body["confidence"] == 0.6
    assert body["source"] == "numista:N#1234 VF"

    # the issue matching both year and mint mark was the one priced
    assert "types/1234/issues/55/prices" in upstream


def test_multiplies_by_quantity(client, upstream):
    configure(client)
    item = make_item(client, quantity=3)
    assert estimate(client, item).json()["estimated_value"] == 90.0


def test_nearest_grade_when_bucket_unpriced(client, upstream):
    configure(client)
    item = make_item(client, grade="MS-65")  # "unc"; only vf/xf are priced

    body = estimate(client, item).json()
    assert body["estimated_value"] == 45.0  # nearest priced bucket
    assert body["source"] == "numista:N#1234 XF (for UNC)"
    assert body["confidence"] == 0.45  # substituted grade, lower confidence


def test_responses_are_cached(client, upstream):
    configure(client)
    item = make_item(client)
    assert estimate(client, item).status_code == 201
    assert len(upstream) == 2  # issues + prices

    assert estimate(client, item).status_code == 201
    assert len(upstream) == 2  # second estimate spent no requests


def test_stale_cache_beats_a_failed_request(client, upstream, monkeypatch):
    configure(client)
    item = make_item(client)
    assert estimate(client, item).status_code == 201

    monkeypatch.setattr(numista, "CATALOG_TTL", timedelta(0))
    monkeypatch.setattr(numista, "PRICE_TTL", timedelta(0))

    def broken(api_key, path, params=None):
        raise SourceUnavailable("upstream down")

    monkeypatch.setattr(numista, "_request", broken)
    assert estimate(client, item).status_code == 201


def test_upstream_failure_without_cache_is_502(client, monkeypatch):
    configure(client)

    def broken(api_key, path, params=None):
        raise SourceUnavailable("upstream down")

    monkeypatch.setattr(numista, "_request", broken)
    item = make_item(client)
    assert estimate(client, item).status_code == 502


def test_not_applicable_reasons(client, upstream):
    configure(client)

    no_ref = client.post("/api/items", json={**COIN}).json()
    resp = estimate(client, no_ref)
    assert resp.status_code == 422 and "catalog reference" in resp.json()["detail"]

    no_grade = make_item(client, grade=None)
    resp = estimate(client, no_grade)
    assert resp.status_code == 422 and "grade" in resp.json()["detail"]

    wrong_year = make_item(client, year=1955)
    resp = estimate(client, wrong_year)
    assert resp.status_code == 422 and "1955" in resp.json()["detail"]

    assert not any(p.endswith("/prices") for p in upstream)  # no request wasted


def test_unknown_type_is_not_applicable(client, monkeypatch):
    configure(client)

    def missing(api_key, path, params=None):
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", missing)
    resp = estimate(client, make_item(client))
    assert resp.status_code == 422 and "no type N#1234" in resp.json()["detail"]


def test_toggle_and_key_are_required(client, upstream):
    item = make_item(client)

    resp = estimate(client, item)  # disabled by default
    assert resp.status_code == 422 and "disabled" in resp.json()["detail"]

    client.put("/api/settings", json={"numista_enabled": True})
    resp = estimate(client, item)  # enabled, but no key
    assert resp.status_code == 422 and "API key" in resp.json()["detail"]

    assert upstream == []


def test_unknown_source_rejected(client, coin):
    resp = client.post(f"/api/items/{coin['id']}/estimate", params={"source": "moon"})
    assert resp.status_code == 422


def test_grade_buckets_cover_both_scales():
    assert numista.bucket_for_rank(4) == "g"  # G-4 / PMG 4
    assert numista.bucket_for_rank(8) == "vg"
    assert numista.bucket_for_rank(12) == "f"
    assert numista.bucket_for_rank(20) == "vf"


def test_refresh_source_estimates_ignores_a_fresher_manual_estimate(client, upstream):
    configure(client)
    item = make_item(client)
    assert estimate(client, item).status_code == 201  # item's only estimate: numista, fresh

    # a fresh manual entry becomes the item's overall-latest
    client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": 999.0})

    # backdate only the numista estimate past the refresh window
    db = _session()
    for est in (
        db.query(PriceEstimate)
        .filter(
            PriceEstimate.item_id == uuid.UUID(item["id"]),
            PriceEstimate.source.like("numista:%"),
        )
        .all()
    ):
        est.fetched_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()
    db.close()

    result = pricing.refresh_source_estimates(_session(), "numista", 7)
    assert result == {"updated": 1, "skipped": 0, "failed": 0}

    history = client.get(f"/api/items/{item['id']}/estimates").json()
    numista_entries = [h for h in history if h["source"].startswith("numista:")]
    assert len(numista_entries) == 2  # refreshed despite manual being the overall-latest


def test_refresh_source_estimates_skips_ineligible_and_counts_failures(
    client, upstream, monkeypatch
):
    configure(client)
    client.post("/api/items", json=COIN)  # no numista ref -> NotApplicable -> skipped
    make_item(client)  # eligible, never estimated -> attempted

    def fail(api_key, path, params=None):
        raise SourceUnavailable("boom")

    monkeypatch.setattr(numista, "_request", fail)

    result = pricing.refresh_source_estimates(_session(), "numista", 7)
    assert result == {"updated": 0, "skipped": 1, "failed": 1}
    assert numista.bucket_for_rank(40) == "xf"
    assert numista.bucket_for_rank(50) == "au"
    assert numista.bucket_for_rank(65) == "unc"


def test_price_map_accepts_both_response_shapes():
    as_list = numista.price_map(PRICES)
    as_object = numista.price_map({"currency": "USD", "prices": {"vf": 30, "xf": "45.0"}})
    assert as_list == as_object == {"vf": Decimal("30"), "xf": Decimal("45.0")}

    # unknown keys, non-numeric and non-positive prices are dropped
    assert numista.price_map({"prices": {"vf": 0, "bogus": 5, "xf": "n/a"}}) == {}
