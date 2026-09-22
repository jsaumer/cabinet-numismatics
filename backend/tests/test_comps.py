"""v0.17.0: the sales log, the `comps` estimate, and Numista auction sales."""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app.services import currency, numista
from tests.conftest import COIN

TODAY = date.today()


def _item(client, grade="VF-20", ref="N#1234", **overrides):
    payload = {**COIN, **overrides}
    if ref:
        payload["catalog_refs"] = [{"catalog": "numista", "ref_code": ref}]
    if grade:
        grades = client.get("/api/grades", params={"scale": "sheldon"}).json()
        payload["grade_id"] = next(g["id"] for g in grades if g["code"] == grade)
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _sale(client, item, price, days_ago=30, **overrides):
    body = {
        "sold_on": (TODAY - timedelta(days=days_ago)).isoformat(),
        "venue": "eBay",
        "price": price,
        "currency": "USD",
        **overrides,
    }
    resp = client.post(f"/api/items/{item['id']}/comparables", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _comps(client, item):
    return client.post(f"/api/items/{item['id']}/estimates/auto", params={"source": "comps"})


# ---------------------------------------------------------------- the sales log


def test_sales_log_crud(client):
    item = _item(client)
    sale = _sale(
        client,
        item,
        42.5,
        currency="eur",
        grade="NGC MS64",
        url="https://example.com/lot/1",
        premium_included=True,
        fees=3.5,
        note="nice toning",
    )
    assert sale["currency"] == "EUR"
    assert (sale["source"], sale["included"], sale["grade_bucket"]) == ("manual", True, None)
    older = _sale(client, item, 30.0, days_ago=400)

    # newest sale first, on the list and on the item itself
    listed = client.get(f"/api/items/{item['id']}/comparables").json()
    assert [s["id"] for s in listed] == [sale["id"], older["id"]]
    detail = client.get(f"/api/items/{item['id']}").json()
    assert [s["id"] for s in detail["comparables"]] == [sale["id"], older["id"]]

    resp = client.patch(f"/api/comparables/{older['id']}", json={"included": False, "url": None})
    assert resp.status_code == 200
    assert resp.json()["included"] is False
    assert client.patch(f"/api/comparables/{older['id']}", json={"venue": None}).status_code == 422
    assert client.patch("/api/comparables/9999", json={"included": True}).status_code == 404

    assert client.delete(f"/api/comparables/{older['id']}").status_code == 204
    assert client.delete(f"/api/comparables/{older['id']}").status_code == 404
    assert len(client.get(f"/api/items/{item['id']}/comparables").json()) == 1


def test_sales_log_validation(client):
    item = _item(client)
    url = f"/api/items/{item['id']}/comparables"
    base = {"sold_on": TODAY.isoformat(), "venue": "eBay", "price": 10}
    assert client.post(url, json={**base, "price": 0}).status_code == 422
    assert client.post(url, json={**base, "venue": ""}).status_code == 422
    assert client.post(url, json={**base, "currency": "EURO"}).status_code == 422
    assert client.post(url, json={**base, "fees": -1}).status_code == 422
    missing = "/api/items/00000000-0000-0000-0000-000000000000/comparables"
    assert client.post(missing, json=base).status_code == 404


def test_deleting_an_item_deletes_its_sales(client):
    item = _item(client)
    sale = _sale(client, item, 10)
    assert client.delete(f"/api/items/{item['id']}?permanent=true").status_code == 204
    assert client.delete(f"/api/comparables/{sale['id']}").status_code == 404


def test_clone_leaves_the_sales_log_behind(client):
    item = _item(client)
    _sale(client, item, 10)
    copy = client.post(f"/api/items/{item['id']}/clone").json()
    assert client.get(f"/api/items/{copy['id']}").json()["comparables"] == []


# ---------------------------------------------------------------- comps estimate


def test_comps_estimate_is_the_median_of_logged_sales(client):
    item = _item(client, quantity=2)
    _sale(client, item, 40.0, days_ago=10)
    _sale(client, item, 50.0, days_ago=20, fees=5.0)  # counts as 55
    _sale(client, item, 60.0, days_ago=30)

    resp = _comps(client, item)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source"] == "comps:3 sales"
    assert body["estimated_value"] == 110.0  # median 55 × quantity 2
    assert (body["currency"], body["sample_size"], body["confidence"]) == ("USD", 3, 0.5)
    details = body["details"]
    assert details["median"] == 55.0
    assert details["quantity"] == 2
    assert details["grade_bucket"] == "vf"
    assert details["older_sales_used"] is False
    assert [s["price"] for s in details["sales"]] == [40.0, 55.0, 60.0]
    assert details["sales"][0]["venue"] == "eBay"


def test_confidence_follows_count_and_spread(client):
    tight = _item(client)
    for price in (100, 101, 99, 100, 102, 98, 100, 100, 101, 99):
        _sale(client, tight, price)
    assert _comps(client, tight).json()["confidence"] == 0.7

    wide = _item(client)
    for price in (10, 100, 300):
        _sale(client, wide, price)
    body = _comps(client, wide).json()
    assert body["details"]["spread_pct"] == 90.0
    assert body["confidence"] == 0.35  # three sales, spread over 50%

    ungraded = _item(client, grade=None)
    _sale(client, ungraded, 20)
    assert _comps(client, ungraded).json()["confidence"] == 0.25  # one sale, no grade


def test_older_sales_are_used_only_when_recent_ones_are_scarce(client):
    item = _item(client)
    _sale(client, item, 10, days_ago=30)
    _sale(client, item, 20, days_ago=365 * 4)
    _sale(client, item, 30, days_ago=365 * 5)
    body = _comps(client, item).json()
    assert body["details"]["older_sales_used"] is True
    assert body["sample_size"] == 3
    assert body["confidence"] == 0.32  # 3 sales (0.5), spread 50% (-0.08), older (-0.1)

    for price in (11, 12):
        _sale(client, item, price, days_ago=60)
    body = _comps(client, item).json()
    assert body["details"]["older_sales_used"] is False
    assert body["sample_size"] == 3
    assert body["estimated_value"] == 11.0


def test_comps_explains_what_is_missing(client):
    item = _item(client)
    resp = _comps(client, item)
    assert resp.status_code == 422
    assert "sales log" in resp.json()["detail"]

    sale = _sale(client, item, 10)
    client.patch(f"/api/comparables/{sale['id']}", json={"included": False})
    assert "left out" in _comps(client, item).json()["detail"]

    client.put("/api/settings", json={"comps_enabled": False})
    assert "disabled" in _comps(client, item).json()["detail"]


def test_comps_converts_other_currencies(client, monkeypatch):
    monkeypatch.setattr(currency, "fetch_rate", lambda base, quote: Decimal("1.5"))
    item = _item(client)
    _sale(client, item, 20.0, currency="EUR")  # 30 USD
    body = _comps(client, item).json()
    assert body["estimated_value"] == 30.0
    assert body["details"]["sales"][0]["converted"] == 30.0


def test_comps_without_a_usable_rate_says_so(client):
    item = _item(client)
    _sale(client, item, 20.0, currency="EUR")  # no rate: the network is off in tests
    resp = _comps(client, item)
    assert resp.status_code == 422
    assert "exchange rate" in resp.json()["detail"]


def test_comps_can_be_the_preferred_source(client):
    item = _item(client)
    _sale(client, item, 80.0)
    assert _comps(client, item).status_code == 201
    client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": 5.0})
    body = {"value_strategy": "preferred_source", "preferred_source": "comps"}
    assert client.put("/api/settings", json=body).status_code == 200
    listed = client.get("/api/items").json()["items"]
    [entry] = [i for i in listed if i["id"] == item["id"]]
    assert (entry["latest_value"], entry["latest_value_source"]) == (80.0, "comps")


def test_coverage_reports_comps(client):
    item = _item(client)
    _sale(client, item, 10)
    body = client.get("/api/pricing/coverage").json()
    assert "comps" in [s["source"] for s in body["sources"]]
    [row] = [i for i in body["items"] if i["item_id"] == item["id"]]
    [comps] = [s for s in row["sources"] if s["source"] == "comps"]
    assert comps["status"] == "not_tried"


# ---------------------------------------------------------------- Numista auction sales

SALES = {
    "sales_count": 3,
    "sales_records": [
        {
            "auction_house": {"id": 71, "name": "Katz Coins Notes & Supplies Corp."},
            "auction_title": "Auction 190",
            "auction_date": (TODAY - timedelta(days=40)).isoformat(),
            "lot_number": "1731",
            "lot_url": "https://katzauction.com/lot/87056",
            "issue_id": 55,
            "grade": "vf",
            "price": {"amount": 25.0, "currency": "USD", "premium_included": False},
            "pictures": [{"url": "https://en.numista.com/x.jpg", "picture_copyright": "Katz"}],
        },
        {
            "auction_house": {"id": 1, "name": "Heritage Auctions"},
            "auction_title": "World & Ancient Coins",
            "auction_date": (TODAY - timedelta(days=90)).isoformat(),
            "lot_number": "61134",
            "issue_id": 55,
            "grade": "unc",
            "grade_details": "NGC MS65",
            "price": {"amount": 547.31, "currency": "USD", "premium_included": True},
        },
        {  # unusable: no price
            "auction_house": {"id": 2, "name": "Somewhere"},
            "auction_date": TODAY.isoformat(),
            "issue_id": 55,
            "price": {"amount": 0, "currency": "USD", "premium_included": None},
        },
    ],
}
ISSUES = [{"id": 55, "year": 1932, "mint_letter": "D"}]


@pytest.fixture()
def numista_http(monkeypatch):
    """Stand in for Numista at the HTTP level, so status handling is real.
    `state["sales_status"]` sets what the sales endpoint answers."""
    state = {"sales_status": 200, "calls": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        state["calls"].append(url)
        request = httpx.Request("GET", url)
        if url.endswith("/issues"):
            return httpx.Response(200, json=ISSUES, request=request)
        if url.endswith("/sales_records"):
            if state["sales_status"] != 200:
                body = {"error_message": "Permission denied"}
                return httpx.Response(state["sales_status"], json=body, request=request)
            assert params["issue_id"] == 55
            return httpx.Response(200, json=SALES, request=request)
        raise AssertionError(url)

    monkeypatch.setattr(numista.httpx, "get", fake_get)
    return state


def _configure(client, sales=True):
    body = {"numista_api_key": "numista-test-key", "numista_sales_enabled": sales}
    assert client.put("/api/settings", json=body).status_code == 200


def _fetch(client, item):
    return client.post(f"/api/items/{item['id']}/comparables/numista")


def test_numista_sales_are_off_by_default(client, numista_http):
    assert client.get("/api/settings").json()["numista_sales_enabled"] is False
    _configure(client, sales=False)
    resp = _fetch(client, _item(client))
    assert resp.status_code == 422
    assert "paid API plan" in resp.json()["detail"]
    assert numista_http["calls"] == []


def test_free_key_gets_the_paid_plan_explanation(client, numista_http):
    _configure(client)
    numista_http["sales_status"] = 403
    resp = _fetch(client, _item(client))
    assert resp.status_code == 422
    assert resp.json()["detail"] == numista.PAID_PLAN


def test_numista_sales_fill_the_sales_log(client, numista_http):
    _configure(client)
    item = _item(client, grade="MS-65")  # the "unc" bucket

    resp = _fetch(client, item)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"found": 2, "added": 2, "already_logged": 0, "issue_id": 55}

    log = client.get(f"/api/items/{item['id']}/comparables").json()
    katz, heritage = log
    assert (katz["venue"], katz["lot"], katz["grade"], katz["grade_bucket"]) == (
        "Katz Coins Notes & Supplies Corp.",
        "1731",
        "VF",
        "vf",
    )
    assert (katz["source"], katz["premium_included"], katz["title"]) == (
        "numista",
        False,
        "Auction 190",
    )
    assert (heritage["grade"], heritage["price"], heritage["url"]) == ("NGC MS65", 547.31, None)

    # a second fetch the same day comes from the cache and adds nothing
    again = _fetch(client, item).json()
    assert (again["added"], again["already_logged"]) == (0, 2)
    assert sum(u.endswith("/sales_records") for u in numista_http["calls"]) == 1

    # only the sale in the item's grade bucket counts
    body = _comps(client, item).json()
    assert body["sample_size"] == 1
    assert body["estimated_value"] == 547.31
    assert body["details"]["sales"][0]["source"] == "numista"


def test_numista_sales_need_a_catalogue_reference(client, numista_http):
    _configure(client)
    resp = _fetch(client, _item(client, ref=None))
    assert resp.status_code == 422
    assert "catalog reference" in resp.json()["detail"]


def test_catalogue_data_is_cached_for_seven_days():
    # Licence §8.4 (personal projects) permits the cache; seven days is §8.3's
    # limit for catalogue metadata, which Cabinet applies to everything.
    assert numista.CATALOG_TTL == timedelta(days=7)
