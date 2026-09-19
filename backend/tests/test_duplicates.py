"""The duplicate warning: GET /api/items/similar, and the importer's note."""

from tests.conftest import COIN
from tests.import_samples import hand_sheet


def similar(client, **params):
    resp = client.get("/api/items/similar", params=params)
    assert resp.status_code == 200
    return resp.json()


def test_matches_by_identity_cert_and_reference(client):
    kept = client.post(
        "/api/items",
        json={
            **COIN,
            "cert_service": "PCGS",
            "cert_number": "12345678",
            "catalog_refs": [{"catalog": "pcgs", "ref_code": "5960"}],
        },
    ).json()
    client.post("/api/items", json={**COIN, "year": 1933})  # a different coin

    # country + denomination + year + mint mark, case and spacing forgiven
    found = similar(
        client, country=" united  STATES ", denomination="25 Cents", year=1932, mint_mark="d"
    )
    assert [f["id"] for f in found] == [kept["id"]]
    assert found[0]["reason"] == "same country, denomination, year, and mint mark"
    assert found[0]["in_trash"] is False and found[0]["status"] == "owned"

    # the mint mark matters
    assert similar(client, country="United States", denomination="25 cents", year=1932) == []

    # a cert number from any service
    found = similar(client, cert_number="12345678")
    assert [f["reason"] for f in found] == ["same cert number"]

    # a catalogue reference
    found = similar(client, ref=["PCGS:5960"])
    assert [f["reason"] for f in found] == ["same pcgs reference"]

    # the item being edited is left out
    assert similar(client, cert_number="12345678", exclude=kept["id"]) == []
    # nothing to go on: nothing found, not everything
    assert similar(client) == []


def test_cert_wins_and_trashed_items_are_flagged(client):
    by_cert = client.post("/api/items", json={**COIN, "year": 1901, "cert_number": "777"}).json()
    by_identity = client.post("/api/items", json=COIN).json()
    client.delete(f"/api/items/{by_identity['id']}")
    found = similar(
        client,
        country="United States",
        denomination="25 cents",
        year=1932,
        mint_mark="D",
        cert_number="777",
    )
    assert [f["id"] for f in found] == [by_cert["id"], by_identity["id"]]
    assert found[1]["in_trash"] is True


def test_import_preview_notes_a_lookalike(client, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("IMPORT_DIR", str(tmp_path / "imports"))
    get_settings.cache_clear()
    # the hand sheet's first row is a 1909-S cent; this is its lookalike
    client.post(
        "/api/items",
        json={**COIN, "denomination": "1 cent", "year": 1909, "mint_mark": "S"},
    )
    path = hand_sheet(tmp_path / "sheet.csv")
    with open(path, "rb") as fh:
        up = client.post("/api/imports", files={"file": (path.name, fh)}).json()
    preview = client.post(f"/api/imports/{up['upload_id']}/preview", json={}).json()
    rows = preview["rows"]
    assert rows[0]["status"] == "new"
    assert any("Looks like one already here" in m for m in rows[0]["messages"]), rows[0]
    assert not any("Looks like" in m for m in rows[1]["messages"])
