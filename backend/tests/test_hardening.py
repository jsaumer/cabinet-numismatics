"""What the November 2026 review reproduced on a real Postgres stack: a
stored row that breaks an input rule must still be readable, and a value a
column has no room for is a 422, never a database error. SQLite (these
tests) raises none of those errors itself, so the bounds are pinned here."""

import uuid

import pytest
from sqlalchemy.exc import DataError

from app.db import get_db
from app.main import app
from app.models import Item
from app.schemas import BULK_YEAR_REQUIRED, NEVER_NULL
from tests.conftest import COIN, import_cabinet_csv

BAR = {
    "type": "bullion",
    "country": "Switzerland",
    "denomination": "1 oz silver bar",
    "composition": "Silver",
    "weight_g": 31.1035,
    "fineness": 0.999,
}


def _session():
    return next(app.dependency_overrides[get_db]())


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- reads never validate a stored row ----------------------------------------


def test_a_bar_with_no_year_cannot_become_a_coin_in_bulk(client):
    bar = _create(client, BAR)
    resp = client.post("/api/items/bulk", json={"ids": [bar["id"]], "set": {"type": "coin"}})
    assert resp.status_code == 422
    assert resp.json()["detail"] == BULK_YEAR_REQUIRED
    assert client.get(f"/api/items/{bar['id']}").json()["type"] == "bullion"

    # With a year in the same edit, or on a bar that has one, it goes through.
    dated = client.post(
        "/api/items/bulk", json={"ids": [bar["id"]], "set": {"type": "coin", "year": 2020}}
    )
    assert dated.status_code == 200
    assert client.get(f"/api/items/{bar['id']}").json()["year_label"] == "2020"


def test_a_stored_row_that_breaks_an_input_rule_still_reads(client):
    """However it got there (an older build, a rule tightened since), one such
    row took the whole list page down with a 500."""
    item = _create(client, COIN)
    db = _session()
    try:
        row = db.get(Item, uuid.UUID(item["id"]))
        row.year, row.year_nd = None, False  # a coin with neither a year nor ND
        row.weight_g = 123456  # past the input bound
        row.designations = ["NOT A DESIGNATION"]
        row.currency = "usd"
        db.commit()
    finally:
        db.close()

    listed = client.get("/api/items")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == item["id"]
    detail = client.get(f"/api/items/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["year"] is None and detail.json()["designations"] == ["NOT A DESIGNATION"]
    # And it can be put right through the API.
    fixed = client.patch(f"/api/items/{item['id']}", json={"year_nd": True, "designations": []})
    assert fixed.status_code == 200


def test_a_struck_date_that_converts_out_of_range_is_refused(client):
    item = _create(client, COIN)
    resp = client.patch(
        f"/api/items/{item['id']}",
        json={"year": None, "struck_calendar": "hebrew", "struck_year": 100},
    )
    assert resp.status_code == 422
    assert "date as struck" in resp.json()["detail"]
    assert client.get(f"/api/items/{item['id']}").json()["year"] == COIN["year"]
    assert client.get("/api/items").status_code == 200


# --- null where a column can't be ------------------------------------------------


@pytest.mark.parametrize("field", NEVER_NULL)
def test_patch_refuses_null_for_a_required_field(client, coin, field):
    resp = client.patch(f"/api/items/{coin['id']}", json={field: None})
    assert resp.status_code == 422, field
    assert field in str(resp.json()["detail"])


def test_bulk_edit_refuses_null_for_a_required_field(client, coin):
    resp = client.post("/api/items/bulk", json={"ids": [coin["id"]], "set": {"country": None}})
    assert resp.status_code == 422


def test_nullable_fields_still_clear_with_null(client, coin):
    resp = client.patch(f"/api/items/{coin['id']}", json={"mint_mark": None, "notes": None})
    assert resp.status_code == 200 and resp.json()["mint_mark"] is None


# --- bounds that match the columns -----------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"weight_g": 100_000},
        {"weight_g": 1_000_000_000},
        {"quantity": 2**31},
        {"mintage": 10**19},
        {"acquisition_price": 10**10},
        {"acquisition_fees": 10**15},
        {"sold_price": 10**10},
        {"sold_fees": 10**10},
        {"tags": ["x" * 51]},
    ],
)
def test_values_with_no_room_in_their_column_are_422(client, coin, extra):
    assert client.post("/api/items", json={**COIN, **extra}).status_code == 422, extra
    assert client.patch(f"/api/items/{coin['id']}", json=extra).status_code == 422, extra


def test_the_largest_values_that_fit_are_accepted(client):
    item = _create(
        client,
        {
            **COIN,
            "weight_g": 99999.9999,
            "quantity": 2**31 - 1,
            "acquisition_price": 9_999_999_999.99,
            "tags": ["x" * 50],
        },
    )
    assert item["quantity"] == 2**31 - 1


def test_other_inputs_are_bounded_too(client, coin):
    too_much = client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 10**10})
    assert too_much.status_code == 422
    long_slot = client.post("/api/checklists", json={"name": "Run", "slots": ["s" * 201]})
    assert long_slot.status_code == 422
    long_tag = client.post("/api/items/bulk", json={"ids": [coin["id"]], "add_tags": ["t" * 51]})
    assert long_tag.status_code == 422


def test_a_database_data_error_is_a_422_not_a_500(client, monkeypatch):
    """The net behind the bounds, for a column they missed. Postgres raises
    this for a numeric overflow or a text too long; SQLite never does."""
    from app.routers import items as items_router

    def refuse(*args, **kwargs):
        raise DataError("INSERT", {}, Exception("numeric field overflow"))

    monkeypatch.setattr(items_router, "_build_item", refuse)
    resp = client.post("/api/items", json=COIN)
    assert resp.status_code == 422
    assert "numeric" not in resp.text and "INSERT" not in resp.text  # nothing of the statement


# --- one form for a currency -----------------------------------------------------


def test_currencies_are_stored_upper_case(client):
    item = _create(client, {**COIN, "currency": "usd", "acquisition_price": 10})
    assert item["currency"] == "USD"
    patched = client.patch(f"/api/items/{item['id']}", json={"currency": " eur "})
    assert patched.json()["currency"] == "EUR"
    estimate = client.post(
        f"/api/items/{item['id']}/estimates", json={"estimated_value": 12, "currency": "usd"}
    )
    assert estimate.status_code == 201 and estimate.json()["currency"] == "USD"
    # Counted in the totals, where "usd" used to match no rate and drop out.
    client.patch(f"/api/items/{item['id']}", json={"currency": "usd"})
    stats = client.get("/api/stats/collection", params={"currency": "USD"}).json()
    assert stats["cost_basis"] == 10 and stats["estimated_value"] == 12
    assert stats["excluded_other_currency"] == 0


@pytest.mark.parametrize("bad", ["us", "usdd", "us1", "u$d", "", 840])
def test_a_currency_is_three_letters(client, coin, bad):
    assert client.post("/api/items", json={**COIN, "currency": bad}).status_code == 422
    assert client.patch(f"/api/items/{coin['id']}", json={"currency": bad}).status_code == 422


# --- imports -----------------------------------------------------------------------


def test_an_oversize_cell_is_that_rows_error(client):
    csv_text = (
        "type,country,denomination,year,weight_g\n"
        "coin,France,1 franc,1960,5\n"
        "coin,France,1 franc,1961,311035\n"  # a weight typed in milligrams
        "coin,France,1 franc,1962,5\n"
    )
    body = import_cabinet_csv(client, csv_text, "weights.csv")
    assert body["created"] == 2
    assert [e["row"] for e in body["errors"]] == [2]


def test_a_row_the_database_refuses_does_not_end_the_import(client, monkeypatch):
    from app.services import pricing

    real = pricing.melt_on_save

    def refuse_1961(db, item):
        if item.year == 1961:
            raise DataError("INSERT", {}, Exception("value too long"))
        return real(db, item)

    monkeypatch.setattr(pricing, "melt_on_save", refuse_1961)
    csv_text = (
        "type,country,denomination,year\n"
        "coin,France,1 franc,1960\n"
        "coin,France,1 franc,1961\n"
        "coin,France,1 franc,1962\n"
    )
    body = import_cabinet_csv(client, csv_text, "refused.csv")
    assert body["created"] == 2
    assert [e["row"] for e in body["errors"]] == [2]
    assert client.get("/api/items").json()["total"] == 2
