"""Alerts (webhook on change, heartbeat), refresh outcomes, and /api/metrics."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services import alerts, backup, numista, pricing, scheduled
from tests.conftest import COIN
from tests.test_numista import ISSUES, PRICES, _session, configure, make_item

HOOK = "https://hooks.example.test/webhook/secret-token-123"
KUMA = "http://kuma.example.test/api/push/pushtoken42?status=up&msg=OK&ping="


def _response(status=200, json=None, url="https://upstream.test/"):
    return httpx.Response(status, json=json, request=httpx.Request("GET", url))


@pytest.fixture()
def posted(monkeypatch):
    """Capture webhook deliveries, delivered inline instead of on a thread."""
    sent = []

    def post(url, timeout, **kwargs):
        sent.append({"url": url, **kwargs})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(alerts.httpx, "post", post)
    monkeypatch.setattr(alerts, "_spawn", lambda fn: fn())
    return sent


def save_hook(client, fmt="generic", url=HOOK):
    resp = client.put("/api/settings", json={"alert_webhook_url": url, "alert_webhook_format": fmt})
    assert resp.status_code == 200
    return resp.json()


# --- settings ---------------------------------------------------------------


def test_webhook_url_is_write_only_and_validated(client):
    body = save_hook(client, "ntfy")
    assert body["alert_webhook_hint"] == "https://hooks.example.test/…"
    assert body["alert_webhook_format"] == "ntfy"
    assert "secret-token" not in str(body)
    assert body["metrics_enabled"] is False
    assert body["alerts"] == [] and body["refresh_last_run"] == {}

    for bad in ("ftp://example.test/x", "not a url", "javascript:alert(1)"):
        assert client.put("/api/settings", json={"alert_webhook_url": bad}).status_code == 422
    assert client.put("/api/settings", json={"alert_webhook_format": "email"}).status_code == 422

    cleared = client.put("/api/settings", json={"alert_webhook_url": ""}).json()
    assert cleared["alert_webhook_hint"] is None


# --- delivery formats ---------------------------------------------------------


@pytest.mark.parametrize(
    "fmt, check",
    [
        ("generic", lambda s: s["json"]["status"] == "test" and s["json"]["app"] == "cabinet"),
        ("discord", lambda s: s["json"]["content"].startswith("**Cabinet: test alert**")),
        ("slack", lambda s: s["json"]["text"].startswith("*Cabinet: test alert*")),
        ("gotify", lambda s: s["json"]["title"] == "Cabinet: test alert"),
        (
            "ntfy",
            lambda s: (
                s["headers"]["Title"] == "Cabinet: test alert"
                and s["content"].startswith(b"Alerts from Cabinet")
            ),
        ),
    ],
)
def test_test_alert_in_each_format(client, posted, fmt, check):
    save_hook(client, fmt)
    resp = client.post("/api/alerts/test")
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert len(posted) == 1 and posted[0]["url"] == HOOK
    assert check(posted[0])
    assert client.get("/api/settings").json()["alert_delivery"]["ok"] is True


def test_test_alert_without_a_url(client):
    body = client.post("/api/alerts/test").json()
    assert body["ok"] is False and "No webhook" in body["detail"]


def test_a_failed_delivery_never_repeats_the_url(client, monkeypatch):
    save_hook(client)

    def refuse(url, timeout, **kwargs):
        raise httpx.ConnectError(f"All connection attempts failed for {url}")

    monkeypatch.setattr(alerts.httpx, "post", refuse)
    body = client.post("/api/alerts/test").json()
    assert body["ok"] is False
    assert "secret-token" not in body["detail"]
    assert "hooks.example.test" in body["detail"]

    monkeypatch.setattr(
        alerts.httpx,
        "post",
        lambda url, timeout, **kw: httpx.Response(404, request=httpx.Request("POST", url)),
    )
    assert client.post("/api/alerts/test").json()["detail"] == "HTTP 404"


# --- alerting on change ---------------------------------------------------------


def test_alerts_fire_on_change_and_on_recovery(client, posted):
    save_hook(client)
    db = _session()
    alerts.fail(db, "backup", "Backup failed: disk full")
    alerts.fail(db, "backup", "Backup failed: disk full")  # same problem: silent
    alerts.fail(db, "backup", "Backup failed: still full")  # new message: silent
    assert [p["json"]["status"] for p in posted] == ["failing"]
    assert posted[0]["json"]["alert"] == "backup"

    listed = client.get("/api/settings").json()["alerts"]
    assert listed[0]["key"] == "backup" and listed[0]["failing"] is True
    assert listed[0]["message"] == "Backup failed: still full"

    alerts.recover(db, "backup")
    alerts.recover(db, "backup")  # already healthy: silent
    alerts.recover(db, "numista_key")  # never failed: silent
    assert [p["json"]["status"] for p in posted] == ["failing", "recovered"]
    assert "still full" in posted[1]["json"]["message"]
    assert client.get("/api/settings").json()["alerts"][0]["failing"] is False


def test_state_is_kept_without_a_webhook(client):
    alerts.fail(_session(), "pcgs_quota", "PCGS request quota exhausted")
    assert list(alerts.failing(_session())) == ["pcgs_quota"]


def test_backup_failure_alerts_and_success_recovers(client, posted, monkeypatch):
    save_hook(client)

    def broken(out, server_major):
        raise backup.BackupError("pg_dump failed: connection refused")

    monkeypatch.setattr(backup, "dump_database", broken)
    assert client.post("/api/backups").status_code == 500
    assert posted[-1]["json"]["alert"] == "backup"
    assert "connection refused" in posted[-1]["json"]["message"]

    monkeypatch.setattr(backup, "dump_database", lambda out, major: out.write(b"PGDMP") or "fake")
    assert client.post("/api/backups").status_code == 200
    assert [p["json"]["status"] for p in posted] == ["failing", "recovered"]


# --- rejected keys, quotas, and refreshes ---------------------------------------


def test_rejected_key_stops_the_refresh_and_alerts(client, posted, monkeypatch):
    configure(client)
    save_hook(client)
    make_item(client)
    make_item(client, ref="N#5678")
    calls = []

    def rejected(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return _response(401, url=url)

    monkeypatch.setattr(numista.httpx, "get", rejected)
    result = pricing.refresh_source_estimates(_session(), "numista", 7)
    assert result["failed"] == 1 and "rejected the API key" in result["stopped"]
    assert len(calls) == 1  # the second item was never tried
    assert "numista_key" in alerts.failing(_session())
    assert posted[-1]["json"]["alert"] == "numista_key"

    # The next answer from Numista clears it.
    def ok(url, params=None, headers=None, timeout=None):
        return _response(200, json=ISSUES["items"] if url.endswith("/issues") else PRICES, url=url)

    monkeypatch.setattr(numista.httpx, "get", ok)
    pricing.refresh_source_estimates(_session(), "numista", 7)
    assert "numista_key" not in alerts.failing(_session())
    assert (posted[-1]["json"]["alert"], posted[-1]["json"]["status"]) == (
        "numista_key",
        "recovered",
    )


def test_quota_and_pcgs_errors_are_classified(monkeypatch):
    from app.services import pcgs

    for status, exc in ((401, pricing.KeyRejected), (429, pricing.QuotaExhausted)):
        monkeypatch.setattr(numista.httpx, "get", lambda *a, s=status, **k: _response(s))
        with pytest.raises(exc):
            numista._request("key", "types/1")
    for status, exc in (
        (401, pricing.KeyRejected),
        (429, pricing.QuotaExhausted),
        (500, pricing.KeyRejected),
    ):
        monkeypatch.setattr(pcgs.httpx, "get", lambda *a, s=status, **k: _response(s))
        with pytest.raises(exc):
            pcgs._request("token", "coindetail/GetCoinFactsByCertNo/1")


def test_scheduled_refresh_records_outcomes_and_alerts(client, posted, monkeypatch):
    configure(client)
    save_hook(client)
    client.put("/api/settings", json={"numista_refresh_days": 7, "melt_enabled": False})
    make_item(client)

    def boom(api_key, path, params=None):
        raise pricing.SourceUnavailable("Numista request failed: timeout")

    monkeypatch.setattr(numista, "_request", boom)
    outcomes = scheduled.refresh(_session())
    assert outcomes == {
        "numista": {
            "updated": 0,
            "skipped": 0,
            "failed": 1,
            "error": "Numista request failed: timeout",
        }
    }
    last = client.get("/api/settings").json()["refresh_last_run"]["numista"]
    assert last["failed"] == 1 and last["error"].endswith("timeout")
    assert posted[-1]["json"]["alert"] == "refresh_numista"
    assert "1 item(s) failed" in posted[-1]["json"]["message"]


# --- heartbeat ------------------------------------------------------------------


@pytest.fixture()
def pushes(monkeypatch):
    sent = []

    def get(url, timeout):
        sent.append(url)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    monkeypatch.setattr(alerts.httpx, "get", get)
    return sent


def test_heartbeat_reports_up_then_down(client, pushes):
    assert client.put("/api/settings", json={"heartbeat_url": KUMA}).json()["heartbeat_hint"] == (
        "http://kuma.example.test/…"
    )
    scheduled.hourly(_session())
    query = parse_qs(urlsplit(pushes[-1]).query)
    assert urlsplit(pushes[-1]).path == "/api/push/pushtoken42"
    assert query["status"] == ["up"] and query["msg"] == ["OK"] and "ping" not in query

    alerts.fail(_session(), "backup", "Backup failed: disk full")
    scheduled.hourly(_session())
    query = parse_qs(urlsplit(pushes[-1]).query)
    assert query["status"] == ["down"] and "disk full" in query["msg"][0]
    assert client.get("/api/settings").json()["heartbeat"]["detail"] == "pushed down"


def test_heartbeat_test_and_a_refused_push(client, monkeypatch):
    body = client.post("/api/alerts/test?target=heartbeat").json()
    assert body["ok"] is False and "No heartbeat" in body["detail"]

    client.put("/api/settings", json={"heartbeat_url": KUMA})
    monkeypatch.setattr(
        alerts.httpx,
        "get",
        lambda url, timeout: httpx.Response(
            200,
            json={"ok": False, "msg": "Monitor not found or not active."},
            request=httpx.Request("GET", url),
        ),
    )
    body = client.post("/api/alerts/test?target=heartbeat").json()
    assert body["ok"] is False and "Monitor not found" in body["detail"]
    assert "pushtoken42" not in body["detail"]


def test_no_heartbeat_without_a_url(client, pushes):
    scheduled.hourly(_session())
    assert pushes == []


# --- metrics --------------------------------------------------------------------


def test_metrics_are_off_by_default(client):
    assert client.get("/api/metrics").status_code == 404


def test_metrics(client):
    client.put("/api/settings", json={"metrics_enabled": True})
    kept = client.post("/api/items", json=COIN).json()
    trashed = client.post("/api/items", json={**COIN, "type": "note"}).json()
    client.post("/api/items", json={**COIN, "status": "wishlist"})
    client.post(
        f"/api/items/{kept['id']}/estimates",
        json={"estimated_value": 150, "currency": "USD", "source": "manual"},
    )
    client.delete(f"/api/items/{trashed['id']}")
    alerts.fail(_session(), "pcgs_key", "rejected")

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "cabinet_info{" in text and 'schema="unknown"' in text  # SQLite: no alembic
    assert 'cabinet_items{status="owned",type="coin"} 1.0' in text
    assert 'cabinet_items{status="wishlist",type="coin"} 1.0' in text
    assert 'cabinet_items{status="owned",type="note"}' not in text  # it's in the trash
    assert "cabinet_items_in_trash 1.0" in text
    assert 'cabinet_collection_value{currency="USD"} 150.0' in text
    assert 'cabinet_collection_cost_basis{currency="USD"} 120.0' in text
    assert 'cabinet_alert_failing{alert="pcgs_key"} 1.0' in text
    assert 'cabinet_alert_failing{alert="backup"} 0.0' in text
    assert "cabinet_backup_scheduled 0.0" in text
    assert "cabinet_backup_archives 0.0" in text


def test_metrics_are_cached_for_a_minute(client):
    client.put("/api/settings", json={"metrics_enabled": True})
    first = client.get("/api/metrics").text
    client.post("/api/items", json=COIN)
    assert client.get("/api/metrics").text == first
