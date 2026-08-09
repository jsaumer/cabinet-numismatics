"""Phase 5B: sets/lots, variety, custom fields, bulk edit."""

import csv
import io

from tests.conftest import COIN


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_sets_crud_and_assignment(client):
    resp = client.post("/api/sets", json={"name": "Mercury dime run", "notes": "1916–1945"})
    assert resp.status_code == 201
    set_id = resp.json()["id"]

    assert client.post("/api/sets", json={"name": "Mercury dime run"}).status_code == 409

    item = _create(client, {**COIN, "set_id": set_id})
    assert item["set"]["name"] == "Mercury dime run"

    sets = client.get("/api/sets").json()
    assert sets[0]["item_count"] == 1

    body = client.get("/api/items", params={"set_id": set_id}).json()
    assert body["total"] == 1

    assert _create(client, COIN)["set"] is None
    assert client.post("/api/items", json={**COIN, "set_id": 999}).status_code == 422

    # deleting the set detaches items rather than deleting them
    assert client.delete(f"/api/sets/{set_id}").status_code == 204
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["set"] is None


def test_variety_roundtrip_and_search(client):
    item = _create(client, {**COIN, "denomination": "1 cent", "year": 1955, "variety": "1955 DDO"})
    assert item["variety"] == "1955 DDO"
    assert client.get("/api/items", params={"q": "DDO"}).json()["total"] == 1


def test_custom_fields(client):
    item = _create(
        client,
        {**COIN, "custom_fields": {"die state": "late", "provenance ref": "lot 4521"}},
    )
    assert item["custom_fields"] == {"die state": "late", "provenance ref": "lot 4521"}

    resp = client.patch(f"/api/items/{item['id']}", json={"custom_fields": {"die state": "early"}})
    assert resp.json()["custom_fields"] == {"die state": "early"}

    too_many = {f"k{i}": "v" for i in range(21)}
    assert client.post("/api/items", json={**COIN, "custom_fields": too_many}).status_code == 422
    assert client.post("/api/items", json={**COIN, "custom_fields": {"k": 5}}).status_code == 422


def test_bulk_edit(client):
    ids = [_create(client, COIN)["id"] for _ in range(3)]

    resp = client.post(
        "/api/items/bulk",
        json={
            "ids": ids,
            "set": {"storage_location": "Safe box 3", "status": "wishlist"},
            "add_tags": ["bulk"],
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 3}

    for item_id in ids:
        detail = client.get(f"/api/items/{item_id}").json()
        assert detail["storage_location"] == "Safe box 3"
        assert detail["status"] == "wishlist"
        assert "bulk" in detail["tags"]

    resp = client.post("/api/items/bulk", json={"ids": ids[:2], "remove_tags": ["bulk"]})
    assert resp.json() == {"updated": 2}
    assert "bulk" not in client.get(f"/api/items/{ids[0]}").json()["tags"]
    assert "bulk" in client.get(f"/api/items/{ids[2]}").json()["tags"]

    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post("/api/items/bulk", json={"ids": [missing]}).status_code == 404


def test_csv_round_trip_with_depth_fields(client):
    set_id = client.post("/api/sets", json={"name": "Type set"}).json()["id"]
    _create(
        client,
        {
            **COIN,
            "variety": "1932-D",
            "set_id": set_id,
            "custom_fields": {"album page": "3"},
        },
    )

    exported = client.get("/api/items/export.csv").text
    row = next(csv.DictReader(io.StringIO(exported)))
    assert row["variety"] == "1932-D"
    assert row["set"] == "Type set"
    assert row["custom_fields"] == '{"album page": "3"}'

    items = client.get("/api/items").json()["items"]
    for item in items:
        client.delete(f"/api/items/{item['id']}")

    resp = client.post(
        "/api/items/import", files={"file": ("items.csv", exported.encode(), "text/csv")}
    )
    assert resp.json() == {"created": 1, "errors": []}
    restored = client.get("/api/items").json()["items"][0]
    assert restored["variety"] == "1932-D"
    assert restored["set"]["name"] == "Type set"
    assert restored["custom_fields"] == {"album page": "3"}
