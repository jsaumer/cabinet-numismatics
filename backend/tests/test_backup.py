"""In-app backups: download archive, stored backups, retention, scheduling."""

import io
import re
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models.auth import AuditEntry
from app.services import backup
from tests.conftest import FAKE_AGE_HEADER, image_bytes, open_archive

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
    """Save a downloaded archive, check it is ciphertext, and return its
    decrypted zip beside it (in the test's temp folder, never BACKUP_DIR)."""
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(FAKE_AGE_HEADER)
    encrypted = path.with_name(path.name + ".age")
    encrypted.write_bytes(resp.content)
    path.write_bytes(open_archive(encrypted))
    return path


def test_download_holds_dump_photos_and_manifest(client, coin, fake_dump, tmp_path):
    upload = client.post(
        f"/api/items/{coin['id']}/photos", files={"file": ("obv.png", image_bytes(), "image/png")}
    )
    assert upload.status_code == 201
    receipt = client.post(
        f"/api/items/{coin['id']}/documents",
        files={"file": ("receipt.png", image_bytes(), "image/png")},
    )
    assert receipt.status_code == 201

    resp = client.get("/api/backup.zip")
    assert resp.headers["content-type"] == "application/octet-stream"
    assert re.search(
        r'filename="cabinet-backup-\d{8}-\d{6}\.zip\.age"', resp.headers["content-disposition"]
    )
    archive = _save(resp, tmp_path.parent / f"{tmp_path.name}-download.zip")

    manifest = backup.verify_archive(archive)
    assert manifest["format"] == "cabinet-backup"
    assert manifest["counts"] == {
        "items": 1,
        "in_trash": 0,
        "photos": 1,
        "documents": 1,
        "estimates": 0,
    }
    assert manifest["includes_photos"] is manifest["includes_documents"] is True
    assert manifest["app_version"] == client.get("/api/health").json()["version"]
    with zipfile.ZipFile(archive) as zf:
        assert set(zf.namelist()) == {
            "db.dump",
            "photos.tar.gz",
            "documents.tar.gz",
            "manifest.json",
            "SHA256SUMS",
        }
        assert zf.read("db.dump") == FAKE_DUMP
        sums = zf.read("SHA256SUMS").decode().splitlines()
        assert sorted(sums) == sorted(
            f"{m['sha256']}  {name}" for name, m in manifest["members"].items()
        )
        with tarfile.open(fileobj=io.BytesIO(zf.read("photos.tar.gz"))) as tar:
            assert any(member.isfile() for member in tar.getmembers())
        with tarfile.open(fileobj=io.BytesIO(zf.read("documents.tar.gz"))) as tar:
            assert any(m.name.endswith("original.png") for m in tar.getmembers())

    # the temp archive behind the download is gone once it has been sent
    assert not list(Path(get_settings().backup_dir).glob(".download-*"))


def test_data_only_download(client, coin, fake_dump, tmp_path):
    resp = client.get("/api/backup.zip?photos=false")
    assert "-data.zip.age" in resp.headers["content-disposition"]
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
    assert client.put("/api/settings", json={"backup_retention_days": 7}).status_code == 200
    dest = Path(get_settings().backup_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "notes.txt").write_text("not ours")

    names = []
    for step in range(3):  # five days apart: the first is past 7 days at the third
        clock[0] = datetime(2026, 9, 4 + 5 * step, 3, 15 + step, tzinfo=UTC)
        resp = client.post("/api/backups")
        assert resp.status_code == 200, resp.text
        names.append(resp.json()["file"])
    assert names[2] == "cabinet-backup-20260914-031700.zip.age"
    assert resp.json()["pruned"] == [names[0]]

    listing = client.get("/api/backups").json()
    assert [b["name"] for b in listing["backups"]] == [names[2], names[1]]
    assert listing["backups"][0]["created_at"].startswith("2026-09-14T03:17:00")
    assert listing["last_run"]["ok"] is True and listing["last_run"]["file"] == names[2]
    assert listing["free_bytes"] > 0
    assert (dest / "notes.txt").exists()  # retention only touches Cabinet's archives

    stored = client.get(f"/api/backups/{names[2]}")
    assert stored.status_code == 200 and stored.content.startswith(FAKE_AGE_HEADER)
    assert client.get(f"/api/backups/{names[0]}").status_code == 404
    assert client.get("/api/backups/notes.txt").status_code == 404


def test_back_up_now_follows_the_photos_setting(client, fake_dump, clock):
    client.put("/api/settings", json={"backup_include_photos": False})
    assert client.post("/api/backups").json()["file"].endswith("-data.zip.age")
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
    assert body["backup_retention_days"] == 90
    assert body["backup_include_photos"] is True
    assert body["backup_retention_choices"] == {
        "daily": [7, 14, 30, 90, 365],
        "weekly": [28, 56, 91, 182, 365],
    }

    resp = client.put(
        "/api/settings",
        json={
            "backup_schedule": "weekly",
            "backup_retention_days": 30,
            "backup_include_photos": False,
        },
    )
    body = resp.json()
    assert (body["backup_schedule"], body["backup_retention_days"]) == ("weekly", 30)
    assert body["backup_include_photos"] is False
    body = client.put("/api/settings", json={"backup_retention_days": 0}).json()  # forever
    assert body["backup_retention_days"] == 0
    assert client.get("/api/settings").json()["backup_retention_days"] == 0

    # Values from either schedule's set are accepted, whatever the current
    # schedule is: the frontend snaps to the new set when the schedule
    # changes, so the backend only enforces "a sensible number of days."
    for good in (28, 91, 365):
        assert client.put("/api/settings", json={"backup_retention_days": good}).status_code == 200

    assert client.put("/api/settings", json={"backup_schedule": "hourly"}).status_code == 422
    for bad in (-1, 5, 29, 366):
        assert client.put("/api/settings", json={"backup_retention_days": bad}).status_code == 422
    # the outcome record is the service's to write, not the API's
    client.put("/api/settings", json={"backup_last_run": {"ok": True}})
    assert client.get("/api/backups").json()["last_run"] is None


def test_retention_choices_follow_the_schedule():
    assert backup.retention_choices(None) == backup.DAILY_RETENTION_CHOICES
    assert backup.retention_choices("daily") == backup.DAILY_RETENTION_CHOICES
    assert backup.retention_choices("weekly") == backup.WEEKLY_RETENTION_CHOICES
    assert backup.RETENTION_CHOICES == tuple(
        sorted(set(backup.DAILY_RETENTION_CHOICES) | set(backup.WEEKLY_RETENTION_CHOICES))
    )


def test_retention_is_by_age_and_keeps_the_newest_of_each_kind(tmp_path, clock):
    """Archives older than the retention go (dated by name, never mtime),
    but the newest full and the newest data-only archive stay whatever
    their age, so a schedule that stopped can't leave nothing; `0`
    keeps everything (v0.30.1)."""
    full = [f"cabinet-backup-2026090{d}-010000.zip.age" for d in range(1, 8)]
    data = [f"cabinet-backup-2026091{d}-010000-data.zip.age" for d in range(1, 8)]
    for name in full + data:
        (tmp_path / name).write_bytes(b"x")
    clock[0] = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)  # cutoff for 7 days: 13 Sept

    assert backup.prune(tmp_path, 0) == []
    removed = backup.prune(tmp_path, 7)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in left if "-data" not in n] == full[-1:]  # all old: the newest stays
    assert [n for n in left if "-data" in n] == data[3:]  # 11 to 13 Sept expired
    assert len(removed) == 9

    clock[0] = datetime(2030, 1, 1, tzinfo=UTC)  # everything is old now
    assert len(backup.prune(tmp_path, 7)) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == [full[-1], data[-1]]


def test_delete_a_stored_backup(client, coin, fake_dump, clock):
    """`DELETE /api/backups/{name}` (v0.30.1, admin and fresh: the gate
    matrix covers that) removes one archive, is audited, and is refused
    while a backup or restore holds the directory."""
    first = client.post("/api/backups").json()["file"]
    clock[0] += timedelta(minutes=1)
    second = client.post("/api/backups").json()["file"]

    assert client.delete("/api/backups/notes.txt").status_code == 404
    assert client.delete("/api/backups/cabinet-backup-20260101-000000.zip.age").status_code == 404
    backup._run_lock.acquire()
    try:
        assert client.delete(f"/api/backups/{first}").status_code == 409
    finally:
        backup._run_lock.release()

    resp = client.delete(f"/api/backups/{first}")
    assert resp.status_code == 200 and resp.json() == {"deleted": first}
    assert [b["name"] for b in client.get("/api/backups").json()["backups"]] == [second]
    assert client.get(f"/api/backups/{first}").status_code == 404
    assert client.delete(f"/api/backups/{first}").status_code == 404
    rows = _session().scalars(select(AuditEntry).where(AuditEntry.action == "backup_deleted"))
    assert [r.target for r in rows] == [first]
