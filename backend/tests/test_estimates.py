import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db import get_db
from app.main import app
from app.models import PriceEstimate
from app.services import currency
from tests.conftest import COIN


def _session():
    """A DB session on the test engine (via the client's dependency override)."""
    return next(app.dependency_overrides[get_db]())


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


def test_value_strategy_preferred_source_with_fallback(client, coin):
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "source": "numista:N#1 XF"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 150.0, "source": "manual"},  # newer, but not preferred
    )
    client.put(
        "/api/settings", json={"value_strategy": "preferred_source", "preferred_source": "numista"}
    )
    entries = {e["id"]: e for e in client.get("/api/items").json()["items"]}
    assert entries[coin["id"]]["latest_value"] == 100.0  # preferred wins over the newer manual one

    fallback_item = client.post("/api/items", json=COIN).json()
    client.post(
        f"/api/items/{fallback_item['id']}/estimates",
        json={"estimated_value": 75.0, "source": "manual"},
    )
    entries = {e["id"]: e for e in client.get("/api/items").json()["items"]}
    assert entries[fallback_item["id"]]["latest_value"] == 75.0  # no numista here: falls back


def test_value_strategy_average_mixed_currency(client, coin, monkeypatch):
    def fake_rate(base, quote):
        if (base, quote) == ("CAD", "USD"):
            return Decimal("0.5")
        raise currency.RateUnavailable("no rate")

    monkeypatch.setattr(currency, "fetch_rate", fake_rate)
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "currency": "USD", "source": "melt:silver @ 0.01/g"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 200.0, "currency": "CAD", "source": "numista:N#1 XF"},
    )
    client.put("/api/settings", json={"value_strategy": "average"})  # display currency stays USD

    entry = client.get("/api/items").json()["items"][0]
    # melt: 100 USD; numista: 200 CAD * 0.5 = 100 USD; average = 100
    assert entry["latest_value"] == 100.0
    assert entry["latest_value_currency"] == "USD"


def test_value_strategy_average_excludes_manual_and_dedupes(client, coin):
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 1000.0, "source": "manual"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "source": "melt:silver @ 0.01/g"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 50.0, "source": "numista:N#1 XF"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 60.0, "source": "numista:N#1 UNC"},  # supersedes the numista above
    )

    # Estimates created in quick succession can land in the same second; pin an
    # explicit order so "most recent per source" is deterministic in the test.
    db = _session()
    item_id = uuid.UUID(coin["id"])
    now = datetime.now(timezone.utc)
    ordered_sources = ["manual", "melt:silver @ 0.01/g", "numista:N#1 XF", "numista:N#1 UNC"]
    rows = db.query(PriceEstimate).filter(PriceEstimate.item_id == item_id).all()
    for est in rows:
        age = len(ordered_sources) - ordered_sources.index(est.source)
        est.fetched_at = now - timedelta(minutes=age)
    db.commit()
    db.close()

    client.put("/api/settings", json={"value_strategy": "average"})
    entry = client.get("/api/items").json()["items"][0]
    # manual excluded, older numista superseded: average of melt (100) and numista (60) = 80
    assert entry["latest_value"] == 80.0


def test_value_strategy_average_falls_back_when_nothing_converts(client, coin, monkeypatch):
    def unavailable(base, quote):
        raise currency.RateUnavailable("offline")

    monkeypatch.setattr(currency, "fetch_rate", unavailable)
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "currency": "CAD", "source": "melt:silver @ 0.01/g"},
    )
    client.put("/api/settings", json={"value_strategy": "average"})  # display currency is USD

    entry = client.get("/api/items").json()["items"][0]
    assert entry["latest_value"] == 100.0  # no rate available: falls back to plain "latest"
    assert entry["latest_value_currency"] == "CAD"


def test_csv_export_respects_value_strategy(client, coin):
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 100.0, "source": "numista:N#1 XF"},
    )
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 150.0, "source": "manual"},
    )
    client.put(
        "/api/settings", json={"value_strategy": "preferred_source", "preferred_source": "numista"}
    )

    resp = client.get("/api/items/export.csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows[0]["latest_value"] == "100.00"
