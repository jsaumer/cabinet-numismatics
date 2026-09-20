"""Roadmap Phase 7, P10: the customisable dashboard layout, and the
`tag`/`set_id` scoping it needs from `GET /api/stats/breakdowns`."""

from app.db import get_db
from app.main import app
from app.services import app_settings as store
from app.services import dashboard
from tests.conftest import COIN


def _session():
    return next(app.dependency_overrides[get_db]())


def _store(widgets, version=1):
    db = _session()
    store.set_setting(db, "dashboard_layout", {"version": version, "widgets": widgets})
    db.commit()
    db.close()


def test_default_layout_when_nothing_saved(client):
    body = client.get("/api/dashboard/layout").json()
    assert body["is_default"] is True
    assert body["version"] == 1
    assert len(body["widgets"]) == 11
    assert [w["type"] for w in body["widgets"]][:3] == [
        "setup",
        "value_summary",
        "value_history",
    ]
    breakdowns = [w for w in body["widgets"] if w["type"] == "breakdown"]
    assert len(breakdowns) == 5
    assert breakdowns[0]["options"]["dimension"] == "country"
    assert breakdowns[0]["size"] == "third"
    value_history = next(w for w in body["widgets"] if w["type"] == "value_history")
    assert value_history["options"] == {"months": 24}  # every option defaulted


def test_round_trip(client):
    widgets = [
        {
            "id": "w-1",
            "type": "recent_additions",
            "size": "half",
            "title": "Freshly added",
            "options": {"count": 10},
        },
        {"id": "w-2", "type": "trash", "size": "third", "title": None, "options": {}},
    ]
    resp = client.put("/api/dashboard/layout", json={"widgets": widgets})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is False
    assert body["widgets"][0]["title"] == "Freshly added"
    assert body["widgets"][0]["options"] == {"count": 10}
    assert body["widgets"][1]["options"] == {"count": 5}  # default filled in

    again = client.get("/api/dashboard/layout").json()
    assert again["is_default"] is False
    assert again == body


def _put(client, widgets):
    return client.put("/api/dashboard/layout", json={"widgets": widgets})


def test_validation_errors(client):
    base = {"id": "w-1", "type": "trash", "size": "third", "title": None, "options": {}}

    assert _put(client, [{**base, "type": "bogus"}]).status_code == 422
    assert _put(client, [{**base, "size": "quarter"}]).status_code == 422
    assert _put(client, [{**base, "id": "Not Valid!"}]).status_code == 422
    assert _put(client, [{**base, "id": ""}]).status_code == 422
    assert _put(client, [base, base]).status_code == 422  # duplicate id
    assert _put(client, [{**base, "title": "x" * 81}]).status_code == 422
    assert (
        _put(
            client,
            [{**base, "type": "recent_additions", "options": {"count": 2}}],
        ).status_code
        == 422
    )  # out of range
    assert (
        _put(
            client,
            [{**base, "type": "wishlist", "options": {"mode": "urgent"}}],
        ).status_code
        == 422
    )  # bad choice
    assert (
        _put(
            client,
            [{**base, "type": "breakdown", "options": {"set_id": "nope"}}],
        ).status_code
        == 422
    )  # wrong type for an option

    too_many = [{**base, "id": f"w-{i}"} for i in range(41)]
    assert _put(client, too_many).status_code == 422


def test_unknown_stored_type_dropped_on_read(client):
    _store(
        [
            {"id": "w-1", "type": "trash", "size": "third", "title": None, "options": {}},
            {
                "id": "w-2",
                "type": "no_longer_exists",
                "size": "full",
                "title": None,
                "options": {},
            },
        ]
    )
    body = client.get("/api/dashboard/layout").json()
    assert body["is_default"] is False
    assert [w["id"] for w in body["widgets"]] == ["w-1"]


def test_stored_bad_option_replaced_by_default(client):
    _store(
        [
            {
                "id": "w-1",
                "type": "breakdown",
                "size": "third",
                "title": None,
                "options": {"dimension": "not-a-dimension", "top_n": 999},
            }
        ]
    )
    opts = client.get("/api/dashboard/layout").json()["widgets"][0]["options"]
    assert opts["dimension"] == "country"
    assert opts["top_n"] == 8


def test_migration_hook_runs_and_bumps_version(client, monkeypatch):
    """No migration exists yet; the hook still runs whatever is registered
    and stamps the current version onto a layout claiming an older one."""
    seen = {}

    def fake_migration(layout: dict) -> dict:
        seen["ran"] = True
        layout = dict(layout)
        layout["widgets"] = []
        return layout

    monkeypatch.setitem(dashboard.MIGRATIONS, 0, fake_migration)
    _store([{"id": "w-1", "type": "trash", "size": "third", "options": {}}], version=0)

    body = client.get("/api/dashboard/layout").json()
    assert seen.get("ran") is True
    assert body["version"] == 1
    assert body["widgets"] == []


def test_delete_resets_to_default(client):
    client.put(
        "/api/dashboard/layout",
        json={"widgets": [{"id": "w-1", "type": "trash", "size": "third", "options": {}}]},
    )
    assert client.get("/api/dashboard/layout").json()["is_default"] is False

    resp = client.delete("/api/dashboard/layout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is True
    assert len(body["widgets"]) == 11

    assert client.get("/api/dashboard/layout").json()["is_default"] is True


def test_dashboard_layout_not_accepted_by_settings(client):
    resp = client.put("/api/dashboard/layout", json={"widgets": []})
    assert resp.status_code == 200

    resp = client.put("/api/settings", json={"dashboard_layout": {"version": 1, "widgets": []}})
    assert resp.status_code == 200
    assert "dashboard_layout" not in resp.json()

    # unaffected by the PUT /api/settings call above
    assert client.get("/api/dashboard/layout").json()["widgets"] == []


def test_breakdowns_tag_and_set_scoping(client):
    set_id = client.post("/api/sets", json={"name": "Set A"}).json()["id"]
    client.post(
        "/api/items",
        json={**COIN, "acquisition_price": 100.0, "tags": ["silver"], "set_id": set_id},
    )
    client.post("/api/items", json={**COIN, "acquisition_price": 50.0, "tags": ["copper"]})

    all_breakdowns = client.get("/api/stats/breakdowns").json()
    assert sum(e["count"] for e in all_breakdowns["by_country"]) == 2

    by_tag = client.get("/api/stats/breakdowns", params={"tag": "silver"}).json()
    assert sum(e["count"] for e in by_tag["by_country"]) == 1

    by_set = client.get("/api/stats/breakdowns", params={"set_id": set_id}).json()
    assert sum(e["count"] for e in by_set["by_country"]) == 1

    # unknown tag/set: empty breakdowns, not an error
    unknown_tag = client.get("/api/stats/breakdowns", params={"tag": "no-such-tag"})
    assert unknown_tag.status_code == 200
    assert unknown_tag.json()["by_country"] == []

    unknown_set = client.get("/api/stats/breakdowns", params={"set_id": 999999})
    assert unknown_set.status_code == 200
    assert unknown_set.json()["by_country"] == []


def test_breakdowns_scoping_hides_trashed_items(client):
    resp = client.post("/api/items", json={**COIN, "tags": ["silver"]})
    item_id = resp.json()["id"]
    client.delete(f"/api/items/{item_id}")

    body = client.get("/api/stats/breakdowns", params={"tag": "silver"}).json()
    assert body["by_country"] == []
