"""The demo collection: loaded into an empty collection in one step, marked
so it can be removed without touching anything else."""

import pytest
from PIL import Image

from app.services import demo, maintenance, photos
from app.services.demo_data import DEMO_ITEMS
from tests.conftest import COIN


def _png() -> bytes:
    import io

    out = io.BytesIO()
    Image.new("RGB", (40, 30), "gray").save(out, "PNG")
    return out.getvalue()


@pytest.fixture()
def inline(monkeypatch):
    """Run the photo thread inline, with Commons answering from memory.
    Returns the list of URLs fetched."""
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _png()

    monkeypatch.setattr(photos, "fetch_remote_image", fetch)
    monkeypatch.setattr(demo, "_spawn", lambda fn: fn())
    return fetched


PHOTO_COUNT = sum(len(fields.get("photos", [])) for fields, _ in DEMO_ITEMS)
VALUE_COUNT = sum(len(values) for _, values in DEMO_ITEMS)


def test_nothing_is_loaded_at_first(client):
    assert client.get("/api/demo").json() == {
        "items": 0,
        "photos": {"state": "idle", "total": 0, "fetched": 0, "failed": 0},
    }


def test_loading_creates_every_piece_with_its_values(client):
    resp = client.post("/api/demo?photos=false")
    assert resp.status_code == 201, resp.text
    assert resp.json()["items"] == len(DEMO_ITEMS) == 17
    assert resp.json()["photos"]["state"] == "idle"

    listing = client.get("/api/items?limit=100").json()
    assert listing["total"] == 17
    types = {entry["type"] for entry in listing["items"]}
    assert types == {"coin", "note", "bullion", "mint_set"}
    values = 0
    for entry in listing["items"]:
        values += client.get(f"/api/items/{entry['id']}/estimates").json()["total"]
    assert values == VALUE_COUNT


def test_a_graded_piece_keeps_its_grade_and_a_note_its_serial_traits(client):
    client.post("/api/demo?photos=false")
    items = client.get("/api/items?limit=100").json()["items"]
    morgan = next(i for i in items if i["series"] == "Morgan Dollar")
    assert client.get(f"/api/items/{morgan['id']}").json()["grade_label"] == "MS-63"
    two = client.get("/api/items?serial_trait=repeater").json()
    assert two["total"] == 1


def test_values_are_spread_over_time_so_the_chart_has_a_line(client):
    client.post("/api/demo?photos=false")
    history = client.get("/api/stats/value-history").json()
    assert len(history["points"]) >= 3


def test_a_demo_value_never_sits_in_the_future_or_out_of_order(client):
    client.post("/api/demo?photos=false")
    items = client.get("/api/items?limit=100").json()["items"]
    sovereign = next(i for i in items if i["denomination"] == "1 sovereign")
    page = client.get(f"/api/items/{sovereign['id']}/estimates").json()
    newest, older = page["items"]  # newest first
    assert float(newest["estimated_value"]) == 612.0
    assert float(older["estimated_value"]) == 505.0
    assert older["fetched_at"] < newest["fetched_at"]


def test_it_is_refused_once_the_collection_holds_anything(client):
    assert client.post("/api/items", json=COIN).status_code == 201
    resp = client.post("/api/demo")
    assert resp.status_code == 409
    assert "empty collection" in resp.json()["detail"]
    assert client.get("/api/demo").json()["items"] == 0


def test_loading_twice_is_refused(client):
    assert client.post("/api/demo?photos=false").status_code == 201
    assert client.post("/api/demo?photos=false").status_code == 409
    assert client.get("/api/items").json()["total"] == 17


def test_it_is_refused_while_demo_pieces_sit_in_the_trash(client):
    client.post("/api/demo?photos=false")
    ids = [i["id"] for i in client.get("/api/items?limit=100").json()["items"]]
    assert client.post("/api/trash/items", json={"ids": ids}).json() == {"count": 17}
    assert client.get("/api/items").json()["total"] == 0
    resp = client.post("/api/demo?photos=false")
    assert resp.status_code == 409
    assert "trash" in resp.json()["detail"]
    assert client.get("/api/demo").json()["items"] == 17


def test_removing_takes_the_demo_and_nothing_else(client, inline):
    client.post("/api/demo")
    mine = client.post("/api/items", json=COIN).json()["id"]
    # One demo piece is in the trash; it goes too.
    demo_id = next(
        i["id"] for i in client.get("/api/items?limit=100").json()["items"] if i["id"] != mine
    )
    assert client.delete(f"/api/items/{demo_id}").status_code == 204

    resp = client.delete("/api/demo")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"removed": 17}
    left = client.get("/api/items?limit=100").json()
    assert [i["id"] for i in left["items"]] == [mine]
    assert client.get("/api/trash").json()["items"] == []
    assert client.get("/api/demo").json()["items"] == 0
    # And it can be loaded again afterwards only once the collection is empty.
    assert client.post("/api/demo?photos=false").status_code == 409


def test_removing_deletes_the_photo_files(client, inline):
    client.post("/api/demo")
    root = photos._root()
    assert any(root.rglob("*.png")) or any(root.rglob("*.jpg"))
    client.delete("/api/demo")
    assert not [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]


def test_photos_are_fetched_one_by_one_from_commons(client, inline):
    resp = client.post("/api/demo")
    assert resp.status_code == 201
    assert len(inline) == PHOTO_COUNT == 22
    assert all(url.startswith("https://upload.wikimedia.org/") for url in inline)
    assert client.get("/api/demo").json()["photos"] == {
        "state": "done",
        "total": 22,
        "fetched": 22,
        "failed": 0,
    }
    items = client.get("/api/items?limit=100").json()["items"]
    morgan = next(i for i in items if i["series"] == "Morgan Dollar")
    detail = client.get(f"/api/items/{morgan['id']}").json()
    assert [p["angle"] for p in detail["photos"]] == ["obverse", "reverse"]
    assert detail["photos"][0]["is_primary"] is True


def test_a_photo_that_cannot_be_fetched_is_counted_not_fatal(client, monkeypatch):
    calls = {"n": 0}

    def fetch(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] % 2:
            raise ValueError("The server answered HTTP 404")
        return _png()

    monkeypatch.setattr(photos, "fetch_remote_image", fetch)
    monkeypatch.setattr(demo, "_spawn", lambda fn: fn())
    assert client.post("/api/demo").status_code == 201
    progress = client.get("/api/demo").json()["photos"]
    assert progress == {"state": "done", "total": 22, "fetched": 11, "failed": 11}
    assert client.get("/api/items").json()["total"] == 17


def test_a_busy_commons_is_tried_again(client, monkeypatch):
    seen: dict[str, int] = {}

    def fetch(url: str) -> bytes:
        seen[url] = seen.get(url, 0) + 1
        if seen[url] == 1:
            raise ValueError("The server answered HTTP 429")
        return _png()

    monkeypatch.setattr(photos, "fetch_remote_image", fetch)
    monkeypatch.setattr(demo, "_spawn", lambda fn: fn())
    client.post("/api/demo")
    assert client.get("/api/demo").json()["photos"]["fetched"] == 22
    assert set(seen.values()) == {2}


def test_the_photo_fetch_stops_when_a_restore_begins(client, monkeypatch):
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        if len(fetched) == 3:
            maintenance.enter()
        return _png()

    monkeypatch.setattr(photos, "fetch_remote_image", fetch)
    monkeypatch.setattr(demo, "_spawn", lambda fn: fn())
    try:
        client.post("/api/demo")
    finally:
        maintenance.leave()
    assert len(fetched) == 3
    assert client.get("/api/demo").json()["photos"]["fetched"] == 2


def test_the_photo_fetch_stops_when_the_demo_is_removed(client, monkeypatch):
    held: list = []
    monkeypatch.setattr(photos, "fetch_remote_image", lambda url: _png())
    monkeypatch.setattr(demo, "_spawn", held.append)
    client.post("/api/demo")
    assert client.delete("/api/demo").json() == {"removed": 17}
    held[0]()  # the thread wakes up after the removal
    assert client.get("/api/demo").json() == {
        "items": 0,
        "photos": {"state": "idle", "total": 0, "fetched": 0, "failed": 0},
    }
    root = photos._root()
    assert not [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]


def test_nothing_on_the_request_reaches_the_network(client, monkeypatch):
    def refuse(url: str) -> bytes:
        raise AssertionError("the request fetched a photo itself")

    monkeypatch.setattr(photos, "fetch_remote_image", refuse)
    # conftest leaves the thread unstarted: only the request's own work runs.
    resp = client.post("/api/demo")
    assert resp.status_code == 201
    assert resp.json()["photos"] == {"state": "running", "total": 22, "fetched": 0, "failed": 0}


def test_who_may_load_and_who_may_remove(client, anon_client, stale_client, token_client):
    assert anon_client.post("/api/demo").status_code == 401
    assert token_client("read").post("/api/demo").status_code == 403
    assert token_client("read").get("/api/demo").status_code == 200
    assert token_client("write").post("/api/demo?photos=false").status_code == 201
    # Deleting for good is the admin's, with a recent password.
    assert token_client("write").delete("/api/demo").status_code == 403
    refused = stale_client.delete("/api/demo")
    assert refused.status_code == 403 and refused.json().get("reauth_required") is True
    assert client.delete("/api/demo").json() == {"removed": 17}


def test_every_demo_photo_is_public_domain_or_cc0_with_its_credit():
    for fields, _ in DEMO_ITEMS:
        for photo in fields.get("photos", []):
            assert photo["license"] in ("Public domain", "CC0"), photo
            assert photo["credit"] and photo["page"].startswith("https://commons.wikimedia.org/")


def test_a_restore_forgets_the_photo_progress(client):
    client.post("/api/demo")
    assert client.get("/api/demo").json()["photos"]["state"] == "running"
    demo.reset_memory()
    assert client.get("/api/demo").json()["photos"]["state"] == "idle"
