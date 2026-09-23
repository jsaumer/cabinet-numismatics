import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import photos as photo_store
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


def test_import_photo_from_url(client, coin, monkeypatch):
    requested = []

    def fetch(url):
        requested.append(url)
        return image_bytes("JPEG")

    monkeypatch.setattr(photo_store, "fetch_remote_image", fetch)
    url = f"/api/items/{coin['id']}/photos/url"
    resp = client.post(url, json={"url": "https://example.com/coin.jpg", "angle": "obverse"})
    assert resp.status_code == 201
    body = resp.json()
    assert (body["angle"], body["is_primary"]) == ("obverse", True)
    assert body["file_key"].endswith(".jpg")
    assert requested == ["https://example.com/coin.jpg"]

    def refused(url):
        raise ValueError("Importing from private or local network addresses isn't allowed")

    monkeypatch.setattr(photo_store, "fetch_remote_image", refused)
    resp = client.post(url, json={"url": "http://192.168.1.5/p.jpg"})
    assert resp.status_code == 422 and "private" in resp.json()["detail"]

    def down(url):
        raise photo_store.RemoteImageUnavailable("Couldn't fetch the image: timed out")

    monkeypatch.setattr(photo_store, "fetch_remote_image", down)
    assert client.post(url, json={"url": "https://example.com/slow.jpg"}).status_code == 502

    monkeypatch.setattr(photo_store, "fetch_remote_image", lambda url: b"<html>not an image")
    assert client.post(url, json={"url": "https://example.com/page"}).status_code == 415


class FakeResponse:
    """Just enough of an httpx streaming response for fetch_remote_image."""

    def __init__(self, status=200, body=b"", location=None):
        self.status_code = status
        self.body = body
        self.headers = {"location": location} if location else {}

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    def iter_bytes(self):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _resolve(monkeypatch, addresses):
    """Make hostnames resolve to the given addresses ({host: ip})."""
    monkeypatch.setattr(
        photo_store.socket,
        "getaddrinfo",
        lambda host, port, **kw: [(2, 1, 6, "", (addresses[host], port))],
    )


def _serve(monkeypatch, responses):
    requested = []

    def stream(method, url, **kwargs):
        requested.append(url)
        return responses[url]

    monkeypatch.setattr(photo_store.httpx, "stream", stream)
    return requested


def test_fetch_remote_image_follows_public_redirects(monkeypatch):
    _resolve(monkeypatch, {"a.example": "93.184.216.34"})
    requested = _serve(
        monkeypatch,
        {
            "https://a.example/x": FakeResponse(302, location="/y.png"),
            "https://a.example/y.png": FakeResponse(200, b"image bytes"),
        },
    )
    assert photo_store.fetch_remote_image("https://a.example/x") == b"image bytes"
    assert requested == ["https://a.example/x", "https://a.example/y.png"]


def test_fetch_remote_image_refuses_the_local_network(monkeypatch):
    for address in ("127.0.0.1", "10.0.0.5", "192.168.1.20", "169.254.169.254", "::1"):
        _resolve(monkeypatch, {"nas.lan": address})
        with pytest.raises(ValueError, match="private"):
            photo_store.fetch_remote_image("http://nas.lan/p.jpg")

    for url in ("file:///etc/passwd", "ftp://a.example/p.jpg", "https:///p.jpg"):
        with pytest.raises(ValueError, match="http"):
            photo_store.fetch_remote_image(url)

    # a public URL that redirects into the LAN is refused at that hop
    _resolve(monkeypatch, {"a.example": "93.184.216.34", "internal": "10.0.0.1"})
    _serve(monkeypatch, {"https://a.example/x": FakeResponse(302, location="http://internal/s")})
    with pytest.raises(ValueError, match="private"):
        photo_store.fetch_remote_image("https://a.example/x")


def test_fetch_remote_image_limits(monkeypatch):
    _resolve(monkeypatch, {"a.example": "93.184.216.34"})
    monkeypatch.setattr(photo_store, "REMOTE_MAX_BYTES", 10)
    _serve(
        monkeypatch,
        {
            "https://a.example/big": FakeResponse(200, b"x" * 11),
            "https://a.example/gone": FakeResponse(404),
            "https://a.example/loop": FakeResponse(302, location="/loop"),
        },
    )
    with pytest.raises(ValueError, match="larger than 25 MB"):
        photo_store.fetch_remote_image("https://a.example/big")
    with pytest.raises(ValueError, match="HTTP 404"):
        photo_store.fetch_remote_image("https://a.example/gone")
    with pytest.raises(ValueError, match="Too many redirects"):
        photo_store.fetch_remote_image("https://a.example/loop")


def test_replace_photo_image_keeps_its_place(client, coin):
    _upload(client, coin["id"], angle="obverse")
    second = _upload(client, coin["id"], angle="reverse").json()
    root = Path(get_settings().photo_dir)

    edited = {"file": ("edited.jpg", image_bytes("JPEG", size=(30, 20)), "image/jpeg")}
    resp = client.put(f"/api/photos/{second['id']}/image", files=edited)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["angle"], body["position"], body["is_primary"]) == ("reverse", 1, False)
    assert (body["width"], body["height"]) == (30, 20)
    assert body["file_key"] != second["file_key"] and body["file_key"].endswith(".jpg")
    assert (root / body["file_key"]).is_file() and (root / body["thumb_key"]).is_file()
    assert not (root / second["file_key"]).exists()
    assert not (root / second["thumb_key"]).exists()

    fake = {"file": ("x.png", b"not an image", "image/png")}
    assert client.put(f"/api/photos/{second['id']}/image", files=fake).status_code == 415
    assert (root / body["file_key"]).is_file()  # a failed replace leaves the image alone
    assert client.put(f"/api/photos/{uuid.uuid4()}/image", files=edited).status_code == 404


# --- deleting for good needs the admin and a recent password (stage 12) --------------------


def _photo(client, coin):
    resp = client.post(
        f"/api/items/{coin['id']}/photos", files={"file": ("p.png", image_bytes(), "image/png")}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_deleting_a_photo_asks_for_the_password(client, stale_client, token_client, coin):
    photo = _photo(client, coin)
    stale = stale_client.delete(f"/api/photos/{photo['id']}")
    assert stale.status_code == 403 and stale.json()["reauth_required"] is True
    assert token_client("write").delete(f"/api/photos/{photo['id']}").status_code == 403
    assert client.get(f"/api/items/{coin['id']}/photos").json()  # still there
    assert client.delete(f"/api/photos/{photo['id']}").status_code == 204


def test_replacing_an_image_asks_for_the_password(client, stale_client, token_client, coin):
    photo = _photo(client, coin)
    files = {"file": ("q.png", image_bytes(color=(0, 0, 200)), "image/png")}
    stale = stale_client.put(f"/api/photos/{photo['id']}/image", files=files)
    assert stale.status_code == 403 and stale.json()["reauth_required"] is True
    assert (
        token_client("write").put(f"/api/photos/{photo['id']}/image", files=files).status_code
        == 403
    )
    assert client.put(f"/api/photos/{photo['id']}/image", files=files).status_code == 200
