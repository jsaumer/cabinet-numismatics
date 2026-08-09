from tests.conftest import COIN


def test_create_and_get_item(client, coin):
    assert coin["type"] == "coin"
    assert coin["country"] == "United States"
    assert coin["id"]

    resp = client.get(f"/api/items/{coin['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["denomination"] == "25 cents"
    assert detail["photos"] == []
    assert detail["estimates"] == []


def test_get_missing_item_404(client):
    resp = client.get("/api/items/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_validation_rejects_bad_input(client):
    assert client.post("/api/items", json={**COIN, "type": "stamp"}).status_code == 422
    assert client.post("/api/items", json={**COIN, "year": 5000}).status_code == 422
    assert client.post("/api/items", json={**COIN, "quantity": 0}).status_code == 422


def test_update_item(client, coin):
    resp = client.patch(f"/api/items/{coin['id']}", json={"quantity": 4, "notes": "album 2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 4
    assert body["notes"] == "album 2"
    assert body["country"] == "United States"  # untouched fields survive


def test_delete_item(client, coin):
    assert client.delete(f"/api/items/{coin['id']}").status_code == 204
    assert client.get(f"/api/items/{coin['id']}").status_code == 404


def test_list_filters_sort_and_pagination(client):
    items = [
        {**COIN, "year": 1932, "country": "United States"},
        {
            **COIN,
            "type": "note",
            "denomination": "10 dollars",
            "year": 1950,
            "country": "Canada",
            "series": "Devil's Face",
        },
        {**COIN, "year": 1889, "country": "Germany", "series": "Wilhelm II"},
    ]
    for item in items:
        assert client.post("/api/items", json=item).status_code == 201

    body = client.get("/api/items").json()
    assert body["total"] == 3 and len(body["items"]) == 3

    body = client.get("/api/items", params={"type": "note"}).json()
    assert body["total"] == 1 and body["items"][0]["country"] == "Canada"

    body = client.get("/api/items", params={"country": "germany"}).json()  # case-insensitive
    assert body["total"] == 1

    body = client.get("/api/items", params={"year": 1932}).json()
    assert body["total"] == 1

    body = client.get("/api/items", params={"q": "devil"}).json()  # matches series
    assert body["total"] == 1 and body["items"][0]["type"] == "note"

    years = [i["year"] for i in client.get("/api/items", params={"sort": "year"}).json()["items"]]
    assert years == [1889, 1932, 1950]
    years = [i["year"] for i in client.get("/api/items", params={"sort": "-year"}).json()["items"]]
    assert years == [1950, 1932, 1889]

    body = client.get("/api/items", params={"sort": "year", "limit": 2, "offset": 2}).json()
    assert body["total"] == 3 and len(body["items"]) == 1 and body["items"][0]["year"] == 1950

    assert client.get("/api/items", params={"sort": "evil"}).status_code == 422
