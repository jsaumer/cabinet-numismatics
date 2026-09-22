"""v0.27.1: undated pieces (ND), and picking the right Numista variety."""

import csv
import io

import pytest

from app.services import importing, numista
from tests.conftest import COIN, import_cabinet_csv
from tests.test_numista import configure, estimate, grade_id
from tests.test_numista_catalogue import catalogue  # noqa: F401  (fixture)

ND_NOTE = {
    "type": "note",
    "country": "Germany",
    "denomination": "50 pfennig",
    "year_nd": True,
    "series": "Notgeld, Stadt Bielefeld",
}


def create(client, payload, **overrides):
    return client.post("/api/items", json={**payload, **overrides})


# ---------------------------------------------------------------- the schema rule


def test_a_year_is_required_unless_the_piece_is_undated(client):
    missing = create(client, {k: v for k, v in COIN.items() if k != "year"})
    assert missing.status_code == 422
    assert "tick ND" in missing.text

    zero = create(client, COIN, year=0)
    assert zero.status_code == 422 and "no year 0" in zero.text

    undated = create(client, ND_NOTE)
    assert undated.status_code == 201, undated.text
    body = undated.json()
    assert (body["year"], body["year_nd"], body["year_label"]) == (None, True, "ND")

    attributed = create(client, ND_NOTE, year=1922).json()
    assert attributed["year_label"] == "ND (1922)"
    assert create(client, COIN).json()["year_label"] == "1932"


def test_the_rule_is_checked_against_the_item_as_it_will_be(client):
    coin = create(client, COIN).json()
    assert client.patch(f"/api/items/{coin['id']}", json={"year": None}).status_code == 422

    turned = client.patch(f"/api/items/{coin['id']}", json={"year": None, "year_nd": True})
    assert turned.status_code == 200 and turned.json()["year_label"] == "ND"
    # and back again: an undated piece needs a year before ND comes off
    assert client.patch(f"/api/items/{coin['id']}", json={"year_nd": False}).status_code == 422
    dated = client.patch(f"/api/items/{coin['id']}", json={"year_nd": False, "year": 1932})
    assert dated.status_code == 200 and dated.json()["year_label"] == "1932"


def test_bulk_edit_leaves_nd_alone(client):
    undated = create(client, ND_NOTE).json()
    resp = client.post(
        "/api/items/bulk", json={"ids": [undated["id"]], "set": {"year_nd": False, "notes": "x"}}
    )
    assert resp.status_code == 200
    after = client.get(f"/api/items/{undated['id']}").json()
    assert (after["year_nd"], after["notes"]) == (True, "x")

    # nor can a bulk edit empty the year, since ND isn't part of it
    empty = client.post("/api/items/bulk", json={"ids": [undated["id"]], "set": {"year": None}})
    assert empty.status_code == 422


def test_the_label_ends_with_the_year_label(client):
    undated = create(client, ND_NOTE, year=1921, mint_mark=None).json()
    trash = client.delete(f"/api/items/{undated['id']}")
    assert trash.status_code == 204
    [entry] = client.get("/api/trash").json()["items"]
    assert entry["label"] == "Germany 50 pfennig ND (1921)"


# ---------------------------------------------------------------- list, filters, stats


def test_sorting_puts_undated_last_and_the_year_filters_skip_it(client):
    create(client, COIN, year=1932)
    create(client, COIN, year=1950)
    create(client, ND_NOTE)

    def years(sort):
        return [i["year"] for i in client.get("/api/items", params={"sort": sort}).json()["items"]]

    assert years("year") == [1932, 1950, None]
    assert years("-year") == [1950, 1932, None]

    for params in ({"year": 1932}, {"year_min": 1900}, {"year_max": 2000}):
        found = client.get("/api/items", params=params).json()["items"]
        assert all(i["year"] is not None for i in found), params

    undated = client.get("/api/items", params={"nd": True}).json()
    assert [i["year_label"] for i in undated["items"]] == ["ND"]
    dated = client.get("/api/items", params={"nd": False}).json()
    assert dated["total"] == 2


def test_the_decade_breakdown_buckets_undated_pieces_last(client):
    create(client, COIN, year=1932)
    create(client, ND_NOTE)
    body = client.get("/api/stats/breakdowns").json()
    assert [entry["key"] for entry in body["by_decade"]] == ["1930s", "Undated"]


def test_similar_matches_undated_pieces_with_no_year(client):
    undated = create(client, ND_NOTE).json()
    params = {"country": "Germany", "denomination": "50 pfennig", "nd": True}
    [found] = client.get("/api/items/similar", params=params).json()
    assert found["id"] == undated["id"]
    assert found["label"] == "Germany 50 pfennig ND"

    # a dated candidate of the same kind is not the same piece
    dated = {**params, "nd": False, "year": 1921}
    assert client.get("/api/items/similar", params=dated).json() == []
    # nor is one with nothing to identify it
    assert client.get("/api/items/similar", params={"country": "Germany"}).json() == []


# ---------------------------------------------------------------- export and import


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def test_export_writes_year_nd_and_import_reads_it_back(client):
    create(client, COIN, year=1932)
    create(client, ND_NOTE, year=1921)
    create(client, ND_NOTE, denomination="1 mark")

    rows = _rows(client.get("/api/items/export.csv").text)
    by_label = {f"{r['denomination']} {r['year']} {r['year_nd']}": r for r in rows}
    assert set(by_label) == {"25 cents 1932 ", "50 pfennig 1921 true", "1 mark  true"}


@pytest.mark.parametrize(
    "header, row, expected",
    [
        ("type,country,denomination,year", "note,Germany,1 mark,ND (1951)", (1951, True)),
        ("type,country,denomination,year", "note,Germany,1 mark,ND", (None, True)),
        ("type,country,denomination,year", "note,Germany,1 mark,", (None, True)),
        ("type,country,denomination,year,year_nd", "note,Germany,1 mark,1951,true", (1951, True)),
        ("type,country,denomination,year,year_nd", "note,Germany,1 mark,1951,", (1951, False)),
    ],
)
def test_import_reads_undated_year_cells(client, header, row, expected):
    body = f"{header}\n{row}\n".encode()
    result = import_cabinet_csv(client, body)
    assert (result["created"], result["skipped"], result["errors"]) == (1, 0, []), result
    [item] = client.get("/api/items").json()["items"]
    assert (item["year"], item["year_nd"]) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (1978, (1978, False)),
        ("1978", (1978, False)),
        ("1982-1993", (1982, False)),
        (1978.0, (1978, False)),
        ("ND", (None, True)),
        ("N.D.", (None, True)),
        ("n.d", (None, True)),
        ("undated", (None, True)),
        ("ND (1951)", (1951, True)),
        ("ND(1951)", (1951, True)),
        ("(1951)", (1951, True)),
        ("", (None, True)),
        (None, (None, True)),
        (0, (None, True)),
        ("no year", (None, True)),
    ],
)
def test_parse_year(value, expected):
    assert importing.parse_year(value) == expected


# ---------------------------------------------------------------- Numista varieties

# N#223126, a 1951 Military Payment Certificate: two issues both resolve to
# 1951, and only the second (the regular note, P# M22a) is priced.
MPC_ISSUES = {
    "items": [
        {
            "id": 101,
            "is_dated": False,
            "min_year": 1951,
            "comment": "Serial number: no suffix letter",
            "references": [{"catalogue": {"code": "P"}, "number": "M22r"}],
        },
        {
            "id": 102,
            "year": 1951,
            "comment": "Serial number: prefix letter and suffix letter",
            "references": [{"catalogue": {"code": "P"}, "number": "M22a"}],
        },
    ]
}
PRICED = {"currency": "USD", "prices": [{"grade": "vf", "price": 30.0}]}
UNPRICED = {"currency": "USD", "prices": []}


@pytest.fixture()
def mpc(monkeypatch):
    """Numista's answers for N#223126, with only issue 102 priced."""
    calls: list[str] = []

    def fake_request(api_key, path, params=None):
        calls.append(path)
        if path == "types/223126/issues":
            return MPC_ISSUES
        if path == "types/223126/issues/102/prices":
            return PRICED
        if path == "types/223126/issues/101/prices":
            return UNPRICED
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    return calls


def note_item(client, **overrides):
    payload = {
        "type": "note",
        "country": "United States",
        "denomination": "5 cents",
        "year": 1951,
        "series": "Military Payment Certificate, Series 481",
        "grade_id": grade_id(client, "pmg", "20"),
        "catalog_refs": [
            {"catalog": "numista", "ref_code": "N#223126"},
            {"catalog": "p", "ref_code": "P#M22a"},
        ],
        **overrides,
    }
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_the_priced_variety_wins_over_the_replacement_note(client, mpc):
    configure(client)
    body = estimate(client, note_item(client)).json()
    assert body["estimated_value"] == 30.0
    details = body["details"]
    assert details["issue_id"] == 102
    assert details["issue_reference"] == "P# M22a"
    assert "prefix letter" in details["issue_comment"]
    assert (details["issue_nd"], details["candidates_tried"]) == (False, 1)
    assert "year_mismatch" not in details
    assert "types/223126/issues/101/prices" not in mpc  # the unpriced one cost nothing


def test_a_replacement_note_tries_its_own_issue_first(client, mpc):
    configure(client)
    item = note_item(client, replacement_note=True, catalog_refs=[
        {"catalog": "numista", "ref_code": "N#223126"}
    ])  # fmt: skip
    details = estimate(client, item).json()["details"]
    assert details["issue_id"] == 102  # 101 was tried first, and has no prices
    assert details["candidates_tried"] == 2
    assert mpc.index("types/223126/issues/101/prices") < mpc.index("types/223126/issues/102/prices")


def test_an_undated_item_pools_the_undated_issues(client, monkeypatch):
    issues = {
        "items": [
            {"id": 8, "year": 1949},
            {"id": 9, "is_dated": False, "min_year": 1951},
        ]
    }

    def fake_request(api_key, path, params=None):
        if path == "types/223126/issues":
            return issues
        if path == "types/223126/issues/9/prices":
            return PRICED
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    configure(client)
    item = note_item(client, year=None, year_nd=True, catalog_refs=[
        {"catalog": "numista", "ref_code": "N#223126"}
    ])  # fmt: skip
    details = estimate(client, item).json()["details"]
    assert (details["issue_id"], details["issue_nd"]) == (9, True)


def test_a_single_issue_type_is_priced_with_a_year_mismatch(client, monkeypatch):
    def fake_request(api_key, path, params=None):
        if path == "types/223126/issues":
            return {"items": [{"id": 5, "is_dated": False}]}
        if path == "types/223126/issues/5/prices":
            return PRICED
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    configure(client)
    item = note_item(client, year=1957, catalog_refs=[
        {"catalog": "numista", "ref_code": "N#223126"}
    ])  # fmt: skip
    details = estimate(client, item).json()["details"]
    assert (details["issue_id"], details["year_mismatch"]) == (5, True)


def test_no_priced_issue_says_how_many_were_tried(client, monkeypatch):
    def fake_request(api_key, path, params=None):
        if path == "types/223126/issues":
            return MPC_ISSUES
        if path.endswith("/prices"):
            return UNPRICED
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    configure(client)
    resp = estimate(client, note_item(client))
    assert resp.status_code == 422
    assert "no priced grade for any of the 2 1951 issue(s)" in resp.json()["detail"]


def test_an_undated_item_with_no_issue_says_undated(client, monkeypatch):
    def fake_request(api_key, path, params=None):
        if path == "types/223126/issues":
            return {"items": [{"id": 8, "year": 1949}, {"id": 9, "year": 1950}]}
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    configure(client)
    item = note_item(client, year=None, year_nd=True, catalog_refs=[
        {"catalog": "numista", "ref_code": "N#223126"}
    ])  # fmt: skip
    resp = estimate(client, item)
    assert resp.status_code == 422
    assert "lists no undated issue" in resp.json()["detail"]


# ---------------------------------------------------------------- a run of undated issues


def test_a_run_can_add_undated_items(client, catalogue):  # noqa: F811
    configure(client)
    resp = client.post(
        "/api/items/run",
        json={"type_id": 1493, "issues": [{"nd": True}, {"year": 1951, "nd": True}]},
    )
    assert resp.status_code == 201, resp.text
    labels = [
        client.get(f"/api/items/{item_id}").json()["year_label"]
        for item_id in resp.json()["item_ids"]
    ]
    assert labels == ["ND", "ND (1951)"]

    # the same undated issue again is skipped as owned
    again = client.post("/api/items/run", json={"type_id": 1493, "issues": [{"nd": True}]})
    assert again.json()["skipped"] == 1
