"""Phase 5C: edit history, checklists."""

from tests.conftest import COIN


def _create(client, payload):
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_edit_history(client):
    item = _create(client, COIN)

    history = client.get(f"/api/items/{item['id']}/history").json()
    assert len(history) == 1
    assert history[0]["action"] == "created"

    client.patch(f"/api/items/{item['id']}", json={"quantity": 3, "notes": "moved"})
    client.patch(f"/api/items/{item['id']}", json={"quantity": 3})  # no-op: no event

    history = client.get(f"/api/items/{item['id']}/history").json()
    assert len(history) == 2
    assert history[0]["action"] == "updated"
    assert history[0]["changes"]["quantity"] == [1, 3]
    assert history[0]["changes"]["notes"] == [None, "moved"]

    clone = client.post(f"/api/items/{item['id']}/clone").json()
    clone_history = client.get(f"/api/items/{clone['id']}/history").json()
    assert clone_history[0]["changes"]["cloned_from"] == [None, item["id"]]

    client.post("/api/items/bulk", json={"ids": [item["id"]], "add_tags": ["bulked"]})
    history = client.get(f"/api/items/{item['id']}/history").json()
    assert history[0]["changes"]["bulk"] == [None, True]
    assert history[0]["changes"]["add_tags"] == [None, ["bulked"]]


def test_tag_change_recorded(client):
    item = _create(client, {**COIN, "tags": ["a"]})
    client.patch(f"/api/items/{item['id']}", json={"tags": ["b"]})
    history = client.get(f"/api/items/{item['id']}/history").json()
    assert history[0]["changes"]["tags"] == [["a"], ["b"]]


def test_checklists(client):
    resp = client.post(
        "/api/checklists",
        json={"name": "Mercury dimes", "slots": ["1916", "1916-D", "1916-S", ""]},
    )
    assert resp.status_code == 201
    checklist = resp.json()
    assert len(checklist["slots"]) == 3  # empty label dropped
    assert [s["position"] for s in checklist["slots"]] == [0, 1, 2]

    summaries = client.get("/api/checklists").json()
    assert summaries == [{"id": checklist["id"], "name": "Mercury dimes", "total": 3, "filled": 0}]

    slot = checklist["slots"][1]
    resp = client.patch(
        f"/api/checklists/{checklist['id']}/slots/{slot['id']}", json={"filled": True}
    )
    assert resp.json()["filled"] is True

    # link a slot to an item: fills it
    item = _create(client, COIN)
    resp = client.patch(
        f"/api/checklists/{checklist['id']}/slots/{checklist['slots'][0]['id']}",
        json={"item_id": item["id"]},
    )
    assert resp.json()["filled"] is True and resp.json()["item_id"] == item["id"]

    assert client.get("/api/checklists").json()[0]["filled"] == 2

    # unchecking clears the link
    resp = client.patch(
        f"/api/checklists/{checklist['id']}/slots/{checklist['slots'][0]['id']}",
        json={"filled": False},
    )
    assert resp.json()["item_id"] is None

    # deleting a linked item leaves the slot (SET NULL)
    client.patch(
        f"/api/checklists/{checklist['id']}/slots/{checklist['slots'][2]['id']}",
        json={"item_id": item["id"]},
    )
    client.delete(f"/api/items/{item['id']}")
    detail = client.get(f"/api/checklists/{checklist['id']}").json()
    assert detail["slots"][2]["item_id"] is None

    assert client.delete(f"/api/checklists/{checklist['id']}").status_code == 204
    assert client.get(f"/api/checklists/{checklist['id']}").status_code == 404


def test_checklist_validation(client):
    assert client.post("/api/checklists", json={"name": "x", "slots": []}).status_code == 422
    assert (
        client.post("/api/checklists", json={"name": "x", "slots": ["  ", ""]}).status_code == 422
    )
