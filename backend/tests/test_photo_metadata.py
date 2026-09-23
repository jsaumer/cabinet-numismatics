"""Photos carry no metadata (v0.32.0, SPEC_0320 stage 4, the review's HIGH 1):
every upload is re-encoded without EXIF, GPS, XMP, IPTC, or text chunks, its
colour profile kept, and photos stored before that are cleaned once by
`photos.strip_existing`. The share view's per-file check (v0.32.1) is an
allowlist walk of the whole file from v0.32.2."""

import io
import json
import logging
import os
import zlib
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
    # A damaged file mustn't put every start on the slow path, so the marker
    # is written; the share view's per-file check refuses to trust it.
    assert photos.marker_exists()
    assert photos.marker_unreadable() == {"item-3/broken.jpg"}  # refused when shared
    assert not photos.looks_clean(broken)
    assert photos.looks_clean(jpeg) and photos.looks_clean(png) and photos.looks_clean(webp)
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


def _clean(fmt: str) -> bytes:
    return photos.clean_bytes(*photos.open_validated(dirty(fmt)))


def _jpeg_with_segment_after_scan() -> bytes:
    """An APP1 hidden after the first scan, where Pillow's header read
    never looks (as between a progressive JPEG's scans)."""
    data = _clean("JPEG")
    payload = b"Exif\0\0" + SECRET
    return data[:-2] + b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload + data[-2:]


@pytest.mark.parametrize(
    "name, make, want",
    [
        ("clean.jpg", lambda: _clean("JPEG"), True),
        ("clean.png", lambda: _clean("PNG"), True),
        ("plain.jpg", clean_jpeg, True),
        ("gps.jpg", lambda: dirty("JPEG"), False),
        ("gps.png", lambda: dirty("PNG"), False),
        ("truncated.jpg", lambda: _clean("JPEG")[:-40], False),
        ("truncated.png", lambda: _clean("PNG")[:-20], False),
        ("trailer.jpg", lambda: _clean("JPEG") + b"trailing " + SECRET, False),
        ("appended.jpg", lambda: _clean("JPEG") + dirty("JPEG"), False),
        ("hidden.jpg", _jpeg_with_segment_after_scan, False),
        ("trailer.png", lambda: _clean("PNG") + SECRET, False),
        ("time.png", png_with_time, False),
        ("app12.jpg", jpeg_with_app12, False),
        ("comment.jpg", old_thumbnail, False),
        ("clean.webp", lambda: _clean("WEBP"), True),
        ("gps.webp", lambda: dirty("WEBP"), False),
        ("truncated.webp", lambda: _clean("WEBP")[:-10], False),
        ("broken.jpg", lambda: b"not an image at all", False),
        ("empty.jpg", lambda: b"", False),
    ],
)
def test_looks_clean_trusts_only_what_it_can_read(tmp_path, name, make, want):
    path = plant(tmp_path, name, make())
    assert photos.looks_clean(path) is want


def test_looks_clean_decodes_no_pixels(tmp_path, monkeypatch):
    """It runs on every shared photo request: headers only. (A load would
    raise here, which looks_clean reads as not clean.)"""
    from PIL import ImageFile

    paths = [
        plant(tmp_path, "clean.png", _clean("PNG")),
        plant(tmp_path, "clean.jpg", _clean("JPEG")),
        plant(tmp_path, "clean.webp", _clean("WEBP")),
    ]

    def refuse(self, *args, **kwargs):
        raise AssertionError("looks_clean decoded the image")

    monkeypatch.setattr(ImageFile.ImageFile, "load", refuse)
    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", refuse)
    for path in paths:
        assert photos.looks_clean(path), path.name


def test_a_restore_during_the_pass_leaves_no_marker(monkeypatch):
    """A pass already walking when a restore removes the marker (and swaps
    photos in behind the walk) must not write it afterwards."""
    root = Path(get_settings().photo_dir)
    plant(root, "item-1/one.jpg", dirty("JPEG"))
    plant(root, "item-1/two.jpg", dirty("JPEG"))
    real = photos._strip_one
    calls = []

    def restore_arrives(path):
        if not calls:
            photos.remove_marker()
        calls.append(path)
        return real(path)

    monkeypatch.setattr(photos, "_strip_one", restore_arrives)
    found = photos.strip_existing()
    assert found["failed"] == 0 and found["rewritten"] == 2
    assert not photos.marker_exists()
    photos.strip_existing()  # the restore's own pass
    assert photos.marker_exists()


def test_the_summary_reaches_the_backend_log(caplog):
    """The line saying how many photos were unreadable is logged at INFO on
    `app.services.photos`, which has no level or handler of its own and
    reaches the container's log through the `app` logger main.py sets up."""
    import app.main  # noqa: F401  # configures logging, as the backend does on import

    root = Path(get_settings().photo_dir)
    plant(root, "item-1/broken.jpg", b"not an image at all")
    plant(root, "item-1/one.jpg", dirty("JPEG"))
    named = logging.getLogger("app.services.photos")
    assert named.level == logging.NOTSET and named.propagate and not named.handlers
    parent = logging.getLogger("app")
    assert parent.level == logging.INFO
    assert any(type(h) is logging.StreamHandler for h in parent.handlers)
    parent.addHandler(caplog.handler)  # where main.py's handler sits
    try:
        with caplog.at_level(logging.INFO, logger="app.services.photos"):
            photos.strip_existing()
    finally:
        parent.removeHandler(caplog.handler)
    summary = [
        r
        for r in caplog.records
        if r.name == "app.services.photos" and r.getMessage().startswith("Photo metadata: rewrote")
    ]
    assert summary and summary[-1].levelno == logging.INFO
    assert "1 of 2 stored photos (1 unreadable, 0 failed)" in summary[-1].getMessage()
    assert any(
        r.levelno == logging.WARNING and "broken.jpg" in r.getMessage() for r in caplog.records
    )


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


# --- the allowlist walks (v0.32.2) --------------------------------------------------


CANARY = b"CANARY-7f3a-where-i-live"


def segment(marker: int, body: bytes) -> bytes:
    """A JPEG marker segment with its length."""
    return bytes([0xFF, marker]) + (len(body) + 2).to_bytes(2, "big") + body


def after_soi(data: bytes, extra: bytes) -> bytes:
    return data[:2] + extra + data[2:]


def before_eoi(data: bytes, extra: bytes) -> bytes:
    return data[:-2] + extra + data[-2:]


def png_chunk(kind: bytes, body: bytes, crc: int | None = None) -> bytes:
    crc = zlib.crc32(kind + body) if crc is None else crc
    return len(body).to_bytes(4, "big") + kind + body + crc.to_bytes(4, "big")


def after_ihdr(data: bytes, extra: bytes) -> bytes:
    return data[:33] + extra + data[33:]  # signature (8) and IHDR (25)


def before_iend(data: bytes, extra: bytes) -> bytes:
    return data[:-12] + extra + data[-12:]


def plain(fmt: str, mode: str = "RGB", icc: bool = False, quality: int = photos.QUALITY) -> bytes:
    """What Cabinet itself writes for an image with no metadata."""
    img = Image.new(mode, (60, 40))
    if icc:
        img.info["icc_profile"] = ICC
    return photos.clean_bytes(img, fmt, quality)


def app0_body(data: bytes) -> bytes:
    assert data[2:4] == b"\xff\xe0"
    return data[6 : 4 + int.from_bytes(data[4:6], "big")]


def with_app0(data: bytes, body: bytes) -> bytes:
    """`data` with its JFIF segment's body replaced."""
    end = 4 + int.from_bytes(data[4:6], "big")
    return data[:2] + segment(0xE0, body) + data[end:]


def gps_bit_flip() -> bytes:
    """The review's case: one bit flipped in an APP1 marker (E1 to F1)
    turns the EXIF segment, GPS and all, into a reserved JPG1 segment that
    Pillow's `applist` doesn't list."""
    exif = Image.Exif()
    exif[0x010F] = CANARY.decode()  # Make
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 12.5), 3: "W", 4: (0.0, 7.0, 39.0)}
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (200, 30, 30)).save(buf, "JPEG", exif=exif.tobytes())
    data = buf.getvalue()
    at = data.index(b"\xff\xe1")
    return data[: at + 1] + b"\xf1" + data[at + 2 :]


def webp_with_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = CANARY.decode()
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (200, 30, 30)).save(buf, "WEBP", exif=exif.tobytes())
    return buf.getvalue()


def riff(chunks: list[tuple[bytes, bytes]], pad: bytes = b"\0") -> bytes:
    body = b"WEBP"
    for kind, payload in chunks:
        body += kind + len(payload).to_bytes(4, "little") + payload
        body += pad if len(payload) % 2 else b""
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def webp_parts(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks, pos = [], 12
    while pos < len(data):
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        chunks.append((data[pos : pos + 4], data[pos + 8 : pos + 8 + size]))
        pos += 8 + size + size % 2
    return chunks


def webp_flagged(flag: int) -> bytes:
    parts = webp_parts(plain("WEBP", icc=True))
    kind, payload = parts[0]
    assert kind == b"VP8X"
    return riff([(kind, bytes([payload[0] | flag]) + payload[1:]), *parts[1:]])


def jpeg_with_fake_icc() -> bytes:
    """An APP2 that says ICC_PROFILE but holds no profile."""
    return after_soi(plain("JPEG"), segment(0xE2, b"ICC_PROFILE\0\x01\x01" + CANARY))


def jpeg_icc_fragments_that_dont_add_up() -> bytes:
    """A real profile, but the fragment count is wrong, so Pillow drops it
    without a word and reports no profile at all."""
    return after_soi(plain("JPEG"), segment(0xE2, b"ICC_PROFILE\0\x01\x02" + ICC + CANARY))


ADOBE = b"Adobe\0d\0\0\0\0\x01"  # APP14's twelve bytes, as Pillow writes them


# (name, bytes) the share view must never send from disk: each carries
# CANARY somewhere past the pixels, or is malformed.
REFUSED = {
    "jpgn-in-header.jpg": lambda: after_soi(plain("JPEG"), segment(0xF1, CANARY)),
    "jpgn-after-scan.jpg": lambda: before_eoi(plain("JPEG"), segment(0xF1, CANARY)),
    "exp.jpg": lambda: after_soi(plain("JPEG"), segment(0xDF, CANARY)),
    "big-jfif.jpg": lambda: with_app0(plain("JPEG"), app0_body(plain("JPEG")) + CANARY),
    "jfif-thumbnail.jpg": lambda: with_app0(
        plain("JPEG"), app0_body(plain("JPEG"))[:12] + b"\x01\x01" + CANARY[:3]
    ),
    "fake-icc.jpg": jpeg_with_fake_icc,
    "icc-miscounted.jpg": jpeg_icc_fragments_that_dont_add_up,
    "fpxr.jpg": lambda: after_soi(plain("JPEG"), segment(0xE2, b"FPXR\0" + CANARY)),
    "big-adobe.jpg": lambda: after_soi(plain("JPEG"), segment(0xEE, ADOBE + CANARY)),
    "comment.jpg": lambda: after_soi(plain("JPEG"), segment(0xFE, CANARY)),
    "app1-after-scan.jpg": lambda: before_eoi(plain("JPEG"), segment(0xE1, b"Exif\0\0" + CANARY)),
    "second-sos-baseline.jpg": lambda: before_eoi(
        plain("JPEG"), segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + CANARY
    ),
    "fill-bytes.jpg": lambda: after_soi(plain("JPEG"), b"\xff\xff"),
    "length-past-end.jpg": lambda: plain("JPEG")[:-2] + b"\xff\xc4\xff\xf0" + CANARY,
    "appended.jpg": lambda: plain("JPEG") + gps_bit_flip(),
    "trailer.jpg": lambda: plain("JPEG") + CANARY,
    "gps-bit-flip.jpg": gps_bit_flip,
    "padded-phys.png": lambda: after_ihdr(
        plain("PNG"), png_chunk(b"pHYs", b"\0\0\x0b\x13\0\0\x0b\x13\x01" + CANARY)
    ),
    "bad-crc.png": lambda: before_iend(plain("PNG"), png_chunk(b"IDAT", CANARY, crc=1)),
    "text.png": lambda: before_iend(plain("PNG"), png_chunk(b"tEXt", b"Comment\0" + CANARY)),
    "private.png": lambda: before_iend(plain("PNG"), png_chunk(b"prVt", CANARY)),
    "chunk-past-end.png": lambda: plain("PNG")[:-12] + png_chunk(b"IDAT", CANARY)[:-6],
    "after-iend.png": lambda: plain("PNG") + CANARY,
    "icc-renamed.png": lambda: after_ihdr(
        plain("PNG"), png_chunk(b"iCCP", CANARY + b"\0\0" + zlib.compress(ICC))
    ),
    "exif.webp": webp_with_exif,
    "xmp-flag.webp": lambda: webp_flagged(0x04),
    "unknown-chunk.webp": lambda: riff([*webp_parts(plain("WEBP", icc=True)), (b"NOTE", CANARY)]),
    "second-iccp.webp": lambda: riff([*webp_parts(plain("WEBP", icc=True)), (b"ICCP", CANARY)]),
    "fake-iccp.webp": lambda: riff(
        [(k, CANARY if k == b"ICCP" else p) for k, p in webp_parts(plain("WEBP", icc=True))]
    ),
    "trailer.webp": lambda: plain("WEBP") + CANARY,
    "riff-size.webp": lambda: (lambda d: d[:4] + len(d).to_bytes(4, "little") + d[8:])(
        plain("WEBP")
    ),
    "nonzero-pad.webp": lambda: riff(webp_parts(plain("WEBP", "RGBA")), pad=b"Z"),
}
# Hidden inside the compressed pixel stream, where a structure-only check
# can't look: known limits of the fast path, pinned so a change is noticed.
BEYOND_STRUCTURE = {
    "text-before-eoi.jpg": lambda: before_eoi(plain("JPEG"), b"plain text " + CANARY),
    "extra-idat.png": lambda: before_iend(plain("PNG"), png_chunk(b"IDAT", CANARY)),
}


@pytest.mark.parametrize(
    "fmt, mode, icc, quality",
    [
        ("JPEG", "RGB", True, photos.QUALITY),
        ("JPEG", "RGB", True, photos.THUMB_QUALITY),
        ("JPEG", "RGB", False, photos.QUALITY),
        ("JPEG", "RGB", False, photos.THUMB_QUALITY),
        ("JPEG", "L", False, photos.QUALITY),
        ("JPEG", "CMYK", False, photos.QUALITY),  # Adobe's APP14
        ("PNG", "RGB", True, photos.QUALITY),
        ("PNG", "RGB", False, photos.QUALITY),
        ("PNG", "RGBA", True, photos.QUALITY),
        ("PNG", "LA", False, photos.QUALITY),
        ("WEBP", "RGB", True, photos.QUALITY),
        ("WEBP", "RGB", False, photos.QUALITY),
        ("WEBP", "RGBA", True, photos.QUALITY),
        ("WEBP", "RGBA", False, photos.QUALITY),
    ],
)
def test_what_cabinet_writes_passes_the_walk(tmp_path, fmt, mode, icc, quality):
    """The fast path has to hold for Cabinet's own output, or every request
    would re-encode: `clean_bytes` at both qualities, with and without a
    profile, is sent as it is."""
    data = plain(fmt, mode, icc, quality)
    path = plant(tmp_path, f"own.{fmt.lower()}", data)
    assert photos.checked_bytes(path) == (data, photos.MEDIA_TYPES[fmt])


@pytest.mark.parametrize("transparency", [1, bytes([0, 128])], ids=["index", "alpha list"])
def test_a_palette_with_transparency_passes_the_walk(tmp_path, transparency):
    img = Image.new("P", (20, 20), 1)
    img.putpalette([0, 0, 0, 255, 0, 0])
    img.info["transparency"] = transparency
    data = photos.clean_bytes(img, "PNG")
    assert photos.checked_bytes(plant(tmp_path, "p.png", data)) == (data, "image/png")


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_the_walk_refuses(tmp_path, name):
    assert not photos.looks_clean(plant(tmp_path, name, REFUSED[name]()))


def test_a_long_trns_or_bkgd_is_refused(tmp_path):
    img = Image.new("P", (20, 20), 1)
    img.putpalette([0, 0, 0, 255, 0, 0])
    data = photos.clean_bytes(img, "PNG")
    assert photos.looks_clean(plant(tmp_path, "p.png", data))
    for extra in (png_chunk(b"tRNS", b"\0\x80\x10"), png_chunk(b"bKGD", b"\0\0")):
        at = data.index(b"IDAT") - 4
        bad = data[:at] + extra + data[at:]
        assert not photos.looks_clean(plant(tmp_path, "bad.png", bad))


@pytest.mark.parametrize("name", sorted(BEYOND_STRUCTURE))
def test_what_structure_cannot_see(tmp_path, name):
    """Bytes inside the compressed stream (after a JPEG's last coded unit,
    or an IDAT after the zlib stream ends) are indistinguishable from pixel
    data without decoding it, which the check never does."""
    assert photos.looks_clean(plant(tmp_path, name, BEYOND_STRUCTURE[name]()))


def test_a_fake_profile_is_not_kept(tmp_path):
    """Pillow reports whatever an ICC_PROFILE segment holds as the profile;
    one that isn't shaped like a profile is dropped, never re-encoded in."""
    img, fmt = photos.open_validated(jpeg_with_fake_icc())
    assert img.info.get("icc_profile", b"").endswith(CANARY)
    data = photos.clean_bytes(img, fmt)
    assert CANARY not in data and "icc_profile" not in Image.open(io.BytesIO(data)).info
    assert photos.looks_clean(plant(tmp_path, "rewritten.jpg", data))


# --- the marker's list of unreadable files (v0.32.2) --------------------------------


def test_the_marker_lists_what_the_pass_could_not_read():
    root = Path(get_settings().photo_dir)
    plant(root, "item-1/one.jpg", dirty("JPEG"))
    plant(root, "item-2/sub/broken.png", b"not an image at all")
    assert photos.marker_unreadable() is None  # no marker yet
    photos.strip_existing()
    assert photos.marker_unreadable() == {"item-2/sub/broken.png"}
    assert json.loads(photos._marker_path().read_text("utf-8")) == {
        "unreadable": ["item-2/sub/broken.png"]
    }


def test_an_older_marker_still_counts():
    """A v0.32.0 or v0.32.1 marker is a line of prose: it lists nothing, and
    the pass isn't run again for it."""
    path = photos._marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Every stored photo has had its metadata removed.\n", "utf-8")
    assert photos.marker_exists() and photos.marker_unreadable() == frozenset()
    assert photos.clean_in_background() is False
    path.write_text('{"unreadable": ', "utf-8")  # cut short: trust nothing
    assert photos.marker_unreadable() is None
