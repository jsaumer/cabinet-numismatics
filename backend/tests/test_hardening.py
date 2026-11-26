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


# --- the last 500s the review listed ---------------------------------------------


def test_renaming_a_set_to_a_taken_name_is_a_conflict(client):
    first = client.post("/api/sets", json={"name": "Type set"}).json()
    second = client.post("/api/sets", json={"name": "Morgans"}).json()
    clash = client.patch(f"/api/sets/{second['id']}", json={"name": " Type set "})
    assert clash.status_code == 409
    assert "already exists" in clash.json()["detail"]
    # Its own name, and a new one, are both fine.
    assert client.patch(f"/api/sets/{first['id']}", json={"name": "Type set"}).status_code == 200
    renamed = client.patch(f"/api/sets/{second['id']}", json={"name": "Morgan dollars"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Morgan dollars"


def test_a_slot_cannot_be_linked_to_a_piece_that_is_not_there(client, coin):
    checklist = client.post("/api/checklists", json={"name": "Run", "slots": ["1964"]}).json()
    slot = checklist["slots"][0]
    url = f"/api/checklists/{checklist['id']}/slots/{slot['id']}"
    missing = client.patch(url, json={"item_id": str(uuid.uuid4())})
    assert missing.status_code == 422
    assert missing.json()["detail"] == "No item with that id"
    linked = client.patch(url, json={"item_id": coin["id"]})
    assert linked.status_code == 200 and linked.json()["item_id"] == coin["id"]

    client.delete(f"/api/items/{coin['id']}")  # in the trash: not there to link either
    other = client.post("/api/checklists", json={"name": "Other", "slots": ["1965"]}).json()
    trashed = client.patch(
        f"/api/checklists/{other['id']}/slots/{other['slots'][0]['id']}",
        json={"item_id": coin["id"]},
    )
    assert trashed.status_code == 422


def test_a_csv_cell_past_the_readers_limit_is_a_422_at_preview(client):
    """The csv module refuses a cell over 131,072 characters. (It refused a
    NUL byte too until Python 3.11; that one is left to whichever Python
    runs, and to the per-row guard in the import itself.)"""
    cell = "x" * 140_000
    body = f"type,country,denomination,year,notes\ncoin,France,1 franc,1960,{cell}\n".encode()
    upload = client.post("/api/imports", files={"file": ("big.csv", body, "text/csv")})
    assert upload.status_code == 201, upload.text
    preview = client.post(
        f"/api/imports/{upload.json()['upload_id']}/preview", json={"format": "cabinet"}
    )
    assert preview.status_code == 422
    assert "can't be read as a spreadsheet" in preview.json()["detail"]


def test_a_sale_cannot_have_its_included_flag_emptied(client, coin):
    sale = client.post(
        f"/api/items/{coin['id']}/comparables",
        json={"sold_on": "2026-01-05", "venue": "eBay", "price": 40},
    )
    assert sale.status_code == 201, sale.text
    emptied = client.patch(f"/api/comparables/{sale.json()['id']}", json={"included": None})
    assert emptied.status_code == 422
    left_out = client.patch(f"/api/comparables/{sale.json()['id']}", json={"included": False})
    assert left_out.status_code == 200 and left_out.json()["included"] is False


# --- one dead upstream costs one request, not one per amount ---------------------


def test_a_rate_that_cannot_be_fetched_is_asked_for_once(client, monkeypatch):
    """Five pieces priced in a currency the rate service doesn't carry used to
    cost five requests (five seconds each when it is down) for every stats
    call the dashboard makes."""
    from app.services import currency

    calls = []

    def unavailable(base, quote):
        calls.append((base, quote))
        raise currency.RateUnavailable("not carried")

    monkeypatch.setattr(currency, "fetch_rate", unavailable)
    for year in range(1960, 1965):
        _create(client, {**COIN, "year": year, "currency": "ARS", "acquisition_price": 10})

    stats = client.get("/api/stats/collection", params={"currency": "USD"}).json()
    assert stats["excluded_other_currency"] == 5  # still excluded and counted, never guessed
    assert calls == [("ARS", "USD")]
    client.get("/api/stats/collection", params={"currency": "USD"})
    client.get("/api/stats/breakdowns", params={"currency": "USD"})
    assert len(calls) == 1  # and left alone for a while after failing

    # Once the wait is over it is tried again.
    monkeypatch.setattr(currency.time, "monotonic", lambda: 10**9)
    client.get("/api/stats/collection", params={"currency": "USD"})
    assert len(calls) == 2


def test_a_rate_that_works_is_fetched_once_and_clears_the_wait(client, monkeypatch):
    from decimal import Decimal

    from app.services import currency

    answers = iter([currency.RateUnavailable("down"), Decimal("0.75")])
    calls = []

    def flaky(base, quote):
        calls.append((base, quote))
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(currency, "fetch_rate", flaky)
    for year in (1960, 1961):
        _create(client, {**COIN, "year": year, "currency": "CAD", "acquisition_price": 100})

    assert client.get("/api/stats/collection").json()["excluded_other_currency"] == 2
    currency.reset_memory()  # the wait over
    stats = client.get("/api/stats/collection").json()
    assert stats["cost_basis"] == 150 and stats["excluded_other_currency"] == 0
    assert calls == [("CAD", "USD"), ("CAD", "USD")]
    assert currency._failed == {}


def test_a_failed_spot_fetch_is_not_repeated_for_every_item(client, monkeypatch):
    from app.services import pricing

    calls = []

    def down(metal):
        calls.append(metal)
        raise pricing.SpotUnavailable("gold-api is down")

    monkeypatch.setattr(pricing, "fetch_spot_price", down)
    silver = {**COIN, "composition": "90% silver", "weight_g": 26.73, "fineness": 0.9}
    for year in range(1921, 1926):
        _create(client, {**silver, "year": year})

    result = client.post("/api/estimates/refresh?source=melt").json()
    assert result["failed"] == 5 and result["updated"] == 0
    assert calls == ["silver"]


# --- exports a spreadsheet program can't read as formulas ---------------------------

FORMULA_LOOKING = {
    "notes": '=HYPERLINK("http://example.com","click")',
    "variety": "+1 over 2",
    "series": "-dash first",
    "acquired_from": "@dealer",
}


def test_csv_export_guards_cells_that_look_like_formulas(client):
    import csv
    import io

    _create(client, {**COIN, **FORMULA_LOOKING})
    text = client.get("/api/items/export.csv").content.decode("utf-8-sig")
    [row] = list(csv.DictReader(io.StringIO(text)))
    for field, value in FORMULA_LOOKING.items():
        assert row[field] == "'" + value, field
    assert row["country"] == COIN["country"]  # ordinary text is left as it is


def test_xlsx_export_stores_them_as_text_not_formulas(client):
    import io

    from openpyxl import load_workbook

    _create(client, {**COIN, **FORMULA_LOOKING})
    sheet = load_workbook(io.BytesIO(client.get("/api/items/export.xlsx").content)).active
    header = [cell.value for cell in sheet[1]]
    notes = sheet.cell(row=2, column=header.index("notes") + 1)
    assert notes.value == FORMULA_LOOKING["notes"]
    assert notes.data_type == "s"  # "f" would be a live formula


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_the_guard_survives_cabinets_own_round_trip(client, extension):
    item = _create(client, {**COIN, **FORMULA_LOOKING})
    exported = client.get(f"/api/items/export.{extension}").content
    client.delete(f"/api/items/{item['id']}?permanent=true")

    upload = client.post(
        "/api/imports", files={"file": (f"cabinet-items.{extension}", exported, "text/csv")}
    )
    assert upload.status_code == 201, upload.text
    run = client.post(f"/api/imports/{upload.json()['upload_id']}/run", json={})
    assert run.status_code == 200 and run.json()["created"] == 1, run.text
    [copy] = client.get("/api/items").json()["items"]
    for field, value in FORMULA_LOOKING.items():
        assert copy[field] == value, field


# --- a save that changes nothing records nothing ----------------------------------


def test_sending_the_same_numbers_back_is_not_an_edit(client):
    """The item form sends every field on each save. JSON floats never equal
    the stored Decimals, so an unchanged save used to add a history row and
    relabel an automatic purchase-day spot price as typed in."""
    item = _create(
        client,
        {
            **COIN,
            "composition": "Silver .999",
            "weight_g": 31.1035,
            "fineness": 0.999,
            "acquisition_price": 12.1,
            "acquisition_fees": 0.3,
            "diameter_mm": 40.6,
        },
    )
    db = _session()
    try:
        row = db.get(Item, uuid.UUID(item["id"]))
        row.spot_at_purchase, row.spot_at_purchase_source = 31.4567, "auto"
        db.commit()
    finally:
        db.close()
    before = client.get(f"/api/items/{item['id']}").json()
    history = client.get(f"/api/items/{item['id']}/history").json()

    numbers = ("weight_g", "fineness", "acquisition_price", "acquisition_fees", "diameter_mm")
    same = {key: before[key] for key in (*numbers, "spot_at_purchase")}
    assert client.patch(f"/api/items/{item['id']}", json=same).status_code == 200
    after = client.get(f"/api/items/{item['id']}").json()
    assert client.get(f"/api/items/{item['id']}/history").json() == history
    assert after["spot_at_purchase_source"] == "auto"

    # A real change is still recorded, with both values.
    client.patch(f"/api/items/{item['id']}", json={"weight_g": 31.2})
    latest = client.get(f"/api/items/{item['id']}/history").json()[0]
    assert latest["changes"] == {"weight_g": [31.1035, 31.2]}

    # And the same holds for a bulk edit, which re-stamps what hangs off a field.
    client.post("/api/items/bulk", json={"ids": [item["id"]], "set": {"quantity": 1}})
    assert client.get(f"/api/items/{item['id']}").json()["spot_at_purchase_source"] == "auto"
