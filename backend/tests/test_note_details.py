"""v0.29.0: note details (width/height, printer, watermark) and
demonetization, for coins and notes alike."""

import csv
import io

import pytest

from app.config import get_settings
from tests.conftest import COIN
from tests.test_imports import _items, _preview, _run, _upload
from tests.test_parity import NOTE, create, listed, patch

NATIONAL = {**NOTE, "width_mm": 190.5, "height_mm": 79.4, "printer": "BEP"}


def test_create_and_read_note_details(client):
    note = create(
        client,
        NOTE,
        width_mm=152.4,
        height_mm=69.85,
        printer="Canadian Bank Note Company",
        watermark="Portrait",
        demonetized_on="1922-05-01",
    )
    assert note["width_mm"] == 152.4
    assert note["height_mm"] == 69.85
    assert note["printer"] == "Canadian Bank Note Company"
    assert note["watermark"] == "Portrait"
    assert note["demonetized_on"] == "1922-05-01"

    coin = create(client, demonetized_on="1965-01-01")  # coins keep diameter_mm
    assert coin["demonetized_on"] == "1965-01-01"
    assert coin["width_mm"] is None and coin["diameter_mm"] is None


def test_update_note_details(client):
    note = create(client, NOTE)
    body = patch(client, note, width_mm=100.0, height_mm=50.0, printer="ABNCo").json()
    assert (body["width_mm"], body["height_mm"], body["printer"]) == (100.0, 50.0, "ABNCo")
    cleared = patch(client, note, width_mm=None).json()
    assert cleared["width_mm"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"width_mm": 0},
        {"width_mm": -1},
        {"width_mm": 2001},
        {"height_mm": 2001},
        {"printer": "x" * 201},
        {"watermark": "x" * 201},
    ],
)
def test_validation(client, bad):
    resp = client.post("/api/items", json={**NOTE, **bad})
    assert resp.status_code == 422, resp.text


def test_q_matches_printer(client):
    create(client, NOTE, printer="Thomas de la Rue")
    create(client, NOTE, printer="Giesecke & Devrient")
    assert len(listed(client, q="de la Rue")) == 1
    assert len(listed(client, q="Giesecke")) == 1
    assert len(listed(client, q="nonexistent printer")) == 0


def test_clone_copies_note_details(client):
    note = create(
        client, NOTE, width_mm=190.5, height_mm=79.4, printer="BEP",
        watermark="Eagle", demonetized_on="1935-07-01",
    )  # fmt: skip
    clone = client.post(f"/api/items/{note['id']}/clone").json()
    assert clone["width_mm"] == 190.5
    assert clone["height_mm"] == 79.4
    assert clone["printer"] == "BEP"
    assert clone["watermark"] == "Eagle"
    assert clone["demonetized_on"] == "1935-07-01"


def test_bulk_edit_refuses_note_details(client):
    note = create(client, NOTE)
    resp = client.post(
        "/api/items/bulk",
        json={
            "ids": [note["id"]],
            "set": {
                "width_mm": 100.0, "height_mm": 50.0, "printer": "X",
                "watermark": "Y", "demonetized_on": "2000-01-01",
            },
        },
    )  # fmt: skip
    assert resp.status_code == 200
    unchanged = client.get(f"/api/items/{note['id']}").json()
    assert unchanged["width_mm"] is None
    assert unchanged["height_mm"] is None
    assert unchanged["printer"] is None
    assert unchanged["watermark"] is None
    assert unchanged["demonetized_on"] is None


@pytest.fixture()
def import_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path / "imports"))
    get_settings.cache_clear()


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_export_and_reimport_round_trip(client, tmp_path, import_dir, extension):
    note = create(
        client, NATIONAL, watermark="Eagle", demonetized_on="1935-07-01",
    )  # fmt: skip
    export = tmp_path / f"cabinet-items.{extension}"
    export.write_bytes(client.get(f"/api/items/export.{extension}").content)
    client.delete(f"/api/items/{note['id']}?permanent=true")

    upload = _upload(client, export)
    assert upload["format"] == "cabinet"
    assert _preview(client, upload)["errors"] == 0
    assert _run(client, upload)["created"] == 1
    [copy] = _items(client).values()
    for key in ("width_mm", "height_mm", "printer", "watermark", "demonetized_on"):
        assert copy[key] == note[key], key


def test_old_csv_import_without_the_new_columns_still_works(client):
    create(client, COIN)
    raw = client.get("/api/items/export.csv").content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    dropped = {"width_mm", "height_mm", "printer", "watermark", "demonetized_on"}
    keep = [i for i, name in enumerate(rows[0]) if name not in dropped]
    old_rows = [[row[i] for i in keep] for row in rows]
    buf = io.StringIO()
    csv.writer(buf).writerows(old_rows)
    old_csv = ("﻿" + buf.getvalue()).encode("utf-8")

    for item in listed(client):
        client.delete(f"/api/items/{item['id']}?permanent=true")
    resp = client.post("/api/items/import", files={"file": ("old.csv", old_csv, "text/csv")})
    assert resp.json()["created"] == 1, resp.text
    [copy] = listed(client)
    assert copy["width_mm"] is None and copy["printer"] is None
