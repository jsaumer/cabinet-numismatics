"""Proof and mint sets (SPEC_0370, v0.37.0, stage 4): imports, exports, and
sharing. The Numista export is synthetic (tests/import_samples.py), shaped
like the owner's but never the file itself."""

import csv
import io

import pytest

from tests import import_samples as samples
from tests.test_imports import _preview, _run, _upload, import_dir  # noqa: F401  (fixture)
from tests.test_mint_sets import SET, create
from tests.test_share import enable, make_link

pytestmark = pytest.mark.usefixtures("import_dir")

SET_COLUMNS = ("piece_count", "packaging", "has_box", "has_coa", "count_in_stack")


def _all(client) -> list[dict]:
    listed = client.get("/api/items", params={"limit": 200}).json()["items"]
    return [client.get(f"/api/items/{i['id']}").json() for i in listed]


def _sets(client) -> dict[str, dict]:
    return {i["denomination"]: i for i in _all(client) if i["type"] == "mint_set"}


def _write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------- Numista's "From set"


@pytest.mark.parametrize("builder", [samples.numista_sets_csv, samples.numista_sets_xlsx])
def test_numista_export_imports_each_set_as_one(client, tmp_path, builder):
    upload = _upload(client, builder(tmp_path / f"export.{builder.__name__[-3:]}"))
    assert upload["format"] == "numista_file"
    body = _preview(client, upload)
    assert (body["total"], body["new"], body["errors"]) == (3, 3, 0)
    # Grouped by title, not by position: the loose quarter between the proof
    # set's rows stays a coin, and each set sits where its first row was.
    rows = body["rows"]
    assert [(r["row"], r["type"], r["set_title"]) for r in rows] == [
        (1, "mint_set", samples.PROOF_SET),
        (4, "coin", None),
        (7, "mint_set", samples.SPECIMEN_SET),
    ]
    assert rows[0]["label"] == "1985 United States Proof Set"
    assert rows[0]["grade"] is None  # Numista's per-coin UNC isn't carried over
    assert any("Left for you: the issuing mint" in m for m in rows[0]["messages"])
    assert any("5 rows" in m and "5 pieces" in m for m in rows[0]["messages"])

    assert _run(client, upload)["created"] == 3
    sets = _sets(client)
    proof = sets["Proof Set"]
    assert (proof["strike"], proof["year"], proof["country"], proof["issuer"]) == (
        "proof",
        1985,
        "United States",
        None,
    )
    assert (proof["piece_count"], proof["quantity"], proof["acquisition_price"]) == (5, 1, 12)
    assert proof["currency"] == "USD" and proof["grade"] is None
    assert proof["notes"] == (
        "Contents: N#9101 1985 S, N#9102 1985 S, N#9103 1985 S, N#9104 1985 S, N#9105 1985 S\n"
        "Proof issue\nOuter box a little worn"
    )
    assert proof["catalog_refs"] == [] and proof["estimates"] == []
    specimen = sets["Specimen Set"]
    assert (specimen["strike"], specimen["country"], specimen["year"]) == (
        "specimen",
        "Canada",
        1995,
    )
    # Two copies exported as rows of 2, one row saying 3: the smallest wins.
    assert (specimen["piece_count"], specimen["quantity"]) == (3, 2)
    assert specimen["acquisition_price"] == 18  # the price was on two rows
    [coin] = [i for i in _all(client) if i["type"] == "coin"]
    assert (coin["year"], coin["mint_mark"], coin["acquisition_price"]) == (1998, "P", 0.5)

    # A second import skips both sets as duplicates, as it does the coin.
    again = _run(client, upload)
    assert (again["created"], again["skipped"]) == (0, 3)


def test_a_set_can_come_in_as_its_coins(client, tmp_path):
    upload = _upload(client, samples.numista_sets_csv(tmp_path / "export.csv"))
    body = _preview(client, upload, sets_as_coins=[samples.PROOF_SET])
    assert (body["total"], body["new"]) == (7, 7)
    from_set = [r for r in body["rows"] if r["set_title"] == samples.PROOF_SET]
    assert [r["type"] for r in from_set] == ["coin"] * 5  # the toggle still has its title
    assert {r["grade"] for r in from_set} == {"PR-60"}  # as the proof coin will print it
    assert _run(client, upload, sets_as_coins=[samples.PROOF_SET])["created"] == 7
    coins = [i for i in _all(client) if i["type"] == "coin" and i["year"] == 1985]
    assert len(coins) == 5
    for coin in coins:
        assert coin["strike"] == "proof"
        assert coin["notes"].endswith("From the set: 1985 United States Proof Set")
    assert list(_sets(client)) == ["Specimen Set"]


def test_copies_as_rows_and_a_title_with_no_year(client, tmp_path):
    header = samples.NUMISTA_SET_HEADER
    title = "Canada Specimen Set"
    row = lambda n: ["Canada", "", str(9300 + n), f"{n} Cents", "1995", "1995", "", "", "",  # noqa: E731
                     "", "1", "", "UNC", title, "", "", "", ""]  # fmt: skip
    # Two copies of a three-coin set, each coin on its own row twice.
    rows = [row(1), row(1), row(5), row(5), row(10), row(10)]
    upload = _upload(client, _write_csv(tmp_path / "export.csv", header, rows))
    body = _preview(client, upload)
    assert (body["total"], body["new"]) == (1, 1)
    _run(client, upload)
    made = _sets(client)["Specimen Set"]  # the issuer comes off the front
    assert (made["year"], made["piece_count"], made["quantity"]) == (1995, 3, 2)
    assert made["notes"] == "Contents: N#9301 1995, N#9305 1995, N#9310 1995"


# ---------------------------------------------------------------- a spreadsheet's Type


def test_spreadsheet_type_words_make_a_set_of_their_kind(client, tmp_path):
    rows = [
        ["Proof set", "United States", "Proof Set", "1999"],
        ["Mint set", "United States", "Mint Set", "2005"],
        ["Uncirculated sets", "Canada", "Uncirculated Set", "2010"],
        ["Specimen Set", "Canada", "Specimen Set", "1995"],
        ["Coin", "Canada", "1 Dollar", "1987"],
    ]
    path = _write_csv(tmp_path / "sheet.csv", ["Type", "Country", "Denomination", "Year"], rows)
    upload = _upload(client, path)
    assert upload["format"] == "spreadsheet"
    assert _run(client, upload)["created"] == 5
    got = {i["denomination"]: (i["type"], i["strike"]) for i in _all(client)}
    assert got == {
        "Proof Set": ("mint_set", "proof"),
        "Mint Set": ("mint_set", "business"),
        "Uncirculated Set": ("mint_set", "business"),
        "Specimen Set": ("mint_set", "specimen"),
        "1 Dollar": ("coin", "business"),
    }


# ---------------------------------------------------------------- Cabinet's export


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_cabinet_export_round_trips_a_set(client, tmp_path, extension):
    made = create(client, count_in_stack=True, has_coa=True, packaging="complete")
    export = tmp_path / f"cabinet-items.{extension}"
    export.write_bytes(client.get(f"/api/items/export.{extension}").content)
    client.delete(f"/api/items/{made['id']}?permanent=true")
    upload = _upload(client, export)
    assert upload["format"] == "cabinet"
    assert _run(client, upload)["created"] == 1
    [copy] = _all(client)
    for key in ("type", "strike", "issuer", "year", "denomination", *SET_COLUMNS):
        assert copy[key] == made[key], key
    assert (copy["piece_count"], copy["packaging"], copy["count_in_stack"]) == (
        6,
        "complete",
        True,
    )


def test_an_older_export_without_the_set_columns_still_imports(client, tmp_path):
    create(client, base=SET | {"type": "coin", "denomination": "1 Dollar", "issuer": None})
    raw = client.get("/api/items/export.csv").content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    header = [c for c in reader.fieldnames if c not in SET_COLUMNS]
    rows = [[r[c] for c in header] for r in reader]
    for item in _all(client):
        client.delete(f"/api/items/{item['id']}?permanent=true")
    upload = _upload(client, _write_csv(tmp_path / "old.csv", header, rows))
    assert upload["format"] == "cabinet"
    assert _run(client, upload)["created"] == 1
    [copy] = _all(client)
    assert (copy["piece_count"], copy["packaging"], copy["count_in_stack"]) == (None, None, False)


# ---------------------------------------------------------------- sharing


def test_a_shared_set_shows_what_it_is_but_not_how_it_is_counted(client, anon_client):
    enable(client)
    create(client, count_in_stack=True)
    token, _ = make_link(client)
    [item] = anon_client.get(f"/api/share/{token}/items").json()["items"]
    assert (item["type"], item["piece_count"], item["packaging"]) == ("mint_set", 6, "sealed")
    assert (item["has_box"], item["has_coa"]) == (True, False)
    assert "count_in_stack" not in item
