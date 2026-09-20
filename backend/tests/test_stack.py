"""Roadmap Phase 7, P7: the bullion stack (fine ounces, cost per ounce, the
premium paid over spot at purchase), the purchase-day spot lookup, and the
spot-price threshold alerts."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import alerts, currency, pricing, stack
from tests.conftest import COIN

# One troy ounce of fine silver per piece, so the arithmetic reads plainly.
OUNCE = {
    **COIN,
    "denomination": "1 dollar",
    "composition": "99.9% silver",
    "weight_g": 31.1035,
    "fineness": 0.999,
    "quantity": 1,
    "acquisition_price": None,
}
IN_COVERAGE = "2025-01-15"


@pytest.fixture()
def spot(monkeypatch):
    """Current spot at $1.00/g, i.e. $31.10 per troy ounce."""
    calls = {"count": 0}

    def fake_fetch(metal):
        calls["count"] += 1
        return Decimal("1.0")

    monkeypatch.setattr(pricing, "fetch_spot_price", fake_fetch)
    return calls


@pytest.fixture()
def history(monkeypatch):
    """The purchase-day source: $20/oz silver, $2000/oz gold, counting calls."""
    calls = {"count": 0, "urls": []}
    prices = {"xag": 20.0, "xau": 2000.0, "xpt": 900.0, "xpd": 1000.0}

    def fake_fetch(code, on):
        calls["count"] += 1
        return {"date": on.isoformat(), code: {"usd": prices[code], "cad": prices[code] * 1.4}}

    monkeypatch.setattr(stack, "_fetch_history", fake_fetch)
    return calls


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _metals(body) -> dict:
    return {m["metal"]: m for m in body["metals"]}


# --- ounces and grouping ----------------------------------------------------


def test_ounces_by_metal_and_quantity(client, spot):
    _create(client, {**OUNCE, "quantity": 3})
    _create(
        client,
        {
            **OUNCE,
            "denomination": "1/2 ounce",
            "composition": "gold",
            "weight_g": 15.55175,
            "fineness": 0.999,
        },
    )
    body = client.get("/api/stack").json()
    metals = _metals(body)
    assert [m["metal"] for m in body["metals"]] == ["gold", "silver"]
    assert metals["silver"]["items"] == 1
    assert metals["silver"]["pieces"] == 3
    assert metals["silver"]["fine_oz"] == 2.997  # 3 pieces × 0.999 fine
    assert metals["silver"]["fine_g"] == 93.22
    assert metals["gold"]["fine_oz"] == 0.5
    assert body["totals"]["fine_oz_by_metal"] == {"gold": 0.5, "silver": 2.997}
    # melt at $31.10/oz for silver
    assert metals["silver"]["melt_value"] == 93.22
    assert metals["silver"]["spot_per_oz"] == 31.1
    assert metals["silver"]["spot_stale"] is False


def test_fineness_from_composition_and_skipped(client, spot):
    _create(client, {**OUNCE, "composition": "90% silver", "fineness": None})
    # A precious metal with no weight is counted as skipped, not as ounces.
    _create(client, {**OUNCE, "weight_g": None})
    # No metal at all is not part of the stack in any way.
    _create(client, COIN)
    body = client.get("/api/stack").json()
    assert body["skipped"] == 1
    assert _metals(body)["silver"]["fine_oz"] == 0.9  # 31.1035 g × 0.90


def test_scope_by_tag_and_set(client, spot):
    _create(client, {**OUNCE, "tags": ["bullion"]})
    _create(client, {**OUNCE, "quantity": 5})
    assert client.get("/api/stack").json()["metals"][0]["pieces"] == 6
    scoped = client.get("/api/stack?tag=bullion").json()
    assert scoped["metals"][0]["pieces"] == 1
    assert client.get("/api/stack?tag=nothing").json()["metals"] == []

    set_id = client.post("/api/sets", json={"name": "Stack"}).json()["id"]
    item = _create(client, {**OUNCE, "quantity": 2, "set_id": set_id})
    assert client.get(f"/api/stack?set_id={set_id}").json()["metals"][0]["pieces"] == 2
    assert client.get(f"/api/stack?set_id={set_id}").json()["items"][0]["item_id"] == item["id"]


def test_trashed_pieces_are_out_of_the_stack(client, spot):
    item = _create(client, {**OUNCE, "quantity": 2})
    _create(client, OUNCE)
    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    body = client.get("/api/stack").json()
    assert body["metals"][0]["pieces"] == 1
    assert len(body["items"]) == 1


def test_only_owned_pieces_count(client, spot):
    _create(client, {**OUNCE, "status": "wishlist"})
    _create(client, {**OUNCE, "status": "sold", "sold_price": 40.0})
    assert client.get("/api/stack").json()["metals"] == []


# --- money ------------------------------------------------------------------


def test_cost_per_ounce_ignores_uncosted_pieces(client, spot):
    _create(client, {**OUNCE, "quantity": 2, "acquisition_price": 50.0, "acquisition_fees": 10.0})
    _create(client, OUNCE)  # no price: its ounces count, its (absent) cost doesn't
    silver = _metals(client.get("/api/stack").json())["silver"]
    assert silver["fine_oz"] == 2.997
    assert silver["costed_oz"] == 1.998
    assert silver["cost_basis"] == 60.0
    assert silver["cost_per_oz"] == 30.03  # 60 / 1.998, the break-even spot
    # gain is the melt value of the costed ounces less their cost
    assert silver["gain"] == pytest.approx(1.998 * 31.1035 - 60.0, abs=0.02)
    assert silver["gain_pct"] == pytest.approx(silver["gain"] / 60.0 * 100, abs=0.02)


def test_other_currency_is_converted(client, spot, monkeypatch):
    monkeypatch.setattr(currency, "fetch_rate", lambda base, quote: Decimal("2"))
    _create(client, {**OUNCE, "currency": "CAD", "acquisition_price": 40.0})
    body = client.get("/api/stack").json()
    row = body["items"][0]
    assert row["currency"] == "CAD" and row["converted"] is True
    assert row["cost_basis"] == 80.0  # 40 CAD at 2.0
    assert body["metals"][0]["cost_basis"] == 80.0
    assert body["excluded_other_currency"] == 0


def test_unconvertible_money_is_excluded_but_its_ounces_count(client, spot):
    # No rate is available in tests, and none is cached for GBP.
    _create(client, {**OUNCE, "currency": "GBP", "acquisition_price": 40.0})
    body = client.get("/api/stack").json()
    assert body["excluded_other_currency"] == 1
    assert body["metals"][0]["fine_oz"] == 0.999  # the ounces still count
    assert body["metals"][0]["cost_basis"] == 0.0
    assert body["metals"][0]["costed_oz"] == 0.0
    assert body["items"][0]["cost_basis"] is None
    assert body["items"][0]["converted"] is False


def test_premium_paid_per_item_and_per_metal(client, spot):
    # Paid 22.50 for an ounce when spot was 20.00: 12.5% over.
    _create(client, {**OUNCE, "acquisition_price": 22.5, "spot_at_purchase": 20.0})
    item = client.get("/api/stack").json()["items"][0]
    assert item["spot_at_purchase"] == 20.0
    assert item["spot_at_purchase_source"] == "manual"
    assert item["premium_paid_pct"] == pytest.approx(12.61, abs=0.02)  # 0.999 oz

    # A second piece with no purchase-day spot leaves the metal's ratio alone.
    _create(client, {**OUNCE, "acquisition_price": 99.0})
    silver = _metals(client.get("/api/stack").json())["silver"]
    assert silver["premium_known_oz"] == 0.999
    assert silver["premium_paid_pct"] == pytest.approx(12.61, abs=0.02)
    assert silver["fine_oz"] == 1.998

    # And the item field is on the item itself.
    detail = client.get(f"/api/items/{item['item_id']}").json()
    assert detail["fine_oz"] == pytest.approx(0.999, abs=0.001)
    assert detail["premium_paid_pct"] == pytest.approx(12.61, abs=0.02)


def test_premium_is_null_without_a_purchase_day_spot(client, spot):
    _create(client, {**OUNCE, "acquisition_price": 40.0})
    body = client.get("/api/stack").json()
    assert body["items"][0]["premium_paid_pct"] is None
    assert body["metals"][0]["premium_paid_pct"] is None
    assert body["metals"][0]["premium_known_oz"] == 0.0


def test_a_metal_with_no_costed_piece_has_no_gain(client, spot):
    _create(client, OUNCE)  # no price paid
    silver = client.get("/api/stack").json()["metals"][0]
    assert silver["melt_value"] is not None
    assert silver["cost_per_oz"] is None and silver["gain"] is None and silver["gain_pct"] is None


def test_spot_unavailable_keeps_the_ounces(client, monkeypatch):
    def broken(metal):
        raise pricing.SpotUnavailable("upstream down")

    monkeypatch.setattr(pricing, "fetch_spot_price", broken)
    _create(client, {**OUNCE, "acquisition_price": 25.0})
    body = client.get("/api/stack").json()
    silver = body["metals"][0]
    assert silver["fine_oz"] == 0.999
    assert silver["cost_per_oz"] == pytest.approx(25.025, abs=0.01)  # the break-even still stands
    assert silver["spot_per_oz"] is None
    assert silver["melt_value"] is None and silver["gain"] is None
    assert body["items"][0]["melt_value"] is None
    assert body["totals"]["melt_value"] == 0.0


def test_items_sorted_by_metal_then_ounces(client, spot):
    _create(client, {**OUNCE, "quantity": 1})
    _create(client, {**OUNCE, "quantity": 4})
    _create(client, {**OUNCE, "composition": "gold", "weight_g": 3.0, "fineness": 0.9})
    body = client.get("/api/stack").json()
    assert [row["metal"] for row in body["items"]] == ["gold", "silver", "silver"]
    assert body["items"][1]["fine_oz"] > body["items"][2]["fine_oz"]


# --- purchase-day spot ------------------------------------------------------


def test_historic_spot_endpoint(client, history):
    resp = client.get(f"/api/reference/historic-spot?metal=silver&date={IN_COVERAGE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "metal": "silver",
        "date": IN_COVERAGE,
        "currency": "USD",
        "per_oz": 20.0,
        "source": "fawazahmed0 currency-api",
    }
    assert history["count"] == 1

    # Cached: the same day costs no request.
    assert (
        client.get(f"/api/reference/historic-spot?metal=silver&date={IN_COVERAGE}").json() == body
    )
    assert history["count"] == 1

    # Another currency comes straight out of the same response.
    other = client.get(
        f"/api/reference/historic-spot?metal=silver&date={IN_COVERAGE}&currency=cad"
    ).json()
    assert other["currency"] == "CAD" and other["per_oz"] == 28.0
    assert history["count"] == 1


def test_historic_spot_refuses_outside_coverage(client, history):
    before = client.get("/api/reference/historic-spot?metal=silver&date=2020-01-01")
    assert before.status_code == 422 and "2024-03-02" in before.json()["detail"]

    today = client.get(f"/api/reference/historic-spot?metal=silver&date={date.today()}")
    assert today.status_code == 422 and "today" in today.json()["detail"]

    unknown = client.get(f"/api/reference/historic-spot?metal=copper&date={IN_COVERAGE}")
    assert unknown.status_code == 422

    missing = client.get(
        f"/api/reference/historic-spot?metal=silver&date={IN_COVERAGE}&currency=XYZ"
    )
    assert missing.status_code == 422
    assert history["count"] == 1


def test_historic_spot_falls_back_to_the_second_host(client, monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append(url)
        raise stack.httpx.ConnectError("no route")

    monkeypatch.setattr(stack.httpx, "get", fake_get)
    resp = client.get(f"/api/reference/historic-spot?metal=silver&date={IN_COVERAGE}")
    assert resp.status_code == 502
    assert len(seen) == 2  # the CDN, then the fallback host
    assert "cdn.jsdelivr.net" in seen[0] and "currency-api.pages.dev" in seen[1]
    assert all(IN_COVERAGE in url and "xag" in url for url in seen)


# --- backfill ---------------------------------------------------------------


def test_backfill_fills_only_what_qualifies(client, spot, history):
    filled = _create(client, {**OUNCE, "acquisition_price": 25.0, "acquisition_date": IN_COVERAGE})
    typed = _create(
        client,
        {
            **OUNCE,
            "acquisition_price": 25.0,
            "acquisition_date": IN_COVERAGE,
            "spot_at_purchase": 18.0,
        },
    )
    too_old = _create(
        client, {**OUNCE, "acquisition_price": 25.0, "acquisition_date": "2020-05-01"}
    )
    no_cost = _create(client, {**OUNCE, "acquisition_date": IN_COVERAGE})

    assert client.get("/api/stack").json()["missing_spot"] == 1
    resp = client.post("/api/stack/backfill")
    assert resp.status_code == 200
    assert resp.json() == {"filled": 1, "failed": 0, "remaining": 0}
    assert history["count"] == 1

    assert client.get(f"/api/items/{filled['id']}").json()["spot_at_purchase"] == 20.0
    assert client.get(f"/api/items/{filled['id']}").json()["spot_at_purchase_source"] == "auto"
    assert client.get(f"/api/items/{typed['id']}").json()["spot_at_purchase"] == 18.0
    assert client.get(f"/api/items/{typed['id']}").json()["spot_at_purchase_source"] == "manual"
    for skipped in (too_old, no_cost):
        assert client.get(f"/api/items/{skipped['id']}").json()["spot_at_purchase"] is None
    assert client.get("/api/stack").json()["missing_spot"] == 0


def test_backfill_caps_each_run(client, spot, history, monkeypatch):
    monkeypatch.setattr(stack, "BACKFILL_LIMIT", 1)
    for _ in range(3):
        _create(client, {**OUNCE, "acquisition_price": 25.0, "acquisition_date": IN_COVERAGE})
    assert client.post("/api/stack/backfill").json() == {"filled": 1, "failed": 0, "remaining": 2}
    assert client.post("/api/stack/backfill").json() == {"filled": 1, "failed": 0, "remaining": 1}


def test_backfill_counts_a_failure(client, spot, monkeypatch):
    def broken(code, on):
        raise pricing.SourceUnavailable("both hosts failed")

    monkeypatch.setattr(stack, "_fetch_history", broken)
    _create(client, {**OUNCE, "acquisition_price": 25.0, "acquisition_date": IN_COVERAGE})
    assert client.post("/api/stack/backfill").json() == {"filled": 0, "failed": 1, "remaining": 1}


def test_hourly_tick_backfills(client, spot, history):
    from app.db import get_db
    from app.main import app

    _create(client, {**OUNCE, "acquisition_price": 25.0, "acquisition_date": IN_COVERAGE})
    db = next(app.dependency_overrides[get_db]())
    try:
        from app.services import scheduled

        scheduled.hourly(db)
    finally:
        db.close()
    assert client.get("/api/stack").json()["items"][0]["spot_at_purchase_source"] == "auto"


# --- the server-set source --------------------------------------------------


def test_spot_source_is_server_set(client):
    item = _create(client, {**OUNCE, "spot_at_purchase": 20.0})
    assert item["spot_at_purchase_source"] == "manual"
    # A client can't claim a source of its own.
    resp = client.patch(f"/api/items/{item['id']}", json={"spot_at_purchase_source": "auto"})
    assert resp.status_code == 200
    assert resp.json()["spot_at_purchase_source"] == "manual"

    cleared = client.patch(f"/api/items/{item['id']}", json={"spot_at_purchase": None}).json()
    assert cleared["spot_at_purchase"] is None
    assert cleared["spot_at_purchase_source"] is None

    typed = client.patch(f"/api/items/{item['id']}", json={"spot_at_purchase": 21.5}).json()
    assert typed["spot_at_purchase"] == 21.5
    assert typed["spot_at_purchase_source"] == "manual"

    clone = client.post(f"/api/items/{item['id']}/clone").json()
    assert clone["spot_at_purchase"] == 21.5
    assert clone["spot_at_purchase_source"] == "manual"

    # Not bulk-editable.
    resp = client.post(
        "/api/items/bulk", json={"ids": [item["id"]], "set": {"spot_at_purchase": 99.0}}
    )
    assert resp.status_code == 200
    assert client.get(f"/api/items/{item['id']}").json()["spot_at_purchase"] == 21.5


def test_export_and_import_round_trip(client):
    _create(client, {**OUNCE, "acquisition_price": 25.0, "spot_at_purchase": 20.0})
    csv_text = client.get("/api/items/export.csv").text
    assert "spot_at_purchase" in csv_text.splitlines()[0]

    # A different id, so the row imports rather than being skipped as known.
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    rows[1][rows[0].index("id")] = ""
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    reimport = out.getvalue().encode()
    resp = client.post("/api/items/import", files={"file": ("items.csv", reimport, "text/csv")})
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
    copies = [i for i in client.get("/api/items").json()["items"] if i["spot_at_purchase"] == 20.0]
    assert len(copies) == 2
    assert {c["spot_at_purchase_source"] for c in copies} == {"manual"}


def test_older_export_without_the_column_still_imports(client):
    csv_text = "type,country,denomination,year\ncoin,United States,1 dollar,1921\n"
    resp = client.post(
        "/api/items/import", files={"file": ("old.csv", csv_text.encode(), "text/csv")}
    )
    assert resp.json()["created"] == 1


# --- spot alerts ------------------------------------------------------------


@pytest.fixture()
def webhook(client, monkeypatch):
    """A saved webhook whose deliveries are recorded instead of sent."""
    sent = []
    monkeypatch.setattr(alerts, "_spawn", lambda fn: fn())
    monkeypatch.setattr(
        alerts,
        "deliver",
        lambda url, fmt, key, status, message, title=None: sent.append(
            {"key": key, "status": status, "message": message, "title": title}
        ),
    )
    resp = client.put("/api/settings", json={"alert_webhook_url": "https://hooks.example/cabinet"})
    assert resp.status_code == 200
    return sent


def _check(client):
    from app.db import get_db
    from app.main import app

    db = next(app.dependency_overrides[get_db]())
    try:
        return stack.check_spot_alerts(db)
    finally:
        db.close()


def test_spot_alert_fires_once_then_re_arms(client, spot, webhook, monkeypatch):
    # Spot is $31.10/oz; the threshold is $30.
    resp = client.put(
        "/api/settings",
        json={
            "spot_alerts": [
                {"metal": "silver", "direction": "above", "price": 30.0, "currency": "usd"}
            ]
        },
    )
    assert resp.status_code == 200
    saved = resp.json()["spot_alerts"]
    assert saved == [
        {
            "metal": "silver",
            "direction": "above",
            "price": 30.0,
            "currency": "USD",  # upper-cased on the way in
            "met": None,  # not checked yet
        }
    ]

    assert _check(client) == 1
    assert len(webhook) == 1
    assert webhook[0]["status"] == "event"
    assert webhook[0]["key"] == "spot_silver"
    assert webhook[0]["title"] == "Silver is above $30.00"
    assert webhook[0]["message"] == "Spot is $31.10 per ounce (threshold $30.00)."
    assert client.get("/api/settings").json()["spot_alerts"][0]["met"] is True

    # Still met: no second event.
    assert _check(client) == 0
    assert len(webhook) == 1

    # Spot falls below it: the threshold re-arms silently, then fires again.
    monkeypatch.setattr(pricing, "CACHE_TTL", timedelta(0))
    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("0.5"))
    assert _check(client) == 0
    assert len(webhook) == 1
    assert client.get("/api/settings").json()["spot_alerts"][0]["met"] is False

    monkeypatch.setattr(pricing, "fetch_spot_price", lambda metal: Decimal("1.0"))
    assert _check(client) == 1
    assert len(webhook) == 2


def test_spot_alert_below_and_other_currency(client, spot, webhook, monkeypatch):
    monkeypatch.setattr(currency, "fetch_rate", lambda base, quote: Decimal("2"))
    # $31.10/oz is 62.21 CAD; below 70 CAD fires, above 70 CAD does not.
    client.put(
        "/api/settings",
        json={
            "spot_alerts": [
                {"metal": "silver", "direction": "below", "price": 70.0, "currency": "CAD"},
                {"metal": "silver", "direction": "above", "price": 70.0, "currency": "CAD"},
            ]
        },
    )
    assert _check(client) == 1
    assert webhook[0]["title"] == "Silver is below CA$70.00"
    met = {a["direction"]: a["met"] for a in client.get("/api/settings").json()["spot_alerts"]}
    assert met == {"below": True, "above": False}


def test_removing_a_threshold_drops_its_state(client, spot, webhook):
    threshold = {"metal": "gold", "direction": "above", "price": 5.0, "currency": "USD"}
    client.put("/api/settings", json={"spot_alerts": [threshold]})
    assert _check(client) == 1

    client.put("/api/settings", json={"spot_alerts": []})
    assert client.get("/api/settings").json()["spot_alerts"] == []
    # Re-added, it alerts again rather than staying quiet.
    client.put("/api/settings", json={"spot_alerts": [threshold]})
    assert client.get("/api/settings").json()["spot_alerts"][0]["met"] is None
    assert _check(client) == 1
    assert len(webhook) == 2


def test_spot_alerts_without_a_webhook_do_not_crash(client, spot):
    client.put(
        "/api/settings",
        json={
            "spot_alerts": [
                {"metal": "silver", "direction": "above", "price": 1.0, "currency": "USD"}
            ]
        },
    )
    assert _check(client) == 1  # counted as fired; nowhere to deliver it
    assert client.get("/api/settings").json()["spot_alerts"][0]["met"] is True


def test_spot_alert_validation(client):
    def put(payload):
        return client.put("/api/settings", json={"spot_alerts": payload})

    assert (
        put([{"metal": "copper", "direction": "above", "price": 1, "currency": "USD"}]).status_code
        == 422
    )
    assert (
        put([{"metal": "gold", "direction": "sideways", "price": 1, "currency": "USD"}]).status_code
        == 422
    )
    assert (
        put([{"metal": "gold", "direction": "above", "price": 0, "currency": "USD"}]).status_code
        == 422
    )
    assert (
        put([{"metal": "gold", "direction": "above", "price": 1, "currency": "US"}]).status_code
        == 422
    )
    too_many = [
        {"metal": "gold", "direction": "above", "price": n + 1, "currency": "USD"}
        for n in range(13)
    ]
    assert put(too_many).status_code == 422
    # The service's own state is never accepted through PUT.
    resp = client.put("/api/settings", json={"spot_alert_state": {"x": True}})
    assert resp.status_code == 200
    assert "spot_alert_state" not in resp.json()


# --- dashboard and metrics --------------------------------------------------


def test_dashboard_stack_widget(client):
    resp = client.put(
        "/api/dashboard/layout",
        json={
            "widgets": [
                {
                    "id": "w-1",
                    "type": "stack",
                    "size": "half",
                    "title": None,
                    "options": {"metal": "silver"},
                }
            ]
        },
    )
    assert resp.status_code == 200
    widget = resp.json()["widgets"][0]
    assert widget["options"] == {"metal": "silver", "tag": None}
    # Not in the default layout.
    assert "stack" not in [
        w["type"] for w in client.delete("/api/dashboard/layout").json()["widgets"]
    ]

    bad = client.put(
        "/api/dashboard/layout",
        json={
            "widgets": [
                {
                    "id": "w-1",
                    "type": "stack",
                    "size": "half",
                    "title": None,
                    "options": {"metal": "copper"},
                }
            ]
        },
    )
    assert bad.status_code == 422


def test_metrics_gauge(client, spot):
    _create(client, {**OUNCE, "quantity": 2})
    client.put("/api/settings", json={"metrics_enabled": True})
    body = client.get("/api/metrics").text
    assert 'cabinet_stack_fine_ounces{metal="silver"} 1.998' in body
