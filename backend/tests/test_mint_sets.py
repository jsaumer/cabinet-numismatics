"""Proof and mint sets (SPEC_0370, v0.37.0, stage 1): the `mint_set` item
type on the backend."""

from datetime import date, timedelta

from app.models import Item
from app.schemas import SET_YEAR_REQUIRED
from app.services import numista, pcgs
from tests.conftest import COIN

SET = {
    "type": "mint_set",
    "country": "United States",
    "denomination": "Proof Set",
    "issuer": "United States Mint",
    "year": 1981,
    "strike": "proof",
    "piece_count": 6,
    "packaging": "sealed",
    "has_box": True,
    "has_coa": False,
    "quantity": 1,
    "currency": "USD",
}


def create(client, base=SET, **fields):
    resp = client.post("/api/items", json={**base, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def listed(client, **params):
    resp = client.get("/api/items", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ---------------------------------------------------------------- the type


def test_a_set_round_trips_its_fields(client):
    made = create(client)
    assert made["type"] == "mint_set"
    assert (made["piece_count"], made["packaging"], made["has_box"], made["has_coa"]) == (
        6,
        "sealed",
        True,
        False,
    )
    assert made["count_in_stack"] is False
    got = client.get(f"/api/items/{made['id']}").json()
    assert got["packaging"] == "sealed" and got["piece_count"] == 6


def test_label_is_year_then_mint_then_name(client):
    made = create(client)
    assert made["year_label"] == "1981"
    trash = client.delete(f"/api/items/{made['id']}")
    assert trash.status_code in (200, 204)
    entry = next(e for e in client.get("/api/trash").json()["items"] if e["id"] == made["id"])
    assert entry["label"] == "1981 United States Mint Proof Set"


def test_label_falls_back_to_country_without_a_mint():
    item = Item(type="mint_set", year=1981, year_nd=False, country="United States")
    item.denomination = "Proof Set"
    assert item.label == "1981 United States Proof Set"


def test_a_set_needs_a_year(client):
    body = {**SET}
    body.pop("year")
    resp = client.post("/api/items", json=body)
    assert resp.status_code == 422
    assert SET_YEAR_REQUIRED in resp.text


def test_a_set_is_never_nd(client):
    resp = client.post("/api/items", json={**SET, "year_nd": True})
    assert resp.status_code == 422
    assert SET_YEAR_REQUIRED in resp.text

    made = create(client)
    for patch in ({"year": None}, {"year_nd": True}):
        resp = client.patch(f"/api/items/{made['id']}", json=patch)
        assert resp.status_code == 422, patch
        assert resp.json()["detail"] == SET_YEAR_REQUIRED


def test_an_undated_coin_cannot_become_a_set(client):
    coin = create(client, COIN, year=None, year_nd=True)
    resp = client.patch(f"/api/items/{coin['id']}", json={"type": "mint_set"})
    assert resp.status_code == 422


def test_issuing_mint_may_be_empty_through_the_api(client):
    made = create(client, issuer=None)
    assert made["issuer"] is None


def test_piece_count_and_packaging_are_checked(client):
    for bad in ({"piece_count": 0}, {"piece_count": 101}, {"packaging": "boxed"}):
        assert client.post("/api/items", json={**SET, **bad}).status_code == 422, bad
    # Packaging is read case-insensitively.
    assert create(client, packaging="Complete")["packaging"] == "complete"


def test_serial_traits_are_never_computed_for_a_set(client):
    made = create(client, serial_number="11111111")
    assert made["serial_traits"] == []
    note = create(client, {**COIN, "type": "note"}, serial_number="11111111")
    assert note["serial_traits"] == ["solid"]
    # Turning the note into a set clears them.
    changed = client.patch(f"/api/items/{note['id']}", json={"type": "mint_set"}).json()
    assert changed["serial_traits"] == []


# ---------------------------------------------------------------- the list


def test_type_and_packaging_filters(client):
    sealed = create(client)
    opened = create(client, packaging="incomplete", year=1982)
    create(client, COIN)

    assert {i["id"] for i in listed(client, type="mint_set")} == {sealed["id"], opened["id"]}
    assert [i["id"] for i in listed(client, packaging="sealed")] == [sealed["id"]]
    assert client.get("/api/items", params={"packaging": "boxed"}).status_code == 422


def test_name_sort_places_a_set_by_its_year(client):
    create(client, COIN, year=1990, mint_mark=None, denomination="5 cents")
    create(client)  # 1981
    create(client, COIN, year=1970, mint_mark=None, denomination="10 cents")
    names = [(i["type"], i["year"]) for i in listed(client, sort="name")]
    assert names == [("coin", 1970), ("mint_set", 1981), ("coin", 1990)]


# ---------------------------------------------------------------- bulk edit


def test_bulk_edit_changes_count_in_stack_but_not_packaging(client):
    one, two = create(client), create(client, year=1982)
    resp = client.post(
        "/api/items/bulk",
        json={
            "ids": [one["id"], two["id"]],
            "set": {"count_in_stack": True, "packaging": "incomplete", "piece_count": 9},
        },
    )
    assert resp.status_code == 200, resp.text
    for made in (one, two):
        got = client.get(f"/api/items/{made['id']}").json()
        assert got["count_in_stack"] is True
        assert (got["packaging"], got["piece_count"]) == ("sealed", 6)


def test_bulk_edit_cannot_make_an_undated_piece_a_set(client):
    dated = create(client, COIN)
    undated = create(client, COIN, year=None, year_nd=True)
    resp = client.post(
        "/api/items/bulk",
        json={"ids": [dated["id"], undated["id"]], "set": {"type": "mint_set"}},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == SET_YEAR_REQUIRED
    assert client.get(f"/api/items/{dated['id']}").json()["type"] == "coin"

    resp = client.post("/api/items/bulk", json={"ids": [dated["id"]], "set": {"type": "mint_set"}})
    assert resp.status_code == 200


# ---------------------------------------------------------------- counts


def test_owned_sets_have_their_own_count(client):
    create(client)
    create(client, status="wishlist")
    create(client, COIN)
    counts = client.get("/api/stats/collection").json()["counts"]
    assert (counts["mint_sets"], counts["coins"], counts["bullion"]) == (1, 1, 0)


def test_metrics_count_sets_by_type(client):
    create(client)
    assert client.put("/api/settings", json={"metrics_enabled": True}).status_code == 200
    body = client.get("/api/metrics").text
    assert 'cabinet_items{status="owned",type="mint_set"} 1.0' in body


# ---------------------------------------------------------------- valuing


def test_pcgs_and_numista_refuse_a_set_before_any_setting():
    item = Item(type="mint_set")
    assert pcgs.prerequisite(None, item) == pcgs.SETS_REFUSED
    assert numista.prerequisite(None, item) == numista.SETS_REFUSED
    assert "no sets" in numista.sales_prerequisite(None, item)


def test_pricing_a_set_from_pcgs_answers_why(client):
    assert client.put("/api/settings", json={"pcgs_enabled": True}).status_code == 200
    made = create(client)
    resp = client.post(f"/api/items/{made['id']}/estimates/auto", params={"source": "pcgs"})
    assert resp.status_code == 422
    assert "doesn't price sets" in resp.text


def test_comps_does_not_mark_a_set_down_for_having_no_grade(client):
    made = create(client)
    coin = create(client, COIN)
    sold = (date.today() - timedelta(days=30)).isoformat()
    for item in (made, coin):
        resp = client.post(
            f"/api/items/{item['id']}/comparables",
            json={"sold_on": sold, "venue": "eBay", "price": 40, "currency": "USD"},
        )
        assert resp.status_code == 201, resp.text

    def confidence(item):
        resp = client.post(f"/api/items/{item['id']}/estimates/auto", params={"source": "comps"})
        assert resp.status_code == 201, resp.text
        return resp.json()["confidence"]

    assert confidence(made) == 0.30  # one sale, nothing taken off
    assert confidence(coin) == 0.25  # one sale, no grade to hold it against


# ---------------------------------------------------------------- insights


def test_quality_figures_leave_sets_out(client):
    create(client)
    create(client, COIN, cert_service="PCGS", cert_number="12345678")
    body = client.get("/api/stats/quality").json()
    assert body["owned"] == 1
    assert body["certified"]["items"] == 1 and body["raw"]["items"] == 0
    assert body["ungraded"] == 1  # the coin; the set isn't counted


def test_data_health_asks_a_set_for_its_mint_not_a_grade(client):
    create(client)
    missing = create(client, issuer=None, year=1982)
    blank = create(client, issuer="  ", year=1983)
    checks = {c["key"]: c for c in client.get("/api/stats/data-health").json()["checks"]}
    assert checks["no_grade"]["count"] == 0
    assert checks["no_issuing_mint"]["count"] == 2
    assert {i["id"] for i in checks["no_issuing_mint"]["items"]} == {missing["id"], blank["id"]}
