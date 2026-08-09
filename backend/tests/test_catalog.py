"""Phase 2: grades, tags, catalog refs, new item fields, clone, import."""

import csv
import io

from tests.conftest import COIN


def _grade_id(client, code, scale="sheldon"):
    grades = client.get("/api/grades", params={"scale": scale}).json()
    return next(g["id"] for g in grades if g["code"] == code)


def test_grades_seeded(client):
    sheldon = client.get("/api/grades", params={"scale": "sheldon"}).json()
    assert any(g["code"] == "MS-65" for g in sheldon)
    assert [g["rank"] for g in sheldon] == sorted(g["rank"] for g in sheldon)
    pmg = client.get("/api/grades", params={"scale": "pmg"}).json()
    assert any(g["code"] == "66" for g in pmg)


def test_item_with_phase2_fields(client):
    grade_id = _grade_id(client, "MS-64")
    resp = client.post(
        "/api/items",
        json={
            **COIN,
            "status": "owned",
            "composition": "90% silver",
            "weight_g": 6.25,
            "fineness": 0.9,
            "grade_id": grade_id,
            "cert_service": "PCGS",
            "cert_number": "12345678",
            "acquired_from": "Heritage auction",
            "storage_location": "Safe box 2",
            "tags": ["type set", "silver"],
            "catalog_refs": [{"catalog": "Numista", "ref_code": "N-1234"}],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["grade"]["code"] == "MS-64"
    assert body["tags"] == ["silver", "type set"]  # sorted by name
    assert body["catalog_refs"] == [{"catalog": "numista", "ref_code": "N-1234"}]
    assert body["weight_g"] == 6.25

    assert client.post("/api/items", json={**COIN, "grade_id": 99999}).status_code == 422
    assert client.post("/api/items", json={**COIN, "status": "melted"}).status_code == 422


def test_sold_item_fields(client, coin):
    resp = client.patch(
        f"/api/items/{coin['id']}",
        json={"status": "sold", "sold_date": "2026-08-01", "sold_price": 180.0},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sold"
    assert resp.json()["sold_price"] == 180.0

    body = client.get("/api/items", params={"status": "sold"}).json()
    assert body["total"] == 1
    assert client.get("/api/items", params={"status": "owned"}).json()["total"] == 0


def test_tag_update_and_filtering(client, coin):
    resp = client.patch(f"/api/items/{coin['id']}", json={"tags": ["wishlist", "silver"]})
    assert sorted(resp.json()["tags"]) == ["silver", "wishlist"]

    resp = client.patch(f"/api/items/{coin['id']}", json={"tags": ["silver"]})
    assert resp.json()["tags"] == ["silver"]

    assert client.get("/api/items", params={"tag": "silver"}).json()["total"] == 1
    assert client.get("/api/items", params={"tag": "gold"}).json()["total"] == 0

    tags = client.get("/api/tags").json()
    silver = next(t for t in tags if t["name"] == "silver")
    assert silver["count"] == 1


def test_grade_range_filter_and_sort(client):
    for code in ["VG-8", "MS-63", "AU-55"]:
        gid = _grade_id(client, code)
        assert client.post("/api/items", json={**COIN, "grade_id": gid}).status_code == 201
    assert client.post("/api/items", json=COIN).status_code == 201  # ungraded

    body = client.get("/api/items", params={"grade_min": 50}).json()
    assert body["total"] == 2
    body = client.get("/api/items", params={"grade_min": 50, "grade_max": 60}).json()
    assert body["total"] == 1

    body = client.get("/api/items", params={"sort": "-grade"}).json()
    codes = [i["grade"]["code"] if i["grade"] else None for i in body["items"]]
    assert codes[:3] == ["MS-63", "AU-55", "VG-8"]


def test_value_range_filter(client):
    for value in [10.0, 100.0]:
        item = client.post("/api/items", json=COIN).json()
        client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": value})
    client.post("/api/items", json=COIN)  # no estimate

    assert client.get("/api/items", params={"value_min": 50}).json()["total"] == 1
    assert client.get("/api/items", params={"value_max": 50}).json()["total"] == 1


def test_search_covers_refs_and_certs(client):
    client.post(
        "/api/items",
        json={
            **COIN,
            "cert_number": "45678901",
            "catalog_refs": [{"catalog": "krause", "ref_code": "KM-164"}],
        },
    )
    assert client.get("/api/items", params={"q": "KM-164"}).json()["total"] == 1
    assert client.get("/api/items", params={"q": "45678901"}).json()["total"] == 1
    assert client.get("/api/items", params={"q": "nonexistent"}).json()["total"] == 0


def test_clone(client):
    gid = _grade_id(client, "XF-40")
    original = client.post(
        "/api/items",
        json={**COIN, "grade_id": gid, "tags": ["clone me"], "notes": "original"},
    ).json()

    resp = client.post(f"/api/items/{original['id']}/clone")
    assert resp.status_code == 201
    copy = resp.json()
    assert copy["id"] != original["id"]
    assert copy["grade"]["code"] == "XF-40"
    assert copy["tags"] == ["clone me"]
    assert copy["notes"] == "original"
    assert client.get("/api/items").json()["total"] == 2


def test_csv_round_trip(client):
    gid = _grade_id(client, "MS-65")
    client.post(
        "/api/items",
        json={
            **COIN,
            "grade_id": gid,
            "composition": "90% silver",
            "weight_g": 6.25,
            "fineness": 0.9,
            "tags": ["silver", "type set"],
            "catalog_refs": [{"catalog": "numista", "ref_code": "N-1"}],
        },
    )
    exported = client.get("/api/items/export.csv").text
    row = next(csv.DictReader(io.StringIO(exported)))
    assert row["grade"] == "MS-65" and row["grade_scale"] == "sheldon"
    assert row["tags"] == "silver|type set"
    assert row["catalog_refs"] == "numista:N-1"

    # delete everything, then re-import the export
    items = client.get("/api/items").json()["items"]
    for item in items:
        client.delete(f"/api/items/{item['id']}")
    assert client.get("/api/items").json()["total"] == 0

    resp = client.post(
        "/api/items/import", files={"file": ("items.csv", exported.encode(), "text/csv")}
    )
    assert resp.status_code == 200
    assert resp.json() == {"created": 1, "errors": []}

    body = client.get("/api/items").json()
    assert body["total"] == 1
    restored = body["items"][0]
    assert restored["grade"]["code"] == "MS-65"
    assert restored["tags"] == ["silver", "type set"]
    assert restored["weight_g"] == 6.25


def test_import_reports_row_errors(client):
    csv_text = (
        "type,country,denomination,year,grade_scale,grade\n"
        "coin,France,1 franc,1960,,\n"
        "coin,France,1 franc,9999,,\n"  # year out of range
        "coin,France,1 franc,1962,sheldon,ZZ-99\n"  # unknown grade
    )
    resp = client.post(
        "/api/items/import", files={"file": ("bad.csv", csv_text.encode(), "text/csv")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert len(body["errors"]) == 2
    assert body["errors"][0]["row"] == 3
    assert "ZZ-99" in body["errors"][1]["error"]
