"""The share view (v0.32.0, SPEC_0320 stages 1 and 4): public read-only
links, the switch, the allowlist, the one 404, the throttle, and the admin
routes."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth import common, gate, throttle
from app.db import Base, get_db
from app.main import app
from app.models import ExchangeRate, ShareLink
from app.models.auth import AuditEntry, AuthBase
from app.services import alerts, currency, share
from tests.conftest import COIN, image_bytes
from tests.test_documents import pdf_bytes

NOT_FOUND = {"detail": "Not found"}
BASE_KEYS = {
    "id",
    "type",
    "country",
    "denomination",
    "year_label",
    "mint_mark",
    "series",
    "variety",
    "composition",
    "weight_g",
    "fineness",
    "diameter_mm",
    "width_mm",
    "height_mm",
    "shape",
    "issuer",
    "quantity",
}
GRADE_KEYS = {
    "grade_label",
    "grade_details",
    "designations",
    "cac_sticker",
    "cert_service",
}
ALL_OFF = dict.fromkeys(share.OPTIONS, False)
ALL_ON = dict.fromkeys(share.OPTIONS, True)
# What a share must never carry, whatever the toggles say.
PRIVATE = {
    "acquisition_price": 987.65,
    "acquisition_fees": 12.34,
    "acquired_from": "Private Dealer Ltd",
    "storage_location": "Safe deposit box 42",
    "serial_number": "SN-SECRET-7",
    "custom_fields": {"insurer": "Hidden Mutual"},
    "target_price": 555.55,
    "spot_at_purchase": 31.31,
    "printer": "Printer Hidden",
}


@pytest.fixture(autouse=True)
def no_fetches(monkeypatch):
    """A public route never makes a network call; alerts are recorded."""

    def boom(*args, **kwargs):
        raise AssertionError("a share route fetched something")

    monkeypatch.setattr(currency, "fetch_rate", boom)


@pytest.fixture()
def sent(monkeypatch):
    found = []
    monkeypatch.setattr(alerts, "event", lambda db, key, title, message: found.append(
        (key, title, message)))  # fmt: skip
    return found


def db_session():
    return next(app.dependency_overrides[get_db]())


def enable(client, on: bool = True):
    resp = client.put("/api/settings", json={"share_enabled": on})
    assert resp.status_code == 200 and resp.json()["share_enabled"] is on


def make_item(client, **overrides) -> dict:
    resp = client.post("/api/items", json={**COIN, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_link(client, **body) -> tuple[str, dict]:
    resp = client.post("/api/share-links", json={"kind": "collection", "name": "Show", **body})
    assert resp.status_code == 201, resp.text
    created = resp.json()
    return created["url"].rsplit("/", 1)[1], created


def grade_id(client, code="MS-64"):
    return next(g["id"] for g in client.get("/api/grades").json() if g["code"] == code)


def full_item(client) -> dict:
    """Every field filled, with a photo, tags, notes, a cert, an estimate, a
    cost, a storage location, custom fields, a serial, and a document."""
    item = make_item(
        client,
        **PRIVATE,
        variety="Doubled die",
        composition="Silver 90%, Copper 10%",
        weight_g=6.25,
        fineness=0.9,
        diameter_mm=24.3,
        width_mm=24.3,
        height_mm=24.3,
        shape="Round",
        issuer="US Mint",
        grade_id=grade_id(client),
        designations=["RD"],
        cac_sticker="green",
        cert_service="PCGS",
        cert_number="12345678",
        grade_details="Cleaned",
        notes="Bought at the spring show",
        tags=["key date"],
    )
    photo = client.post(f"/api/items/{item['id']}/photos", files={"file": ("a.png", image_bytes())})
    assert photo.status_code == 201
    estimate = client.post(
        f"/api/items/{item['id']}/estimates", json={"estimated_value": 250, "currency": "USD"}
    )
    assert estimate.status_code == 201
    doc = client.post(
        f"/api/items/{item['id']}/documents",
        files={"file": ("receipt.pdf", pdf_bytes(1))},
        data={"title": "Dealer invoice"},
    )
    assert doc.status_code == 201, doc.text
    return {**item, "photo_id": photo.json()["id"]}


# --- the allowlist -------------------------------------------------------------------


def test_the_item_view_is_exactly_the_allowlist(client, anon_client):
    enable(client)
    full_item(client)
    token, link = make_link(client, **ALL_OFF)
    item = anon_client.get(f"/api/share/{token}/items").json()["items"][0]
    assert set(item) == BASE_KEYS
    client.patch(f"/api/share-links/{link['id']}", json=ALL_ON)
    item = anon_client.get(f"/api/share/{token}/items").json()["items"][0]
    everything = {"photos", "tags", "notes", "value", "cert_number"}
    assert set(item) == BASE_KEYS | GRADE_KEYS | everything
    assert item["value"] == {"amount": 250.0, "currency": "USD"}
    assert item["cert_number"] == "12345678" and item["cert_service"] == "PCGS"
    assert item["tags"] == ["key date"] and item["notes"] == "Bought at the spring show"
    assert set(item["photos"][0]) == {"id", "angle", "has_thumbnail"}
    assert item["weight_g"] == 6.25 and item["fineness"] == 0.9  # JSON numbers
    assert item["grade_label"].startswith("MS-64 RD")
    text = json.dumps(item)
    for secret in ("987.65", "12.34", "Private Dealer", "Safe deposit", "SN-SECRET", "Hidden",
                   "555.55", "31.31", "Dealer invoice", "receipt"):  # fmt: skip
        assert secret not in text, secret


@pytest.mark.parametrize(
    "option, keys",
    [
        ("show_photos", {"photos"}),
        ("show_grades", GRADE_KEYS),
        ("show_tags", {"tags"}),
        ("show_notes", {"notes"}),
        ("show_values", {"value"}),
        ("show_certs", {"cert_number"}),
    ],
)
def test_each_toggle_adds_only_its_own_keys(client, anon_client, option, keys):
    enable(client)
    item = full_item(client)
    token, _ = make_link(client, **{**ALL_OFF, option: True})
    assert set(anon_client.get(f"/api/share/{token}/items/{item['id']}").json()) == (
        BASE_KEYS | keys
    )


def test_value_is_null_when_it_cannot_be_converted_from_the_cache(client, anon_client):
    enable(client)
    item = make_item(client)
    client.post(
        f"/api/items/{item['id']}/estimates", json={"estimated_value": 80, "currency": "EUR"}
    )
    bare = make_item(client, country="Canada")
    token, _ = make_link(client, show_values=True)
    view = anon_client.get(f"/api/share/{token}/items/{item['id']}").json()
    assert view["value"] is None  # no cached rate, and nothing is fetched
    assert anon_client.get(f"/api/share/{token}/items/{bare['id']}").json()["value"] is None
    db = db_session()
    try:
        old = datetime.now(timezone.utc) - timedelta(days=30)
        db.add(ExchangeRate(base="EUR", quote="USD", rate=2, source="test", fetched_at=old))
        db.commit()
    finally:
        db.close()
    view = anon_client.get(f"/api/share/{token}/items/{item['id']}").json()
    assert view["value"] == {"amount": 160.0, "currency": "USD"}  # a stale cache still serves


# --- the switch and the one 404 -------------------------------------------------------


def public_paths(token: str, item_id: str = "x", photo_id: str = "x") -> list[str]:
    return [
        f"/api/share/{token}",
        f"/api/share/{token}/items",
        f"/api/share/{token}/items/{item_id}",
        f"/api/share/{token}/checklist",
        f"/api/share/{token}/photos/{photo_id}/thumb",
    ]


def assert_not_found(resp):
    assert resp.status_code == 404
    assert resp.json() == NOT_FOUND
    assert resp.headers["x-robots-tag"] == "noindex, nofollow"
    assert resp.headers["cache-control"] == "no-store"


def test_switched_off_a_stranger_gets_the_gates_401(client, anon_client):
    """Off, the gate has no share rule at all: a stranger is refused like on
    any other path (v0.31.0 looked the same), and the signed-in admin, who
    gets past the gate, finds nothing."""
    enable(client)
    item = full_item(client)
    token, link = make_link(client)
    assert anon_client.get(f"/api/share/{token}/items").status_code == 200
    enable(client, False)
    paths = public_paths(token, item["id"], item["photo_id"])
    for path in paths:
        resp = anon_client.get(path)
        assert resp.status_code == 401 and resp.json() == {"detail": "Sign in to continue."}
    assert throttle.share_size() == 0  # nothing anonymous reached the share throttle
    for path in paths:
        assert_not_found(client.get(path))
    resp = client.post("/api/share-links", json={"kind": "collection", "name": "Again"})
    assert resp.status_code == 409 and resp.json()["detail"] == share.SWITCHED_OFF
    assert client.post(f"/api/share-links/{link['id']}/regenerate").status_code == 409
    assert len(client.get("/api/share-links").json()) == 1  # kept
    enable(client)
    assert anon_client.get(f"/api/share/{token}/items").status_code == 200  # works again


def test_wrong_unknown_and_revoked_tokens_look_the_same(client, anon_client):
    enable(client)
    token, link = make_link(client)
    assert client.delete(f"/api/share-links/{link['id']}").status_code == 204
    for n, bad in enumerate(("abc", "share_short", share.new_token(), token, token + "x")):
        for path in public_paths(bad):  # an address each, to stay under the throttle
            assert_not_found(anon_client.get(path, headers={"X-Real-IP": f"192.0.2.{n}"}))


@pytest.fixture()
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(common, "monotonic", lambda: now[0])
    return now


def test_unknown_tokens_are_throttled_per_address(client, anon_client, clock):
    """Resolve first: a failed lookup inside the address's wait is 429 and
    not counted, a counted one is 404, and a live link is never refused,
    whoever else shares its viewer's address."""
    enable(client)
    token, _ = make_link(client)
    here = {"X-Real-IP": "203.0.113.9"}

    def bogus():
        return anon_client.get(f"/api/share/{share.new_token()}", headers=here)

    for _ in range(20):
        assert bogus().status_code == 404
    refused = bogus()
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) >= 1
    assert refused.headers["x-robots-tag"] == "noindex, nofollow"
    assert anon_client.get(f"/api/share/{token}", headers=here).status_code == 200
    assert anon_client.get(f"/api/share/{token}/items", headers=here).status_code == 200
    for _ in range(5):
        assert bogus().status_code == 429  # not counted: the wait stays one second
    clock[0] += 1.5
    assert bogus().status_code == 404  # the 21st counted failure
    assert bogus().status_code == 429  # and now two seconds
    clock[0] += 2.5
    assert bogus().status_code == 404
    elsewhere = {"X-Real-IP": "198.51.100.7"}
    assert anon_client.get(f"/api/share/{share.new_token()}", headers=elsewhere).status_code == 404


def test_failed_lookups_have_a_global_cap(client, anon_client, clock, monkeypatch):
    monkeypatch.setattr(throttle, "SHARE_GLOBAL_PER_MINUTE", 30)
    enable(client)
    token, _ = make_link(client)
    for n in range(30):
        resp = anon_client.get(
            f"/api/share/{share.new_token()}", headers={"X-Real-IP": f"192.0.2.{n}"}
        )
        assert resp.status_code == 404
    fresh = {"X-Real-IP": "198.51.100.200"}
    refused = anon_client.get(f"/api/share/{share.new_token()}", headers=fresh)
    assert refused.status_code == 429 and 1 <= int(refused.headers["retry-after"]) <= 60
    assert anon_client.get(f"/api/share/{token}", headers=fresh).status_code == 200
    clock[0] += 61
    assert anon_client.get(f"/api/share/{share.new_token()}", headers=fresh).status_code == 404


def test_share_failures_never_push_out_sign_in_buckets(clock):
    """The v0.32.0 review's check, the other way round: 10,000 failed share
    lookups from as many addresses leave the admin's own bucket alone."""
    for _ in range(30):
        throttle.fail("user", "admin")
        throttle.fail("addr", "192.0.2.1")
    assert throttle.wait("user", "admin") == 60
    for n in range(throttle.MAX_KEYS + 1):
        throttle.fail("share", f"2001:db8:{n // 65536:x}:{n % 65536:x}::1")
    assert throttle.wait("user", "admin") == 60
    assert throttle.wait("addr", "192.0.2.1") == 60
    assert throttle.share_size() == throttle.MAX_KEYS
    assert throttle.size() == 2


def test_an_ipv6_client_is_counted_by_its_64():
    assert throttle.share_address("2001:db8:1:2:aaaa::1") == "2001:db8:1:2::/64"
    assert throttle.share_address("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert throttle.share_address("2001:db8:1:3::1") == "2001:db8:1:3::/64"
    assert throttle.share_address("::ffff:192.0.2.7") == "192.0.2.7"
    assert throttle.share_address("192.0.2.7") == "192.0.2.7"
    assert throttle.share_address("unknown") == "unknown"
    for n in range(20):
        assert throttle.share_failure(f"2001:db8:1:2::{n:x}") == 0
    assert throttle.share_failure("2001:db8:1:2:dead::1") > 0  # same /64
    assert throttle.share_failure("2001:db8:1:3::1") == 0  # its neighbour isn't


def test_sharing_off_costs_the_gate_nothing(client, anon_client, monkeypatch):
    """Off is known from memory: no database read, no lookup, no throttle."""
    enable(client, False)

    def boom(*args, **kwargs):
        raise AssertionError("the database was read for an anonymous share request")

    monkeypatch.setattr(share, "load", boom)
    monkeypatch.setattr(gate, "_lookup", boom)
    for _ in range(3):
        assert anon_client.get(f"/api/share/{share.new_token()}").status_code == 401
    assert throttle.share_size() == 0


def test_the_switch_is_loaded_once_then_held(client, anon_client, monkeypatch):
    enable(client)
    token, _ = make_link(client)
    share.reset_memory()
    reads = []
    real = share.load
    monkeypatch.setattr(share, "load", lambda db=None: reads.append(1) or real(db))
    for _ in range(3):
        assert anon_client.get(f"/api/share/{token}").status_code == 200
    assert len(reads) == 1 and share.cached() is True


# --- what a link covers -----------------------------------------------------------


def test_the_manifest_counts_opens(client, anon_client):
    enable(client)
    make_item(client)
    token, link = make_link(client, name="Spring show")
    body = anon_client.get(f"/api/share/{token}").json()
    assert body == {"kind": "collection", "name": "Spring show", **{
        "show_photos": True, "show_grades": True, "show_tags": True, "show_notes": False,
        "show_values": False, "show_certs": False}, "item_count": 1}  # fmt: skip
    anon_client.get(f"/api/share/{token}")
    listed = client.get("/api/share-links").json()[0]
    assert listed["opens"] == 2 and listed["last_opened_at"] is not None


def test_a_collection_share_holds_owned_untrashed_pieces_only(client, anon_client):
    enable(client)
    owned = make_item(client)
    make_item(client, status="sold")
    make_item(client, status="wishlist")
    trashed = make_item(client, country="Trash")
    client.delete(f"/api/items/{trashed['id']}")
    token, _ = make_link(client)
    body = anon_client.get(f"/api/share/{token}/items").json()
    assert body["total"] == 1 and [i["id"] for i in body["items"]] == [owned["id"]]
    assert_not_found(anon_client.get(f"/api/share/{token}/items/{trashed['id']}"))
    assert_not_found(anon_client.get(f"/api/share/{token}/checklist"))


def test_paging(client, anon_client):
    enable(client)
    for n in range(3):
        make_item(client, denomination=f"{n} cents")
    token, _ = make_link(client)
    page = anon_client.get(f"/api/share/{token}/items?offset=1&limit=1").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert anon_client.get(f"/api/share/{token}/items?limit=101").status_code == 422
    far = anon_client.get(f"/api/share/{token}/items?offset=1000000")
    assert far.status_code == 200 and far.json()["items"] == []
    for offset in ("1000001", "-1", str(2**70)):
        assert anon_client.get(f"/api/share/{token}/items?offset={offset}").status_code == 422


def test_a_set_share(client, anon_client):
    enable(client)
    set_id = client.post("/api/sets", json={"name": "Quarters"}).json()["id"]
    inside = make_item(client, set_id=set_id)
    make_item(client, set_id=set_id, status="sold")
    outside = make_item(client)
    token, created = make_link(client, kind="set", set_id=set_id)
    assert created["target_name"] == "Quarters"
    body = anon_client.get(f"/api/share/{token}/items").json()
    assert [i["id"] for i in body["items"]] == [inside["id"]]
    assert_not_found(anon_client.get(f"/api/share/{token}/items/{outside['id']}"))
    assert anon_client.get(f"/api/share/{token}").json()["item_count"] == 1


def test_a_checklist_share_shows_filled_slots_only(client, anon_client):
    enable(client)
    checklist = client.post(
        "/api/checklists/generate",
        json={"source": "range", "country": "United States", "denomination": "25 cents",
              "year_from": 1932, "year_to": 1934, "mint_marks": ["", "D"]},
    ).json()  # fmt: skip
    piece = make_item(client)  # 1932-D fills its slot
    make_item(client, country="Canada")
    detail = client.get(f"/api/checklists/{checklist['id']}").json()
    ticked = next(s for s in detail["slots"] if s["label"] == "1933")
    client.patch(f"/api/checklists/{checklist['id']}/slots/{ticked['id']}", json={"filled": True})
    token, _ = make_link(client, kind="checklist", checklist_id=checklist["id"])
    manifest = anon_client.get(f"/api/share/{token}").json()
    assert (manifest["filled"], manifest["total"], manifest["item_count"]) == (2, 6, 1)
    slots = anon_client.get(f"/api/share/{token}/checklist").json()["slots"]
    assert [(s["label"], s["item_id"]) for s in slots] == [
        ("1932-D", piece["id"]),
        ("1933", None),
    ]
    assert set(slots[0]) == {"position", "label", "year", "mint_mark", "item_id"}
    items = anon_client.get(f"/api/share/{token}/items").json()["items"]
    assert [i["id"] for i in items] == [piece["id"]]


def test_photos_through_the_share(client, anon_client):
    enable(client)
    item = full_item(client)
    other = make_item(client, status="sold")
    other_photo = client.post(
        f"/api/items/{other['id']}/photos", files={"file": ("b.png", image_bytes())}
    ).json()["id"]
    token, link = make_link(client)
    for variant in ("thumb", "full"):
        resp = anon_client.get(f"/api/share/{token}/photos/{item['photo_id']}/{variant}")
        assert resp.status_code == 200 and resp.content
        assert resp.headers["cache-control"] == "private, max-age=3600"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert resp.headers["x-robots-tag"] == "noindex, nofollow"
        # Both would say when the photo was uploaded.
        assert "last-modified" not in resp.headers and "etag" not in resp.headers
    assert_not_found(anon_client.get(f"/api/share/{token}/photos/{item['photo_id']}/huge"))
    assert_not_found(anon_client.get(f"/api/share/{token}/photos/{other_photo}/thumb"))
    client.patch(f"/api/share-links/{link['id']}", json={"show_photos": False})
    assert_not_found(anon_client.get(f"/api/share/{token}/photos/{item['photo_id']}/thumb"))


def test_a_credential_changes_nothing(client, anon_client, token_client):
    enable(client)
    item = full_item(client)
    token, _ = make_link(client, **ALL_ON)
    paths = [f"/api/share/{token}/items", f"/api/share/{token}/items/{item['id']}"]
    for path in paths:
        want = anon_client.get(path).json()
        assert client.get(path).json() == want
        assert token_client("write").get(path).json() == want
        cross = client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
        assert cross.status_code == 200 and cross.json() == want


# --- the admin's routes -------------------------------------------------------------


def test_the_url_is_shown_once_and_never_stored(client, sent):
    enable(client)
    token, created = make_link(client)
    assert created["url"] == f"https://testserver/s/{token}"
    assert created["show_certs"] is False
    assert share.TOKEN_RE.fullmatch(token) and len(token) == len("share_") + 43
    listed = client.get("/api/share-links")
    assert "url" not in listed.json()[0] and token not in listed.text
    assert "token" not in listed.text and "hash" not in listed.text
    assert created["created_by"] == "owner" and created["opens"] == 0
    db = db_session()
    try:
        row = db.scalar(select(ShareLink))
        assert row.token_hash == share.token_hash(token) != token
    finally:
        db.close()


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "set"},
        {"kind": "set", "set_id": 999},
        {"kind": "checklist", "checklist_id": 999},
        {"kind": "collection", "set_id": 1},
        {"kind": "checklist", "set_id": 1},
        {"kind": "album"},
        {"kind": "collection", "name": "   "},
    ],
)
def test_a_link_needs_a_real_target(client, body):
    enable(client)
    client.post("/api/sets", json={"name": "Quarters"})
    resp = client.post("/api/share-links", json={"name": "Show", **body})
    assert resp.status_code == 422, resp.text


def test_at_most_twenty_links(client):
    enable(client)
    for n in range(share.MAX_LINKS):
        make_link(client, name=f"Link {n}")
    resp = client.post("/api/share-links", json={"kind": "collection", "name": "One more"})
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "origins, origin, want",
    [
        ("http://cabinet.lan,https://cabinet.example.com", None, "https://cabinet.example.com"),
        ("http://cabinet.lan,https://cabinet.example.com", "http://cabinet.lan", "http://cabinet.lan"),
        ("http://cabinet.lan,https://cabinet.example.com", "https://evil.example", "https://cabinet.example.com"),
        ("http://cabinet.lan,https://cabinet.example.com", "HTTPS://Cabinet.Example.com:443", "https://cabinet.example.com"),
        ("http://cabinet.lan,http://cabinet.local", "null", "http://cabinet.lan"),
        ("https://a.example,https://b.example", "https://b.example", "https://b.example"),
    ],
)  # fmt: skip
def test_the_links_origin(monkeypatch, origins, origin, want):
    """The request's Origin when it is one of PUBLIC_ORIGINS, else the first
    https origin, else the first: never a LAN name over plain http when a
    public https one exists."""
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_ORIGINS", origins)
    get_settings.cache_clear()
    assert share.link_origin(origin) == want


def test_a_new_links_url_follows_the_admins_origin(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_ORIGINS", "http://cabinet.lan,https://testserver")
    get_settings.cache_clear()
    enable(client)
    _, created = make_link(client)
    assert created["url"].startswith("https://testserver/s/share_")
    resp = client.post(
        "/api/share-links",
        json={"kind": "collection", "name": "Lan"},
        headers={"Origin": "http://cabinet.lan"},
    )
    assert resp.json()["url"].startswith("http://cabinet.lan/s/share_")


def test_patch_regenerate_and_revoke(client, anon_client, sent):
    enable(client)
    make_item(client)
    token, link = make_link(client)
    patched = client.patch(
        f"/api/share-links/{link['id']}", json={"name": "Renamed", "show_notes": True}
    ).json()
    assert (patched["name"], patched["show_notes"], patched["show_photos"]) == (
        "Renamed",
        True,
        True,
    )
    fresh = client.post(f"/api/share-links/{link['id']}/regenerate").json()
    new_token = fresh["url"].rsplit("/", 1)[1]
    assert new_token != token and fresh["id"] == link["id"]
    assert_not_found(anon_client.get(f"/api/share/{token}"))
    assert anon_client.get(f"/api/share/{new_token}").json()["name"] == "Renamed"
    assert client.delete(f"/api/share-links/{link['id']}").status_code == 204
    assert_not_found(anon_client.get(f"/api/share/{new_token}"))
    assert client.get("/api/share-links").json() == []
    assert client.delete(f"/api/share-links/{link['id']}").status_code == 404


def test_deleting_the_set_or_checklist_deletes_its_links(client):
    enable(client)
    set_id = client.post("/api/sets", json={"name": "Quarters"}).json()["id"]
    checklist = client.post("/api/checklists", json={"name": "Run", "slots": ["1932"]}).json()
    make_link(client, kind="set", set_id=set_id)
    make_link(client, kind="checklist", checklist_id=checklist["id"])
    make_link(client)
    assert client.delete(f"/api/sets/{set_id}").status_code == 204
    assert client.delete(f"/api/checklists/{checklist['id']}").status_code == 204
    assert [row["kind"] for row in client.get("/api/share-links").json()] == ["collection"]


def test_minting_or_killing_a_link_asks_for_the_password(client, stale_client, token_client):
    enable(client)
    _, link = make_link(client)
    for method, path, body in (
        ("POST", "/api/share-links", {"kind": "collection", "name": "x"}),
        ("POST", f"/api/share-links/{link['id']}/regenerate", None),
        ("PATCH", f"/api/share-links/{link['id']}", {"show_values": True}),
        ("DELETE", f"/api/share-links/{link['id']}", None),
    ):
        resp = stale_client.request(method, path, json=body)
        assert resp.json().get("reauth_required") is True, path
        assert token_client("write").request(method, path, json=body).status_code == 403
    assert stale_client.get("/api/share-links").status_code == 200


def test_a_change_is_audited_and_widening_is_alerted(client, sent):
    enable(client)
    _, link = make_link(client, name="Spring show")
    sent.clear()
    url = f"/api/share-links/{link['id']}"
    assert client.patch(url, json={"show_tags": True}).status_code == 200  # no change
    assert client.patch(url, json={"show_tags": False, "name": "Autumn"}).status_code == 200
    assert sent == []  # narrower, and a rename: audited, not alerted
    body = {"show_notes": True, "show_values": True, "show_certs": True, "show_photos": True}
    assert client.patch(url, json=body).json()["show_certs"] is True
    db = db_session()
    try:
        rows = db.scalars(
            select(AuditEntry)
            .where(AuditEntry.action == "share_link_changed")
            .order_by(AuditEntry.id)
        ).all()
    finally:
        db.close()
    assert [(r.target, r.detail) for r in rows] == [
        (
            link["id"],
            {"name": "Autumn", "kind": "collection", "changed": {"show_tags": False},
             "renamed_from": "Spring show"},
        ),
        (
            link["id"],
            {"name": "Autumn", "kind": "collection",
             "changed": {"show_notes": True, "show_values": True, "show_certs": True}},
        ),
    ]  # fmt: skip
    assert [(key, title) for key, title, _ in sent] == [
        ("share_link_changed", "Cabinet share link now shows more")
    ]
    assert "notes, values, cert numbers" in sent[0][2]


def test_every_event_is_audited_and_alerted_without_the_token(client, sent):
    enable(client)
    token, link = make_link(client, name="Spring show")
    new = client.post(f"/api/share-links/{link['id']}/regenerate").json()["url"]
    client.delete(f"/api/share-links/{link['id']}")
    enable(client, False)
    db = db_session()
    try:
        rows = db.scalars(select(AuditEntry).order_by(AuditEntry.id)).all()
    finally:
        db.close()
    ours = [(r.action, r.target, r.detail) for r in rows if "shar" in r.action]
    detail = {"name": "Spring show", "kind": "collection"}
    assert ours == [
        ("sharing_switched", None, {"enabled": True}),
        ("share_link_created", link["id"], detail),
        ("share_link_regenerated", link["id"], detail),
        ("share_link_revoked", link["id"], detail),
        ("sharing_switched", None, {"enabled": False}),
    ]
    assert all(r.actor_label == "owner" for r in rows if "shar" in r.action)
    assert [(key, title) for key, title, _ in sent] == [
        ("sharing_switched", "Cabinet sharing switched on"),
        ("share_link_created", "Cabinet share link created"),
        ("share_link_regenerated", "Cabinet share link regenerated"),
        ("share_link_revoked", "Cabinet share link revoked"),
        ("sharing_switched", "Cabinet sharing switched off"),
    ]
    everything = json.dumps([[r.target, r.detail] for r in rows]) + json.dumps(sent)
    for secret in (token, new, new.rsplit("/", 1)[1]):
        assert secret not in everything


def test_saving_the_same_value_records_nothing(client, sent):
    client.put("/api/settings", json={"share_enabled": False})
    assert sent == []


# --- metrics, status, and where the table lives ----------------------------------------


def test_metrics_count_links_and_opens(client, anon_client):
    client.put("/api/settings", json={"metrics_enabled": True})
    enable(client)
    token, _ = make_link(client)
    make_link(client, name="Other")
    for _ in range(3):
        anon_client.get(f"/api/share/{token}")
    text = client.get("/api/metrics").text
    assert "cabinet_share_links 2.0" in text
    assert "cabinet_share_opens_total 3.0" in text


def test_status_says_whether_sharing_is_on(client, cli_admin, capsys):
    from app import cli

    enable(client)
    make_link(client)
    assert cli.main(["status"]) == 0
    assert "Sharing:       on, 1 link" in capsys.readouterr().out


def test_share_links_live_in_the_collection_schema():
    """In `public`, so every backup carries them and a restore brings them
    back (pg_dump itself is mocked in tests); never in `cabinet_auth`."""
    table = Base.metadata.tables["share_links"]
    assert table.schema is None and "share_links" not in AuthBase.metadata.tables
    assert {fk.column.table.name for fk in table.foreign_keys} == {"sets", "checklists"}


def test_the_access_log_never_carries_a_token():
    """uvicorn logs every path, and a share link's path is its token."""
    import logging

    token = share.new_token()
    args = ("192.0.2.1:5000", "GET", f"/api/share/{token}/items?limit=5", "1.1", 200)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None
    )
    assert all(f.filter(record) for f in logging.getLogger("uvicorn.access").filters)
    line = record.getMessage()
    assert token not in line and "/api/share/[token]/items?limit=5" in line


def test_settings_and_the_hourly_tick_reread_the_switch(client, anon_client):
    """A database changed behind the backend's back (restore.sh) is picked
    up by opening Settings, and by the hourly tick."""
    from app.services import app_settings, scheduled

    enable(client)
    token, _ = make_link(client)

    def flip(on: bool):
        db = db_session()
        try:
            app_settings.set_setting(db, "share_enabled", on)
            db.commit()
        finally:
            db.close()

    flip(False)
    assert share.cached() is True  # memory still says on
    assert client.get("/api/settings").json()["share_enabled"] is False
    assert share.cached() is False
    assert anon_client.get(f"/api/share/{token}").status_code == 401
    flip(True)
    db = db_session()
    try:
        scheduled.hourly(db)
    finally:
        db.close()
    assert share.cached() is True
    assert anon_client.get(f"/api/share/{token}").status_code == 200
