"""Photos carry no metadata (v0.32.0, SPEC_0320 stage 4, the review's HIGH 1):
every upload is re-encoded without EXIF, GPS, XMP, IPTC, or text chunks, its
colour profile kept, and photos stored before that are cleaned once by
`photos.strip_existing`."""

import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from app.config import get_settings
from app.services import photos
from tests.conftest import COIN

ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
SECRET = b"Secret Street 7"


def _exif(orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x0110] = "Phone 9"  # Model
    exif[0x9003] = "2026:09:01 10:00:00"  # DateTimeOriginal (in the base IFD here)
    if orientation:
        exif[0x0112] = orientation
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 12.5), 3: "W", 4: (0.0, 7.0, 39.0)}  # GPS IFD
    return exif.tobytes()


def dirty(fmt: str, size=(60, 40), orientation: int | None = None) -> bytes:
    """An image carrying GPS EXIF, XMP (or PNG text), and an ICC profile."""
    img = Image.new("RGB", size, (200, 30, 30))
    img.putpixel((0, 0), (0, 0, 255))  # a marker pixel, to see the turn
    buf = io.BytesIO()
    xmp = b"<x:xmpmeta>" + SECRET + b"</x:xmpmeta>"
    if fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", SECRET.decode())
        info.add_itxt("XML:com.adobe.xmp", xmp.decode())
        img.save(buf, "PNG", pnginfo=info, exif=_exif(orientation), icc_profile=ICC)
    else:
        img.save(buf, fmt, exif=_exif(orientation), xmp=xmp, icc_profile=ICC)
    return buf.getvalue()


def assert_clean(data: bytes, fmt: str, icc: bool = True) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.format == fmt
    assert not photos.carries_metadata(img, data), sorted(img.info)
    assert dict(img.getexif()) == {}
    for needle in (b"GPS", b"Phone", SECRET, b"2026:09:01", b"xmpmeta"):
        assert needle not in data, needle
    if icc:
        assert img.info.get("icc_profile") == ICC  # the colour stays
    return img


def upload(client, data: bytes, name: str) -> tuple[dict, dict]:
    item = client.post("/api/items", json=COIN).json()
    resp = client.post(f"/api/items/{item['id']}/photos", files={"file": (name, data)})
    assert resp.status_code == 201, resp.text
    return item, resp.json()


def stored(photo: dict) -> bytes:
    return (Path(get_settings().photo_dir) / photo["file_key"]).read_bytes()


@pytest.mark.parametrize("fmt, name", [("JPEG", "a.jpg"), ("PNG", "a.png"), ("WEBP", "a.webp")])
def test_an_upload_is_stored_and_shared_without_metadata(client, anon_client, fmt, name):
    source = dirty(fmt)
    assert b"GPS" in source or b"Phone" in source  # the fixture does carry it
    _, photo = upload(client, source, name)
    assert_clean(stored(photo), fmt)
    client.put("/api/settings", json={"share_enabled": True})
    token = (
        client.post("/api/share-links", json={"kind": "collection", "name": "Show"})
        .json()["url"]
        .rsplit("/", 1)[1]
    )
    for variant in ("full", "thumb"):
        resp = anon_client.get(f"/api/share/{token}/photos/{photo['id']}/{variant}")
        assert resp.status_code == 200
        if variant == "full":
            assert_clean(resp.content, fmt)
        else:
            assert b"GPS" not in resp.content and b"Phone" not in resp.content


def test_orientation_is_applied_before_it_is_dropped(client):
    _, photo = upload(client, dirty("JPEG", size=(60, 40), orientation=6), "turned.jpg")
    img = assert_clean(stored(photo), "JPEG")
    assert img.size == (40, 60) == (photo["width"], photo["height"])


def test_a_replaced_image_is_cleaned_too(client):
    _, photo = upload(client, dirty("PNG"), "a.png")
    resp = client.put(
        f"/api/photos/{photo['id']}/image", files={"file": ("edit.jpg", dirty("JPEG"))}
    )
    assert resp.status_code == 200, resp.text
    assert_clean(stored(resp.json()), "JPEG")


def test_a_palette_keeps_its_transparency(client):
    img = Image.new("P", (20, 20), 1)
    img.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    buf = io.BytesIO()
    img.save(buf, "PNG", transparency=1, pnginfo=_text_info())
    _, photo = upload(client, buf.getvalue(), "p.png")
    back = Image.open(io.BytesIO(stored(photo)))
    assert back.mode == "P" and back.info.get("transparency") == 1
    assert "Comment" not in back.info


def _text_info():
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", SECRET.decode())
    return info


# --- the one-time pass --------------------------------------------------------------


def plant(root: Path, relative: str, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def clean_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 10)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def test_the_pass_rewrites_every_stored_photo_thumbnails_included():
    """Every original and thumbnail is re-encoded, whatever it seems to
    carry: no check is trusted to find everything (the second review's N3)."""
    root = Path(get_settings().photo_dir)
    jpeg = plant(root, "item-1/one.jpg", dirty("JPEG", orientation=6))
    png = plant(root, "item-1/two.png", dirty("PNG"))
    webp = plant(root, "item-2/three.webp", dirty("WEBP"))
    tidy = plant(root, "item-2/four.jpg", clean_jpeg())
    thumb = plant(root, "item-1/one_thumb.jpg", old_thumbnail())
    working = plant(root, ".restore-new/item-9/nine.jpg", dirty("JPEG"))
    broken = plant(root, "item-3/broken.jpg", b"not an image at all")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (working, broken)}
    tidy_before = tidy.read_bytes()
    assert not photos.marker_exists()

    found = photos.strip_existing()

    assert found == {"checked": 6, "rewritten": 5, "unreadable": 1, "failed": 0}
    assert assert_clean(jpeg.read_bytes(), "JPEG").size == (40, 60)
    assert_clean(png.read_bytes(), "PNG")
    assert_clean(webp.read_bytes(), "WEBP")
    assert tidy.read_bytes() != tidy_before  # rewritten although it was clean
    assert_clean(tidy.read_bytes(), "JPEG", icc=False)
    assert b"owner Jayson" not in thumb.read_bytes()
    assert_clean(thumb.read_bytes(), "JPEG", icc=False)
    for path, (data, mtime) in before.items():
        assert path.read_bytes() == data and path.stat().st_mtime_ns == mtime, path
    assert not [p for p in root.rglob(".strip-*")]  # no temporary left behind
    assert photos.marker_exists()
    # A second pass (the container command) finds everything still clean.
    assert photos.strip_existing()["failed"] == 0
    assert_clean(jpeg.read_bytes(), "JPEG")


def old_thumbnail() -> bytes:
    """A thumbnail made the pre-v0.32.0 way: Pillow's JPEG encoder takes the
    comment from the source image's `info`."""
    img = Image.new("RGB", (40, 30), (90, 90, 200))
    img.info["comment"] = b"owner Jayson"
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    assert b"owner Jayson" in buf.getvalue()
    return buf.getvalue()


def jpeg_with_app12() -> bytes:
    """A JPEG whose only metadata is an APP12 segment ("Ducky"), which
    Pillow keeps in `applist` but not in `info`."""
    data = clean_jpeg()
    payload = b"Ducky\0" + SECRET
    segment = b"\xff\xec" + (len(payload) + 2).to_bytes(2, "big") + payload
    return data[:2] + segment + data[2:]


def png_with_time() -> bytes:
    """A PNG whose only extra is a `tIME` chunk, which Pillow doesn't read."""
    info = PngImagePlugin.PngInfo()
    info.add(b"tIME", (2026).to_bytes(2, "big") + bytes([9, 1, 10, 0, 0]))
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 10)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def png_with_harmless_named_text() -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("timestamp", SECRET.decode())
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 10)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


@pytest.mark.parametrize(
    "name, make, fmt",
    [
        ("app12.jpg", jpeg_with_app12, "JPEG"),
        ("time.png", png_with_time, "PNG"),
        ("named.png", png_with_harmless_named_text, "PNG"),
        ("old_thumb.jpg", old_thumbnail, "JPEG"),
    ],
)
def test_what_the_first_check_missed_is_seen_and_rewritten(name, make, fmt):
    data = make()
    img = Image.open(io.BytesIO(data))
    img.load()
    assert photos.carries_metadata(img, data)  # the check sees it now
    path = plant(Path(get_settings().photo_dir), f"item-1/{name}", data)
    assert photos.strip_existing()["rewritten"] == 1
    assert_clean(path.read_bytes(), fmt, icc=False)


def test_the_pass_never_follows_a_symlink(tmp_path):
    root = Path(get_settings().photo_dir)
    outside = plant(tmp_path, "elsewhere/private.jpg", dirty("JPEG"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(outside, root / "linked.jpg")
        os.symlink(outside.parent, root / "linked-folder", target_is_directory=True)
    except OSError:
        pytest.skip("this machine can't make symlinks")
    before = outside.read_bytes()
    found = photos.strip_existing()
    assert found["rewritten"] == 0 and outside.read_bytes() == before


def test_a_failed_rewrite_leaves_the_marker_unwritten(monkeypatch):
    root = Path(get_settings().photo_dir)
    plant(root, "item-1/one.jpg", dirty("JPEG"))

    def refuse(*args, **kwargs):
        raise PermissionError("read-only volume")

    monkeypatch.setattr(photos.os, "replace", refuse)
    found = photos.strip_existing()  # never raises
    assert found["failed"] == 1 and not photos.marker_exists()
    assert not list(root.rglob(".strip-*"))


def test_the_background_pass_runs_only_without_the_marker(monkeypatch):
    started = []
    monkeypatch.setattr(photos, "_spawn", lambda fn: started.append(fn) or fn())
    assert photos.clean_in_background() is True
    assert photos.marker_exists() and len(started) == 1
    assert photos.clean_in_background() is False  # marked: nothing to do
    assert photos.clean_in_background(force=True) is True  # after a restore
    photos.remove_marker()
    assert not photos.marker_exists()


def test_the_startup_pass_runs_without_auto_migrate(monkeypatch):
    """It needs no database, so an install that migrates by hand cleans its
    photos too (the second review's N1)."""
    from fastapi.testclient import TestClient

    from app.main import app

    started = []
    monkeypatch.setattr(photos, "_spawn", started.append)
    assert get_settings().auto_migrate is False
    with TestClient(app):
        pass
    assert len(started) == 1
    photos._write_marker()
    with TestClient(app):
        pass
    assert len(started) == 1  # marked: not again


def test_the_container_command(capsys):
    from app import cli

    root = Path(get_settings().photo_dir)
    path = plant(root, "item-1/one.png", dirty("PNG"))
    assert cli.main(["strip-photo-metadata"]) == 0
    assert "Rewrote 1 of 1 stored photos" in capsys.readouterr().out
    assert_clean(path.read_bytes(), "PNG")
    assert photos.marker_exists()
