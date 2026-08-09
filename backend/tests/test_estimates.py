import csv
import io


def test_manual_estimate_and_history(client, coin):
    resp = client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 150.0, "currency": "USD", "source": "manual"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["estimated_value"] == 150.0
    assert body["source"] == "manual"
    assert body["confidence"] is None  # manual entries carry no confidence score

    resp = client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 165.0})
    assert resp.status_code == 201

    history = client.get(f"/api/items/{coin['id']}/estimates").json()
    assert len(history) == 2  # append-only: both retained

    detail = client.get(f"/api/items/{coin['id']}").json()
    assert len(detail["estimates"]) == 2


def test_estimate_validation(client, coin):
    assert (
        client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 0}).status_code
        == 422
    )


def test_list_shows_latest_value(client, coin):
    client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 150.0})
    entry = client.get("/api/items").json()["items"][0]
    assert entry["latest_value"] == 150.0
    assert entry["latest_value_currency"] == "USD"


def test_csv_export(client, coin):
    client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 150.0})

    resp = client.get("/api/items/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert rows[0]["country"] == "United States"
    assert rows[0]["latest_value"] == "150.00"
