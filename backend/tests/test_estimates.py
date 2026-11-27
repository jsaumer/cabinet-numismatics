import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.db import get_db
from app.main import app
from app.models import PriceEstimate
from app.services import currency
from tests.conftest import COIN, source_estimate


def _session():
    """A DB session on the test engine (via the client's dependency override)."""
    return next(app.dependency_overrides[get_db]())


def _age(item_id, days: float, source: str | None = None) -> None:
    """Move an item's estimates (or one source's) back in time, so order is
    unmistakable on SQLite's whole seconds."""
    db = _session()
    query = db.query(PriceEstimate).filter(PriceEstimate.item_id == uuid.UUID(str(item_id)))
    for row in query:
        if source is None or row.source == source:
            row.fetched_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()
    db.close()


def test_the_item_carries_the_newest_estimate_per_source(client, coin):
    item_id = coin["id"]
    base = f"/api/items/{item_id}/estimates"
    # Oldest first; each is aged as it goes in.
    for days, source, value in (
        (9, "numista:N#1 VF", 40.0),
        (8, "eBay sold", 55.0),
        (7, "melt:silver @ 0.01/g", 5.0),
        (6, "numista:N#1 XF", 60.0),
        (5, "dealer quote", 70.0),
        (4, "pcgs:guide 3912", 80.0),
    ):
        if source.split(":")[0] in ("melt", "numista", "pcgs"):
            source_estimate(item_id, estimated_value=value, source=source)
        else:
            made = client.post(base, json={"estimated_value": value, "source": source})
            assert made.status_code == 201
        _age(item_id, days, source)

    latest = client.get(f"/api/items/{item_id}").json()["latest_estimates"]
    # One per source, newest first; every typed-in value is "manual".
    assert [(e["source_key"], e["estimated_value"]) for e in latest] == [
        ("pcgs", 80.0),
        ("manual", 70.0),
        ("numista", 60.0),
        ("melt", 5.0),
    ]
    assert latest[1]["source"] == "dealer quote"  # the sentence is still there

    page = client.get(base).json()
    assert (page["total"], page["limit"], page["offset"]) == (6, 100, 0)
    assert [e["estimated_value"] for e in page["items"]] == [80.0, 70.0, 60.0, 5.0, 55.0, 40.0]

    second = client.get(base, params={"limit": 2, "offset": 2}).json()
    assert second["total"] == 6
    assert [e["estimated_value"] for e in second["items"]] == [60.0, 5.0]

    numista = client.get(base, params={"source": "numista"}).json()
    assert (numista["total"], [e["estimated_value"] for e in numista["items"]]) == (2, [60.0, 40.0])
    typed = client.get(base, params={"source": "manual"}).json()
    assert (typed["total"], [e["source"] for e in typed["items"]]) == (
        2,
        ["dealer quote", "eBay sold"],
    )
    assert client.get(base, params={"source": "comps"}).json()["items"] == []


@pytest.mark.parametrize(
    "params", [{"source": "moon"}, {"limit": 0}, {"limit": 501}, {"offset": -1}, {"offset": 10**12}]
)
def test_the_estimate_history_refuses_a_bad_page(client, coin, params):
    assert client.get(f"/api/items/{coin['id']}/estimates", params=params).status_code == 422
    if "source" not in params:
        assert client.get(f"/api/items/{coin['id']}/history", params=params).status_code == 422


def test_the_edit_history_comes_a_page_at_a_time(client, coin):
    for year in (1933, 1934, 1935):
        assert client.patch(f"/api/items/{coin['id']}", json={"year": year}).status_code == 200
    base = f"/api/items/{coin['id']}/history"
    page = client.get(base).json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 100, 0)
    assert [e["action"] for e in page["items"]] == ["updated", "updated", "updated", "created"]
    second = client.get(base, params={"limit": 2, "offset": 1}).json()
    assert second["total"] == 4
    assert [e["changes"]["year"][1] for e in second["items"]] == [1934, 1933]
    assert client.get(base, params={"offset": 10}).json()["items"] == []


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
    assert body["source_key"] == "manual"

    _age(coin["id"], days=1)  # SQLite keeps whole seconds
    resp = client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 165.0})
    assert resp.status_code == 201

    history = client.get(f"/api/items/{coin['id']}/estimates").json()["items"]
    assert len(history) == 2  # append-only: both retained

    # The item itself carries the newest per source: one typed-in value.
    detail = client.get(f"/api/items/{coin['id']}").json()
    assert "estimates" not in detail
    assert [e["estimated_value"] for e in detail["latest_estimates"]] == [165.0]


def test_manual_estimate_note(client, coin):
    url = f"/api/items/{coin['id']}/estimates"
    body = client.post(url, json={"estimated_value": 150.0, "note": "  eBay lot 123, raw  "}).json()
    assert body["details"] == {"note": "eBay lot 123, raw"}
    assert client.post(url, json={"estimated_value": 150.0}).json()["details"] is None
    blank = client.post(url, json={"estimated_value": 150.0, "note": "   "}).json()
    assert blank["details"] is None
    assert client.post(url, json={"estimated_value": 150.0, "note": "x" * 501}).status_code == 422


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
    assert entry["latest_value_source"] == "manual"


def test_list_shows_latest_value_source_for_preferred_strategy(client, coin):
    source_estimate(coin["id"], estimated_value=100.0, source="numista:N#1 XF")
    client.post(
        f"/api/items/{coin['id']}/estimates",
        json={"estimated_value": 150.0, "source": "manual"},  # newer, but not preferred
    )
    client.put(
        "/api/settings", json={"value_strategy": "preferred_source", "preferred_source": "numista"}
    )
    entry = client.get("/api/items").json()["items"][0]
    assert entry["latest_value"] == 100.0
    assert entry["latest_value_source"] == "numista"


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
    source_estimate(coin["id"], estimated_value=100.0, source="numista:N#1 XF")
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
    source_estimate(
        coin["id"], estimated_value=100.0, currency="USD", source="melt:silver @ 0.01/g"
    )
    source_estimate(coin["id"], estimated_value=200.0, currency="CAD", source="numista:N#1 XF")
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
    source_estimate(coin["id"], estimated_value=100.0, source="melt:silver @ 0.01/g")
    source_estimate(coin["id"], estimated_value=50.0, source="numista:N#1 XF")
    source_estimate(
        coin["id"], estimated_value=60.0, source="numista:N#1 UNC"
    )  # supersedes the numista above

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
    source_estimate(
        coin["id"], estimated_value=100.0, currency="CAD", source="melt:silver @ 0.01/g"
    )
    client.put("/api/settings", json={"value_strategy": "average"})  # display currency is USD

    entry = client.get("/api/items").json()["items"][0]
    assert entry["latest_value"] == 100.0  # no rate available: falls back to plain "latest"
    assert entry["latest_value_currency"] == "CAD"


def test_csv_export_respects_value_strategy(client, coin):
    source_estimate(coin["id"], estimated_value=100.0, source="numista:N#1 XF")
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


def test_a_typed_value_can_be_deleted_and_a_source_value_cannot(client, coin):
    base = f"/api/items/{coin['id']}/estimates"
    typed = client.post(base, json={"estimated_value": 1.7, "source": "ebay lot"}).json()
    kept = client.post(base, json={"estimated_value": 2.0}).json()

    session = _session()
    sourced = PriceEstimate(
        item_id=uuid.UUID(coin["id"]),
        source="numista:N#1 VG",
        estimated_value=Decimal("1.74"),
        currency="USD",
    )
    session.add(sourced)
    session.commit()
    sourced_id = sourced.id

    assert client.delete(f"{base}/{typed['id']}").status_code == 204
    refused = client.delete(f"{base}/{sourced_id}")
    assert refused.status_code == 409 and "typed" in refused.json()["detail"]
    assert client.delete(f"{base}/{uuid.uuid4()}").status_code == 404

    left = {e["id"] for e in client.get(base).json()["items"]}
    assert left == {kept["id"], str(sourced_id)}


def test_an_estimate_is_only_deleted_through_its_own_item(client, coin):
    other = client.post("/api/items", json={**COIN, "year": 1901}).json()
    typed = client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 5.0}).json()
    assert client.delete(f"/api/items/{other['id']}/estimates/{typed['id']}").status_code == 404
    assert len(client.get(f"/api/items/{coin['id']}/estimates").json()["items"]) == 1
