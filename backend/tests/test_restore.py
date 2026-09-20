"""In-app restore: inspecting an archive, the safeguards, the run itself
(database step faked: SQLite has no pg_restore), and the file swap."""

import hashlib
import io
import json
import os
import shutil
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import backup, maintenance, restore, scheduled, schema
from tests.conftest import COIN, image_bytes
from tests.test_backup import FAKE_DUMP, _session

UTC = timezone.utc
HEAD = schema.script_revisions()[0]


@pytest.fixture()
def fake_dump(monkeypatch):
    def dump(out, server_major):
        out.write(FAKE_DUMP)
        return "pg_dump (fake)"

    monkeypatch.setattr(backup, "dump_database", dump)
    # create_all leaves no alembic_version; archives must name a revision.
    revision = [HEAD]
    monkeypatch.setattr(schema, "current_revision", lambda conn: revision[0])
    return revision


@pytest.fixture()
def clock(monkeypatch):
    now = [datetime(2026, 9, 14, 3, 15, tzinfo=UTC)]
    monkeypatch.setattr(backup, "utcnow", lambda: now[0])
    return now


@pytest.fixture()
def calls(monkeypatch):
    """Run the restore inline, with the database step recorded, not run."""
    seen = {"dumps": [], "migrated": 0, "during": None}

    def fake_restore(dump_path):
        seen["dumps"].append(Path(dump_path).read_bytes())
        if seen["during"]:
            seen["during"]()

    monkeypatch.setattr(restore, "restore_database", fake_restore)
    monkeypatch.setattr(restore, "_spawn", lambda fn: fn())
    # Disposing the tests' StaticPool engine would drop the in-memory database.
    monkeypatch.setattr(restore, "dispose_engine", lambda engine: None)
    monkeypatch.setattr(
        restore, "migrate", lambda engine: seen.__setitem__("migrated", seen["migrated"] + 1)
    )
    return seen


def _dirs():
    config = get_settings()
    return Path(config.photo_dir), Path(config.document_dir), Path(config.backup_dir)


def _stored(client, photos: bool | None = None) -> str:
    query = "" if photos is None else f"?photos={str(photos).lower()}"
    resp = client.post(f"/api/backups{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()["file"]


def _inspect(client, name: str) -> dict:
    resp = client.post(f"/api/restore/inspect?name={name}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run(client, restore_id: str, phrase: str = "RESTORE"):
    return client.post(f"/api/restore/{restore_id}/run", json={"confirm": phrase})


def _rewrite(src: Path, dst: Path, manifest=None, replace=None, drop=()) -> Path:
    """Copy an archive, editing its manifest or members on the way."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            if name in drop:
                continue
            data = zin.read(name)
            if name == "manifest.json" and manifest:
                edited = json.loads(data)
                manifest(edited)
                data = json.dumps(edited).encode()
            if replace and name in replace:
                data = replace[name]
            zout.writestr(name, data)
    return dst


def _tar(members: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                tar.addfile(member)
            else:
                info = tarfile.TarInfo(member[0])
                info.size = len(member[1])
                tar.addfile(info, io.BytesIO(member[1]))
    return buf.getvalue()


def _archive_with(path: Path, files: dict[str, bytes]) -> Path:
    """A well-formed archive (checksums and all) around the given members."""
    members = {"db.dump": FAKE_DUMP, **files}
    manifest = {
        "format": "cabinet-backup",
        "format_version": 1,
        "app_version": "0.0.0",
        "schema_revision": HEAD,
        "created_at": "2026-09-01T00:00:00+00:00",
        "counts": {"items": 1, "in_trash": 0, "photos": 1, "documents": 0},
        "members": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in members.items()
        },
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest))
    return path


def _upload(client, path: Path, filename: str = "my-backup.zip"):
    with open(path, "rb") as fh:
        return client.post(
            "/api/restore/inspect", files={"file": (filename, fh, "application/zip")}
        )


# --- inspect ----------------------------------------------------------------


def test_inspect_by_name_summarises_archive_and_current(client, coin, fake_dump, clock):
    client.post(
        f"/api/items/{coin['id']}/photos", files={"file": ("o.png", image_bytes(), "image/png")}
    )
    name = _stored(client)
    client.post("/api/items", json=COIN)  # here now, not in the archive
    trashed = client.post("/api/items", json=COIN).json()["id"]
    client.delete(f"/api/items/{trashed}")

    body = _inspect(client, name)  # no request body at all
    assert len(body["restore_id"]) == 32
    archive = body["archive"]
    assert archive["name"] == name and archive["size"] > 0
    assert archive["created_at"].startswith("2026-09-14T03:15")
    assert archive["app_version"] == client.get("/api/health").json()["version"]
    assert archive["revision"] == HEAD
    assert archive["includes_photos"] is archive["includes_documents"] is True
    assert (archive["items"], archive["photos"], archive["documents"]) == (1, 1, 0)
    assert archive["trashed"] == 0
    assert body["current"] == {
        "revision": HEAD,
        "items": 3,
        "photos": 1,
        "documents": 0,
        "trashed": 1,
    }
    assert body["will_migrate"] is False
    assert body["replaces_files"] is True
    assert "SECRET_KEY" in body["secrets_note"]


def test_inspect_data_only_archive(client, coin, fake_dump):
    body = _inspect(client, _stored(client, photos=False))
    assert body["replaces_files"] is False
    assert body["archive"]["includes_photos"] is body["archive"]["includes_documents"] is False


def test_inspect_older_revision_will_migrate(client, coin, fake_dump):
    older = sorted(schema.script_revisions()[1] - {HEAD})[0]
    fake_dump[0] = older
    name = _stored(client)
    fake_dump[0] = HEAD
    body = _inspect(client, name)
    assert body["will_migrate"] is True
    assert body["archive"]["revision"] == older


def test_inspect_unknown_name_and_traversal(client, fake_dump):
    _, _, backups = _dirs()
    backups.mkdir(parents=True, exist_ok=True)
    (backups.parent / "cabinet-backup-20260101-000000.zip").write_bytes(b"outside")
    for name in (
        "cabinet-backup-20260101-000000.zip",
        "../cabinet-backup-20260101-000000.zip",
        "..%2Fcabinet-backup-20260101-000000.zip",
        "notes.txt",
    ):
        resp = client.post(f"/api/restore/inspect?name={name}")
        assert resp.status_code == 404, name
        assert isinstance(resp.json()["detail"], str)
    assert client.post("/api/restore/inspect").status_code == 422


def test_inspect_rejects_bad_archives(client, coin, fake_dump, tmp_path):
    _, _, backups = _dirs()
    good = backups / _stored(client)
    work = tmp_path.with_name(tmp_path.name + "-work")
    work.mkdir()

    not_zip = work / "plain.zip"
    not_zip.write_bytes(b"this is not a zip")
    cases = {
        "not a zip": not_zip,
        "manifest.json": _rewrite(good, work / "nomanifest.zip", drop={"manifest.json"}),
        "Not a Cabinet backup": _rewrite(
            good, work / "format.zip", manifest=lambda m: m.update(format="something-else")
        ),
        "db.dump does not match": _rewrite(
            good, work / "tampered.zip", replace={"db.dump": b"tampered"}
        ),
        "newer Cabinet": _rewrite(
            good, work / "newer.zip", manifest=lambda m: m.update(schema_revision="9999")
        ),
        "schema revision": _rewrite(
            good, work / "norev.zip", manifest=lambda m: m.update(schema_revision=None)
        ),
    }
    for expected, path in cases.items():
        resp = _upload(client, path)
        assert resp.status_code == 422, expected
        detail = resp.json()["detail"]
        assert isinstance(detail, str) and expected in detail, detail
    # nothing rejected stays staged
    assert list((backups / ".restore-staging").iterdir()) == []


def test_inspect_rejects_unsafe_tar_members(client, fake_dump, tmp_path):
    work = tmp_path.with_name(tmp_path.name + "-work")
    work.mkdir()
    link = tarfile.TarInfo("./escape")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc"
    for label, tar in {
        "dotdot": _tar([("../evil.txt", b"x")]),
        "absolute": _tar([("/etc/evil.txt", b"x")]),
        "link": _tar([link]),
    }.items():
        resp = _upload(client, _archive_with(work / f"{label}.zip", {"photos.tar.gz": tar}))
        assert resp.status_code == 422, label
        assert "archive holds" in resp.json()["detail"]


def test_upload_is_staged_and_discarded(client, coin, fake_dump, tmp_path):
    _, _, backups = _dirs()
    download = tmp_path.with_name(tmp_path.name + "-dl.zip")
    download.write_bytes(client.get("/api/backup.zip").content)

    resp = _upload(client, download, filename="C:\\Users\\me\\from-the-nas.zip")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["archive"]["name"] == "from-the-nas.zip"
    staged = backups / ".restore-staging" / f"{body['restore_id']}.zip"
    assert staged.read_bytes() == download.read_bytes()
    # the staging folder is not an archive: never listed, never pruned
    assert client.get("/api/backups").json()["backups"] == []
    assert backup.prune(backups, 1) == [] and staged.exists()

    assert client.delete(f"/api/restore/{body['restore_id']}").status_code == 204
    assert not staged.exists()
    assert client.delete(f"/api/restore/{body['restore_id']}").status_code == 404
    assert _run(client, body["restore_id"]).status_code == 404


def test_discard_never_deletes_a_stored_archive(client, coin, fake_dump):
    _, _, backups = _dirs()
    name = _stored(client)
    restore_id = _inspect(client, name)["restore_id"]
    assert client.delete(f"/api/restore/{restore_id}").status_code == 204
    assert (backups / name).is_file()
    assert _run(client, restore_id).status_code == 404  # forgotten, that's all
    assert client.delete("/api/restore/not-an-id").status_code == 404


def test_upload_over_the_limit_is_413(client, coin, fake_dump, monkeypatch, tmp_path):
    download = tmp_path.with_name(tmp_path.name + "-dl.zip")
    download.write_bytes(client.get("/api/backup.zip").content)
    monkeypatch.setenv("RESTORE_MAX_GB", "0.0000001")  # about 100 bytes
    get_settings.cache_clear()
    resp = _upload(client, download)
    assert resp.status_code == 413
    assert "RESTORE_MAX_GB" in resp.json()["detail"]
    assert list((_dirs()[2] / ".restore-staging").iterdir()) == []


def test_stale_staged_uploads_are_removed(client, fake_dump):
    staging = restore.staging_dir()
    old, fresh = staging / ("a" * 32 + ".zip"), staging / ("b" * 32 + ".zip")
    for path in (old, fresh):
        path.write_bytes(b"x")
    then = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(old, (then, then))
    restore.clean_staging()
    assert not old.exists() and fresh.exists()


# --- run ---------------------------------------------------------------------


def test_run_needs_the_exact_phrase(client, coin, fake_dump, calls):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    for phrase in ("restore", "RESTORE ", "", "yes"):
        resp = _run(client, restore_id, phrase)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], str)
    assert client.post(f"/api/restore/{restore_id}/run", json={}).status_code == 422
    assert calls["dumps"] == []
    assert _run(client, "0" * 32).status_code == 404
    assert client.get("/api/restore/status").json()["state"] == "idle"


def test_run_restores_database_and_swaps_files(client, coin, fake_dump, calls, clock):
    photos, documents, backups = _dirs()
    client.post(
        f"/api/items/{coin['id']}/photos", files={"file": ("o.png", image_bytes(), "image/png")}
    )
    client.post(
        f"/api/items/{coin['id']}/documents",
        files={"file": ("receipt.png", image_bytes(), "image/png")},
    )
    before = {
        p.relative_to(photos).as_posix(): p.read_bytes() for p in photos.rglob("*") if p.is_file()
    }
    docs_before = sorted(p.name for p in documents.rglob("*") if p.is_file())
    assert before and docs_before
    name = _stored(client)

    # after the backup: a new file, and an archived one changed
    (photos / "added-later.txt").write_text("not in the archive")
    victim = photos / next(iter(before))
    victim.write_bytes(b"overwritten")
    for path in list(documents.iterdir()):
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    (documents / "stray.pdf").write_bytes(b"stray")

    def during():
        # the database step: API closed, status and health still answer
        assert client.get("/api/items").status_code == 503
        assert "restoring" in client.get("/api/items").json()["detail"]
        assert client.post("/api/backups").status_code == 503
        status = client.get("/api/restore/status").json()
        assert (status["state"], status["step"]) == ("running", "database")
        assert status["started_at"]
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["db"] == "restoring"
        assert scheduled.hourly(_session()) is None  # sits out
        assert scheduled.refresh(_session()) == {}
        # nothing live has been touched yet
        assert victim.read_bytes() == b"overwritten"

    calls["during"] = during
    clock[0] += timedelta(minutes=5)
    restore_id = _inspect(client, name)["restore_id"]
    resp = _run(client, restore_id)
    assert resp.status_code == 202 and resp.json() == {"state": "running"}

    assert calls["dumps"] == [FAKE_DUMP] and calls["migrated"] == 0
    status = client.get("/api/restore/status").json()
    assert status["state"] == "done" and status["step"] is None
    last = status["last"]
    assert last["ok"] is True and last["error"] is None
    assert last["archive"] == name
    assert last["archive_created_at"].startswith("2026-09-14T03:15")
    assert (last["items"], last["photos"], last["documents"]) == (1, 1, 1)
    assert last["safety_backup"] == "cabinet-backup-20260914-032000-prerestore.zip"

    after = {
        p.relative_to(photos).as_posix(): p.read_bytes() for p in photos.rglob("*") if p.is_file()
    }
    assert after == before
    assert sorted(p.name for p in documents.rglob("*") if p.is_file()) == docs_before
    for folder in (photos, documents):
        assert not [p for p in folder.iterdir() if p.name.startswith(".restore-")]
    assert list((backups / ".restore-staging").iterdir()) == []  # the unpacked dump is gone

    # the safety backup holds the state just before, files included
    safety = backups / last["safety_backup"]
    with (
        zipfile.ZipFile(safety) as zf,
        tarfile.open(fileobj=io.BytesIO(zf.read("photos.tar.gz"))) as tar,
    ):
        assert "./added-later.txt" in tar.getnames()
    listing = client.get("/api/backups").json()["backups"]
    assert [(b["name"], b["prerestore"]) for b in listing] == [
        (last["safety_backup"], True),
        (name, False),
    ]

    # maintenance is over, and the outcome is on the state volume
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/health").json()["db"] != "restoring"
    saved = Path(get_settings().secret_key_file).parent / "restore_last.json"
    assert json.loads(saved.read_text())["safety_backup"] == last["safety_backup"]
    assert not saved.with_name("restore_journal.json").exists()
    # a backup straight afterwards isn't refused as "already running"
    clock[0] += timedelta(minutes=1)
    assert client.post("/api/backups").status_code == 200

    # after a restart the state is idle and `last` comes from the file
    restore.reset_memory()
    status = client.get("/api/restore/status").json()
    assert status["state"] == "idle" and status["last"]["ok"] is True


def test_data_only_archive_leaves_files_alone(client, coin, fake_dump, calls, clock):
    photos, documents, backups = _dirs()
    (photos / "keep.txt").write_text("still here")
    documents.mkdir(parents=True, exist_ok=True)
    (documents / "keep.pdf").write_bytes(b"still here")
    name = _stored(client, photos=False)
    clock[0] += timedelta(minutes=1)
    assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202

    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is True
    assert (photos / "keep.txt").read_text() == "still here"
    assert (documents / "keep.pdf").read_bytes() == b"still here"
    # and the safety backup is data-only too
    with zipfile.ZipFile(backups / last["safety_backup"]) as zf:
        assert "photos.tar.gz" not in zf.namelist()


def test_older_archive_is_migrated(client, coin, fake_dump, calls, clock):
    fake_dump[0] = sorted(schema.script_revisions()[1] - {HEAD})[0]
    name = _stored(client)
    fake_dump[0] = HEAD
    clock[0] += timedelta(minutes=1)
    seen = []
    calls["during"] = lambda: seen.append(calls["migrated"])
    assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202
    assert seen == [0] and calls["migrated"] == 1  # after the database step
    assert client.get("/api/restore/status").json()["state"] == "done"


def test_restore_from_an_upload_removes_the_staged_file(client, coin, fake_dump, calls, tmp_path):
    download = tmp_path.with_name(tmp_path.name + "-dl.zip")
    download.write_bytes(client.get("/api/backup.zip").content)
    body = _upload(client, download).json()
    assert _run(client, body["restore_id"]).status_code == 202
    status = client.get("/api/restore/status").json()
    assert status["state"] == "done" and status["last"]["archive"] == "my-backup.zip"
    staged = _dirs()[2] / ".restore-staging"
    assert list(staged.iterdir()) == []


def test_failed_safety_backup_stops_the_restore(client, coin, fake_dump, calls, monkeypatch):
    photos, _, backups = _dirs()
    name = _stored(client)
    (photos / "live.txt").write_text("live")
    restore_id = _inspect(client, name)["restore_id"]

    def broken(out, server_major):
        raise backup.BackupError("pg_dump failed: connection refused")

    monkeypatch.setattr(backup, "dump_database", broken)
    assert _run(client, restore_id).status_code == 202
    status = client.get("/api/restore/status").json()
    assert status["state"] == "failed"
    error = status["last"]["error"]
    assert "safety backup failed" in error and "connection refused" in error
    assert error.endswith("Nothing was changed.")
    assert status["last"]["ok"] is False and status["last"]["safety_backup"] is None
    assert calls["dumps"] == []
    assert (photos / "live.txt").read_text() == "live"
    assert not list(backups.glob("*prerestore*"))
    assert client.get("/api/items").status_code == 200  # maintenance is off again


def test_failed_database_step_changes_nothing(client, coin, fake_dump, calls, clock):
    photos, documents, _ = _dirs()
    (photos / "in-archive.txt").write_text("archived")
    name = _stored(client)
    (photos / "in-archive.txt").write_text("changed since")
    clock[0] += timedelta(minutes=1)

    def fail():
        raise restore.RestoreError("pg_restore failed: relation is locked")

    calls["during"] = fail
    restore_id = _inspect(client, name)["restore_id"]
    assert _run(client, restore_id).status_code == 202
    status = client.get("/api/restore/status").json()
    assert status["state"] == "failed"
    assert "relation is locked" in status["last"]["error"]
    assert status["last"]["error"].endswith("Nothing was changed.")
    assert status["last"]["safety_backup"].endswith("-prerestore.zip")
    assert (photos / "in-archive.txt").read_text() == "changed since"
    assert not (photos / ".restore-new").exists() and not (documents / ".restore-new").exists()
    # the id still works for another try
    calls["during"] = None
    clock[0] += timedelta(minutes=1)
    assert _run(client, restore_id).status_code == 202
    assert client.get("/api/restore/status").json()["state"] == "done"
    assert (photos / "in-archive.txt").read_text() == "archived"


def test_database_failure_after_dropping_newer_tables_says_so(client, coin, fake_dump, calls):
    def fail():
        raise restore.PartialDatabase("pg_restore failed: boom. Newer tables were removed (x).")

    calls["during"] = fail
    assert _run(client, _inspect(client, _stored(client))["restore_id"]).status_code == 202
    last = client.get("/api/restore/status").json()["last"]
    assert "Nothing was changed" not in last["error"]
    assert f"Restore {last['safety_backup']} to return" in last["error"]


def test_failed_file_step_puts_the_old_files_back(client, coin, fake_dump, calls, monkeypatch):
    photos, documents, _ = _dirs()
    documents.mkdir(parents=True, exist_ok=True)
    (photos / "a.txt").write_text("archived photo")
    (documents / "d.txt").write_text("archived doc")
    name = _stored(client)
    (photos / "a.txt").write_text("current photo")
    (photos / "b.txt").write_text("current only")
    (documents / "d.txt").write_text("current doc")

    real_apply = restore._Swap.apply

    def apply(self):
        if self.folder == documents:
            # half way: some entries moved out, then the disk says no
            self.old.mkdir(exist_ok=True)
            (documents / "d.txt").rename(self.old / "d.txt")
            raise OSError("No space left on device")
        real_apply(self)

    monkeypatch.setattr(restore._Swap, "apply", apply)
    assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202
    status = client.get("/api/restore/status").json()
    assert status["state"] == "failed"
    error = status["last"]["error"]
    assert "the previous files were put back" in error and "No space left" in error
    assert status["last"]["safety_backup"] in error
    assert (photos / "a.txt").read_text() == "current photo"
    assert (photos / "b.txt").read_text() == "current only"
    assert (documents / "d.txt").read_text() == "current doc"
    for folder in (photos, documents):
        assert not [p for p in folder.iterdir() if p.name.startswith(".restore-")]
    assert client.get("/api/items").status_code == 200


def test_extract_refuses_unsafe_members(client, tmp_path):
    work = tmp_path.with_name(tmp_path.name + "-work")
    target = work / "volume"
    target.mkdir(parents=True)
    link = tarfile.TarInfo("./sub/escape")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../outside"
    hard = tarfile.TarInfo("./hard")
    hard.type = tarfile.LNKTYPE
    hard.linkname = "/etc/passwd"
    for label, tar in {
        "dotdot": _tar([("./ok.txt", b"fine"), ("./../outside.txt", b"x")]),
        "absolute": _tar([("/outside.txt", b"x")]),
        "symlink": _tar([link]),
        "hardlink": _tar([hard]),
    }.items():
        archive = _archive_with(work / f"{label}.zip", {"photos.tar.gz": tar})
        with pytest.raises(restore.RestoreError, match="archive holds"):
            restore._extract(archive, "photos.tar.gz", target)
        assert not (work / "outside.txt").exists()
        shutil.rmtree(target / ".restore-new")

    # a restore's own working folders inside an archive are skipped
    fine = _tar([("./keep/a.txt", b"a"), ("./.restore-old/x.txt", b"x")])
    restore._extract(
        _archive_with(work / "fine.zip", {"photos.tar.gz": fine}), "photos.tar.gz", target
    )
    assert (target / ".restore-new" / "keep" / "a.txt").read_bytes() == b"a"
    assert not (target / ".restore-new" / ".restore-old").exists()


def test_working_folders_stay_out_of_backups(client, coin, fake_dump, tmp_path):
    photos, _, _ = _dirs()
    (photos / ".restore-old").mkdir()
    (photos / ".restore-old" / "secret.txt").write_text("x")
    (photos / "real.txt").write_text("y")
    archive = tmp_path.with_name(tmp_path.name + "-dl.zip")
    archive.write_bytes(client.get("/api/backup.zip").content)
    with (
        zipfile.ZipFile(archive) as zf,
        tarfile.open(fileobj=io.BytesIO(zf.read("photos.tar.gz"))) as tar,
    ):
        names = tar.getnames()
    assert "./real.txt" in names
    assert not [n for n in names if ".restore-" in n]


def test_leftover_old_files_block_a_restore(client, coin, fake_dump, calls):
    photos, _, _ = _dirs()
    name = _stored(client)
    (photos / ".restore-old").mkdir()
    (photos / ".restore-old" / "stranded.jpg").write_bytes(b"only copy")
    assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202
    status = client.get("/api/restore/status").json()
    assert status["state"] == "failed" and ".restore-old" in status["last"]["error"]
    assert (photos / ".restore-old" / "stranded.jpg").read_bytes() == b"only copy"
    assert calls["dumps"] == []


def test_busy_is_409(client, coin, fake_dump, calls):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    for lock in (backup._run_lock, restore._lock, maintenance._scheduled):
        lock.acquire()
        try:
            resp = _run(client, restore_id)
            assert resp.status_code == 409 and isinstance(resp.json()["detail"], str)
        finally:
            lock.release()
    assert calls["dumps"] == []
    assert client.get("/api/restore/status").json()["state"] == "idle"
    # and a backup can't start while a restore holds the lock
    calls["during"] = lambda: pytest.raises(backup.BackupBusy, backup.run_backup, _session())
    assert _run(client, restore_id).status_code == 202
    assert client.get("/api/restore/status").json()["state"] == "done"


def test_disabled_by_the_deployment(client, coin, fake_dump, monkeypatch):
    name = _stored(client)
    restore_id = _inspect(client, name)["restore_id"]
    monkeypatch.setenv("RESTORE_ENABLED", "false")
    get_settings.cache_clear()
    status = client.get("/api/restore/status")
    assert status.status_code == 200
    assert status.json() == {
        "enabled": False,
        "state": "idle",
        "step": None,
        "started_at": None,
        "last": None,
        "confirm_phrase": "RESTORE",
    }
    assert client.post(f"/api/restore/inspect?name={name}").status_code == 404
    assert _run(client, restore_id).status_code == 404
    assert client.delete(f"/api/restore/{restore_id}").status_code == 404
    assert (_dirs()[2] / name).is_file()


def test_prerestore_archives_have_their_own_retention(client, coin, fake_dump, calls, clock):
    _, _, backups = _dirs()
    client.put("/api/settings", json={"backup_keep": 2})
    name = _stored(client)
    safeties = []
    for _ in range(5):
        clock[0] += timedelta(minutes=1)
        assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202
        safeties.append(client.get("/api/restore/status").json()["last"]["safety_backup"])
    kept = sorted(p.name for p in backups.glob("*-prerestore.zip"))
    assert kept == sorted(safeties[-3:])

    # ordinary retention neither counts nor removes them
    for _ in range(3):
        clock[0] += timedelta(minutes=1)
        _stored(client)
    listing = client.get("/api/backups").json()["backups"]
    assert sorted(b["name"] for b in listing if b["prerestore"]) == kept
    assert len([b for b in listing if not b["prerestore"]]) == 2
    assert all(b["created_at"] for b in listing)
    # and one of them restores like any other, without pruning itself away
    oldest = kept[0]
    clock[0] += timedelta(minutes=1)
    assert _run(client, _inspect(client, oldest)["restore_id"]).status_code == 202
    assert client.get("/api/restore/status").json()["state"] == "done"
    assert client.get(f"/api/backups/{oldest}").status_code == 200


# --- interrupted runs ---------------------------------------------------------


def _journal(phase: str) -> Path:
    path = Path(get_settings().secret_key_file).parent / "restore_journal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"phase": phase, "archive": "x.zip", "at": "2026-09-14T00:00:00"}))
    return path


def test_recover_rolls_an_interrupted_swap_forward(client):
    photos, _, _ = _dirs()
    (photos / ".restore-old").mkdir()
    (photos / ".restore-old" / "old-1.txt").write_text("old")
    (photos / "old-2.txt").write_text("old, not yet moved out")
    (photos / ".restore-new").mkdir()
    (photos / ".restore-new" / "new-1.txt").write_text("new")
    journal = _journal("swapping")
    restore.recover()
    assert sorted(p.name for p in photos.iterdir()) == ["new-1.txt"]
    assert not journal.exists()
    assert restore.last_outcome()["ok"] is True


def test_recover_before_the_database_step_clears_up(client):
    photos, _, _ = _dirs()
    (photos / "live.txt").write_text("live")
    (photos / ".restore-new").mkdir()
    (photos / ".restore-new" / "new.txt").write_text("new")
    journal = _journal("preparing")
    restore.recover()
    assert sorted(p.name for p in photos.iterdir()) == ["live.txt"]
    assert not journal.exists()
    last = restore.last_outcome()
    assert last["ok"] is False and last["error"].endswith("Nothing was changed.")
