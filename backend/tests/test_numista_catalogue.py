"""Roadmap Phase 5.7 C5: filling items in from the Numista catalogue."""

import pytest

from app.services import numista
from app.services.pricing import SourceUnavailable
from tests.conftest import COIN

COIN_TYPE = {
    "id": 1493,
    "url": "https://en.numista.com/1493",
    "title": '1 Dollar "American Silver Eagle"',
    "category": "coin",
    "issuer": {"code": "etats-unis", "name": "United States"},
    "min_year": 1986,
    "max_year": 2021,
    "value": {"text": "1 Dollar", "numeric_value": 1},
    "composition": {"text": "Silver (.999)"},
    "weight": 31.103,
    "size": 40.6,
    "thickness": 2.98,
    "shape": "Round",
    "edge": {"description": "Reeded"},
    "series": "American Eagle",
    "references": [{"catalogue": {"id": 3, "code": "KM"}, "number": "273"}],
}
COIN_ISSUES = {
    "items": [
        {"is_dated": True, "year": 1986, "gregorian_year": 1986, "mintage": 5393005},
        {"is_dated": True, "year": 2000, "mint_letter": "W", "mintage": 600743, "comment": "Proof"},
    ]
}
NOTE_TYPE = {
    "id": 207,
    "title": "10 Dollars",
    "category": "banknote",
    "issuer": {"code": "canada", "name": "Canada"},
    "issuing_entity": {"id": 5, "name": "Bank of Canada"},
    "min_year": 1954,
    "max_year": 1954,
    "value": {"text": "10 Dollars"},
    "composition": {"text": "Paper"},
    "size": 152.4,
    "size2": 69.9,
    "references": [{"catalogue": {"id": 9, "code": "Pick"}, "number": "79a"}],
}
SEARCH = {
    "count": 1,
    "types": [
        {
            "id": 1493,
            "title": '1 Dollar "American Silver Eagle"',
            "category": "coin",
            "issuer": {"code": "etats-unis", "name": "United States"},
            "min_year": 1986,
            "max_year": 2021,
            "obverse_thumbnail": "https://en.numista.com/catalogue/photos/1493-180.jpg",
        }
    ],
}


@pytest.fixture()
def catalogue(monkeypatch):
    """Stand in for the Numista API, recording (path, params) per call."""
    calls: list[tuple[str, dict | None]] = []
    responses = {
        "types": SEARCH,
        "types/1493": COIN_TYPE,
        "types/1493/issues": COIN_ISSUES,
        "types/207": NOTE_TYPE,
    }

    def fake_request(api_key, path, params=None):
        calls.append((path, params))
        if path in responses:
            return responses[path]
        raise numista._NotFound()

    monkeypatch.setattr(numista, "_request", fake_request)
    return calls


def configure(client):
    # A key is enough: looking items up doesn't need Numista pricing switched on.
    assert client.put("/api/settings", json={"numista_api_key": "k"}).status_code == 200


def test_lookups_need_a_key(client, catalogue):
    resp = client.get("/api/numista/search", params={"q": "silver eagle"})
    assert resp.status_code == 422 and "API key" in resp.json()["detail"]
    assert client.get("/api/numista/types/1493").status_code == 422
    assert catalogue == []


def test_search(client, catalogue):
    configure(client)
    resp = client.get("/api/numista/search", params={"q": "  Silver  eagle ", "category": "coin"})
    assert resp.status_code == 200
    assert resp.json() == {
        "count": 1,
        "results": [
            {
                "type_id": 1493,
                "title": '1 Dollar "American Silver Eagle"',
                "category": "coin",
                "issuer": "United States",
                "min_year": 1986,
                "max_year": 2021,
                "thumbnail": "https://en.numista.com/catalogue/photos/1493-180.jpg",
            }
        ],
    }
    assert catalogue == [("types", {"q": "Silver eagle", "count": 20, "category": "coin"})]

    client.get("/api/numista/search", params={"q": "silver EAGLE", "category": "coin"})
    assert len(catalogue) == 1  # cached, case-insensitively

    assert client.get("/api/numista/search", params={"q": "x"}).status_code == 422
    bad = client.get("/api/numista/search", params={"q": "eagle", "category": "medal"})
    assert bad.status_code == 422


def test_coin_type_fills_fields_refs_and_issues(client, catalogue):
    configure(client)
    body = client.get("/api/numista/types/1493").json()
    assert body["url"] == "https://en.numista.com/1493"
    assert body["fields"] == {
        "type": "coin",
        "country": "United States",
        "denomination": "1 Dollar",
        "series": "American Eagle",
        "composition": "Silver (.999)",
        "fineness": 0.999,
        "weight_g": 31.103,
        "diameter_mm": 40.6,
        "thickness_mm": 2.98,
        "shape": "Round",
        "edge": "Reeded",
    }  # no year: the type spans 1986–2021
    assert body["catalog_refs"] == [
        {"catalog": "numista", "ref_code": "N#1493"},
        {"catalog": "km", "ref_code": "KM#273"},
    ]
    assert body["issues"] == [
        {
            "year": 1986,
            "nd": False,
            "mint_letter": None,
            "mintage": 5393005,
            "comment": None,
            "reference": None,
            "owned": False,
        },
        {
            "year": 2000,
            "nd": False,
            "mint_letter": "W",
            "mintage": 600743,
            "comment": "Proof",
            "reference": None,
            "owned": False,
        },
    ]

    client.get("/api/numista/types/1493")
    assert len(catalogue) == 2  # type + issues, both cached

    # the filled fields and refs save as an item as they are
    item = {**COIN, **body["fields"], "catalog_refs": body["catalog_refs"], "year": 1986}
    assert client.post("/api/items", json=item).status_code == 201


def test_banknote_type(client, catalogue):
    configure(client)
    body = client.get("/api/numista/types/207").json()
    assert body["fields"] == {
        "type": "note",
        "country": "Canada",
        "denomination": "10 Dollars",
        "year": 1954,
        "composition": "Paper",
        "issuer": "Bank of Canada",
        "width_mm": 152.4,
        "height_mm": 69.9,
    }  # no diameter from a note's size (that's width_mm), no fineness from paper
    assert body["catalog_refs"][1] == {"catalog": "pick", "ref_code": "Pick#79a"}
    assert body["issues"] == []  # no issues listed upstream


def test_banknote_printer_watermark_demonetization_present(client):
    fields = numista.catalogue_fields(
        {
            **NOTE_TYPE,
            "printers": [{"name": "Canadian Bank Note Company"}, {"name": "British American"}],
            "watermark": {"description": "Queen's portrait"},
            "demonetization": {"is_demonetized": True, "demonetization_date": "1971-01-01"},
        }
    )
    assert fields["printer"] == "Canadian Bank Note Company, British American"
    assert fields["watermark"] == "Queen's portrait"
    assert fields["demonetized_on"].isoformat() == "1971-01-01"


def test_banknote_printer_watermark_demonetization_absent(client):
    fields = numista.catalogue_fields(NOTE_TYPE)
    assert "printer" not in fields
    assert "watermark" not in fields
    assert "demonetized_on" not in fields


@pytest.mark.parametrize(
    "extra",
    [
        {"printers": "not a list"},
        {"printers": [{"name": ""}, "not a dict"]},
        {"watermark": 12345},
        {"watermark": {"description": ""}},
        {"demonetization": "not a dict"},
        {"demonetization": {"is_demonetized": "yes"}},  # not a bool True
        {"demonetization": {"is_demonetized": True, "demonetization_date": "not a date"}},
        {"demonetization": {"is_demonetized": True, "demonetization_date": 12345}},
        {"demonetization": {"is_demonetized": False, "demonetization_date": "1971-01-01"}},
    ],
)
def test_banknote_malformed_fields_never_fail(client, extra):
    fields = numista.catalogue_fields({**NOTE_TYPE, **extra})
    assert "watermark" not in fields or isinstance(fields["watermark"], str)
    assert "printer" not in fields or isinstance(fields["printer"], str)
    assert "demonetized_on" not in fields


def test_banknote_watermark_as_string(client):
    fields = numista.catalogue_fields({**NOTE_TYPE, "watermark": "Plain watermark text"})
    assert fields["watermark"] == "Plain watermark text"


def test_unknown_type_and_upstream_failure(client, catalogue, monkeypatch):
    configure(client)
    resp = client.get("/api/numista/types/999")
    assert resp.status_code == 404 and "N#999" in resp.json()["detail"]
    assert client.get("/api/numista/types/0").status_code == 422

    def down(api_key, path, params=None):
        raise SourceUnavailable("Numista request quota exhausted. Try again later")

    monkeypatch.setattr(numista, "_request", down)
    resp = client.get("/api/numista/types/4242")
    assert resp.status_code == 502 and "quota" in resp.json()["detail"]
    assert client.get("/api/numista/search", params={"q": "sovereign"}).status_code == 502


def test_fineness_from_composition():
    assert numista.fineness_from_composition("Silver (.900)") == 0.9
    assert numista.fineness_from_composition("90% silver") == 0.9
    assert numista.fineness_from_composition("Gold 916.7") == 0.9167
    assert numista.fineness_from_composition("Silver 999") == 0.999
    assert numista.fineness_from_composition("Silver") is None
    assert numista.fineness_from_composition("Bronze 950") is None  # not a precious metal
    assert numista.fineness_from_composition(None) is None
