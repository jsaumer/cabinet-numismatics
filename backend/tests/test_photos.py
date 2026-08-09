from pathlib import Path

from app.config import get_settings

PNG = ("file", ("obverse.png", b"\x89PNG fake image bytes", "image/png"))


def _upload(client, item_id, angle=None, name="p.png"):
    data = {"angle": angle} if angle else {}
    return client.post(
        f"/api/items/{item_id}/photos",
        files={"file": (name, b"\x89PNG fake image bytes", "image/png")},
        data=data,
    )


def test_upload_and_primary_designation(client, coin):
    first = _upload(client, coin["id"], angle="obverse")
    assert first.status_code == 201
    assert first.json()["is_primary"] is True  # first photo becomes primary
    assert first.json()["angle"] == "obverse"

    second = _upload(client, coin["id"], angle="reverse")
    assert second.status_code == 201
    assert second.json()["is_primary"] is False

    # file landed on disk under PHOTO_DIR
    assert (Path(get_settings().photo_dir) / first.json()["file_key"]).is_file()


def test_reassign_primary(client, coin):
    first = _upload(client, coin["id"]).json()
    second = _upload(client, coin["id"]).json()

    resp = client.patch(f"/api/photos/{second['id']}", json={"is_primary": True})
    assert resp.status_code == 200 and resp.json()["is_primary"] is True

    photos = client.get(f"/api/items/{coin['id']}/photos").json()
    flags = {p["id"]: p["is_primary"] for p in photos}
    assert flags[second["id"]] is True and flags[first["id"]] is False


def test_delete_primary_promotes_successor(client, coin):
    first = _upload(client, coin["id"]).json()
    second = _upload(client, coin["id"]).json()

    assert client.delete(f"/api/photos/{first['id']}").status_code == 204
    assert not (Path(get_settings().photo_dir) / first["file_key"]).is_file()

    photos = client.get(f"/api/items/{coin['id']}/photos").json()
    assert len(photos) == 1
    assert photos[0]["id"] == second["id"] and photos[0]["is_primary"] is True


def test_upload_rejects_non_image(client, coin):
    resp = client.post(
        f"/api/items/{coin['id']}/photos",
        files={"file": ("evil.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 415


def test_list_photos_missing_item_404(client):
    assert client.get("/api/items/00000000-0000-0000-0000-000000000000/photos").status_code == 404
