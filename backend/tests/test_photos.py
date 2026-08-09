from pathlib import Path

from app.config import get_settings
from tests.conftest import image_bytes


def _upload(client, item_id, angle=None, name="p.png", data=None, mime="image/png"):
    form = {"angle": angle} if angle else {}
    return client.post(
        f"/api/items/{item_id}/photos",
        files={"file": (name, data if data is not None else image_bytes(), mime)},
        data=form,
    )


def test_upload_and_primary_designation(client, coin):
    first = _upload(client, coin["id"], angle="obverse")
    assert first.status_code == 201
    body = first.json()
    assert body["is_primary"] is True  # first photo becomes primary
    assert body["angle"] == "obverse"
    assert body["width"] == 60 and body["height"] == 40

    second = _upload(client, coin["id"], angle="reverse")
    assert second.status_code == 201
    assert second.json()["is_primary"] is False
    assert second.json()["position"] == 1

    # original and generated thumbnail both landed on disk
    root = Path(get_settings().photo_dir)
    assert (root / body["file_key"]).is_file()
    assert body["thumb_key"] and (root / body["thumb_key"]).is_file()


def test_upload_rejects_fake_and_unsupported_images(client, coin):
    # fake bytes with an image content-type: rejected by real validation
    resp = _upload(client, coin["id"], data=b"\x89PNG not really an image")
    assert resp.status_code == 415

    resp = _upload(client, coin["id"], name="a.gif", data=image_bytes("GIF"), mime="image/gif")
    assert resp.status_code == 415  # GIF is not a supported format

    # declared content-type is ignored; real format wins
    resp = _upload(client, coin["id"], name="j.txt", data=image_bytes("JPEG"), mime="text/plain")
    assert resp.status_code == 201
    assert resp.json()["file_key"].endswith(".jpg")


def test_reassign_primary(client, coin):
    first = _upload(client, coin["id"]).json()
    second = _upload(client, coin["id"]).json()

    resp = client.patch(f"/api/photos/{second['id']}", json={"is_primary": True})
    assert resp.status_code == 200 and resp.json()["is_primary"] is True

    photos = client.get(f"/api/items/{coin['id']}/photos").json()
    flags = {p["id"]: p["is_primary"] for p in photos}
    assert flags[second["id"]] is True and flags[first["id"]] is False


def test_reorder_photos(client, coin):
    a = _upload(client, coin["id"]).json()
    b = _upload(client, coin["id"]).json()
    c = _upload(client, coin["id"]).json()

    resp = client.post(
        f"/api/items/{coin['id']}/photos/order",
        json={"order": [c["id"], a["id"], b["id"]]},
    )
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()] == [c["id"], a["id"], b["id"]]
    assert [p["position"] for p in resp.json()] == [0, 1, 2]

    # incomplete order is rejected
    resp = client.post(f"/api/items/{coin['id']}/photos/order", json={"order": [a["id"]]})
    assert resp.status_code == 422


def test_delete_primary_promotes_successor(client, coin):
    first = _upload(client, coin["id"]).json()
    second = _upload(client, coin["id"]).json()

    assert client.delete(f"/api/photos/{first['id']}").status_code == 204
    root = Path(get_settings().photo_dir)
    assert not (root / first["file_key"]).is_file()
    assert not (root / first["thumb_key"]).is_file()

    photos = client.get(f"/api/items/{coin['id']}/photos").json()
    assert len(photos) == 1
    assert photos[0]["id"] == second["id"] and photos[0]["is_primary"] is True
    assert photos[0]["position"] == 0


def test_list_photos_missing_item_404(client):
    assert client.get("/api/items/00000000-0000-0000-0000-000000000000/photos").status_code == 404
