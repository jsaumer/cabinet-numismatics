"""v0.18.0: importing from Numista, OpenNumismat, and spreadsheets."""

import httpx
import pytest

from app.config import get_settings
from app.services import importing, numista
from app.services import photos as photo_store
from tests import import_samples as samples
from tests.conftest import image_bytes


@pytest.fixture(autouse=True)
def import_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path / "imports"))
    get_settings.cache_clear()


def _upload(client, path):
    with open(path, "rb") as fh:
        resp = client.post("/api/imports", files={"file": (path.name, fh)})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _preview(client, upload, **options):
    resp = client.post(f"/api/imports/{upload['upload_id']}/preview", json=options)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run(client, upload, **options):
    resp = client.post(f"/api/imports/{upload['upload_id']}/run", json=options)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _items(client):
    return {
        f"{i['country']} {i['denomination']} {i['year']}": client.get(
            f"/api/items/{i['id']}"
        ).json()
        for i in client.get("/api/items", params={"limit": 200}).json()["items"]
    }


# ---------------------------------------------------------------- grades and values


@pytest.mark.parametrize(
    "text, rank, strike, plus, approximate",
    [
        ("MS-64", 64, None, False, False),
        ("ms64+", 64, None, True, False),
        ("PF-69 DCAM", 69, "proof", False, False),
        ("PR 70", 70, "proof", False, False),
        ("64 EPQ", 64, None, False, False),
        ("VF 30", 30, None, False, False),
        ("XF", 40, None, False, True),
        ("Choice Very Fine", 20, None, False, True),
        ("Uncirculated", 60, None, False, True),
        ("BU", 60, None, False, True),
    ],
)
def test_parse_grade(text, rank, strike, plus, approximate):
    match = importing.parse_grade(text)
    assert (match.rank, match.strike, match.plus, match.approximate) == (
        rank,
        strike,
        plus,
        approximate,
    )


def test_parse_grade_designations_and_nothing():
    assert importing.parse_grade("PMG 66 EPQ ★").designations == ["EPQ"]
    assert importing.parse_grade("PMG 66 EPQ ★").star is True
    assert importing.parse_grade("nice!") is None
    assert importing.parse_grade("") is None


@pytest.mark.parametrize(
    "text, expected",
    [("$1,250.00", 1250), ("1.234,50", 1234.5), ("12,5", 12.5), ("€ 3", 3), ("", None)],
)
def test_to_float(text, expected):
    assert importing.to_float(text) == expected


def test_to_date():
    assert str(importing.to_date("3/14/2024")) == "2024-03-14"
    assert str(importing.to_date("14/3/2024")) == "2024-03-14"
    assert str(importing.to_date("14.03.2024")) == "2024-03-14"
    assert str(importing.to_date("2024-03-14T10:00:00Z")) == "2024-03-14"
    assert importing.to_date("soon") is None


# ---------------------------------------------------------------- uploads


def test_upload_detects_the_format(client, tmp_path):
    cases = {
        samples.opennumismat(tmp_path / "c.db"): "opennumismat",
        samples.numista_csv(tmp_path / "n.csv"): "numista_file",
        samples.numista_xlsx(tmp_path / "n.xlsx"): "numista_file",
        samples.hand_sheet(tmp_path / "h.csv"): "spreadsheet",
    }
    for path, fmt in cases.items():
        assert _upload(client, path)["format"] == fmt


def test_unknown_or_discarded_upload(client, tmp_path):
    assert client.post("/api/imports/" + "0" * 32 + "/preview", json={}).status_code == 404
    assert client.post("/api/imports/not-an-id/preview", json={}).status_code == 404
    upload = _upload(client, samples.hand_sheet(tmp_path / "h.csv"))
    assert client.delete(f"/api/imports/{upload['upload_id']}").status_code == 204
    resp = client.post(f"/api/imports/{upload['upload_id']}/preview", json={})
    assert resp.status_code == 404
    assert "expired" in resp.json()["detail"]


def test_a_text_file_is_not_an_opennumismat_collection(client, tmp_path):
    upload = _upload(client, samples.hand_sheet(tmp_path / "h.csv"))
    resp = client.post(
        f"/api/imports/{upload['upload_id']}/preview", json={"format": "opennumismat"}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------- OpenNumismat


def test_opennumismat_preview_writes_nothing(client, tmp_path):
    upload = _upload(client, samples.opennumismat(tmp_path / "c.db", 10))
    body = _preview(client, upload)
    assert body["format"] == "opennumismat"
    assert (body["total"], body["new"], body["duplicates"], body["errors"]) == (7, 5, 0, 2)
    assert body["photos"] == 2
    errors = {r["row"]: r["error"] for r in body["rows"] if r["status"] == "error"}
    assert "lost at auction" in errors[5]
    assert "year" in errors[6]
    assert client.get("/api/items").json()["total"] == 0


@pytest.mark.parametrize("version", [10, 11])
def test_opennumismat_import(client, tmp_path, version):
    upload = _upload(client, samples.opennumismat(tmp_path / f"c{version}.db", version))
    result = _run(client, upload)
    assert (result["created"], result["skipped"], result["photos_added"]) == (5, 0, 2)
    assert [e["row"] for e in result["errors"]] == [5, 6]

    items = _items(client)
    ike = items["United States 1 Dollar 1978"]
    assert (ike["grade"]["code"], ike["acquisition_price"], ike["acquisition_fees"]) == (
        "AU-50",
        3.5,
        0.75,
    )
    assert (ike["acquired_from"], ike["storage_location"]) == ("Coin show", "Album 2, page 4")
    assert ike["acquisition_date"] == "2025-06-01"
    refs = {(r["catalog"], r["ref_code"]) for r in ike["catalog_refs"]}
    assert refs == {("km", "KM#203"), ("red book", "Red Book#5820")}
    assert ike["tags"] == ["Type set"]
    assert [p["angle"] for p in ike["photos"]] == ["obverse", "reverse"]
    assert ike["notes"] == "Apollo 11 reverse."

    quarter = items["United States 0.25 Dollar 1932"]
    assert (quarter["status"], quarter["sold_price"], quarter["sold_fees"]) == ("sold", 400, 40)
    assert (quarter["sold_to"], quarter["fineness"], quarter["mint_mark"]) == ("Heritage", 0.9, "D")

    wish = items["Germany 5 Mark 1975"]
    assert (wish["status"], wish["grade"]["code"]) == ("wishlist", "MS-60")

    note = items["United States 1 Dollar 2017"]
    assert (note["type"], note["grade"]["scale"], note["grade"]["code"]) == ("note", "pmg", "64")
    assert (note["designations"], note["cert_service"], note["cert_number"]) == (
        ["EPQ"],
        "PMG",
        "8081234-001",
    )
    assert (note["signatures"], note["issuer"]) == (
        "Carranza / Mnuchin",
        "Federal Reserve Bank of New York",
    )

    proof = items["United States 1 Dollar 1986"]
    assert (proof["strike"], proof["grade_label"]) == ("proof", "PR-69 DCAM")
    assert proof["acquisition_date"] is None  # OpenNumismat's 2000-01-01 placeholder
    assert proof["acquisition_fees"] == 7.5
    assert proof["currency"] == ("EUR" if version == 11 else "USD")

    again = _run(client, upload)
    assert (again["created"], again["skipped"]) == (0, 5)


def test_opennumismat_defaults_set_the_currency(client, tmp_path):
    upload = _upload(client, samples.opennumismat(tmp_path / "c.db", 10))
    _run(client, upload, defaults={"currency": "cad"})
    assert _items(client)["United States 1 Dollar 1978"]["currency"] == "CAD"


def test_imported_items_record_their_origin_and_clones_do_not(client, tmp_path):
    upload = _upload(client, samples.opennumismat(tmp_path / "c.db", 10))
    _run(client, upload)
    ike = _items(client)["United States 1 Dollar 1978"]
    history = client.get(f"/api/items/{ike['id']}/history").json()
    assert history[-1]["changes"]["via"] == ["import", "OpenNumismat: c.db"]
    copy = client.post(f"/api/items/{ike['id']}/clone")
    assert copy.status_code == 201  # the origin isn't copied, so no unique clash
    assert _run(client, upload)["skipped"] == 5


# ---------------------------------------------------------------- Numista export file


@pytest.mark.parametrize("builder", [samples.numista_csv, samples.numista_xlsx])
def test_numista_export(client, tmp_path, builder):
    upload = _upload(client, builder(tmp_path / f"export.{builder.__name__[-3:]}"))
    body = _preview(client, upload)
    assert (body["total"], body["new"], body["errors"]) == (4, 4, 0)
    messages = [m for r in body["rows"] for m in r["messages"]]
    assert any("VF band recorded as VF-20" in m for m in messages)
    assert any("Undated issue" in m for m in messages)

    result = _run(client, upload)
    assert result["created"] == 4
    items = _items(client)
    ike = items["United States 1 Dollar 1978"]
    assert (ike["series"], ike["grade"]["code"], ike["acquisition_price"]) == (
        "Eisenhower Apollo 11",
        "AU-50",
        3.5,
    )
    assert [r["ref_code"] for r in ike["catalog_refs"]] == ["N#1340"]
    assert (ike["tags"], ike["storage_location"], ike["notes"]) == (
        ["Main"],
        "Album 2",
        "Nice luster",
    )
    egypt = items["Egypt 5 Millieme 1933"]  # the Gregorian year, not AH 1352
    assert (egypt["quantity"], egypt["mint_mark"], egypt["weight_g"]) == (2, "H", 5)
    note = items["United States 1 Dollar 2017"]
    assert (note["type"], note["serial_number"], note["grade"]["code"]) == (
        "note",
        "B12345678C",
        "60",
    )
    assert note["diameter_mm"] is None
    assert items["France 1 Franc 1960"]["year"] == 1960
    assert _run(client, upload)["skipped"] == 4


# ---------------------------------------------------------------- spreadsheets


def test_spreadsheet_suggests_a_mapping(client, tmp_path):
    upload = _upload(client, samples.hand_sheet(tmp_path / "sheet.csv"))
    body = _preview(client, upload)
    assert body["headers"][0] == "Country"
    assert body["mapping"] == {
        "country": "Country",
        "denomination": "Denomination",
        "year": "Year",
        "mint_mark": "Mint",
        "grade": "Grade",
        "quantity": "Qty",
        "acquisition_date": "Purchase Date",
        "acquisition_price": "Price Paid",
        "acquired_from": "Seller",
        "notes": "Notes",
    }
    assert {f["key"] for f in body["fields"]} >= {"country", "grade", "numista"}
    assert (body["total"], body["new"], body["errors"]) == (4, 3, 1)


def test_spreadsheet_import(client, tmp_path):
    upload = _upload(client, samples.hand_sheet(tmp_path / "sheet.csv"))
    result = _run(client, upload)
    assert result["created"] == 3
    items = _items(client)
    cent = items["United States 1 Cent 1909"]
    assert (cent["acquisition_price"], cent["acquisition_date"], cent["grade"]["code"]) == (
        1250,
        "2024-03-14",
        "VF-20",
    )
    assert items["United States 5 Cents 1937"]["grade"]["code"] == "MS-63"
    dime = items["United States 10 Cents 1964"]
    assert (dime["quantity"], dime["grade"]["code"]) == (20, "MS-60")


def test_spreadsheet_mapping_can_be_changed(client, tmp_path):
    upload = _upload(client, samples.hand_sheet(tmp_path / "sheet.csv"))
    mapping = {"country": "Country", "denomination": "Denomination", "year": "Year",
               "series": "Notes"}  # fmt: skip
    body = _preview(
        client, upload, mapping=mapping, defaults={"type": "coin", "status": "wishlist"}
    )
    assert body["mapping"] == mapping
    _run(client, upload, mapping=mapping, defaults={"status": "wishlist"})
    cent = _items(client)["United States 1 Cent 1909"]
    assert (cent["series"], cent["status"], cent["grade"]) == ("VDB", "wishlist", None)

    bad = client.post(
        f"/api/imports/{upload['upload_id']}/preview", json={"mapping": {"year": "Nope"}}
    )
    assert bad.status_code == 422
    assert "Nope" in bad.json()["detail"]


def test_spreadsheet_finds_a_header_below_a_preamble(client, tmp_path):
    upload = _upload(client, samples.colnect_like(tmp_path / "colnect.csv"))
    body = _preview(client, upload)
    assert body["header_row"] == 7
    assert body["mapping"]["denomination"] == "Face value"
    assert body["mapping"]["year"] == "Issued on"
    assert body["mapping"]["catalog_refs"] == "Catalog Codes"
    assert body["mapping"]["grade"] == "Condition"
    assert body["new"] == 2
    _run(client, upload)
    krone = _items(client)["Denmark 1 Krone 1992"]
    assert (krone["grade"]["code"], krone["notes"], krone["catalog_refs"][0]["ref_code"]) == (
        "XF-40",
        "holed",
        "KM#873",
    )
    assert krone["currency"] == "DKK"

    # the header row can also be set by hand
    body = _preview(client, upload, skip_rows=0)
    assert body["headers"][0] == "Colnect collection export"


# ---------------------------------------------------------------- Numista account


@pytest.fixture()
def numista_account(client, monkeypatch):
    """Numista at the HTTP level: the token, the collection, and types."""
    state = {"calls": [], "token_status": 200}

    def fake_get(url, params=None, headers=None, timeout=None):
        state["calls"].append(url.rsplit("/api/v3/", 1)[1])
        request = httpx.Request("GET", url)
        if url.endswith("/oauth_token"):
            assert params == {"grant_type": "client_credentials", "scope": "view_collection"}
            if state["token_status"] != 200:
                return httpx.Response(state["token_status"], json={}, request=request)
            body = {"access_token": "t0k", "token_type": "bearer", "expires_in": 60, "user_id": 42}
            return httpx.Response(200, json=body, request=request)
        if url.endswith("/users/42/collected_items"):
            assert headers["Authorization"] == "Bearer t0k"
            return httpx.Response(200, json=samples.NUMISTA_COLLECTION, request=request)
        type_id = int(url.rsplit("/", 1)[1])
        return httpx.Response(200, json=samples.NUMISTA_TYPES[type_id], request=request)

    monkeypatch.setattr(numista.httpx, "get", fake_get)
    client.put("/api/settings", json={"numista_api_key": "numista-test-key"})
    return state


def test_numista_account_preview(client, numista_account):
    resp = client.post("/api/imports/numista/preview", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["format"] == "numista_account"
    assert (body["total"], body["new"], body["errors"]) == (3, 2, 1)
    assert (body["types"], body["types_to_fetch"]) == (2, 2)
    assert body["photos"] == 1
    assert "exonumia" in body["rows"][2]["error"]
    # the preview spends the token and the collection, never type lookups
    assert numista_account["calls"] == ["oauth_token", "users/42/collected_items"]
    # a second preview within the hour is served from the cache
    client.post("/api/imports/numista/preview", json={})
    assert len(numista_account["calls"]) == 2


def test_numista_account_import(client, numista_account):
    result = client.post("/api/imports/numista/run", json={}).json()
    assert (result["created"], result["photos_added"]) == (2, 0)  # pictures are opt-in
    assert sorted(numista_account["calls"][2:]) == ["types/1340", "types/7777"]

    items = _items(client)
    ike = items["United States 1 Dollar 1978"]
    assert (ike["series"], ike["composition"], ike["weight_g"]) == (
        "Eisenhower Dollar",
        "Copper-nickel clad copper",
        22.68,
    )
    assert (ike["grade"]["code"], ike["acquisition_price"], ike["acquired_from"]) == (
        "AU-50",
        3.5,
        "Coin show",
    )
    assert ike["tags"] == ["Main"]
    assert [r["ref_code"] for r in ike["catalog_refs"]] == ["N#1340"]
    morgan = items["United States 1 Dollar 1881"]
    assert (morgan["grade_label"], morgan["cert_service"], morgan["cert_number"]) == (
        "MS-64 DMPL",
        "PCGS",
        "12345678",
    )
    assert (morgan["cac_sticker"], morgan["mint_mark"], morgan["fineness"]) == ("green", "S", 0.9)
    assert morgan["tags"] == ["for swap"]

    again = client.post("/api/imports/numista/run", json={}).json()
    assert (again["created"], again["skipped"]) == (0, 2)


def test_numista_account_pictures_on_request(client, numista_account, monkeypatch):
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return image_bytes("JPEG")

    monkeypatch.setattr(photo_store, "fetch_remote_image", fake_fetch)
    result = client.post("/api/imports/numista/run", json={"fetch_photos": True}).json()
    assert (result["photos_added"], fetched) == (1, ["https://example.com/ike.jpg"])


def test_numista_account_without_details(client, numista_account):
    result = client.post("/api/imports/numista/run", json={"catalogue_details": False}).json()
    assert result["created"] == 2
    assert not any(c.startswith("types/") for c in numista_account["calls"])
    ike = _items(client)["United States 1 Dollar 1978"]
    assert (ike["denomination"], ike["series"]) == ("1 Dollar", "Eisenhower Apollo 11")


def test_numista_account_needs_a_key_and_a_user(client, numista_account):
    client.put("/api/settings", json={"numista_api_key": ""})
    resp = client.post("/api/imports/numista/preview", json={})
    assert (resp.status_code, "API key" in resp.json()["detail"]) == (422, True)

    client.put("/api/settings", json={"numista_api_key": "another-key"})
    numista_account["token_status"] = 501
    resp = client.post("/api/imports/numista/preview", json={})
    assert resp.status_code == 422
    assert "isn't linked" in resp.json()["detail"]

    numista_account["token_status"] = 401
    assert client.post("/api/imports/numista/preview", json={}).status_code == 502
