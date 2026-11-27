"""The credit PCGS's API agreement asks for on every page that shows its
data: due from the moment anything from PCGS is held, and for as long as it
is, whether or not the source is still switched on."""

import uuid
from datetime import datetime, timezone

from app.db import get_db
from app.main import app
from app.models import Item, SourceCache
from app.services import credits
from tests.conftest import COIN, source_estimate

URL = "/api/reference/data-credits"


def _session():
    return next(app.dependency_overrides[get_db]())


def test_nothing_is_due_until_pcgs_is_used(client, coin):
    client.post(f"/api/items/{coin['id']}/estimates", json={"estimated_value": 5})
    source_estimate(coin["id"], estimated_value=6, source="numista:N#1 XF")
    source_estimate(coin["id"], estimated_value=7, source="melt:silver @ 0.01/g")
    assert client.get(URL).json() == []


def test_the_credit_is_the_agreements_own_sentence(client, coin):
    source_estimate(coin["id"], estimated_value=80, source="pcgs:guide 3912")
    assert client.get(URL).json() == [
        {
            "source": "pcgs",
            "name": "PCGS",
            "url": "https://www.pcgs.com",
            "notice": (
                "The Data is obtained from and is subject to a license agreement with "
                "Collectors Universe, Inc. and its divisions PCGS and PSA."
            ),
        }
    ]


def test_switching_the_source_on_is_enough(client):
    assert client.get(URL).json() == []
    put = client.put("/api/settings", json={"pcgs_api_token": "t", "pcgs_enabled": True})
    assert put.status_code == 200, put.text
    assert [c["source"] for c in client.get(URL).json()] == ["pcgs"]


def test_a_population_or_a_cached_answer_is_pcgs_data_too(client):
    made = client.post("/api/items", json={**COIN, "pcgs_population": 12}).json()
    assert [c["source"] for c in client.get(URL).json()] == ["pcgs"]
    # Still due from the trash: the data is still held.
    assert client.delete(f"/api/items/{made['id']}").status_code == 204
    assert [c["source"] for c in client.get(URL).json()] == ["pcgs"]

    db = _session()
    db.delete(db.get(Item, uuid.UUID(made["id"]), execution_options={"include_deleted": True}))
    db.commit()
    assert credits.due(db) == []
    at = datetime.now(timezone.utc)
    db.add(SourceCache(source="pcgs", cache_key="certfacts:1", payload={}, fetched_at=at))
    db.commit()
    assert [c["source"] for c in client.get(URL).json()] == ["pcgs"]


def test_a_read_token_may_read_it_and_a_stranger_may_not(client, anon_client, token_client):
    assert anon_client.get(URL).status_code == 401
    assert token_client("read").get(URL).status_code == 200
