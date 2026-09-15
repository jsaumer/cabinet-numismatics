"""In-app backups: download archive, stored backups, retention, scheduling."""

import io
import re
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.services import backup
from tests.conftest import image_bytes

FAKE_DUMP = b"PGDMP fake custom-format dump"
UTC = timezone.utc


@pytest.fixture()
def fake_dump(monkeypatch):
    """SQLite has no pg_dump; the archive handling around it is under test."""

    def dump(out, server_major):
        out.write(FAKE_DUMP)
        return "pg_dump (fake)"

    monkeypatch.setattr(backup, "dump_database", dump)


@pytest.fixture()
def clock(monkeypatch):
    now = [datetime(2026, 9, 14, 3, 15, tzinfo=UTC)]
    monkeypatch.setattr(backup, "utcnow", lambda: now[0])
    return now


def _session():
    return next(app.dependency_overrides[get_db]())


def _save(resp, path: Path) -> Path:
    assert resp.status_code == 200, resp.text
    path.write_bytes(resp.content)
    return path


def test_download_holds_dump_photos_and_manifest(client, coin, fake_dump, tmp_path):
    upload = client.post(
        f"/api/items/{coin['id']}/photos", files={"file": ("obv.png", image_bytes(), "image/png")}
    )
    assert upload.status_code == 201

    resp = client.get("/api/backup.zip")
    assert resp.headers["content-type"] == "application/zip"
    assert re.search(
        r'filename="cabinet-backup-\d{8}-\d{6}\.zip"', resp.headers["content-disposition"]
    )
    archive = _save(resp, tmp_path.parent / f"{tmp_path.name}-download.zip")

    manifest = backup.verify_archive(archive)
    assert manifest["format"] == "cabinet-backup"
    assert manifest["counts"] == {"items": 1, "photos": 1, "estimates": 0}
    assert manifest["includes_photos"] is True
    assert manifest["app_version"] == client.get("/api/health").json()["version"]
    with zipfile.ZipFile(archive) as zf:
        assert set(zf.namelist()) == {"db.dump", "photos.tar.gz", "manifest.json", "SHA256SUMS"}
        assert zf.read("db.dump") == FAKE_DUMP
        sums = zf.read("SHA256SUMS").decode().splitlines()
        assert sorted(sums) == sorted(
            f"{m['sha256']}  {name}" for name, m in manifest["members"].items()
        )
        with tarfile.open(fileobj=io.BytesIO(zf.read("photos.tar.gz"))) as tar:
            assert any(member.isfile() for member in tar.getmembers())

    # the temp archive behind the download is gone once it has been sent
    assert not list(Path(get_settings().backup_dir).glob(".download-*"))


def test_data_only_download(client, coin, fake_dump, tmp_path):
    resp = client.get("/api/backup.zip?photos=false")
    assert "-data.zip" in resp.headers["content-disposition"]
    archive = _save(resp, tmp_path.parent / f"{tmp_path.name}-data.zip")
    assert backup.verify_archive(archive)["includes_photos"] is False
    with zipfile.ZipFile(archive) as zf:
        assert "photos.tar.gz" not in zf.namelist()


def test_verify_rejects_a_tampered_archive(client, fake_dump, tmp_path):
    good = _save(client.get("/api/backup.zip"), tmp_path.parent / f"{tmp_path.name}-good.zip")
    bad = good.with_name(good.stem + "-bad.zip")
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            dst.writestr(name, b"tampered" if name == "db.dump" else data)
    with pytest.raises(backup.BackupError, match="db.dump"):
        backup.verify_archive(bad)


def test_backup_dir_inside_photo_dir_is_refused(client, monkeypatch, fake_dump, tmp_path):
    # nginx serves the photo volume publicly; archives there would be downloadable.
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    get_settings.cache_clear()
    resp = client.post("/api/backups")
    assert resp.status_code == 500
    assert "photo" in resp.json()["detail"]


def test_back_up_now_lists_downloads_and_prunes(client, coin, fake_dump, clock):
    assert client.put("/api/settings", json={"backup_keep": 2}).status_code == 200
    dest = Path(get_settings().backup_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "notes.txt").write_text("not ours")

    names = []
    for minute in range(3):
        clock[0] = datetime(2026, 9, 14, 3, 15 + minute, tzinfo=UTC)
        resp = client.post("/api/backups")
        assert resp.status_code == 200, resp.text
        names.append(resp.json()["file"])
    assert names[2] == "cabinet-backup-20260914-031700.zip"
    assert resp.json()["pruned"] == [names[0]]

    listing = client.get("/api/backups").json()
    assert [b["name"] for b in listing["backups"]] == [names[2], names[1]]
    assert listing["backups"][0]["created_at"].startswith("2026-09-14T03:17:00")
    assert listing["last_run"]["ok"] is True and listing["last_run"]["file"] == names[2]
    assert listing["free_bytes"] > 0
    assert (dest / "notes.txt").exists()  # retention only touches Cabinet's archives

    stored = client.get(f"/api/backups/{names[2]}")
    assert stored.status_code == 200 and stored.content[:2] == b"PK"
    assert client.get(f"/api/backups/{names[0]}").status_code == 404
    assert client.get("/api/backups/notes.txt").status_code == 404


def test_back_up_now_follows_the_photos_setting(client, fake_dump, clock):
    client.put("/api/settings", json={"backup_include_photos": False})
    assert client.post("/api/backups").json()["file"].endswith("-data.zip")
    assert client.post("/api/backups?photos=true").status_code == 200


def test_failed_backup_is_recorded_and_leaves_nothing_behind(client, monkeypatch, clock):
    def broken(out, server_major):
        out.write(b"half a dump")
        raise backup.BackupError("pg_dump failed: connection refused")

    monkeypatch.setattr(backup, "dump_database", broken)
    resp = client.post("/api/backups")
    assert resp.status_code == 500
    assert "connection refused" in resp.json()["detail"]
    assert client.get("/api/backup.zip").status_code == 500

    listing = client.get("/api/backups").json()
    assert listing["backups"] == []
    assert listing["last_run"]["ok"] is False
    assert "connection refused" in listing["last_run"]["error"]
    assert list(Path(listing["directory"]).iterdir()) == []


def test_concurrent_backup_is_rejected(client, fake_dump):
    backup._run_lock.acquire()
    try:
        assert client.post("/api/backups").status_code == 409
    finally:
        backup._run_lock.release()


def test_missing_pg_dump_is_explained(monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "PG_CLIENT_ROOT", tmp_path / "none")
    monkeypatch.setattr(backup.shutil, "which", lambda name: None)
    with pytest.raises(backup.BackupError, match="pg_dump is not installed"):
        backup.dump_database(io.BytesIO(), 16)


def test_pg_tool_matches_the_server_major(monkeypatch, tmp_path):
    for major in (14, 16, 18):
        (tmp_path / str(major)).mkdir()
    monkeypatch.setattr(backup, "PG_CLIENT_ROOT", tmp_path)
    assert backup.pg_tool("pg_dump", 16) == str(tmp_path / "16" / "pg_dump")
    assert backup.pg_tool("pg_restore", 15) == str(tmp_path / "16" / "pg_restore")
    assert backup.pg_tool("pg_dump", 18) == str(tmp_path / "18" / "pg_dump")
    with pytest.raises(backup.BackupError, match="PostgreSQL 19 is newer"):
        backup.pg_tool("pg_dump", 19)


def test_pg_env_comes_from_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://numis:p%40ss@db:5433/cabinet?sslmode=require")
    get_settings.cache_clear()
    try:
        env = backup._pg_env()
    finally:
        get_settings.cache_clear()
    assert (env["PGHOST"], env["PGPORT"], env["PGUSER"]) == ("db", "5433", "numis")
    assert (env["PGPASSWORD"], env["PGDATABASE"], env["PGSSLMODE"]) == (
        "p@ss",
        "cabinet",
        "require",
    )


def test_backup_due():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)

    def last(hours, ok=True):
        return {"at": (now - timedelta(hours=hours)).isoformat(), "ok": ok}

    assert not backup.backup_due(None, None, now)
    assert backup.backup_due("daily", None, now)
    assert not backup.backup_due("daily", last(23), now)
    assert backup.backup_due("daily", last(23.9), now)  # within the scheduler slack
    assert not backup.backup_due("weekly", last(24 * 6), now)
    assert backup.backup_due("weekly", last(24 * 7), now)
    assert not backup.backup_due("daily", last(0.5, ok=False), now)
    assert backup.backup_due("daily", last(1, ok=False), now)  # failures retry hourly


def test_scheduled_backup_runs_when_due(client, fake_dump, clock):
    assert backup.run_scheduled(_session()) is None  # off by default

    client.put("/api/settings", json={"backup_schedule": "daily"})
    assert backup.run_scheduled(_session())["ok"] is True
    clock[0] += timedelta(hours=1)
    assert backup.run_scheduled(_session()) is None
    clock[0] += timedelta(hours=23)
    assert backup.run_scheduled(_session())["ok"] is True
    assert len(client.get("/api/backups").json()["backups"]) == 2


def test_backup_settings(client):
    body = client.get("/api/settings").json()
    assert body["backup_schedule"] is None
    assert body["backup_keep"] == 7
    assert body["backup_include_photos"] is True

    resp = client.put(
        "/api/settings",
        json={"backup_schedule": "weekly", "backup_keep": 30, "backup_include_photos": False},
    )
    body = resp.json()
    assert (body["backup_schedule"], body["backup_keep"]) == ("weekly", 30)
    assert body["backup_include_photos"] is False

    assert client.put("/api/settings", json={"backup_schedule": "hourly"}).status_code == 422
    assert client.put("/api/settings", json={"backup_keep": 0}).status_code == 422
    # the outcome record is the service's to write, not the API's
    client.put("/api/settings", json={"backup_last_run": {"ok": True}})
    assert client.get("/api/backups").json()["last_run"] is None
