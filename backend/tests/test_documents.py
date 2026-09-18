"""v0.19.0: documents attached to items, shared between them."""

import io

import pytest
from PIL import Image

from app.config import get_settings
from app.services import documents as store
from tests.conftest import COIN, image_bytes


def pdf_bytes(pages: int = 2) -> bytes:
    frames = [Image.new("RGB", (300, 420), (255, 255, 255 - 40 * i)) for i in range(pages)]
    buf = io.BytesIO()
    frames[0].save(buf, "PDF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _item(client, **overrides):
    resp = client.post("/api/items", json={**COIN, **overrides})
    assert resp.status_code == 201
    return resp.json()


def _upload(client, item, data, name="receipt.pdf", **form):
    return client.post(
        f"/api/items/{item['id']}/documents", files={"file": (name, data)}, data=form
    )


def test_upload_a_pdf(client):
    item = _item(client)
    resp = _upload(client, item, pdf_bytes(), kind="receipt", title="Show receipt",
                   doc_date="2025-06-01", note="Table 12")  # fmt: skip
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert (doc["kind"], doc["title"], doc["doc_date"], doc["note"]) == (
        "receipt",
        "Show receipt",
        "2025-06-01",
        "Table 12",
    )
    assert (doc["content_type"], doc["pages"], doc["has_thumb"]) == ("application/pdf", 2, True)
    assert doc["filename"] == "receipt.pdf"
    assert [i["id"] for i in doc["items"]] == [item["id"]]

    detail = client.get(f"/api/items/{item['id']}").json()
    assert [d["id"] for d in detail["documents"]] == [doc["id"]]
    history = client.get(f"/api/items/{item['id']}/history").json()
    assert history[0]["changes"] == {"document": [None, "Show receipt"]}

    thumb = client.get(f"/api/documents/{doc['id']}/thumb")
    assert thumb.status_code == 200
    assert Image.open(io.BytesIO(thumb.content)).format == "JPEG"


def test_pdf_is_served_inline_with_safe_headers(client):
    doc = _upload(client, _item(client), pdf_bytes(1), name="Schön invoice.pdf").json()
    resp = client.get(f"/api/documents/{doc['id']}/file")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")
    headers = resp.headers
    assert headers["content-type"] == "application/pdf"
    assert headers["x-content-type-options"] == "nosniff"
    # no `sandbox` for PDFs: it stops Chrome's viewer from rendering them at all
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'self'"
    assert headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''Sch%C3%B6n%20invoice.pdf" in headers["content-disposition"]

    download = client.get(f"/api/documents/{doc['id']}/file", params={"download": True})
    assert download.headers["content-disposition"].startswith("attachment;")


def test_images_are_sandboxed_and_named_by_their_real_type(client):
    doc = _upload(client, _item(client), image_bytes("PNG"), name="scan.jpg").json()
    assert (doc["content_type"], doc["filename"], doc["pages"]) == ("image/png", "scan.png", None)
    resp = client.get(f"/api/documents/{doc['id']}/file")
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"


@pytest.mark.parametrize(
    "data, name, message",
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.svg",
         "Only PDF, JPEG, PNG, and WebP"),
        (b"<html><script>alert(1)</script></html>", "x.pdf", "Only PDF, JPEG, PNG, and WebP"),
        (b"%PDF-1.4 not really a pdf", "x.pdf", "readable PDF"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", "x.heic", "HEIC"),
        (b"", "empty.pdf", "empty"),
    ],
)  # fmt: skip
def test_unsupported_files_are_refused(client, data, name, message):
    resp = _upload(client, _item(client), data, name=name)
    assert resp.status_code == 415
    assert message in resp.json()["detail"]


def test_oversized_files_are_refused(client, monkeypatch):
    monkeypatch.setattr(store, "MAX_BYTES", 1000)
    resp = _upload(client, _item(client), pdf_bytes())
    assert resp.status_code == 413


def test_edit_a_document(client):
    doc = _upload(client, _item(client), pdf_bytes()).json()
    resp = client.patch(
        f"/api/documents/{doc['id']}",
        json={"kind": "certificate", "title": " COA ", "doc_date": None, "note": "signed"},
    )
    assert resp.status_code == 200
    assert (resp.json()["kind"], resp.json()["title"], resp.json()["note"]) == (
        "certificate",
        "COA",
        "signed",
    )
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/documents/{doc['id']}", json={"kind": "bogus"}).status_code == 422


def test_share_a_document_between_items(client):
    first, second, third = _item(client), _item(client, year=1933), _item(client, year=1934)
    doc = _upload(client, first, pdf_bytes(), title="Lot invoice").json()

    resp = client.post(
        f"/api/documents/{doc['id']}/items", json={"item_ids": [second["id"], third["id"]]}
    )
    assert resp.status_code == 200
    assert {i["id"] for i in resp.json()["items"]} == {first["id"], second["id"], third["id"]}
    # linking again is harmless; an unknown item is a 404
    client.post(f"/api/documents/{doc['id']}/items", json={"item_ids": [second["id"]]})
    missing = client.post(
        f"/api/documents/{doc['id']}/items",
        json={"item_ids": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert missing.status_code == 404
    assert len(client.get(f"/api/items/{second['id']}/documents").json()) == 1

    # removing it from one item leaves it on the others
    assert client.delete(f"/api/items/{first['id']}/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/items/{first['id']}").json()["documents"] == []
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200
    again = client.delete(f"/api/items/{first['id']}/documents/{doc['id']}")
    assert again.status_code == 404

    # deleting an item keeps a document another item still holds…
    assert client.delete(f"/api/items/{second['id']}?permanent=true").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200
    # …and removing it from its last item deletes the file
    assert client.delete(f"/api/items/{third['id']}/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 404
    assert not (store.root() / doc["id"]).exists()


def test_deleting_an_item_deletes_documents_only_it_held(client):
    item = _item(client)
    doc = _upload(client, item, pdf_bytes()).json()
    assert client.delete(f"/api/items/{item['id']}?permanent=true").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 404
    assert not (store.root() / doc["id"]).exists()


def test_delete_a_document_everywhere(client):
    first, second = _item(client), _item(client, year=1940)
    doc = _upload(client, first, pdf_bytes()).json()
    client.post(f"/api/documents/{doc['id']}/items", json={"item_ids": [second["id"]]})
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    for item in (first, second):
        assert client.get(f"/api/items/{item['id']}").json()["documents"] == []
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 404


def test_clone_does_not_copy_documents(client):
    item = _item(client)
    _upload(client, item, pdf_bytes())
    copy = client.post(f"/api/items/{item['id']}/clone").json()
    assert client.get(f"/api/items/{copy['id']}").json()["documents"] == []


def test_uploads_need_a_mounted_volume(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_DOCUMENT_MOUNT", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(store, "_mount_points", lambda: {"/", "/data/photos"})
    assert client.get("/api/health").json()["documents"] == "not_mounted"
    resp = _upload(client, _item(client), pdf_bytes())
    assert resp.status_code == 503
    assert "isn't a mounted volume" in resp.json()["detail"]

    monkeypatch.setattr(store, "_mount_points", lambda: {str(store.root().resolve())})
    assert client.get("/api/health").json()["documents"] == "ok"
    assert _upload(client, _item(client), pdf_bytes()).status_code == 201


def test_documents_never_live_inside_the_photo_volume(client, monkeypatch):
    monkeypatch.setenv("DOCUMENT_DIR", str(get_settings().photo_dir) + "/documents")
    get_settings.cache_clear()
    assert client.get("/api/health").json()["documents"] == "inside_photos"
    assert _upload(client, _item(client), pdf_bytes()).status_code == 503


def test_stored_keys_cannot_escape_the_document_folder():
    with pytest.raises(FileNotFoundError):
        store.path_of("../secret.key")
