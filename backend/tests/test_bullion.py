"""Bars and rounds (P11, v0.31.0, stage 2): the `bullion` item type on the
backend, and its Numista and import paths."""

import pytest

from app.models import Item
from app.services import import_formats as formats
from app.services import numista
from app.services.pricing import NotApplicable
from tests.conftest import COIN, import_cabinet_csv
from tests.test_numista_catalogue import catalogue, configure  # noqa: F401  (fixtures)

BULLION = {
    "type": "bullion",
    "country": "Switzerland",
    "denomination": "1 oz silver bar",
    "issuer": "PAMP Suisse",
    "composition": "Silver (.999)",
    "weight_g": 31.1035,
    "fineness": 0.999,
    "quantity": 1,
    "currency": "USD",
}
NOTE = {
    "type": "note",
    "country": "United States",
    "denomination": "1 dollar",
    "year": 1957,
    "currency": "USD",
}


def create(client, base=BULLION, **fields):
    resp = client.post("/api/items", json={**base, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def listed(client, **params):
    resp = client.get("/api/items", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ---------------------------------------------------------------- the year rule


def test_bullion_needs_no_year(client):
    bar = create(client)
    assert (bar["year"], bar["year_nd"], bar["year_label"]) == (None, False, "")

    dated = create(client, year=2015)
    assert (dated["year"], dated["year_nd"], dated["year_label"]) == (2015, False, "2015")

    # A patch that clears the year on a coin still needs ND; bullion doesn't.
    resp = client.patch(f"/api/items/{bar['id']}", json={"year": None})
    assert resp.status_code == 200


def test_coin_without_year_or_nd_is_still_422(client):
    missing = client.post("/api/items", json={k: v for k, v in COIN.items() if k != "year"})
    assert missing.status_code == 422
    assert "tick ND" in missing.text


# ---------------------------------------------------------------- label and year_label


def test_bullion_label_and_year_label():
    """`Item.label` isn't on the API response, so this is a model-level check
    (no session needed: the property only reads scalar columns)."""
    bar = Item(type="bullion", country="Switzerland", denomination="1 oz silver bar",
               issuer="PAMP Suisse")  # fmt: skip
    assert bar.year_label == ""
    assert bar.label == "PAMP Suisse 1 oz silver bar"  # no double space, no "ND"

    no_issuer = Item(type="bullion", country="Switzerland", denomination="1 oz silver bar")
    assert no_issuer.label == "Switzerland 1 oz silver bar"  # falls back to country

    dated = Item(type="bullion", country="Switzerland", denomination="1 oz silver bar", year=2015)
    assert dated.year_label == "2015"
    assert dated.label == "Switzerland 1 oz silver bar 2015"  # no mint mark ever

    coin = Item(type="coin", country="United States", denomination="25 cents")
    assert coin.year_label == "ND"  # coins and notes keep "ND"


# ---------------------------------------------------------------- serial traits


def test_serial_traits_are_never_computed_for_bullion(client):
    bar = create(client, serial_number="12344321")  # a radar serial on a coin/note
    assert bar["serial_traits"] == []

    note = create(client, NOTE, serial_number="12344321")
    assert note["serial_traits"] == ["radar"]

    changed = client.patch(f"/api/items/{note['id']}", json={"type": "bullion"}).json()
    assert changed["serial_traits"] == []

    back = client.patch(f"/api/items/{note['id']}", json={"type": "note"}).json()
    assert back["serial_traits"] == ["radar"]  # recomputed, not left cleared


# ---------------------------------------------------------------- counts, breakdown, metrics


def test_counts_and_breakdown_include_bullion(client):
    create(client)
    create(client, COIN)
    create(client, NOTE)

    counts = client.get("/api/stats/collection").json()["counts"]
    assert (counts["bullion"], counts["coins"], counts["notes"]) == (1, 1, 1)

    by_type = {e["key"]: e["count"] for e in client.get("/api/stats/breakdowns").json()["by_type"]}
    assert by_type["bullion"] == 1


def test_metrics_include_bullion(client):
    client.put("/api/settings", json={"metrics_enabled": True})
    create(client)
    text = client.get("/api/metrics").text
    assert 'cabinet_items{status="owned",type="bullion"} 1.0' in text


# ---------------------------------------------------------------- list filter and bulk edit


def test_type_filter_and_bulk_edit(client):
    bar = create(client)
    note = create(client, NOTE, serial_number="12344321")
    assert note["serial_traits"] == ["radar"]

    assert {i["id"] for i in listed(client, type="bullion")} == {bar["id"]}
    assert {i["id"] for i in listed(client)} == {bar["id"], note["id"]}

    resp = client.post("/api/items/bulk", json={"ids": [note["id"]], "set": {"type": "bullion"}})
    assert resp.status_code == 200 and resp.json()["updated"] == 1
    updated = client.get(f"/api/items/{note['id']}").json()
    assert updated["type"] == "bullion"
    assert updated["serial_traits"] == []  # cleared by the bulk type change


# ---------------------------------------------------------------- imports


@pytest.mark.parametrize("value,expected", [
    ("Bar", "bullion"),
    ("round", "bullion"),
    ("Ingot", "bullion"),
    ("Bullion", "bullion"),
    ("Coin", "coin"),
    ("Banknote", "note"),
    ("", "coin"),
])  # fmt: skip
def test_spreadsheet_type_mapping(value, expected):
    assert formats._item_type(value, "coin") == expected


def test_cabinet_csv_round_trip_with_bullion(client, tmp_path):
    bar = create(client, year=2015)
    export = tmp_path / "cabinet-items.csv"
    export.write_bytes(client.get("/api/items/export.csv").content)
    client.delete(f"/api/items/{bar['id']}?permanent=true")

    result = import_cabinet_csv(client, export.read_bytes(), "cabinet-items.csv")
    assert result["created"] == 1, result
    [copy] = listed(client)
    assert copy["type"] == "bullion"
    assert copy["year"] == 2015
    assert copy["denomination"] == BULLION["denomination"]
    assert copy["issuer"] == BULLION["issuer"]


# ---------------------------------------------------------------- Numista

# The live shape, from the owner's probe of types/430821 (22 September 2026),
# trimmed to the fields Cabinet reads.
BAR_TYPE = {
    "id": 430821,
    "title": "1 Oz Silver - Majestic Merlion (Singapore Mint and PAMP Silver Bar)",
    "object_type": {"id": 36, "name": "Bars"},
    "issuer": {"code": "singapour", "name": "Singapore"},
    "min_year": 2015,
    "max_year": 2015,
    "size": 55,
    "size2": 32,
    "thickness": 1.7,
    "shape": "Rectangular",
    "composition": {"text": "Silver (.9999)"},
    "tags": ["Mythology"],
    "weight": 31.1,
    "orientation": "medal",
    "edge": {"description": "Plain"},
    "mints": [
        {"id": 1874, "name": "Produits Artistiques M\u00e9taux Pr\u00e9cieux (PAMP)"},
        {"id": 25, "name": "Singapore Mint"},
    ],
    "category": "exonumia",
    "type": "Bars",
}
# A cafe token: its object type NAMES a bar, and is not one.
TOKEN_TYPE = {
    "id": 323738,
    "title": "30 Centimes - Grand caf\u00e9 d'Alger",
    "object_type": {"id": 186, "name": "Restaurant, bar, cafe and hotel tokens"},
    "issuer": {"code": "algerie", "name": "Algeria"},
    "category": "exonumia",
    "type": "Restaurant, bar, cafe and hotel tokens",
}
# A collector piece with a face value, filed under exonumia: not bullion.
COLLECTOR_TYPE = {
    "id": 555817,
    "title": "10 Diners (Silver Bar - Golden Eagle)",
    "object_type": {"id": 47, "name": "Collector coins"},
    "issuer": {"code": "andorre", "name": "Andorra"},
    "min_year": 2011,
    "max_year": 2012,
    "category": "exonumia",
}


def test_catalogue_fields_bar_reads_as_bullion():
    fields = numista.catalogue_fields(BAR_TYPE)
    assert fields["type"] == "bullion"
    assert fields["country"] == "Singapore"
    assert (
        fields["issuer"] == "Produits Artistiques M\u00e9taux Pr\u00e9cieux (PAMP)"
    )  # the first mint
    assert fields["denomination"] == BAR_TYPE["title"]  # the product name, not a face value
    assert fields["composition"] == "Silver (.9999)"
    assert fields["fineness"] == 0.9999
    assert fields["weight_g"] == 31.1
    assert (fields["width_mm"], fields["height_mm"]) == (55, 32)  # a bar is not round
    assert "diameter_mm" not in fields
    assert fields["thickness_mm"] == 1.7
    assert fields["shape"] == "Rectangular"
    assert fields["edge"] == "Plain"
    assert fields["year"] == 2015


def test_catalogue_fields_bar_by_id_or_name_only():
    by_name = {**BAR_TYPE, "object_type": {"id": 999, "name": "Rounds"}}
    assert numista.catalogue_fields(by_name)["type"] == "bullion"
    by_id = {**BAR_TYPE, "object_type": {"id": 36, "name": "Something new"}}
    assert numista.catalogue_fields(by_id)["type"] == "bullion"
    bare = {**BAR_TYPE, "mints": [], "object_type": None}  # only the top-level type says Bars
    fields = numista.catalogue_fields(bare)
    assert fields["type"] == "bullion" and "issuer" not in fields


@pytest.mark.parametrize("payload", [TOKEN_TYPE, COLLECTOR_TYPE], ids=["token", "collector"])
def test_catalogue_fields_other_exonumia_is_refused(payload):
    with pytest.raises(NotApplicable, match="bars and rounds"):
        numista.catalogue_fields(payload)


def test_search_accepts_exonumia_category(client, catalogue):  # noqa: F811
    configure(client)
    resp = client.get("/api/numista/search", params={"q": "bar", "category": "exonumia"})
    assert resp.status_code == 200
    assert catalogue == [("types", {"q": "bar", "count": 20, "category": "exonumia"})]
