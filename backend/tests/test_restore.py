"""In-app restore: inspecting an archive, the safeguards, the run itself
(database step faked: SQLite has no pg_restore), and the file swap."""

import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import backup, maintenance, restore, scheduled, schema
from tests.conftest import COIN, image_bytes, open_archive, seal
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


# What a Cabinet dump's table of contents looks like (pg_restore --list),
# with no cabinet_auth: dumps leave that schema out.
CLEAN_LISTING = [
    ";",
    "; Archive created at 2026-09-14 03:15:00 UTC",
    ";     dbname: cabinet",
    "215; 1259 16390 TABLE public items cabinet",
    "216; 1259 16400 TABLE public app_settings cabinet",
    "3401; 0 16390 TABLE DATA public items cabinet",
]


@pytest.fixture(autouse=True)
def dump_readers(monkeypatch):
    """Stand in for pg_restore reading a dump (no pg_restore here): its table
    of contents, and the app_settings rows it holds. Tests edit both."""
    seen = {"listing": list(CLEAN_LISTING), "settings": {}, "read": []}

    def list_dump(path, server_major):
        path = Path(path)
        seen["read"].append(path)
        assert path.read_bytes() == FAKE_DUMP  # the archive's own dump, unpacked
        return seen["listing"]

    monkeypatch.setattr(backup, "list_dump", list_dump)
    monkeypatch.setattr(backup, "dump_settings", lambda path, major: seen["settings"])
    return seen


@pytest.fixture()
def clock(monkeypatch):
    now = [datetime(2026, 9, 14, 3, 15, tzinfo=UTC)]
    monkeypatch.setattr(backup, "utcnow", lambda: now[0])
    return now


@pytest.fixture()
def calls(monkeypatch):
    """Run the restore inline, with the database step recorded, not run."""
    seen = {"dumps": [], "migrated": 0, "during": None}

    def fake_restore(dump_path, on_drop=None):
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


def _rewrite(src: Path, dst: Path, manifest=None, replace=None, drop=(), sign=True) -> Path:
    """Copy an archive, editing its manifest or members on the way, then
    encrypt it again. Re-signed by default, so the checks after the MAC are
    what's tested; `sign=False` keeps the old MAC, as a forger would have to."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(open_archive(src))) as zin, zipfile.ZipFile(buf, "w") as zout:
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
    dst.write_bytes(seal(buf.getvalue(), sign=sign and "manifest.json" not in drop))
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr(
            "SHA256SUMS", "".join(f"{m['sha256']}  {n}\n" for n, m in manifest["members"].items())
        )
    path.write_bytes(seal(buf.getvalue()))
    return path


def _plain(path: Path) -> zipfile.ZipFile:
    """An encrypted archive's decrypted zip, opened (tests only)."""
    return zipfile.ZipFile(io.BytesIO(open_archive(path)))


def _restore(client, name: str):
    """Inspect a stored archive and run it with the phrase it asks for
    (RESTORE, or RESTORE OLDER for an archive older than the newest)."""
    body = _inspect(client, name)
    return _run(client, body["restore_id"], body["confirm_phrase"])


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
        "Not a Cabinet backup archive": not_zip,
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
    staged = backups / ".restore-staging" / f"{body['restore_id']}.upload"
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
    staging = restore.upload_dir()
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
        # answered with no lookup of anyone, so only the status (v0.30.0)
        assert health.status_code == 200 and health.json() == {"status": "ok"}
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
    assert last["safety_backup"] == "cabinet-backup-20260914-032000-prerestore.zip.age"

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
        _plain(safety) as zf,
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
    with _plain(backups / last["safety_backup"]) as zf:
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
    assert status["last"]["safety_backup"].endswith("-prerestore.zip.age")
    assert (photos / "in-archive.txt").read_text() == "changed since"
    assert not (photos / ".restore-new").exists() and not (documents / ".restore-new").exists()
    # the id still works for another try, but the safety backup it took is
    # now the newest archive, so the retry is a restore of an older one
    calls["during"] = None
    clock[0] += timedelta(minutes=1)
    resp = _run(client, restore_id)
    assert resp.status_code == 422 and "RESTORE OLDER" in resp.json()["detail"]
    assert _run(client, restore_id, "RESTORE OLDER").status_code == 202
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
        archive = work / f"{label}.zip"  # _extract reads the decrypted zip
        archive.write_bytes(
            open_archive(_archive_with(work / f"{label}.age", {"photos.tar.gz": tar}))
        )
        with pytest.raises(restore.RestoreError, match="archive holds"):
            restore._extract(archive, "photos.tar.gz", target)
        assert not (work / "outside.txt").exists()
        shutil.rmtree(target / ".restore-new")

    # a restore's own working folders inside an archive are skipped
    fine = _tar([("./keep/a.txt", b"a"), ("./.restore-old/x.txt", b"x")])
    plain = work / "fine.zip"
    plain.write_bytes(open_archive(_archive_with(work / "fine.age", {"photos.tar.gz": fine})))
    restore._extract(plain, "photos.tar.gz", target)
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
        _plain(archive) as zf,
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
        # each run's safety backup is newer, so from the second on it is "older"
        assert _restore(client, name).status_code == 202
        safeties.append(client.get("/api/restore/status").json()["last"]["safety_backup"])
    kept = sorted(p.name for p in backups.glob("*-prerestore.zip.age"))
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
    assert _restore(client, oldest).status_code == 202
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


def test_a_folder_the_backend_cannot_move_stops_the_restore_before_the_database(
    tmp_path, monkeypatch
):
    # Found on the first NFS restore: photos uploaded as root before v0.23.1
    # sat in folders the unprivileged backend couldn't move, and the swap
    # failed after the database had been replaced.
    photos = tmp_path / "photos"
    (photos / "old-item").mkdir(parents=True)
    (photos / "fine-item").mkdir()
    monkeypatch.setattr(restore, "_file_targets", lambda: (("photos.tar.gz", "photos", photos),))
    real = restore.os.access
    monkeypatch.setattr(
        restore.os, "access", lambda p, mode: Path(p).name != "old-item" and real(p, mode)
    )

    with pytest.raises(restore.RestoreError) as err:
        restore.check_movable({"members": {"db.dump": {}, "photos.tar.gz": {}}})
    assert "old-item" in str(err.value) and "1 folder(s)" in str(err.value)

    restore.check_movable({"members": {"db.dump": {}}})  # data-only: files aren't touched


# --- v0.30.0: sign-in data, the private staging folder, the marker -----------


def _engine():
    return _session().get_bind()


def _staging() -> Path:
    return Path(get_settings().staging_dir)


def _plant_setting(key: str, value) -> None:
    """Write straight into app_settings, as an archive's database would."""
    from app.models import AppSetting

    db = _session()
    try:
        db.merge(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _setting_row(key: str):
    from app.models import AppSetting

    db = _session()
    try:
        row = db.get(AppSetting, key)
        return None if row is None else row.value
    finally:
        db.close()


def test_inspect_refuses_an_archive_holding_sign_in_data(
    client, coin, fake_dump, dump_readers, tmp_path
):
    dump_readers["listing"] += [
        "5; 2615 16385 SCHEMA - cabinet_auth cabinet",
        "220; 1259 16500 TABLE cabinet_auth users cabinet",
    ]
    resp = client.post(f"/api/restore/inspect?name={_stored(client)}")
    assert resp.status_code == 422
    assert resp.json()["detail"] == restore.AUTH_REFUSED
    # an upload holding it is not kept either
    download = tmp_path / "dl.zip"
    download.write_bytes(client.get("/api/backup.zip").content)
    assert _upload(client, download).status_code == 422
    assert list((_dirs()[2] / ".restore-staging").iterdir()) == []
    assert list(_staging().iterdir()) == []


def test_a_listing_line_that_only_mentions_it_in_a_comment_is_fine(
    client, coin, fake_dump, dump_readers
):
    dump_readers["listing"] += [";     cabinet_auth was excluded"]
    assert _inspect(client, _stored(client))["restore_id"]


def test_inspect_reads_the_dump_only_in_private_staging(client, coin, fake_dump, dump_readers):
    backups = _dirs()[2]
    _inspect(client, _stored(client))
    [read] = dump_readers["read"]
    assert read.parent == _staging().resolve()
    assert list(_staging().iterdir()) == []  # gone again
    assert not list(backups.rglob("*.dump"))  # never on the backup share
    if sys.platform != "win32":
        assert stat.S_IMODE(_staging().stat().st_mode) == 0o700


def test_staged_dump_is_owner_only(client, coin, fake_dump, dump_readers, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("POSIX modes")
    modes = []

    def list_dump(path, major):
        modes.append(stat.S_IMODE(Path(path).stat().st_mode))
        return CLEAN_LISTING

    monkeypatch.setattr(backup, "list_dump", list_dump)
    _inspect(client, _stored(client))
    assert modes == [0o600]


def test_inspect_needs_room_in_staging(client, coin, fake_dump, monkeypatch):
    name = _stored(client)
    real = shutil.disk_usage
    monkeypatch.setattr(
        backup.shutil,
        "disk_usage",
        lambda path: (
            real(path)._replace(free=0) if Path(path) == _staging().resolve() else real(path)
        ),
    )
    resp = client.post(f"/api/restore/inspect?name={name}")
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("Not enough space to open this archive")


def test_staging_is_never_inside_a_shared_folder(client, monkeypatch):
    monkeypatch.setenv("STAGING_DIR", str(_dirs()[2] / "staging"))
    get_settings.cache_clear()
    with pytest.raises(backup.BackupError, match="must be apart from the backup directory"):
        backup.staging_dir()


def test_inspect_names_the_secrets_an_archive_would_set(client, coin, fake_dump, dump_readers):
    from app.services import crypto

    dump_readers["settings"] = {
        "numista_api_key": crypto.encrypt("numista-secret-1234"),  # this key: kept
        "alert_webhook_url": "https://planted.example/hook",  # plain text: cleared
        "pcgs_api_token": "",
        "display_currency": "EUR",
    }
    body = _inspect(client, _stored(client))
    assert body["credentials_note"] == restore.CREDENTIALS_NOTE
    assert body["secrets"] == ["Numista API key"]
    assert body["secrets_cleared"] == ["alert webhook"]
    text = json.dumps(body)
    assert "numista-secret" not in text and "planted.example" not in text


def test_run_refuses_sign_in_data_found_at_run_time(client, coin, fake_dump, calls, dump_readers):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    dump_readers["listing"] = CLEAN_LISTING + ["220; 1259 16500 TABLE cabinet_auth users x"]
    assert _run(client, restore_id).status_code == 202
    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is False
    assert restore.AUTH_REFUSED in last["error"] and "Nothing was changed." in last["error"]
    assert calls["dumps"] == []
    assert _setting_row(restore.MARKER_KEY) is None  # never written: refused first
    assert list(_staging().iterdir()) == []


def test_the_marker_is_journalled_and_gone_after_a_restore(client, coin, fake_dump, calls):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    seen = {}

    def during():
        journal = json.loads(restore._journal_path().read_text(encoding="utf-8"))
        seen["journal"] = journal
        seen["row"] = _setting_row(restore.MARKER_KEY)
        # the dump being restored, and the archive it came from, decrypted,
        # are both in private staging, and only there
        assert sorted(p.suffix for p in _staging().iterdir()) == [".dump", ".zip"]

    calls["during"] = during
    assert _run(client, restore_id).status_code == 202
    assert client.get("/api/restore/status").json()["last"]["ok"] is True
    assert seen["journal"]["phase"] == "database"
    assert len(seen["journal"]["marker"]) == 32 and seen["row"] == seen["journal"]["marker"]
    assert seen["journal"]["dropped"] == []
    assert _setting_row(restore.MARKER_KEY) is None
    assert list(_staging().iterdir()) == []
    assert not restore._journal_path().exists()


def test_a_marker_the_archive_brought_is_removed(client, coin, fake_dump, calls):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    calls["during"] = lambda: _plant_setting(restore.MARKER_KEY, "f" * 32)  # the archive's row
    assert _run(client, restore_id).status_code == 202
    assert _setting_row(restore.MARKER_KEY) is None


def test_a_failed_database_step_leaves_no_marker(client, coin, fake_dump, calls, monkeypatch):
    restore_id = _inspect(client, _stored(client))["restore_id"]

    def failing(dump_path, on_drop=None):
        raise restore.RestoreError("pg_restore failed: boom")

    monkeypatch.setattr(restore, "restore_database", failing)
    _run(client, restore_id)
    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is False and last["error"].endswith("Nothing was changed.")
    assert _setting_row(restore.MARKER_KEY) is None


def test_restored_plain_text_secrets_are_cleared_and_named(client, coin, fake_dump, calls):
    restore_id = _inspect(client, _stored(client))["restore_id"]
    # the archive's database brings a plain-text webhook address
    calls["during"] = lambda: _plant_setting("alert_webhook_url", "https://planted.example/x")
    assert _run(client, restore_id).status_code == 202
    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is True
    assert last["secrets_cleared"] == ["alert webhook"]
    assert _setting_row("alert_webhook_url") == ""
    assert client.get("/api/settings").json()["secrets_cleared"] == ["alert webhook"]


def test_sign_in_rows_are_untouched_by_a_restore(client, coin, fake_dump, calls, token_client):
    """A session, a read token, and a revoked token before the restore; after
    it the session and the token still answer, and the revoked one doesn't."""
    from app.auth import accounts
    from app.auth.audit import Actor
    from app.models.auth import User

    reader = token_client("read")
    revoked = token_client("read")
    db = _session()
    try:
        user = accounts.admin(db)
        row = next(t for t in accounts.tokens.live(db, user.id) if t.name == "read-1")
        accounts.revoke_token(db, user, row.id, Actor.system())
    finally:
        db.close()
    assert revoked.get("/api/items").status_code == 401

    restore_id = _inspect(client, _stored(client))["restore_id"]
    assert _run(client, restore_id).status_code == 202
    assert client.get("/api/restore/status").json()["last"]["ok"] is True
    assert client.get("/api/items").status_code == 200
    assert reader.get("/api/items").status_code == 200
    assert revoked.get("/api/items").status_code == 401
    db = _session()
    try:
        assert [u.username for u in db.query(User)] == ["owner"]
    finally:
        db.close()


def test_a_restore_migrates_the_collection_chain_only(client, monkeypatch):
    seen = []
    monkeypatch.setattr(schema, "upgrade_to_head", lambda engine, auth=True: seen.append(auth))
    restore.migrate(None)
    assert seen == [False]


# --- recover(), row by row ----------------------------------------------------


def _database_journal(marker: str, dropped=()) -> Path:
    path = restore._journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "phase": "database",
                "marker": marker,
                "dropped": list(dropped),
                "archive": "x.zip",
                "at": "2026-09-14T00:00:00",
                "safety_backup": "cabinet-backup-20260914-031500-prerestore.zip",
            }
        )
    )
    return path


def _unpacked_photos() -> Path:
    photos = _dirs()[0]
    (photos / "live.txt").write_text("live")
    (photos / ".restore-new").mkdir()
    (photos / ".restore-new" / "new.txt").write_text("new")
    return photos


def test_recover_database_step_marker_still_there_changed_nothing(client):
    photos = _unpacked_photos()
    _plant_setting(restore.MARKER_KEY, "a" * 32)
    journal = _database_journal("a" * 32)
    (_staging()).mkdir(parents=True, exist_ok=True)
    (_staging() / "left.dump").write_bytes(b"plain")
    restore.recover(_engine())
    assert sorted(p.name for p in photos.iterdir()) == ["live.txt"]
    assert not journal.exists()
    last = restore.last_outcome()
    assert last["ok"] is False and last["error"].endswith("Nothing was changed.")
    assert _setting_row(restore.MARKER_KEY) is None
    assert list(_staging().iterdir()) == []  # staging emptied at startup


def test_recover_database_step_after_dropping_tables_is_partial(client):
    photos = _unpacked_photos()
    _plant_setting(restore.MARKER_KEY, "a" * 32)
    _database_journal("a" * 32, dropped=["spot_history"])
    restore.recover(_engine())
    assert sorted(p.name for p in photos.iterdir()) == ["live.txt"]
    last = restore.last_outcome()
    assert last["ok"] is False
    assert "spot_history" in last["error"]
    assert "cabinet-backup-20260914-031500-prerestore.zip" in last["error"]


@pytest.mark.parametrize("found", [None, "f" * 32], ids=["no row", "another value"])
def test_recover_database_step_replaced_rolls_forward(client, found):
    """No marker row, or one with another value (an archive can carry a row,
    never this restore's value): the database is the archive's."""
    photos = _unpacked_photos()
    if found is not None:
        _plant_setting(restore.MARKER_KEY, found)
    _plant_setting("alert_webhook_url", "https://planted.example/x")
    journal = _database_journal("a" * 32)
    restore.recover(_engine())
    assert sorted(p.name for p in photos.iterdir()) == ["new.txt"]
    assert not journal.exists()
    last = restore.last_outcome()
    assert last["ok"] is True and last["finished_after_restart"] is True
    assert last["secrets_cleared"] == ["alert webhook"]
    assert _setting_row(restore.MARKER_KEY) is None
    assert _setting_row("alert_webhook_url") == ""


def test_recover_database_step_unreachable_stays_in_maintenance(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    photos = _unpacked_photos()
    journal = _database_journal("a" * 32)

    def unreachable(engine, timeout=60):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(schema, "wait_for_database", unreachable)
    restore.recover(_engine())
    assert journal.exists()  # kept for the next start to decide
    assert maintenance.active()
    assert (photos / ".restore-new" / "new.txt").exists()  # nothing moved either way
    assert client.get("/api/items").status_code == 503
    assert client.get("/api/health").json() == {"status": "ok"}  # no lookup, no database


def test_restore_alerts_and_audit_never_carry_the_error(
    client, coin, fake_dump, calls, clock, monkeypatch
):
    """pg_restore's output can quote the collection's rows, so the webhook
    says only that it failed and where to look (the start and the end are
    also audited under the admin's name)."""
    from app.models.auth import AuditEntry
    from app.services import alerts

    sent = []
    monkeypatch.setattr(
        alerts, "event", lambda db, key, title, message: sent.append((key, message))
    )
    name = _stored(client)
    clock[0] += timedelta(minutes=1)

    def fail():
        raise restore.RestoreError("DETAIL: Failing row contains (United States, 25 cents)")

    calls["during"] = fail
    assert _run(client, _inspect(client, name)["restore_id"]).status_code == 202
    finished = [m for k, m in sent if k == "restore_finished"]
    assert finished == [f"Restore of {name} failed. The reason is in Settings, Backups."]
    assert all("United States" not in m for _, m in sent)
    db = _session()
    try:
        rows = db.query(AuditEntry).filter(AuditEntry.action.like("restore_%")).all()
        assert [(r.action, r.actor_label) for r in rows] == [
            ("restore_started", "owner"),
            ("restore_finished", "owner"),
        ]
        assert rows[1].detail == {"ok": False}
    finally:
        db.close()


def test_a_refused_second_run_leaves_the_first_runs_grant(client, coin, fake_dump):
    """A second run that finds a restore under way (409) never replaces or
    drops the grant the first run's session holds."""
    name = _stored(client)
    restore_id = _inspect(client, name)["restore_id"]
    marker = object()
    restore.issue_grant(b"first-session-hash-000000000000", "first", marker)
    assert restore._lock.acquire(blocking=False)  # a restore is running
    try:
        assert _run(client, restore_id).status_code == 409
        assert restore.granted(b"first-session-hash-000000000000") is marker
    finally:
        restore._lock.release()
        restore.drop_grant()
