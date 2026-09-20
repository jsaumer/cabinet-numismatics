"""v0.20.0: the trash: delete moves an item there, restore brings it back."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Item
from app.services import documents as document_store
from app.services import trash
from tests.conftest import COIN, image_bytes
from tests.test_documents import pdf_bytes


def _session():
    return next(app.dependency_overrides[get_db]())


def _item(client, **overrides):
    resp = client.post("/api/items", json={**COIN, **overrides})
    assert resp.status_code == 201
    return resp.json()


def _age(item_id, days):
    """Backdate an item's time in the trash."""
    db = _session()
    item = db.execute(
        select(Item).where(Item.id == uuid.UUID(item_id)).execution_options(include_deleted=True)
    ).scalar_one()
    item.deleted_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()
    db.close()


def test_a_trashed_item_keeps_everything_and_comes_back(client):
    item = _item(client, tags=["Silver"], set_id=None)
    client.post(
        f"/api/items/{item['id']}/photos", files={"file": ("o.png", image_bytes(), "image/png")}
    )
    client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": 100})
    client.post(
        f"/api/items/{item['id']}/comparables",
        json={"sold_on": "2026-01-01", "venue": "eBay", "price": 90},
    )
    client.post(f"/api/items/{item['id']}/documents", files={"file": ("r.pdf", pdf_bytes())})

    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    detail = client.get(f"/api/items/{item['id']}").json()
    assert detail["deleted_at"] is not None
    assert (len(detail["photos"]), len(detail["estimates"])) == (1, 1)
    assert (len(detail["comparables"]), len(detail["documents"])) == (1, 1)

    resp = client.post(f"/api/items/{item['id']}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None
    assert client.get("/api/items").json()["total"] == 1
    actions = [e["action"] for e in client.get(f"/api/items/{item['id']}/history").json()]
    assert actions[:2] == ["restored", "trashed"]


def test_trashed_items_are_hidden_everywhere(client):
    kept = _item(client, tags=["Silver"], acquisition_price=10.0)
    gone = _item(client, tags=["Silver"], acquisition_price=1000.0, year=1950)
    set_id = client.post("/api/sets", json={"name": "Lot A"}).json()["id"]
    for i in (kept, gone):
        client.patch(f"/api/items/{i['id']}", json={"set_id": set_id})
    client.delete(f"/api/items/{gone['id']}")

    assert [i["id"] for i in client.get("/api/items").json()["items"]] == [kept["id"]]
    stats = client.get("/api/stats/collection").json()
    assert (stats["counts"]["owned"], stats["cost_basis"]) == (1, 10.0)
    tags = {t["name"]: t["count"] for t in client.get("/api/tags").json()}
    assert tags["Silver"] == 1
    sets = {s["name"]: s["item_count"] for s in client.get("/api/sets").json()}
    assert sets["Lot A"] == 1
    assert gone["id"] not in client.get("/api/items/export.csv").text
    coverage = client.get("/api/pricing/coverage").json()
    assert coverage["owned_items"] == 1


def test_a_trashed_item_is_read_only(client):
    item = _item(client)
    client.delete(f"/api/items/{item['id']}")
    assert client.patch(f"/api/items/{item['id']}", json={"notes": "x"}).status_code == 404
    assert client.post(f"/api/items/{item['id']}/clone").status_code == 404
    assert (
        client.post(f"/api/items/{item['id']}/estimates", json={"estimated_value": 1}).status_code
        == 404
    )
    upload = client.post(
        f"/api/items/{item['id']}/photos", files={"file": ("o.png", image_bytes(), "image/png")}
    )
    assert upload.status_code == 404


def test_trash_list_and_bulk_actions(client):
    a, b, c = _item(client), _item(client, year=1940), _item(client, year=1950)
    resp = client.post("/api/trash/items", json={"ids": [a["id"], b["id"], c["id"]]})
    assert resp.json() == {"count": 3}
    assert client.post("/api/trash/items", json={"ids": [a["id"]]}).json() == {"count": 0}

    body = client.get("/api/trash").json()
    assert body["retention_days"] == 30
    assert {e["id"] for e in body["items"]} == {a["id"], b["id"], c["id"]}
    entry = body["items"][0]
    assert entry["label"].startswith("United States 25 cents")
    assert entry["purge_at"] is not None

    assert client.post("/api/trash/restore", json={"ids": [a["id"]]}).json() == {"count": 1}
    assert client.post("/api/trash/purge", json={"ids": [b["id"], a["id"]]}).json() == {"count": 1}
    assert client.get(f"/api/items/{a['id']}").status_code == 200  # restored, not purged
    assert client.get(f"/api/items/{b['id']}").status_code == 404
    assert client.delete("/api/trash").json() == {"count": 1}
    assert client.get("/api/trash").json()["items"] == []


def test_the_trash_empties_itself_after_the_retention(client):
    old, recent = _item(client), _item(client, year=1960)
    client.post("/api/trash/items", json={"ids": [old["id"], recent["id"]]})
    _age(old["id"], 31)
    _age(recent["id"], 5)

    db = _session()
    assert trash.purge_expired(db) == 1
    db.close()
    assert client.get(f"/api/items/{old['id']}").status_code == 404
    assert client.get(f"/api/items/{recent['id']}").status_code == 200

    # off: nothing is emptied automatically
    assert client.put("/api/settings", json={"trash_retention_days": 0}).status_code == 200
    assert client.get("/api/settings").json()["trash_retention_days"] == 0
    _age(recent["id"], 400)
    db = _session()
    assert trash.purge_expired(db) == 0
    db.close()
    assert client.get("/api/trash").json()["items"][0]["purge_at"] is None
    assert client.put("/api/settings", json={"trash_retention_days": 12}).status_code == 422


def test_a_document_on_a_trashed_item_is_kept(client):
    first, second = _item(client), _item(client, year=1933)
    doc = client.post(
        f"/api/items/{first['id']}/documents", files={"file": ("lot.pdf", pdf_bytes())}
    ).json()
    client.post(f"/api/documents/{doc['id']}/items", json={"item_ids": [second["id"]]})
    client.delete(f"/api/items/{second['id']}")  # to the trash, still holding the invoice

    # the only item still showing it lets it go, but the trashed one holds it
    assert client.delete(f"/api/items/{first['id']}/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200
    client.post(f"/api/items/{second['id']}/restore")
    documents = client.get(f"/api/items/{second['id']}").json()["documents"]
    assert [d["id"] for d in documents] == [doc["id"]]

    # deleting that item for good takes the file with it
    client.delete(f"/api/items/{second['id']}?permanent=true")
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 404
    assert not (document_store.root() / doc["id"]).exists()


def test_reimporting_skips_trashed_items(client, tmp_path):
    item = _item(client, notes="to be trashed")
    export = tmp_path / "cabinet-items.csv"
    export.write_bytes(client.get("/api/items/export.csv").content)
    client.delete(f"/api/items/{item['id']}")

    with export.open("rb") as fh:
        upload = client.post("/api/imports", files={"file": (export.name, fh)}).json()
    body = client.post(f"/api/imports/{upload['upload_id']}/preview", json={}).json()
    assert (body["new"], body["duplicates"]) == (0, 1)
    assert "in the trash" in body["rows"][0]["messages"][0]


def test_backups_count_the_trash(client, monkeypatch):
    from app.services import backup

    _item(client)
    trashed = _item(client, year=1960)
    client.delete(f"/api/items/{trashed['id']}")
    db = _session()
    counts = backup._counts(db)
    db.close()
    assert (counts["items"], counts["in_trash"]) == (2, 1)
