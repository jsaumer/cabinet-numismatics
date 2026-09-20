"""v0.25.0: population, wish-list targets, paper money depth, fancy serials,
the die axis, and dates as struck."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.models import PriceEstimate
from app.services import calendars, serials
from tests.conftest import COIN
from tests.test_imports import _items, _preview, _run, _upload
from tests.test_monitoring import posted, save_hook  # noqa: F401 (fixture)
from tests.test_numista import _session
from tests.test_pcgs import (  # noqa: F401
    CERT_FACTS,
    by_cert,
    by_number,
    configure,
    estimate,
    upstream,
)

NOTE = {
    "type": "note",
    "country": "United States",
    "denomination": "1 dollar",
    "year": 1957,
    "series": "Series 1957 Silver Certificate",
    "signatures": "Priest / Anderson",
    "serial_number": "A12344321B",
    "currency": "USD",
}


def create(client, base=COIN, **fields):
    resp = client.post("/api/items", json={**base, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def patch(client, item, **fields):
    return client.patch(f"/api/items/{item['id']}", json=fields)


def listed(client, **params):
    resp = client.get("/api/items", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def add_value(client, item, value, currency="USD", days_ago=0):
    resp = client.post(
        f"/api/items/{item['id']}/estimates",
        json={"estimated_value": value, "currency": currency},
    )
    assert resp.status_code == 201, resp.text
    if days_ago:  # SQLite keeps whole seconds, so order is made explicit
        db = _session()
        row = db.get(PriceEstimate, uuid.UUID(resp.json()["id"]))
        row.fetched_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        db.commit()
        db.close()
    return resp.json()


# --- P5: fancy serial numbers -------------------------------------------------


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("77777777", ["solid"]),
        ("A 7777 7777 B", ["solid"]),  # letters and spaces don't count
        ("12345678", ["ladder"]),
        ("87654321", ["ladder"]),
        ("01234567", ["ladder"]),
        ("12345679", []),
        ("12344321", ["radar"]),
        ("12344322", []),
        ("10000001", ["super_radar", "binary"]),  # never also a plain radar
        ("12341234", ["repeater"]),
        ("12341235", []),
        ("12121212", ["super_repeater", "binary"]),  # never also a plain repeater
        ("38383838", ["super_repeater", "binary"]),
        ("11010011", ["binary"]),
        ("110100", ["binary"]),
        ("1101", []),  # too short to be a binary
        ("12312213", ["trinary"]),
        ("1231221", []),  # trinary is for eight digits
        ("00000042", ["trinary", "low"]),
        ("00000100", ["binary", "low"]),
        ("00000101", ["binary"]),
        ("00000000", ["solid"]),  # zero is not a low number
        ("000042", ["low"]),  # three digits, but not eight long
        ("00042", []),  # too narrow
        ("99999912", ["trinary", "high"]),
        ("99999899", ["binary"]),
        ("11112222", ["binary", "double_quad"]),
        ("11112223", ["trinary"]),
        ("07041776", ["date"]),  # MMDDYYYY
        ("19450508", ["date"]),  # YYYYMMDD
        ("13451599", []),  # no such month either way
        ("02301999", []),  # 30 February
        ("123", []),
        ("", []),
        (None, []),
    ],
)
def test_serial_traits(serial, expected):
    assert serials.traits(serial) == expected


def test_a_solid_is_nothing_else():
    assert serials.traits("77777777") == ["solid"]  # not a radar, repeater, or double quad


def test_star_notes():
    assert serials.traits("A1290567*") == ["star"]
    assert serials.traits("★ 12344321") == ["radar", "star"]
    assert serials.traits("A1290567B", replacement=True) == ["star"]
    assert serials.traits(None, replacement=True) == ["star"]
    assert serials.traits("A1290567B") == []


def test_traits_come_in_reference_order_and_round_trip_through_storage():
    found = serials.traits("*10000001")
    assert found == ["super_radar", "binary", "star"]
    assert serials.encode(found) == ",super_radar,binary,star,"
    assert serials.decode(",super_radar,binary,star,") == found
    assert serials.encode([]) is None and serials.decode(None) == []


def test_serial_traits_reference(client):
    body = client.get("/api/reference/serial-traits").json()
    assert [t["key"] for t in body] == list(serials.TRAITS)
    radar = next(t for t in body if t["key"] == "radar")
    assert radar == {"key": "radar", "label": "Radar", "description": "Reads the same backwards"}
    assert all(chr(0x2014) not in t["description"] for t in body)


def test_serial_traits_are_server_set_and_follow_the_serial(client):
    note = create(client, NOTE, serial_traits=["solid"], population_as_of="2001-01-01T00:00:00Z")
    assert note["serial_traits"] == ["radar"]  # the client's list is ignored
    assert note["population_as_of"] is None
    assert create(client)["serial_traits"] == []  # always a list

    body = patch(client, note, serial_number="B12121212A", serial_traits=["date"]).json()
    assert body["serial_traits"] == ["super_repeater", "binary"]
    assert patch(client, note, replacement_note=True).json()["serial_traits"] == [
        "super_repeater",
        "binary",
        "star",
    ]
    assert (
        patch(client, note, serial_number=None, replacement_note=False).json()["serial_traits"]
        == []
    )
    detail = client.get(f"/api/items/{note['id']}").json()
    assert detail["serial_traits"] == []


def test_fancy_filters(client):
    radar = create(client, NOTE)
    solid = create(client, NOTE, serial_number="C77777777D")
    plain = create(client, NOTE, serial_number="C12905673D")
    create(client)

    assert {i["id"] for i in listed(client, fancy="true")} == {radar["id"], solid["id"]}
    assert [i["id"] for i in listed(client, serial_trait="radar")] == [radar["id"]]
    assert [i["serial_traits"] for i in listed(client, serial_trait="solid")] == [["solid"]]
    assert listed(client, serial_trait="super_radar") == []  # "radar" is not "super_radar"
    assert client.get("/api/items", params={"serial_trait": "shiny"}).status_code == 422
    row = next(i for i in listed(client) if i["id"] == plain["id"])
    assert row["serial_traits"] == []


# --- P6: die axis and dates as struck -------------------------------------------


def test_calendar_conversions():
    assert calendars.to_gregorian("hijri", 1340) == 1921
    assert calendars.to_gregorian("japanese", 39, "showa") == 1964
    assert calendars.to_gregorian("thai_buddhist", 2500) == 1957
    assert calendars.to_gregorian("solar_hijri", 1350) == 1971
    assert calendars.to_gregorian("hebrew", 5708) == 1948
    assert calendars.to_gregorian("vikram_samvat", 2000) == 1943
    assert calendars.to_gregorian("saka", 1900) == 1978
    assert calendars.to_gregorian("minguo", 3) == 1914
    assert calendars.to_gregorian("chula_sakarat", 1238) == 1876
    assert calendars.to_gregorian("rattanakosin", 127) == 1908
    assert calendars.to_gregorian("ethiopian", 1936) == 1944
    assert calendars.to_gregorian("japanese", 1, "reiwa") == 2019
    with pytest.raises(ValueError):
        calendars.to_gregorian("japanese", 39)
    with pytest.raises(ValueError):
        calendars.to_gregorian("japanese", 39, "edo")
    with pytest.raises(ValueError):
        calendars.to_gregorian("hijri", 1340, "showa")
    with pytest.raises(ValueError):
        calendars.to_gregorian("mayan", 12)


def test_calendar_reference_and_conversion_endpoints(client):
    body = client.get("/api/reference/calendars").json()
    assert {"key": "hijri", "label": "Islamic (AH)"} in body["calendars"]
    assert [c["key"] for c in body["calendars"]] == list(calendars.CALENDARS)
    assert {"key": "showa", "label": "Showa", "offset": 1925} in body["eras"]
    # the item page reads the abbreviation out of the label
    labels = {c["key"]: c["label"] for c in body["calendars"]}
    assert labels["thai_buddhist"].endswith("(BE)") and labels["solar_hijri"].endswith("(SH)")

    convert = lambda **params: client.get("/api/reference/convert-date", params=params)  # noqa: E731
    assert convert(calendar="hijri", year=1340).json() == {
        "calendar": "hijri",
        "year": 1340,
        "era": None,
        "gregorian_year": 1921,
    }
    assert convert(calendar="japanese", year=39, era="showa").json()["gregorian_year"] == 1964
    assert convert(calendar="thai_buddhist", year=2500).json()["gregorian_year"] == 1957
    assert convert(calendar="japanese", year=39).status_code == 422
    assert convert(calendar="mayan", year=39).status_code == 422
    assert convert(calendar="hijri", year=0).status_code == 422
    assert convert(calendar="hijri").status_code == 422


def test_year_is_filled_from_the_date_as_struck(client):
    base = {k: v for k, v in COIN.items() if k != "year"}
    coin = create(client, base, year=None, struck_calendar="hijri", struck_year=1340)
    assert (coin["year"], coin["struck_calendar"], coin["struck_year"]) == (1921, "hijri", 1340)
    assert create(client, base, struck_calendar="thai_buddhist", struck_year=2500)["year"] == 1957
    yen = create(client, base, struck_calendar="japanese", struck_year=39, struck_era="showa")
    assert (yen["year"], yen["struck_era"]) == (1964, "showa")
    # a year that is given stands
    assert create(client, struck_calendar="hijri", struck_year=1340, year=1922)["year"] == 1922
    # and without a date as struck the year is as required as ever
    assert client.post("/api/items", json=base).status_code == 422
    assert client.post("/api/items", json={**base, "year": None}).status_code == 422
    assert client.post("/api/items", json={**base, "struck_year": 1340}).status_code == 422


def test_struck_date_validation(client):
    bad = lambda **fields: client.post("/api/items", json={**COIN, **fields}).status_code  # noqa: E731
    assert bad(struck_calendar="mayan", struck_year=12) == 422
    assert bad(struck_calendar="japanese", struck_year=39) == 422  # no era
    assert bad(struck_calendar="japanese", struck_year=39, struck_era="edo") == 422
    assert bad(struck_calendar="hijri", struck_year=1340, struck_era="showa") == 422
    assert bad(struck_era="showa") == 422
    assert bad(struck_calendar="hijri", struck_year=0) == 422
    assert bad(struck_calendar="hijri", struck_year=10000) == 422
    assert bad(die_axis=360) == 422 and bad(die_axis=-1) == 422
    assert bad(struck_calendar="hijri", struck_year=1340, struck_era=None) == 201


def test_struck_date_on_update(client, coin):
    body = patch(client, coin, struck_calendar="hijri", struck_year=1340, struck_era=None)
    assert body.status_code == 200, body.text
    assert body.json()["year"] == 1932  # the year it had is left alone
    assert patch(client, coin, year=None).json()["year"] == 1921  # asked for: converted
    assert patch(client, coin, struck_calendar="japanese").status_code == 422  # needs its era
    body = patch(client, coin, struck_calendar="japanese", struck_year=39, struck_era="showa")
    assert body.json()["struck_era"] == "showa" and body.json()["year"] == 1921
    assert patch(client, coin, struck_calendar="hijri").status_code == 422  # era left behind
    cleared = patch(client, coin, struck_calendar=None, struck_year=None, struck_era=None).json()
    assert cleared["struck_calendar"] is None
    assert patch(client, coin, year=None).status_code == 422  # nothing to convert from

    history = client.get(f"/api/items/{coin['id']}/history").json()
    assert history[-2]["changes"]["struck_year"] == [None, 1340]  # edits are recorded as usual


def test_die_axis(client, coin):
    assert coin["die_axis"] is None
    assert patch(client, coin, die_axis=180).json()["die_axis"] == 180
    assert patch(client, coin, die_axis=0).json()["die_axis"] == 0
    assert patch(client, coin, die_axis=400).status_code == 422


# --- P4: paper money depth --------------------------------------------------------

NATIONAL = {
    **NOTE,
    "denomination": "10 dollars",
    "year": 1902,
    "series": "Series 1902 Plain Back",
    "signatures": "Lyons / Roberts",
    "serial_number": "A541263",
    "issuer": "The First National Bank of Cooperstown",
    "charter_number": " 280 ",
    "bank_city": "Cooperstown",
    "bank_state": "New York",
    "plate_position": "B",
}


def test_national_bank_note_fields(client):
    note = create(client, NATIONAL)
    assert note["charter_number"] == "280"  # trimmed
    assert (note["bank_city"], note["bank_state"], note["plate_position"]) == (
        "Cooperstown",
        "New York",
        "B",
    )
    assert create(client, NOTE, bank_city="   ")["bank_city"] is None
    assert patch(client, note, bank_city=" Albany ").json()["bank_city"] == "Albany"
    for field, limit in (
        ("charter_number", 10),
        ("bank_city", 100),
        ("bank_state", 50),
        ("plate_position", 20),
    ):
        assert client.post("/api/items", json={**NOTE, field: "x" * (limit + 1)}).status_code == 422

    create(client, NOTE)
    for q in ("cooperstown", "280", "first national"):
        assert [i["id"] for i in listed(client, q=q)] == [note["id"]], q


def test_notes_by_signature(client):
    assert client.get("/api/stats/notes-by-signature").json() == {"groups": [], "total": 0}
    late = create(client, NOTE, serial_number="B20000000A", quantity=2)
    early = create(client, NOTE, serial_number="A10000000A")
    other = create(client, NOTE, signatures="Smith / Dillon")
    loose = create(client, NOTE, series=None, signatures=None, serial_number=None)
    create(client, NOTE, status="wishlist")
    create(client, NOTE, status="sold")
    create(client)  # a coin
    trashed = create(client, NOTE, serial_number="Z99999999Z")
    client.delete(f"/api/items/{trashed['id']}")

    body = client.get("/api/stats/notes-by-signature").json()
    assert body["total"] == 4
    assert [(g["series"], g["signatures"], g["count"], g["quantity"]) for g in body["groups"]] == [
        (NOTE["series"], "Priest / Anderson", 2, 3),
        (NOTE["series"], "Smith / Dillon", 1, 1),
        (None, None, 1, 1),
    ]
    first = body["groups"][0]["items"]
    assert [n["id"] for n in first] == [early["id"], late["id"]]  # by serial number
    assert first[0] == {
        "id": early["id"],
        "label": "United States 1 dollar 1957",
        "serial_number": "A10000000A",
        "grade_label": None,
    }
    assert body["groups"][1]["items"][0]["id"] == other["id"]
    assert body["groups"][2]["items"][0]["id"] == loose["id"]


# --- P3: wish-list depth ------------------------------------------------------------

WANTED = {**COIN, "status": "wishlist", "target_price": 1000, "priority": 1}


def test_target_and_priority_validation(client):
    wanted = create(client, WANTED)
    assert (wanted["target_price"], wanted["priority"]) == (1000.0, 1)
    assert (wanted["target_gap"], wanted["target_reached"]) == (None, False)
    # the form sends both for any status
    owned = create(client, target_price=50, priority=3)
    assert (owned["status"], owned["target_price"], owned["priority"]) == ("owned", 50.0, 3)
    assert create(client, target_price=None, priority=None)["priority"] is None
    for fields in ({"target_price": 0}, {"target_price": -5}, {"priority": 0}, {"priority": 4}):
        assert client.post("/api/items", json={**COIN, **fields}).status_code == 422, fields
        assert patch(client, wanted, **fields).status_code == 422, fields
    assert patch(client, wanted, priority=None, target_price=None).json()["priority"] is None


def test_target_gap(client):
    wanted = create(client, WANTED)
    add_value(client, wanted, 1120, days_ago=2)
    detail = client.get(f"/api/items/{wanted['id']}").json()
    assert (detail["target_gap"], detail["target_reached"]) == (120.0, False)

    add_value(client, wanted, 950, days_ago=1)
    [row] = listed(client, status="wishlist")
    assert (row["target_price"], row["priority"]) == (1000.0, 1)
    assert row["target_gap"] == -50.0 and row["target_reached"] is True
    assert isinstance(row["target_gap"], float) and isinstance(row["priority"], int)

    add_value(client, wanted, 1000)  # at the target counts
    assert client.get(f"/api/items/{wanted['id']}").json()["target_reached"] is True

    # nothing is converted: another currency gives no gap
    euro = create(client, WANTED, currency="EUR")
    add_value(client, euro, 10, currency="USD")
    body = client.get(f"/api/items/{euro['id']}").json()
    assert (body["target_gap"], body["target_reached"]) == (None, False)


def test_target_reached_filter_and_the_new_sorts(client):
    low = create(client, WANTED, denomination="low", target_price=100, priority=3)
    high = create(client, WANTED, denomination="high", target_price=900, priority=1)
    none = create(client, denomination="none")
    euro = create(client, WANTED, denomination="euro", currency="EUR", target_price=500, priority=2)
    add_value(client, low, 90)
    add_value(client, high, 80, days_ago=3)
    add_value(client, high, 950)  # the newest counts, and it is over
    add_value(client, euro, 10, currency="USD")  # under, but not in the item's currency
    add_value(client, none, 1)

    assert [i["id"] for i in listed(client, target_reached="true")] == [low["id"]]

    order = lambda sort: [i["denomination"] for i in listed(client, sort=sort)]  # noqa: E731
    assert order("priority") == ["high", "euro", "low", "none"]
    assert order("-priority") == ["low", "euro", "high", "none"]  # empty last both ways
    assert order("target_price") == ["low", "euro", "high", "none"]
    assert order("-target_price") == ["high", "euro", "low", "none"]


def test_target_alert_fires_once_on_crossing(client, posted):  # noqa: F811
    save_hook(client)
    wanted = create(client, WANTED, country="United States", denomination="1 cent", year=1909)
    add_value(client, wanted, 1200, days_ago=3)
    assert posted == []
    add_value(client, wanted, 950, days_ago=2)
    assert len(posted) == 1
    sent = posted[0]["json"]
    assert sent["title"] == "Cabinet: Wish-list target reached"
    assert sent["status"] == "event" and sent["alert"] == "wishlist_target"
    assert sent["message"] == (
        'United States 1 cent 1909 "D": estimate $950.00 is at or under your $1,000.00 target'
    )
    add_value(client, wanted, 940, days_ago=1)  # still under: no second alert
    assert len(posted) == 1
    assert client.get("/api/settings").json().get("alert_state") in (None, {})  # not a condition

    # over and back under is a new crossing
    add_value(client, wanted, 1500, days_ago=0.5)
    add_value(client, wanted, 1000)
    assert len(posted) == 2


def test_target_alert_only_for_the_wish_list_and_the_same_currency(client, posted):  # noqa: F811
    save_hook(client)
    add_value(client, create(client, target_price=1000), 5)  # owned
    add_value(client, create(client, status="wishlist"), 5)  # no target
    add_value(client, create(client, WANTED), 5, currency="EUR")  # not the item's currency
    assert posted == []
    # a first estimate already under the target is a crossing
    add_value(client, create(client, WANTED), 5)
    assert len(posted) == 1


def test_target_alert_without_a_webhook_is_silent(client, posted):  # noqa: F811
    add_value(client, create(client, WANTED), 5)
    assert posted == []


@pytest.mark.parametrize("fmt", ["ntfy", "discord", "slack", "gotify"])
def test_target_alert_in_each_format(client, posted, fmt):  # noqa: F811
    save_hook(client, fmt)
    add_value(client, create(client, WANTED), 5)
    [sent] = posted
    text = str(sent.get("json") or sent.get("headers"))
    assert "Wish-list target reached" in text


def test_target_alert_from_an_automatic_estimate(client, posted, upstream):  # noqa: F811
    configure(client)
    save_hook(client)
    wanted = by_number(client, status="wishlist", target_price=500)
    assert estimate(client, wanted).status_code == 201  # 480 from three sales
    assert len(posted) == 1 and "$480.00" in posted[0]["json"]["message"]


# --- P1: population -------------------------------------------------------------------


def test_population_is_dated_by_the_server(client, coin):
    assert coin["pcgs_population"] is None and coin["population_as_of"] is None
    body = patch(
        client, coin, pcgs_population=3, pcgs_pop_higher=0, population_as_of="2001-01-01T00:00:00Z"
    ).json()
    assert (body["pcgs_population"], body["pcgs_pop_higher"]) == (3, 0)
    stamped = datetime.fromisoformat(body["population_as_of"].replace("Z", "+00:00"))
    assert stamped.year >= 2026  # the server's clock, not the client's

    # an edit elsewhere leaves the date alone
    db = _session()
    from app.models import Item

    row = db.get(Item, uuid.UUID(coin["id"]))
    row.population_as_of = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()
    assert patch(client, coin, notes="x").json()["population_as_of"].startswith("2020-01-01")
    assert patch(client, coin, pcgs_population=3).json()["population_as_of"].startswith("2020")
    assert not patch(client, coin, pcgs_population=4).json()["population_as_of"].startswith("2020")
    cleared = patch(client, coin, pcgs_population=None, pcgs_pop_higher=None).json()
    assert cleared["population_as_of"] is None

    made = create(client, pcgs_pop_higher=0)
    assert made["population_as_of"] is not None
    assert client.post("/api/items", json={**COIN, "pcgs_population": -1}).status_code == 422


def test_pcgs_estimate_stores_the_population(client, upstream):  # noqa: F811
    configure(client)
    upstream.body = {**CERT_FACTS, "PopHigher": 0}
    item = by_cert(client)
    body = estimate(client, item).json()
    assert (body["details"]["population"], body["details"]["pop_higher"]) == (812, 0)
    item = client.get(f"/api/items/{item['id']}").json()
    assert (item["pcgs_population"], item["pcgs_pop_higher"]) == (812, 0)
    assert item["population_as_of"] is not None


def test_pcgs_estimate_without_a_population_leaves_the_item_alone(client, upstream):  # noqa: F811
    configure(client)
    item = by_number(client, pcgs_population=7)
    body = estimate(client, item).json()
    assert body["details"]["population"] is None
    assert client.get(f"/api/items/{item['id']}").json()["pcgs_population"] == 7


def test_cert_fill_carries_the_population(client, upstream):  # noqa: F811
    configure(client)
    upstream.body = {**CERT_FACTS, "Population": 3, "PopHigher": 0}
    body = client.get("/api/pcgs/cert/12345678").json()
    assert body["fields"]["pcgs_population"] == 3
    assert body["fields"]["pcgs_pop_higher"] == 0  # none higher is worth saying
    assert (body["population"], body["pop_higher"]) == (3, 0)
    upstream.body = {k: v for k, v in CERT_FACTS.items() if k not in ("Population", "PopHigher")}
    body = client.get("/api/pcgs/cert/87654321").json()
    assert "pcgs_population" not in body["fields"] and body["population"] is None


# --- shared: export and import, clone, bulk edit -----------------------------------------

ROUND_TRIP = (
    "target_price", "priority", "charter_number", "bank_city", "bank_state", "plate_position",
    "die_axis", "struck_calendar", "struck_year", "struck_era", "pcgs_population",
    "pcgs_pop_higher", "serial_number", "serial_traits",
)  # fmt: skip


@pytest.fixture()
def import_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path / "imports"))
    get_settings.cache_clear()


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_export_and_reimport_carry_the_new_fields(client, tmp_path, import_dir, extension):
    note = create(
        client, NATIONAL, status="wishlist", target_price=1250.5, priority=2,
        serial_number="A12344321",
    )  # fmt: skip
    coin = create(
        client, denomination="1 yen", country="Japan", die_axis=0, struck_calendar="japanese",
        struck_year=39, struck_era="showa", year=1964, pcgs_population=3, pcgs_pop_higher=0,
    )  # fmt: skip
    export = tmp_path / f"cabinet-items.{extension}"
    export.write_bytes(client.get(f"/api/items/export.{extension}").content)
    for item in (note, coin):
        client.delete(f"/api/items/{item['id']}?permanent=true")

    upload = _upload(client, export)
    assert upload["format"] == "cabinet"
    assert _preview(client, upload)["errors"] == 0
    assert _run(client, upload)["created"] == 2
    copies = _items(client)
    for original in (note, coin):
        copy = copies[f"{original['country']} {original['denomination']} {original['year']}"]
        for key in ROUND_TRIP:
            assert copy[key] == original[key], key
    assert copies["Japan 1 yen 1964"]["population_as_of"] is not None


def test_old_csv_import_reads_the_new_columns(client):
    create(client, WANTED, die_axis=180)
    raw = client.get("/api/items/export.csv").content
    for item in listed(client):
        client.delete(f"/api/items/{item['id']}?permanent=true")
    resp = client.post("/api/items/import", files={"file": ("items.csv", raw, "text/csv")})
    assert resp.json()["created"] == 1, resp.text
    [copy] = listed(client)
    assert (copy["target_price"], copy["priority"], copy["die_axis"]) == (1000.0, 1, 180)


def test_clone_copies_the_new_fields(client):
    note = create(
        client, NATIONAL, serial_number="A12344321", target_price=40, priority=2, die_axis=90,
        struck_calendar="hijri", struck_year=1340, pcgs_population=5,
    )  # fmt: skip
    db = _session()
    from app.models import Item

    db.get(Item, uuid.UUID(note["id"])).population_as_of = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    db.close()
    copy = client.post(f"/api/items/{note['id']}/clone").json()
    for key in (*ROUND_TRIP, "issuer"):
        assert copy[key] == note[key], key
    assert copy["serial_traits"] == ["radar"]
    assert not copy["population_as_of"].startswith("2020")  # dated afresh


def test_bulk_edit_sets_priority(client):
    a, b = create(client, WANTED, priority=None), create(client, WANTED, priority=3)
    ids = [a["id"], b["id"]]
    resp = client.post("/api/items/bulk", json={"ids": ids, "set": {"priority": 2}})
    assert resp.status_code == 200 and resp.json() == {"updated": 2}
    assert {i["priority"] for i in listed(client)} == {2}
    assert (
        client.post("/api/items/bulk", json={"ids": ids, "set": {"priority": 9}}).status_code == 422
    )
    client.post("/api/items/bulk", json={"ids": ids, "set": {"priority": None}})
    assert {i["priority"] for i in listed(client)} == {None}
    history = client.get(f"/api/items/{a['id']}/history").json()
    assert history[0]["changes"] == {"bulk": [None, True], "priority": [None, None]}


def test_bulk_edit_keeps_serial_traits_in_step(client):
    note = create(client, NOTE, serial_number="A1290567B")
    client.post("/api/items/bulk", json={"ids": [note["id"]], "set": {"replacement_note": True}})
    assert client.get(f"/api/items/{note['id']}").json()["serial_traits"] == ["star"]
