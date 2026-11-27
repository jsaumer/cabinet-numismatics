"""Inputs tightened before 1.0, while a stricter rule is still free: a
typed-in value can't borrow a price source's name, a search matches what was
typed, a tag is one whatever the capitals, and a Numista reference has one
written form. Each would be a breaking change after 1.0."""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from app.db import get_db
from app.main import app
from app.models import CatalogRef, Item, Tag
from app.schemas import RESERVED_SOURCES
from app.services import checklists, pricing, refs
from tests.conftest import COIN

BACKEND = Path(__file__).parents[1]


def _session():
    return next(app.dependency_overrides[get_db]())


def _create(client, **fields):
    resp = client.post("/api/items", json={**COIN, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ids(client, **params):
    resp = client.get("/api/items", params=params)
    assert resp.status_code == 200, resp.text
    return {i["id"] for i in resp.json()["items"]}


# ---------------------------------------------------------------- estimate sources


def test_the_reserved_names_are_the_price_sources():
    assert RESERVED_SOURCES == pricing.ADAPTER_NAMES


@pytest.mark.parametrize(
    "source", ["pcgs: dealer said", "numista", "Numista:N#1 XF", " MELT : by hand", "comps", "PCGS"]
)
def test_a_typed_value_cannot_use_a_price_sources_name(client, coin, source):
    resp = client.post(
        f"/api/items/{coin['id']}/estimates", json={"estimated_value": 10, "source": source}
    )
    assert resp.status_code == 422, resp.text
    assert "price sources" in resp.text
    assert client.get(f"/api/items/{coin['id']}/estimates").json() == []


@pytest.mark.parametrize(
    "source", ["PCGS price guide", "Numista catalog", "eBay sold", "manual", "melted down: scrap"]
)
def test_a_source_that_only_mentions_one_is_fine(client, coin, source):
    resp = client.post(
        f"/api/items/{coin['id']}/estimates", json={"estimated_value": 10, "source": f" {source} "}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source"] == source  # trimmed
    # And it is the owner's to delete, which a source's own value is not.
    assert (
        client.delete(f"/api/items/{coin['id']}/estimates/{resp.json()['id']}").status_code == 204
    )


def test_a_blank_source_is_refused_and_a_missing_one_is_manual(client, coin):
    base = f"/api/items/{coin['id']}/estimates"
    assert client.post(base, json={"estimated_value": 10, "source": "   "}).status_code == 422
    assert client.post(base, json={"estimated_value": 10}).json()["source"] == "manual"


# ---------------------------------------------------------------- searches match what was typed


def test_percent_and_underscore_in_a_search_are_themselves(client):
    half = _create(client, notes="bought at 50% off")
    plain = _create(client, notes="bought for 500 at a show")
    slab = _create(client, variety="MS_65 holder")
    near = _create(client, variety="MS-65 holder")
    slash = _create(client, notes="box 3\\4")

    assert _ids(client, q="50%") == {half["id"]}
    assert _ids(client, q="500") == {plain["id"]}
    assert _ids(client, q="MS_65") == {slab["id"]}
    assert _ids(client, q="ms-65") == {near["id"]}  # still any capitals
    assert _ids(client, q="3\\4") == {slash["id"]}
    assert _ids(client, q="%") == {half["id"]}
    assert _ids(client, q="_") == {slab["id"]}


def test_the_country_filter_is_the_whole_name_in_any_capitals(client):
    us = _create(client)
    _create(client, country="United Kingdom")
    assert _ids(client, country="united states") == {us["id"]}
    assert _ids(client, country="United%") == set()
    assert _ids(client, country="Unite_ States") == set()
    assert _ids(client, country="United") == set()


# ---------------------------------------------------------------- one tag, whatever the capitals


def _tags(client) -> dict[str, int]:
    return {t["name"]: t["count"] for t in client.get("/api/tags").json()}


def test_a_tag_is_one_whatever_the_capitals(client):
    first = _create(client, tags=["Silver"])
    second = _create(client, tags=["silver", "SILVER ", "key date"])
    # One tag, spelled the way it was first typed, on both pieces.
    assert _tags(client) == {"Silver": 2, "key date": 1}
    assert second["tags"] == ["Silver", "key date"]

    updated = client.patch(f"/api/items/{first['id']}", json={"tags": ["sILVER", "Key Date"]})
    assert updated.status_code == 200 and updated.json()["tags"] == ["Silver", "key date"]
    assert _tags(client) == {"Silver": 2, "key date": 2}


def test_every_tag_filter_reads_it_the_same_way(client):
    bar = {
        "type": "bullion",
        "denomination": "1 oz silver bar",
        "composition": "Silver",
        "weight_g": 31.1035,
        "fineness": 0.999,
        "year": None,
    }
    tagged = _create(client, tags=["Stack"], **bar)
    _create(client, tags=["other"], **bar)

    for spelling in ("Stack", "stack", " STACK "):
        assert _ids(client, tag=spelling) == {tagged["id"]}
        by_type = client.get("/api/stats/breakdowns", params={"tag": spelling}).json()["by_type"]
        assert [(e["key"], e["count"]) for e in by_type] == [("bullion", 1)]
        stack = client.get("/api/stack", params={"tag": spelling}).json()
        assert [i["item_id"] for i in stack["items"]] == [tagged["id"]]
    # A name that is no tag matches nothing, everywhere.
    assert _ids(client, tag="stac") == set()
    assert client.get("/api/stats/breakdowns", params={"tag": "stac"}).json()["by_type"] == []
    assert client.get("/api/stack", params={"tag": "stac"}).json()["items"] == []


def test_bulk_edit_adds_and_removes_a_tag_in_any_capitals(client):
    one, two = _create(client, tags=["Album"]), _create(client)
    ids = [one["id"], two["id"]]
    assert (
        client.post("/api/items/bulk", json={"ids": ids, "add_tags": ["album"]}).status_code == 200
    )
    assert _tags(client) == {"Album": 2}
    assert (
        client.post("/api/items/bulk", json={"ids": ids, "remove_tags": ["ALBUM"]}).status_code
        == 200
    )
    assert _tags(client) == {"Album": 0}


def test_the_database_refuses_a_second_spelling(client):
    _create(client, tags=["Silver"])
    db = _session()
    db.add(Tag(name="SILVER"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------------------------------------------------------------- one Numista reference form


@pytest.mark.parametrize(
    "typed",
    ["1234", "N#1234", "n#1234", "N# 1234", " N # 1234 ", "N-1234", "N1234", "n 1234", "N#001234"],
)
def test_a_numista_reference_is_saved_in_one_form(client, typed):
    item = _create(client, catalog_refs=[{"catalog": " Numista ", "ref_code": typed}])
    assert item["catalog_refs"] == [{"catalog": "numista", "ref_code": "N#1234"}]


@pytest.mark.parametrize("typed", ["N#12a", "see notes", "N#0", "12 34", "KM#164", "N#1234567890"])
def test_a_numista_reference_that_is_not_a_number_is_refused(client, typed):
    payload = {**COIN, "catalog_refs": [{"catalog": "numista", "ref_code": typed}]}
    resp = client.post("/api/items", json=payload)
    assert resp.status_code == 422 and refs.NUMISTA_REF_ERROR in resp.text
    made = _create(client)
    patched = client.patch(
        f"/api/items/{made['id']}", json={"catalog_refs": payload["catalog_refs"]}
    )
    assert patched.status_code == 422


def test_other_catalogs_keep_what_was_typed(client):
    typed = [
        {"catalog": "Krause", "ref_code": " KM# 164 "},
        {"catalog": "numista_set", "ref_code": "S2077"},
        {"catalog": "pcgs", "ref_code": "5790"},
    ]
    item = _create(client, catalog_refs=typed)
    assert sorted((r["catalog"], r["ref_code"]) for r in item["catalog_refs"]) == [
        ("krause", "KM# 164"),
        ("numista_set", "S2077"),
        ("pcgs", "5790"),
    ]


def test_two_spellings_of_one_reference_are_one_reference(client):
    both = [
        {"catalog": "numista", "ref_code": "1234"},
        {"catalog": "Numista", "ref_code": "N# 1234"},
    ]
    item = _create(client, catalog_refs=both)
    assert item["catalog_refs"] == [{"catalog": "numista", "ref_code": "N#1234"}]
    assert _session().query(CatalogRef).count() == 1


def test_a_hand_typed_number_is_found_wherever_a_reference_is_matched(client):
    item = _create(client, catalog_refs=[{"catalog": "numista", "ref_code": "1234"}])
    # The duplicate check, asked in any spelling.
    for asked in ("numista:1234", "Numista:N# 1234", "numista:N#1234"):
        found = client.get("/api/items/similar", params={"ref": asked}).json()
        assert [f["id"] for f in found] == [item["id"]], asked
    # Checklists and "Add a run" ask for the type as N#<id>, and by its digits.
    for asked in ("N#1234", "1234"):
        owned = checklists.owned_by_issue(_session(), catalog="numista", ref=asked)
        assert [str(i.id) for i in owned.values()] == [item["id"]]
    # And the search box still finds it by its number.
    assert _ids(client, q="N#1234") == {item["id"]}


def test_a_row_from_before_the_rule_still_reads(client):
    """Reading never validates: a stored reference the rule would refuse
    today can't turn the item, or the list holding it, into an error."""
    item = _create(client)
    db = _session()
    old = CatalogRef(catalog="numista", ref_code="see notes")
    db.add(old)
    db.flush()
    stored = db.get(Item, uuid.UUID(item["id"]))
    stored.catalog_refs.append(old)
    db.commit()

    read = client.get(f"/api/items/{item['id']}")
    assert read.status_code == 200
    assert read.json()["catalog_refs"] == [{"catalog": "numista", "ref_code": "see notes"}]
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/items/similar", params={"ref": "numista:see notes"}).json()


# ---------------------------------------------------------------- migration 0024


def _migration():
    path = next((BACKEND / "alembic" / "versions").glob("0024_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0024", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_keeps_its_own_copy_of_the_rule():
    module = _migration()
    for code in ("1234", "N# 1234", "n-1234", "N#0012", "N#0", "see notes", "", "N#12a"):
        assert module._numista_ref(code) == refs.numista_ref(code), code


def test_the_migration_merges_tags_and_references():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        for statement in (
            "CREATE TABLE tags (id INTEGER PRIMARY KEY, name VARCHAR(50) UNIQUE)",
            "CREATE TABLE item_tags (item_id CHAR(32), tag_id INTEGER, "
            "PRIMARY KEY (item_id, tag_id))",
            "CREATE TABLE catalog_refs (id INTEGER PRIMARY KEY, catalog VARCHAR(50), "
            "ref_code VARCHAR(100), UNIQUE (catalog, ref_code))",
            "CREATE TABLE item_catalog_refs (item_id CHAR(32), catalog_ref_id INTEGER, "
            "PRIMARY KEY (item_id, catalog_ref_id))",
            "INSERT INTO tags VALUES (1, 'Silver'), (2, 'key date'), (3, 'silver'), (4, 'SILVER')",
            # a has two spellings, b only a later one, c an unrelated tag
            "INSERT INTO item_tags VALUES ('a', 1), ('a', 3), ('b', 4), ('c', 2), ('b', 2)",
            "INSERT INTO catalog_refs VALUES (1, 'numista', '1234'), (2, 'numista', 'N#1234'), "
            "(3, 'numista', 'N# 77'), (4, 'numista', 'see notes'), (5, 'krause', '1234'), "
            "(6, 'numista', 'n-77'), (7, 'numista', 'N#5')",
            "INSERT INTO item_catalog_refs VALUES ('a', 1), ('a', 2), ('b', 1), ('c', 3), "
            "('d', 6), ('d', 4), ('e', 5), ('e', 7)",
        ):
            conn.execute(sa.text(statement))
        module = _migration()
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        def rows(sql):
            return [tuple(r) for r in conn.execute(sa.text(sql))]

        # The first spelling stays, every item keeps the tag once.
        assert rows("SELECT id, name FROM tags ORDER BY id") == [(1, "Silver"), (2, "key date")]
        assert rows("SELECT item_id, tag_id FROM item_tags ORDER BY 1, 2") == [
            ("a", 1),
            ("b", 1),
            ("b", 2),
            ("c", 2),
        ]
        # 1234 joins the row already written N#1234; "N# 77" is rewritten in
        # place and "n-77" joins it; the rest are untouched.
        assert rows("SELECT id, catalog, ref_code FROM catalog_refs ORDER BY id") == [
            (2, "numista", "N#1234"),
            (3, "numista", "N#77"),
            (4, "numista", "see notes"),
            (5, "krause", "1234"),
            (7, "numista", "N#5"),
        ]
        assert rows("SELECT item_id, catalog_ref_id FROM item_catalog_refs ORDER BY 1, 2") == [
            ("a", 2),
            ("b", 2),
            ("c", 3),
            ("d", 3),
            ("d", 4),
            ("e", 5),
            ("e", 7),
        ]
        with pytest.raises(IntegrityError):
            conn.execute(sa.text("INSERT INTO tags VALUES (9, 'KEY DATE')"))
