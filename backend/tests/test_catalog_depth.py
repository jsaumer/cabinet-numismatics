"""v0.14.0 catalog depth: grading depth, physical and banknote fields, costs."""

import csv
import io

from tests.conftest import COIN, import_cabinet_csv


def _grade_id(client, code, scale="sheldon"):
    grades = client.get("/api/grades", params={"scale": scale}).json()
    return next(g["id"] for g in grades if g["code"] == code)


def _create(client, **fields):
    resp = client.post("/api/items", json={**COIN, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_grade_labels(client):
    proof = _create(
        client,
        grade_id=_grade_id(client, "MS-69"),
        strike="proof",
        designations=["dcam"],
        grade_star=True,
    )
    assert proof["grade_label"] == "PR-69 DCAM ★"
    assert proof["designations"] == ["DCAM"]

    plus = _create(
        client,
        grade_id=_grade_id(client, "MS-64"),
        grade_plus=True,
        designations=["RD"],
        cac_sticker="green",
    )
    assert (plus["grade_label"], plus["cac_sticker"]) == ("MS-64+ RD", "green")

    cleaned = _create(client, grade_id=_grade_id(client, "VF-20"), grade_details="Cleaned")
    assert cleaned["grade_label"] == "VF-20 Details (Cleaned)"

    note = _create(
        client,
        type="note",
        grade_id=_grade_id(client, "64", "pmg"),
        designations=["EPQ"],
        grade_star=True,
    )
    assert note["grade_label"] == "64 EPQ ★"

    ungraded = _create(client)
    assert (ungraded["grade_label"], ungraded["strike"]) == (None, "business")


def test_grading_and_field_validation(client):
    for bad in (
        {"designations": ["SHINY"]},
        {"cac_sticker": "blue"},
        {"strike": "restrike"},
        {"mintage": -1},
        {"diameter_mm": 0},
        {"acquisition_fees": -5},
        {"sold_fees": -1},
    ):
        assert client.post("/api/items", json={**COIN, **bad}).status_code == 422, bad


def test_pmg_scale_starts_at_one(client):
    codes = [g["code"] for g in client.get("/api/grades", params={"scale": "pmg"}).json()]
    assert codes[:4] == ["1", "2", "3", "4"]


def test_physical_and_banknote_fields(client):
    coin = _create(
        client,
        diameter_mm=24.26,
        thickness_mm=1.75,
        edge="Reeded",
        shape="Round",
        mintage=1_234_567_890,
        strike="proof",
    )
    note = _create(
        client,
        type="note",
        serial_number="A12345678*",
        prefix_block="A/A",
        signatures="Coyne–Towers",
        issuer="Bank of Canada",
        replacement_note=True,
    )
    assert (coin["diameter_mm"], coin["mintage"], coin["edge"]) == (24.26, 1234567890, "Reeded")
    assert (note["replacement_note"], note["issuer"]) == (True, "Bank of Canada")

    found = client.get("/api/items", params={"q": "A12345678"}).json()["items"]
    assert [i["id"] for i in found] == [note["id"]]
    proofs = client.get("/api/items", params={"strike": "proof"}).json()["items"]
    assert [i["id"] for i in proofs] == [coin["id"]]
    assert client.get("/api/items", params={"strike": "restrike"}).status_code == 422

    client.patch(f"/api/items/{note['id']}", json={"serial_number": "B00000001"})
    latest = client.get(f"/api/items/{note['id']}/history").json()[0]
    assert latest["changes"]["serial_number"] == ["A12345678*", "B00000001"]


def test_csv_round_trip_with_catalog_depth(client):
    _create(
        client,
        grade_id=_grade_id(client, "MS-66"),
        strike="proof",
        grade_plus=True,
        grade_star=True,
        designations=["CAM", "RD"],
        grade_details="Scratched",
        cac_sticker="gold",
        diameter_mm=19.05,
        mintage=5000,
        serial_number="X1",
        acquisition_price=100.0,
        acquisition_fees=12.5,
        status="sold",
        sold_price=150.0,
        sold_fees=15.0,
        sold_to="Heritage",
    )
    exported = client.get("/api/items/export.csv").text
    row = next(csv.DictReader(io.StringIO(exported)))
    assert (row["grade"], row["strike"], row["grade_plus"]) == ("MS-66", "proof", "true")
    assert (row["designations"], row["cac_sticker"], row["mintage"]) == ("CAM|RD", "gold", "5000")
    assert float(row["acquisition_fees"]) == 12.5 and float(row["sold_fees"]) == 15.0

    for item in client.get("/api/items").json()["items"]:
        client.delete(f"/api/items/{item['id']}?permanent=true")
    result = import_cabinet_csv(client, exported)
    assert (result["created"], result["skipped"], result["errors"]) == (1, 0, [])

    [restored] = client.get("/api/items").json()["items"]
    assert restored["grade_label"] == "PR-66+ CAM RD ★ Details (Scratched)"
    assert (restored["cac_sticker"], restored["mintage"], restored["serial_number"]) == (
        "gold",
        5000,
        "X1",
    )
    assert (restored["sold_to"], restored["cost_basis"], restored["sale_proceeds"]) == (
        "Heritage",
        112.5,
        135.0,
    )


def test_import_reads_label_style_grades(client):
    csv_text = (
        "type,country,denomination,year,grade_scale,grade\n"
        "coin,United States,1 dollar,1960,sheldon,PR-65\n"
        "coin,United States,1 dollar,1961,,MS-64+\n"
        "coin,United States,1 dollar,1962,,PF-70\n"
        "coin,United States,1 dollar,1963,,SP-99\n"  # no such grade number
    )
    body = import_cabinet_csv(client, csv_text, "labels.csv")
    assert body["created"] == 3
    assert [e["row"] for e in body["errors"]] == [4]  # data rows count from 1

    items = client.get("/api/items").json()["items"]
    assert sorted(i["grade_label"] for i in items) == ["MS-64+", "PR-65", "PR-70"]


def test_fees_flow_into_cost_basis_and_gains(client):
    owned = _create(client, acquisition_price=100.0, acquisition_fees=10.0)
    client.post(f"/api/items/{owned['id']}/estimates", json={"estimated_value": 150.0})
    sold = _create(
        client,
        acquisition_price=50.0,
        acquisition_fees=5.0,
        status="sold",
        sold_price=100.0,
        sold_fees=12.0,
    )
    assert (owned["cost_basis"], sold["sale_proceeds"]) == (110.0, 88.0)

    stats = client.get("/api/stats/collection").json()
    assert (stats["cost_basis"], stats["unrealized_gain"], stats["realized_gain"]) == (
        110.0,
        40.0,
        33.0,
    )
    gains = client.get("/api/stats/gains").json()
    assert [(g["cost_basis"], g["value"], g["gain"]) for g in gains["unrealized"]] == [
        (110.0, 150.0, 40.0)
    ]
    assert [(g["cost_basis"], g["value"], g["gain"]) for g in gains["realized"]] == [
        (55.0, 88.0, 33.0)
    ]
    assert client.get("/api/stats/breakdowns").json()["by_country"][0]["cost_basis"] == 110.0
