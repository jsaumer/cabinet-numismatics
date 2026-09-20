"""Pricing program M3: the PCGS adapter."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import pcgs
from app.services.pricing import SourceUnavailable
from tests.conftest import COIN


def ago(days: int) -> str:
    """A sale date that many days back, as PCGS writes a full date."""
    return (date.today() - timedelta(days=days)).strftime("%m-%d-%Y")


def iso(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


FACTS = {
    "PCGSNo": "5960",
    "Name": "1932-D 25C",
    "PriceGuideValue": 400.0,
    "AuctionList": [
        {"Date": ago(190), "Price": 520.0, "Auctioneer": "Heritage"},
        {"Date": ago(320), "Price": 480.0, "Auctioneer": "Stack's"},
        {"Date": ago(400), "Price": 470.0, "Auctioneer": "Heritage"},
        {"Date": ago(2800), "Price": 200.0, "Auctioneer": "Heritage"},  # too old to count
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
    assert body["estimated_value"] == 480.0  # median of 520/480/470, not the 400 guide
    assert body["currency"] == "USD"
    assert body["confidence"] == 0.75  # real sales, but only three of them
    assert body["sample_size"] == 3
    assert body["source"] == "pcgs:apr #5960 MS-65"

    details = body["details"]
    assert details["lookup"] == "grade"
    assert details["pcgs_number"] == "5960" and details["grade"] == "MS-65"
    assert details["basis"] == "apr"
    assert [lot["date"] for lot in details["lots"]] == [iso(190), iso(320), iso(400)]
    assert [lot["price"] for lot in details["older_lots"]] == [200.0]  # kept, not counted
    assert details["lots"][0]["auctioneer"] == "Heritage"
    assert details["median"] == 480.0
    assert details["price_guide_value"] == 400.0  # recorded even though sales won
    assert details["stale"] is False

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
    assert body["details"]["basis"] == "guide"
    assert body["details"]["lots"] == [] and body["details"]["median"] is None


def test_cert_number_looked_up_directly(client, upstream):
    configure(client)
    item = by_cert(client, grade=None)  # a slab needs no grade of its own

    body = estimate(client, item).json()
    assert body["source"] == "pcgs:apr cert 12345678"
    assert body["details"]["lookup"] == "cert" and body["details"]["cert"] == "12345678"
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


def test_one_old_sale_does_not_beat_the_guide(client, upstream):
    # Cert 2575126 as the live API returned it: a single Heritage lot dated by
    # month, 23 years back, against a guide value nearly four times higher.
    configure(client)
    upstream.body = {
        **FACTS,
        "PriceGuideValue": 160000.0,
        "AuctionList": [{"Date": "07-2003", "Price": 43700.0, "Auctioneer": "Heritage Auctions"}],
    }
    body = estimate(client, by_number(client)).json()
    assert body["estimated_value"] == 160000.0 and body["confidence"] == 0.6
    assert body["details"]["basis"] == "guide" and body["details"]["lots"] == []
    assert body["details"]["older_lots"] == [
        {
            "date": "2003-07-01",
            "price": 43700.0,
            "auctioneer": "Heritage Auctions",
            "sale": None,
            "url": None,
        }
    ]


def test_few_recent_sales_are_trusted_less_and_old_ones_stand_in_last(client, upstream):
    configure(client)
    upstream.body = {**FACTS, "AuctionList": FACTS["AuctionList"][:2]}
    body = estimate(client, by_number(client)).json()
    assert body["estimated_value"] == 500.0 and body["confidence"] == 0.65

    upstream.body = {**FACTS, "PriceGuideValue": None, "AuctionList": FACTS["AuctionList"][3:]}
    other = make_item(client, year=1933, catalog_refs=[{"catalog": "pcgs", "ref_code": "5961"}])
    body = estimate(client, other).json()
    assert body["estimated_value"] == 200.0 and body["confidence"] == 0.35
    assert body["details"]["basis"] == "apr_old" and body["source"].startswith("pcgs:apr-old")


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


def test_plus_grade_and_proof_strike_reach_the_lookup(client, upstream):
    configure(client)
    body = estimate(client, by_number(client, grade_plus=True)).json()
    assert upstream[-1][1]["PlusGrade"] == "true"
    assert body["source"] == "pcgs:apr #5960 MS-65+"

    proof = by_number(client, ref="5961", strike="proof")
    assert estimate(client, proof).json()["source"] == "pcgs:apr #5961 PR-65"


def test_details_grade_needs_a_cert(client, upstream):
    configure(client)
    resp = estimate(client, by_number(client, grade_details="Cleaned"))
    assert resp.status_code == 422 and "details grade" in resp.json()["detail"]
    assert upstream == []
    assert estimate(client, by_cert(client, grade_details="Cleaned")).status_code == 201


# --- filling an item in from a cert (v0.22.0) ---------------------------------

CERT_FACTS = {
    **FACTS,
    "CertNo": "12345678",
    "Year": 1932,
    "Denomination": "25C",
    "MintMark": "D",
    "SeriesName": "Washington Quarter",
    "MetalContent": "90% Silver, 10% Copper",
    "Weight": 6.25,
    "Diameter": 24.3,
    "Edge": "Reeded",
    "Mintage": "436,800",
    "Grade": "MS64+",
    "Designation": "",
    "MajorVariety": "",
    "MinorVariety": "",
    "DieVariety": "",
    "Population": 812,
    "PopHigher": 240,
    "CoinFactsLink": "www.pcgs.com/coinfacts/coin/5960",
}


def test_cert_fill_maps_the_coin(client, upstream):
    configure(client)
    upstream.body = CERT_FACTS
    resp = client.get("/api/pcgs/cert/1234-5678")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cert"] == "12345678" and body["pcgs_number"] == "5960"
    assert body["fields"] == {
        "type": "coin",
        "country": "United States",
        "denomination": "25 cents",
        "year": 1932,
        "mint_mark": "D",
        "series": "Washington Quarter",
        "composition": "90% Silver, 10% Copper",
        "weight_g": 6.25,
        "diameter_mm": 24.3,
        "edge": "Reeded",
        "mintage": 436800,
        "cert_service": "PCGS",
        "cert_number": "12345678",
        "pcgs_population": 812,
        "pcgs_pop_higher": 240,
    }
    assert body["grade"] == {"rank": 64, "strike": "business", "plus": True, "designations": []}
    assert body["catalog_refs"] == [{"catalog": "pcgs", "ref_code": "5960"}]
    assert body["population"] == 812 and body["pop_higher"] == 240
    assert body["price_guide_value"] == 400.0
    assert upstream == [("coindetail/GetCoinFactsByCertNo/12345678", {"retrieveAllData": "true"})]
    # the same cached response then prices the item without a second request
    item = by_cert(client)
    assert estimate(client, item).status_code == 201
    assert len(upstream) == 1


def test_cert_fill_spells_the_country_and_philadelphia_cabinets_way():
    # As PCGS returned cert 2575126: an 1864 two cents, which carries no letter.
    shield = {
        **CERT_FACTS,
        "Country": "The United States of America",
        "Year": 1864,
        "Denomination": "2C",
        "MintMark": "P",
    }
    fields = pcgs.cert_fields("2575126", shield)["fields"]
    assert fields["country"] == "United States"
    assert "mint_mark" not in fields

    def mark(year, denomination, letter="P"):
        facts = {**CERT_FACTS, "Year": year, "Denomination": denomination, "MintMark": letter}
        return pcgs.cert_fields("1", facts)["fields"].get("mint_mark")

    assert mark(1943, "5C") == "P"  # wartime nickel
    assert mark(1941, "5C") is None
    assert mark(1979, "$1") == "P" and mark(1979, "25C") is None
    assert mark(1980, "25C") == "P" and mark(1999, "1C") is None
    assert mark(2017, "1C") == "P"
    assert mark(1864, "2C", "S") == "S"  # other mints are untouched
    assert (
        pcgs.cert_fields("1", {**CERT_FACTS, "Country": "Canada"})["fields"]["country"] == "Canada"
    )


def test_cert_fill_grades_and_designations():
    assert pcgs.parse_grade("PR-65 DCAM") == {
        "rank": 65,
        "strike": "proof",
        "plus": False,
        "designations": ["DCAM"],
    }
    assert pcgs.parse_grade("AU58", "FB")["designations"] == ["FB"]
    assert pcgs.parse_grade("SP66")["strike"] == "specimen"
    assert pcgs.parse_grade("64", "+ RD") == {
        "rank": 64,
        "strike": "business",
        "plus": True,
        "designations": ["RD"],
    }
    assert pcgs.parse_grade("Genuine") is None and pcgs.parse_grade(None) is None
    assert pcgs.cert_fields("1", {"Denomination": "$20", "Mintage": 0})["fields"] == {
        "type": "coin",
        "country": "United States",
        "denomination": "20 dollars",
        "cert_service": "PCGS",
        "cert_number": "1",
    }


def test_cert_fill_needs_a_token_and_a_known_cert(client, upstream):
    assert client.get("/api/pcgs/cert/1").status_code == 422
    configure(client)
    upstream.body = {"IsValidRequest": True, "ServerMessage": "No data found"}
    resp = client.get("/api/pcgs/cert/1")
    assert resp.status_code == 422 and "no record" in resp.json()["detail"]
    assert client.get("/api/pcgs/cert/abc").status_code == 422
