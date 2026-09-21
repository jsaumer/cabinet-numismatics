"""Roadmap Phase 7, P10 follow-up ("group C"): the two new sorts, the
`by_metal` breakdown, and the quality / value-spread / data-health /
showcase stats endpoints."""

from decimal import Decimal

from app.services import currency
from tests.conftest import COIN
from tests.test_parity import add_value, create, listed

SILVER = {**COIN, "composition": "90% silver", "weight_g": 12.5, "fineness": 0.9}
GOLD = {**COIN, "composition": "91.7% gold", "weight_g": 8.36, "fineness": 0.917}


# --- sorts -------------------------------------------------------------------


def test_sort_by_value(client):
    low = create(client, denomination="low")
    high = create(client, denomination="high")
    create(client, denomination="none")
    add_value(client, low, 10)
    add_value(client, high, 100)

    order = lambda sort: [i["denomination"] for i in listed(client, sort=sort)]  # noqa: E731
    assert order("value") == ["low", "high", "none"]
    assert order("-value") == ["high", "low", "none"]  # empty last both ways


def test_sort_by_pcgs_pop_higher(client):
    create(client, denomination="low", pcgs_population=1, pcgs_pop_higher=5)
    create(client, denomination="high", pcgs_population=1, pcgs_pop_higher=50)
    create(client, denomination="none")

    order = lambda sort: [i["denomination"] for i in listed(client, sort=sort)]  # noqa: E731
    assert order("pcgs_pop_higher") == ["low", "high", "none"]
    assert order("-pcgs_pop_higher") == ["high", "low", "none"]


# --- by_metal ------------------------------------------------------------


def test_by_metal_breakdown(client):
    create(client, SILVER)
    create(client, GOLD)
    create(client, {**COIN, "composition": None})  # no detectable metal

    body = client.get("/api/stats/breakdowns").json()
    by_key = {e["key"]: e for e in body["by_metal"]}
    assert by_key["Silver"]["count"] == 1
    assert by_key["Gold"]["count"] == 1
    assert by_key["Other"]["count"] == 1


# --- quality ---------------------------------------------------------------


def test_quality_empty_collection(client):
    body = client.get("/api/stats/quality").json()
    assert body["owned"] == 0
    assert body["certified"] == {"items": 0, "value": 0.0}
    assert body["raw"] == {"items": 0, "value": 0.0}
    assert body["by_service"] == []
    assert (body["graded"], body["ungraded"]) == (0, 0)


def test_quality_certified_vs_raw(client):
    certified = create(client, cert_service="PCGS", cert_number="12345")
    add_value(client, certified, 100)
    raw = create(client, denomination="raw")
    add_value(client, raw, 40)
    create(client, status="sold", denomination="not owned")  # excluded

    body = client.get("/api/stats/quality").json()
    assert body["owned"] == 2
    assert body["certified"] == {"items": 1, "value": 100.0}
    assert body["raw"] == {"items": 1, "value": 40.0}
    assert body["by_service"] == [{"key": "PCGS", "count": 1, "estimated_value": 100.0}]


def test_quality_trashed_hidden(client):
    item = create(client, cert_service="PCGS", cert_number="1")
    client.delete(f"/api/items/{item['id']}")
    body = client.get("/api/stats/quality").json()
    assert body["owned"] == 0


def test_quality_currency_conversion(client, monkeypatch):
    monkeypatch.setattr(currency, "fetch_rate", lambda base, quote: Decimal("2"))
    create(client, currency="EUR", cert_service="PCGS", cert_number="1", acquisition_price=None)
    item = listed(client)[0]
    add_value(client, item, 50, currency="EUR")
    body = client.get("/api/stats/quality", params={"currency": "USD"}).json()
    assert body["certified"]["value"] == 100.0  # converted at the fake 2x rate


# --- value-spread ------------------------------------------------------------


def test_value_spread_empty_collection(client):
    body = client.get("/api/stats/value-spread").json()
    assert body == {
        "currency": "USD",
        "items": 0,
        "min": None,
        "median": None,
        "max": None,
        "mean": None,
        "top_share_pct": None,
    }


def test_value_spread_stats(client):
    for value in (10, 20, 30, 1000):
        item = create(client, denomination=str(value))
        add_value(client, item, value)
    body = client.get("/api/stats/value-spread").json()
    assert body["items"] == 4
    assert body["min"] == 10.0
    assert body["max"] == 1000.0
    assert body["median"] == 25.0
    assert body["mean"] == 265.0
    # top 10% of 4 items rounds up to 1 item: the 1000 piece.
    assert body["top_share_pct"] == round(1000 / 1060 * 100, 2)


def test_value_spread_trashed_hidden(client):
    item = create(client)
    add_value(client, item, 100)
    client.delete(f"/api/items/{item['id']}")
    body = client.get("/api/stats/value-spread").json()
    assert body["items"] == 0


# --- data-health -------------------------------------------------------------


def test_data_health_empty_collection(client):
    body = client.get("/api/stats/data-health").json()
    assert body["owned"] == 0
    for check in body["checks"]:
        assert check["count"] == 0
        assert check["items"] == []


def test_data_health_checks(client):
    complete = create(
        client,
        cert_service="PCGS",
        cert_number="1",
        acquisition_price=50,
        storage_location="Safe",
        catalog_refs=[{"catalog": "km", "ref_code": "1"}],
    )
    client.patch(f"/api/items/{complete['id']}", json={})  # no-op; needs a grade to be "graded"
    add_value(client, complete, 100)

    bare = create(client, denomination="bare", acquisition_price=None)  # missing everything

    silver_no_weight = create(
        client, denomination="silver", composition="90% silver", weight_g=None
    )

    body = client.get("/api/stats/data-health").json()
    assert body["owned"] == 3
    checks = {c["key"]: c for c in body["checks"]}
    assert checks["no_photo"]["count"] == 3  # none of them have a photo
    assert checks["no_grade"]["count"] == 3  # none carry a grade_id
    assert bare["id"] in [i["id"] for i in checks["no_cost"]["items"]]
    assert checks["no_cost"]["count"] == 1
    assert checks["no_value"]["count"] == 2  # bare and silver_no_weight
    assert silver_no_weight["id"] in [i["id"] for i in checks["no_weight"]["items"]]
    assert checks["no_weight"]["count"] == 1
    assert checks["no_storage"]["count"] == 2
    assert checks["no_reference"]["count"] == 2


def test_data_health_trashed_hidden(client):
    item = create(client)
    client.delete(f"/api/items/{item['id']}")
    body = client.get("/api/stats/data-health").json()
    assert body["owned"] == 0


# --- showcase ----------------------------------------------------------------


def test_showcase_empty_collection(client):
    body = client.get("/api/stats/showcase").json()
    assert body == {"piece_of_the_day": None, "oldest": None, "newest": None, "on_this_day": []}


def test_showcase_oldest_and_newest(client):
    old = create(client, year=1850, acquisition_date="2020-01-01")
    new = create(client, year=2020, acquisition_date="2024-06-01")
    create(client, year=None, year_nd=True, acquisition_date="2010-01-01")  # undated: not oldest

    body = client.get("/api/stats/showcase").json()
    assert body["oldest"]["id"] == old["id"]
    assert body["newest"]["id"] == new["id"]


def test_showcase_piece_of_the_day_stable_and_prefers_photo(client):
    for i in range(5):
        create(client, denomination=str(i))
    first = client.get("/api/stats/showcase").json()
    second = client.get("/api/stats/showcase").json()
    assert first["piece_of_the_day"] == second["piece_of_the_day"]


def test_showcase_on_this_day(client):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    earlier_year = today.year - 5
    on_day = create(client, acquisition_date=f"{earlier_year}-{today.month:02d}-{today.day:02d}")
    create(client, acquisition_date="2001-01-01")  # different day: not included

    body = client.get("/api/stats/showcase").json()
    assert [p["id"] for p in body["on_this_day"]] == [on_day["id"]]


def test_showcase_currency_conversion(client, monkeypatch):
    monkeypatch.setattr(currency, "fetch_rate", lambda base, quote: Decimal("2"))
    item = create(client, currency="EUR", acquisition_price=None, acquisition_date="2024-01-01")
    add_value(client, item, 50, currency="EUR")
    body = client.get("/api/stats/showcase").json()
    assert body["newest"]["value"] == 100.0
    assert body["newest"]["currency"] == "USD"


def test_showcase_trashed_hidden(client):
    item = create(client)
    client.delete(f"/api/items/{item['id']}")
    body = client.get("/api/stats/showcase").json()
    assert body == {"piece_of_the_day": None, "oldest": None, "newest": None, "on_this_day": []}


def test_showcase_wishlist_and_sold_excluded(client):
    create(client, status="wishlist")
    create(client, status="sold", sold_price=10)
    body = client.get("/api/stats/showcase").json()
    assert body["piece_of_the_day"] is None
