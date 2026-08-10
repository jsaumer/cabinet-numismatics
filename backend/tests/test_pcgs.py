"""Pricing program M3: the PCGS adapter."""

from decimal import Decimal

import pytest

from app.services import pcgs
from app.services.pricing import SourceUnavailable
from tests.conftest import COIN

FACTS = {
    "PCGSNo": "5960",
    "Name": "1932-D 25C",
    "PriceGuideValue": 400.0,
    "AuctionList": [
        {"Date": "03-14-2026", "Price": 520.0, "Auctioneer": "Heritage"},
        {"Date": "11-02-2025", "Price": 480.0, "Auctioneer": "Stack's"},
        {"Date": "01-09-2019", "Price": 200.0, "Auctioneer": "Heritage"},
    ],
    "IsValidRequest": True,
    "ServerMessage": "Request successful",
}
GUIDE_ONLY = {**FACTS, "AuctionList": []}


@pytest.fixture()
def upstream(monkeypatch):
    """Stand in for the PCGS API: records (path, params) per call, and lets a
    test swap the response by assigning to `.body`."""

    class Upstream(list):
        body = FACTS

    calls = Upstream()

    def fake_request(token, path, params=None):
        calls.append((path, params))
        return calls.body

    monkeypatch.setattr(pcgs, "_request", fake_request)
    return calls


def configure(client, token="pcgs-test-token"):
    resp = client.put("/api/settings", json={"pcgs_enabled": True, "pcgs_api_token": token})
    assert resp.status_code == 200


def grade_id(client, code, scale="sheldon"):
    grades = client.get("/api/grades", params={"scale": scale}).json()
    return next(g["id"] for g in grades if g["code"] == code)


def make_item(client, grade="MS-65", **overrides):
    payload = {**COIN, **overrides}
    if grade is not None:
        payload["grade_id"] = grade_id(client, grade)
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def by_number(client, ref="5960", **overrides):
    return make_item(client, catalog_refs=[{"catalog": "pcgs", "ref_code": ref}], **overrides)


def by_cert(client, **overrides):
    return make_item(client, cert_service="PCGS", cert_number="12345678", **overrides)


def estimate(client, item):
    return client.post(f"/api/items/{item['id']}/estimate", params={"source": "pcgs"})


def test_auction_prices_preferred_over_the_guide(client, upstream):
    configure(client)
    item = by_number(client)

    body = estimate(client, item).json()
    assert body["estimated_value"] == 480.0  # median of 520/480/200, not the 400 guide
    assert body["currency"] == "USD"
    assert body["confidence"] == 0.75  # real sales, but only three of them
    assert body["sample_size"] == 3
    assert body["source"] == "pcgs:apr #5960 MS-65"

    path, params = upstream[0]
    assert path == "coindetail/GetCoinFactsByGrade"
    assert params == {"PCGSNo": "5960", "GradeNo": 65, "PlusGrade": "false"}


def test_price_guide_used_when_there_are_no_sales(client, upstream):
    configure(client)
    upstream.body = GUIDE_ONLY

    body = estimate(client, by_number(client)).json()
    assert body["estimated_value"] == 400.0
    assert body["confidence"] == 0.6
    assert body["sample_size"] is None
    assert body["source"] == "pcgs:guide #5960 MS-65"


def test_cert_number_looked_up_directly(client, upstream):
    configure(client)
    item = by_cert(client, grade=None)  # a slab needs no grade of its own

    body = estimate(client, item).json()
    assert body["source"] == "pcgs:apr cert 12345678"
    assert upstream[0][0] == "coindetail/GetCoinFactsByCertNo/12345678"


def test_cert_wins_over_catalog_ref(client, upstream):
    configure(client)
    item = make_item(
        client,
        cert_service="PCGS",
        cert_number="12345678",
        catalog_refs=[{"catalog": "pcgs", "ref_code": "5960"}],
    )
    estimate(client, item)
    assert "GetCoinFactsByCertNo" in upstream[0][0]


def test_other_services_cert_is_ignored(client, upstream):
    configure(client)
    item = make_item(
        client,
        cert_service="NGC",
        cert_number="999",
        catalog_refs=[{"catalog": "pcgs", "ref_code": "5960"}],
    )
    estimate(client, item)
    assert upstream[0][0] == "coindetail/GetCoinFactsByGrade"  # fell through to the ref


def test_multiplies_by_quantity_and_caches(client, upstream):
    configure(client)
    item = by_number(client, quantity=2)
    assert estimate(client, item).json()["estimated_value"] == 960.0
    assert len(upstream) == 1

    assert estimate(client, item).status_code == 201
    assert len(upstream) == 1  # second estimate spent no request


def test_in_body_failures_are_not_applicable(client, upstream):
    configure(client)
    item = by_number(client)

    upstream.body = {"IsValidRequest": True, "ServerMessage": "No data found"}
    resp = estimate(client, item)
    assert resp.status_code == 422 and "no record" in resp.json()["detail"]

    upstream.body = {"IsValidRequest": False, "ServerMessage": "Invalid CertNo"}
    resp = estimate(client, by_number(client, ref="9999"))  # a fresh cache key
    assert resp.status_code == 422 and "Invalid CertNo" in resp.json()["detail"]


def test_missing_prerequisites(client, upstream):
    configure(client)

    no_ref = make_item(client)
    resp = estimate(client, no_ref)
    assert resp.status_code == 422 and "cert number" in resp.json()["detail"]

    no_grade = by_number(client, grade=None)
    resp = estimate(client, no_grade)
    assert resp.status_code == 422 and "grade" in resp.json()["detail"]

    note = client.post(
        "/api/items",
        json={**COIN, "type": "note", "catalog_refs": [{"catalog": "pcgs", "ref_code": "5960"}]},
    ).json()
    resp = estimate(client, note)
    assert resp.status_code == 422 and "coins only" in resp.json()["detail"]

    assert upstream == []  # nothing reached the network


def test_pmg_graded_item_is_rejected(client, upstream):
    configure(client)
    item = by_number(client, grade=None)
    client.patch(f"/api/items/{item['id']}", json={"grade_id": grade_id(client, "64", "pmg")})

    resp = estimate(client, item)
    assert resp.status_code == 422 and "Sheldon" in resp.json()["detail"]


def test_upstream_failure_is_502(client, monkeypatch):
    configure(client)

    def broken(token, path, params=None):
        raise SourceUnavailable("PCGS returned a server error")

    monkeypatch.setattr(pcgs, "_request", broken)
    assert estimate(client, by_number(client)).status_code == 502


def test_toggle_and_token_are_required(client, upstream):
    item = by_number(client)

    resp = estimate(client, item)  # disabled by default
    assert resp.status_code == 422 and "disabled" in resp.json()["detail"]

    client.put("/api/settings", json={"pcgs_enabled": True})
    resp = estimate(client, item)  # enabled, but no token
    assert resp.status_code == 422 and "API token" in resp.json()["detail"]

    assert upstream == []


def test_recent_sales_prefers_newest_and_drops_junk():
    payload = {
        "Auctions": [
            {"Date": "01-01-2020", "Price": 100},
            {"Date": "2026-03-14T00:00:00", "Price": 300},
            {"Date": "bogus", "Price": 200},
            {"Date": "05-05-2025", "Price": 0},  # non-positive, dropped
            {"Date": "05-05-2025", "Price": "not a number"},
        ]
    }
    # newest first, then the undated one; the two junk prices are gone
    assert pcgs.recent_sales(payload) == [Decimal("300"), Decimal("100"), Decimal("200")]


def test_apr_window_caps_the_sample():
    lots = [{"Date": f"01-01-20{10 + n:02d}", "Price": n + 1} for n in range(15)]
    assert len(pcgs.recent_sales({"AuctionList": lots})) == pcgs.APR_WINDOW
