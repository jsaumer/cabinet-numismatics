"""v0.23.0: "Add a run" and checklists that fill themselves."""

from tests.conftest import COIN
from tests.test_numista_catalogue import catalogue, configure  # noqa: F401  (fixture)

EAGLE_REF = {"catalog": "numista", "ref_code": "N#1493"}


def run(client, issues, **body):
    return client.post("/api/items/run", json={"type_id": 1493, "issues": issues, **body})


def test_add_a_run_creates_one_item_per_issue(client, catalogue):  # noqa: F811
    configure(client)
    resp = run(
        client,
        [{"year": 1986, "mintage": 5393005}, {"year": 2000, "mint_mark": "W"}],
        shared={
            "acquisition_price": 32.5,
            "acquired_from": "LCS",
            "storage_location": "Box 2",
            "tags": ["bullion"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["created"], body["skipped"]) == (2, 0)

    first = client.get(f"/api/items/{body['item_ids'][0]}").json()
    assert (first["country"], first["denomination"], first["year"]) == (
        "United States",
        "1 Dollar",
        1986,
    )
    assert first["mintage"] == 5393005 and first["weight_g"] == 31.103
    assert first["acquisition_price"] == 32.5 and first["storage_location"] == "Box 2"
    assert first["tags"] == ["bullion"]
    assert EAGLE_REF in first["catalog_refs"]
    second = client.get(f"/api/items/{body['item_ids'][1]}").json()
    assert second["mint_mark"] == "W" and second["mintage"] is None

    # a second pass skips what's owned, and repeats within one request
    again = run(client, [{"year": 1986}, {"year": 1987}, {"year": 1987}]).json()
    assert (again["created"], again["skipped"]) == (1, 2)
    # unless asked not to
    assert run(client, [{"year": 1986}], skip_owned=False).json()["created"] == 1


def test_run_needs_a_key_and_a_known_type(client, catalogue):  # noqa: F811
    assert run(client, [{"year": 1986}]).status_code == 422  # no Numista key
    configure(client)
    assert (
        client.post(
            "/api/items/run", json={"type_id": 99999, "issues": [{"year": 1986}]}
        ).status_code
        == 404
    )
    assert run(client, []).status_code == 422


def test_type_lookup_flags_owned_issues(client, catalogue):  # noqa: F811
    configure(client)
    run(client, [{"year": 2000, "mint_mark": "w"}])
    issues = client.get("/api/numista/types/1493").json()["issues"]
    assert [(i["year"], i["owned"]) for i in issues] == [(1986, False), (2000, True)]


def test_checklist_from_a_numista_type_fills_itself(client, catalogue):  # noqa: F811
    configure(client)
    resp = client.post("/api/checklists/generate", json={"source": "numista", "type_id": 1493})
    assert resp.status_code == 201, resp.text
    made = resp.json()
    assert made["name"] == '1 Dollar "American Silver Eagle"'
    assert (made["match_catalog"], made["match_ref"]) == ("numista", "N#1493")
    assert [(s["label"], s["year"], s["mint_mark"]) for s in made["slots"]] == [
        ("1986", 1986, None),
        ("2000-W", 2000, "W"),
    ]
    assert (made["total"], made["filled"]) == (2, 0)

    item_id = run(client, [{"year": 2000, "mint_mark": "W"}]).json()["item_ids"][0]
    got = client.get(f"/api/checklists/{made['id']}").json()
    assert got["filled"] == 1
    slot = got["slots"][1]
    assert slot["filled"] and slot["matched_item_id"] == item_id
    assert slot["matched_label"] == 'United States 1 Dollar 2000 "W"'
    summary = client.get("/api/checklists").json()[0]
    assert (summary["filled"], summary["generated"]) == (1, True)

    # a sold or trashed coin reopens the slot; a hand tick survives
    client.patch(f"/api/items/{item_id}", json={"status": "sold"})
    assert client.get(f"/api/checklists/{made['id']}").json()["filled"] == 0
    client.patch(f"/api/items/{item_id}", json={"status": "owned"})
    client.delete(f"/api/items/{item_id}")
    assert client.get(f"/api/checklists/{made['id']}").json()["filled"] == 0
    client.patch(
        f"/api/checklists/{made['id']}/slots/{got['slots'][0]['id']}", json={"filled": True}
    )
    assert client.get(f"/api/checklists/{made['id']}").json()["filled"] == 1


def test_checklist_from_a_range(client):
    resp = client.post(
        "/api/checklists/generate",
        json={
            "source": "range",
            "country": "United States",
            "denomination": "25 cents",
            "year_from": 1932,
            "year_to": 1934,
            "mint_marks": ["", "D", "S"],
            "skip": ["1933", "1933-d", "1933-S", "1934-S"],
        },
    )
    assert resp.status_code == 201, resp.text
    made = resp.json()
    assert made["name"] == "United States 25 cents 1932–1934"
    assert [s["label"] for s in made["slots"]] == ["1932", "1932-D", "1932-S", "1934", "1934-D"]

    client.post("/api/items", json=COIN)  # the 1932-D quarter, by country and denomination
    client.post("/api/items", json={**COIN, "denomination": "10 cents"})  # not a quarter
    got = client.get(f"/api/checklists/{made['id']}").json()
    assert [s["label"] for s in got["slots"] if s["filled"]] == ["1932-D"]

    for bad in (
        {"source": "range", "country": "X", "denomination": "Y", "year_from": 2, "year_to": 1},
        {"source": "range", "country": "X"},
        {"source": "numista"},
        {"source": "range", "country": "X", "denomination": "Y", "year_from": 1, "year_to": 600},
    ):
        assert client.post("/api/checklists/generate", json=bad).status_code == 422, bad
