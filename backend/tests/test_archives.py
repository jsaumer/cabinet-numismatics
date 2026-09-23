"""Encrypted, tamper-evident archives (v0.30.0): the backup key, the MAC,
the archive record and RESTORE OLDER, legacy archives, key location, the
container commands, and the rule that no plain archive ever touches the
backup directory. The age program is stood in for by conftest's fake_age."""

import hashlib
import hmac
import io
import json
import os
import stat
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

from app import cli
from app.config import ConfigError, get_settings
from app.main import app
from app.models.auth import BackupRecord
from app.services import archive_keys, backup, restore, schema
from tests.conftest import FAKE_AGE_HEADER, open_archive, seal
from tests.test_backup import FAKE_DUMP, _session

UTC = timezone.utc
HEAD = schema.script_revisions()[0]
FIXED = archive_keys.identity_from_secret(bytes(range(1, 33)))


@pytest.fixture()
def fake_dump(monkeypatch):
    monkeypatch.setattr(backup, "dump_database", lambda out, major: out.write(FAKE_DUMP) and "x")
    monkeypatch.setattr(schema, "current_revision", lambda conn: HEAD)


@pytest.fixture()
def clock(monkeypatch):
    now = [datetime(2026, 9, 14, 3, 15, tzinfo=UTC)]
    monkeypatch.setattr(backup, "utcnow", lambda: now[0])
    return now


@pytest.fixture(autouse=True)
def dump_readers(monkeypatch):
    """No pg_restore here: a clean table of contents and no settings."""
    monkeypatch.setattr(backup, "list_dump", lambda path, major: ["215; 1 2 TABLE public items x"])
    monkeypatch.setattr(backup, "dump_settings", lambda path, major: {})


@pytest.fixture()
def runs(monkeypatch):
    """Restores run inline with the database step recorded, not run."""
    seen = {"during": None}

    def fake_restore(dump_path, on_drop=None):
        if seen["during"]:
            seen["during"]()

    monkeypatch.setattr(restore, "restore_database", fake_restore)
    monkeypatch.setattr(restore, "_spawn", lambda fn: fn())
    monkeypatch.setattr(restore, "dispose_engine", lambda engine: None)
    monkeypatch.setattr(restore, "migrate", lambda engine: None)
    monkeypatch.setattr(backup, "list_dump", lambda path, major: ["215; 1 2 TABLE public items x"])
    monkeypatch.setattr(backup, "dump_settings", lambda path, major: {})
    return seen


def _backups() -> Path:
    return Path(get_settings().backup_dir)


def _staging() -> Path:
    return Path(get_settings().staging_dir)


def _share_holds_only_ciphertext() -> None:
    """Every file anywhere in the backup directory is age ciphertext (or an
    empty partial), never a zip, a dump, or a manifest."""
    for path in _backups().rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert data == b"" or data.startswith(FAKE_AGE_HEADER), path
            assert not path.name.endswith((".dump", ".json")), path


def _stored(client) -> str:
    resp = client.post("/api/backups")
    assert resp.status_code == 200, resp.text
    return resp.json()["file"]


def _inspect(client, name: str):
    return client.post(f"/api/restore/inspect?name={name}")


def _plain_zip(archive: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(open_archive(archive)))


def _put(name: str, blob: bytes) -> Path:
    path = _backups() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return path


# --- the key format and the MAC -------------------------------------------------


def test_bech32_matches_the_reference_vector():
    assert archive_keys.bech32_decode("A12UEL5L") == ("a", b"")
    with pytest.raises(ValueError):
        archive_keys.bech32_decode("A12UEL5X")


def test_identities_round_trip():
    fresh = archive_keys.new_identity()
    assert fresh.text.startswith("AGE-SECRET-KEY-1") and fresh.recipient.startswith("age1")
    assert archive_keys.parse_identity(fresh.text) == fresh
    text = f"# a comment\n\n{fresh.text}\n{FIXED.text}\n"
    assert archive_keys.parse_identities(text) == [fresh, FIXED]
    with pytest.raises(ValueError, match="line 2"):
        archive_keys.parse_identities(f"{fresh.text}\nnot-a-key\n")


def test_mac_is_exactly_the_specified_bytes():
    """HMAC-SHA256, keyed by HKDF-SHA256 over the raw X25519 secret (empty
    salt, info cabinet-backup-mac-v1), over the canonical manifest without
    `mac` (sorted keys, no spaces, UTF-8) followed by SHA256SUMS."""
    manifest = {"format": "cabinet-backup", "created_at": "2026-09-14T03:15:00+00:00", "é": 1}
    sums = b"abc  db.dump\n"
    archive_keys.sign(manifest, sums, FIXED)

    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"", info=b"cabinet-backup-mac-v1"
    ).derive(bytes(range(1, 33)))
    body = {k: v for k, v in manifest.items() if k != "mac"}
    covered = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert covered.startswith(b'{"created_at":') and b'"mac_recipient":"' + FIXED.recipient.encode()
    expected = hmac.new(key, covered + sums, hashlib.sha256).hexdigest()
    assert manifest["mac"] == expected
    assert manifest["mac_recipient"] == FIXED.recipient


def test_mac_refuses_every_change(monkeypatch):
    monkeypatch.setattr(archive_keys, "identities", lambda: [FIXED])
    sums = b"abc  db.dump\n"
    good = archive_keys.sign({"format": "cabinet-backup", "created_at": "x"}, sums, FIXED)
    assert archive_keys.verify(dict(good), sums) == FIXED
    for bad_manifest, bad_sums in (
        ({**good, "created_at": "y"}, sums),  # a manifest field
        (good, b"abd  db.dump\n"),  # SHA256SUMS
        ({**good, "mac_recipient": archive_keys.new_identity().recipient}, sums),
        ({k: v for k, v in good.items() if k != "mac"}, sums),
    ):
        with pytest.raises(archive_keys.NotOurs, match="not made with your backup key"):
            archive_keys.verify(bad_manifest, bad_sums)
    other = archive_keys.new_identity()
    forged = archive_keys.sign({"format": "cabinet-backup", "created_at": "x"}, sums, other)
    with pytest.raises(archive_keys.NotOurs):
        archive_keys.verify(forged, sums)  # a key this deployment doesn't have


# --- the key ----------------------------------------------------------------------


def test_the_key_is_generated_private_and_never_leaves_by_the_api(client, fake_dump):
    path = archive_keys.key_path()
    assert path.name == "backup.key" and path.exists()
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    secret = archive_keys.primary().text
    name = _stored(client)
    for url in ("/api/backups", "/api/settings", "/api/health", "/api/restore/status"):
        assert secret not in client.get(url).text, url
    assert secret not in _inspect(client, name).text
    listing = client.get("/api/backups").json()
    assert listing["key"]["fingerprint"] == archive_keys.primary().recipient
    assert listing["key"]["supplied"] is False


def test_backup_key_show_prints_it(cli_admin, capsys):
    assert cli.main(["backup-key", "show"]) == 0
    out = capsys.readouterr().out
    assert archive_keys.primary().text in out and archive_keys.primary().recipient in out


def test_a_supplied_key_is_used_and_never_changed(cli_admin, tmp_path, monkeypatch, capsys):
    key_file = tmp_path.with_name(tmp_path.name + "-secret.key")
    key_file.write_text(f"# mine\n{FIXED.text}\n", encoding="utf-8")
    before = key_file.read_bytes()
    monkeypatch.setenv("BACKUP_KEY_FILE", str(key_file))
    get_settings.cache_clear()
    assert archive_keys.primary() == FIXED
    assert archive_keys.location() == "secret"
    assert cli.main(["backup-key", "rotate"]) == 0
    assert "Nothing was changed" in capsys.readouterr().out
    assert key_file.read_bytes() == before


@pytest.mark.parametrize("content", [None, "not a key\n", ""], ids=["missing", "garbage", "empty"])
def test_an_unusable_supplied_key_stops_startup(tmp_path, monkeypatch, content):
    key_file = tmp_path / "backup.key"
    if content is not None:
        key_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("BACKUP_KEY_FILE", str(key_file))
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="BACKUP_KEY_FILE"):
            with TestClient(app):
                pass
    finally:
        get_settings.cache_clear()


def test_saving_the_key_is_remembered_until_it_rotates(client):
    assert client.get("/api/backups").json()["key"]["saved"] is False
    assert client.post("/api/backups/key/saved").json()["saved"] is True
    assert client.get("/api/backups").json()["key"]["saved"] is True
    archive_keys.rotate()
    assert client.get("/api/backups").json()["key"]["saved"] is False  # a new key to save


# --- writing: every path, ciphertext only, recorded -------------------------------


def test_every_write_path_is_encrypted_and_recorded(client, coin, fake_dump, runs, clock):
    client.put("/api/settings", json={"backup_schedule": "daily"})
    assert backup.run_scheduled(_session())["ok"] is True  # scheduled (none yet, so due)
    clock[0] += timedelta(minutes=1)
    client.get("/api/backup.zip")  # download
    clock[0] += timedelta(minutes=1)
    _stored(client)  # run now
    clock[0] += timedelta(minutes=1)
    name = _stored(client)
    body = _inspect(client, name).json()
    clock[0] += timedelta(minutes=1)
    assert (
        client.post(
            f"/api/restore/{body['restore_id']}/run", json={"confirm": body["confirm_phrase"]}
        ).status_code
        == 202
    )  # prerestore
    assert client.get("/api/restore/status").json()["last"]["ok"] is True

    kinds = sorted(r.kind for r in _session().query(BackupRecord))
    assert kinds == ["download", "manual", "manual", "prerestore", "scheduled"]
    stored = [p.name for p in _backups().iterdir() if p.is_file()]
    assert stored and all(n.endswith(".zip.age") for n in stored)
    _share_holds_only_ciphertext()
    assert list(_staging().iterdir()) == []


def test_a_failed_write_leaves_no_partial(client, monkeypatch):
    def broken(out, major):
        out.write(b"half")
        raise backup.BackupError("pg_dump failed: boom")

    monkeypatch.setattr(backup, "dump_database", broken)
    assert client.post("/api/backups").status_code == 500
    assert client.get("/api/backup.zip").status_code == 500
    assert [p for p in _backups().rglob("*") if p.is_file()] == []
    assert _session().query(BackupRecord).count() == 0


def test_the_record_keeps_180_days_but_never_fewer_than_50(client, clock):
    db = _session()
    for i in range(60):
        db.add(
            BackupRecord(
                name=f"old-{i}", kind="manual", created_at=clock[0] - timedelta(days=400 - i),
                mac_recipient="age1x", mac_digest=bytes(32), size=1,
            )
        )  # fmt: skip
    db.commit()
    manifest = {"created_at": clock[0].isoformat(), "mac_recipient": "age1x", "mac": "00" * 32}
    backup.record_archive(db, "new", "manual", manifest, 1)
    assert db.query(BackupRecord).count() == 50  # all past 180 days, so down to the newest 50


# --- opening: refusals ------------------------------------------------------------


def _resealed(client, name: str, edit_manifest=None, edit_sums=None, sign=False, identity=None):
    """A copy of a genuine archive, changed and encrypted again to this key."""
    with _plain_zip(_backups() / name) as src:
        members = {n: src.read(n) for n in src.namelist()}
    if edit_manifest:
        manifest = json.loads(members["manifest.json"])
        edit_manifest(manifest)
        members["manifest.json"] = json.dumps(manifest).encode()
    if edit_sums:
        members["SHA256SUMS"] = edit_sums(members["SHA256SUMS"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n, data in members.items():
            out.writestr(n, data)
    blob = seal(buf.getvalue(), sign=sign, identity=identity)
    if identity is not None and not sign:
        blob = seal(buf.getvalue(), sign=False)
    return _put("cabinet-backup-20990101-000000.zip.age", blob).name


def test_an_altered_manifest_is_refused(client, coin, fake_dump):
    good = _stored(client)
    forged = _resealed(client, good, edit_manifest=lambda m: m.update(created_at="2099-01-01"))
    resp = _inspect(client, forged)
    assert resp.status_code == 422 and "not made with your backup key" in resp.json()["detail"]
    _share_holds_only_ciphertext()
    assert list(_staging().iterdir()) == []


def test_altered_checksums_are_refused(client, coin, fake_dump):
    forged = _resealed(client, _stored(client), edit_sums=lambda s: s.replace(b"0", b"1", 1))
    assert "not made with your backup key" in _inspect(client, forged).json()["detail"]


def test_another_signer_is_refused_even_encrypted_to_this_key(client, coin, fake_dump):
    other = archive_keys.new_identity()
    buf_name = _stored(client)
    with _plain_zip(_backups() / buf_name) as src:
        members = {n: src.read(n) for n in src.namelist()}
    manifest = json.loads(members["manifest.json"])
    archive_keys.sign(manifest, members["SHA256SUMS"], other)  # the forger's own key
    members["manifest.json"] = json.dumps(manifest).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n, data in members.items():
            out.writestr(n, data)
    from tests.conftest import fake_age_encrypt

    forged = _put(
        "cabinet-backup-20990101-000001.zip.age",
        fake_age_encrypt(buf.getvalue(), archive_keys.primary().recipient),  # public, so anyone
    )
    resp = _inspect(client, forged.name)
    assert resp.status_code == 422 and "not made with your backup key" in resp.json()["detail"]


def test_another_key_or_a_flipped_byte_cannot_be_opened(client, coin, fake_dump):
    name = _stored(client)
    with _plain_zip(_backups() / name) as src:
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as out:
            for n in src.namelist():
                out.writestr(n, src.read(n))
    other = seal(zipped.getvalue(), identity=archive_keys.new_identity())
    _put("cabinet-backup-20990101-000002.zip.age", other)
    flipped = bytearray((_backups() / name).read_bytes())
    flipped[-10] ^= 0x01
    _put("cabinet-backup-20990101-000003.zip.age", bytes(flipped))
    for forged in (
        "cabinet-backup-20990101-000002.zip.age",
        "cabinet-backup-20990101-000003.zip.age",
    ):
        resp = _inspect(client, forged)
        assert resp.status_code == 422 and resp.json()["detail"] == restore.UNOPENABLE
    assert list(_staging().iterdir()) == []


def test_a_plain_archive_is_never_restored(client, coin, fake_dump, tmp_path):
    # a genuine pre-v0.30.0-style zip, and a forged one
    genuine = io.BytesIO()
    backup.write_archive(genuine, _session(), include_photos=False)
    _put("cabinet-backup-20260101-000000.zip", genuine.getvalue())
    resp = _inspect(client, "cabinet-backup-20260101-000000.zip")
    assert resp.status_code == 422 and resp.json()["detail"] == restore.LEGACY_REFUSED
    upload = tmp_path / "old.zip"
    upload.write_bytes(genuine.getvalue())
    with upload.open("rb") as fh:
        resp = client.post(
            "/api/restore/inspect", files={"file": ("old.zip", fh, "application/zip")}
        )
    assert resp.status_code == 422 and resp.json()["detail"] == restore.LEGACY_REFUSED
    assert list((_backups() / ".restore-staging").iterdir()) == []


def test_unencrypted_archives_are_listed_and_deleted_alone(client, coin, fake_dump):
    kept = _stored(client)
    _put("cabinet-backup-20260101-000000.zip", b"PK plain")
    _put("cabinet-backup-20260102-000000-data.zip", b"PK plain")
    _put("notes.txt", b"not ours")
    (_backups() / ".restore-staging").mkdir(exist_ok=True)
    listing = {b["name"]: b["encrypted"] for b in client.get("/api/backups").json()["backups"]}
    assert listing == {
        kept: True,
        "cabinet-backup-20260101-000000.zip": False,
        "cabinet-backup-20260102-000000-data.zip": False,
    }
    resp = client.delete("/api/backups/unencrypted")
    assert sorted(resp.json()["deleted"]) == [
        "cabinet-backup-20260101-000000.zip",
        "cabinet-backup-20260102-000000-data.zip",
    ]
    assert sorted(p.name for p in _backups().iterdir()) == [".restore-staging", kept, "notes.txt"]


# --- the archive record and RESTORE OLDER -----------------------------------------


def _phrase(client, name: str) -> dict:
    resp = _inspect(client, name)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_newest_needs_plain_restore_and_an_older_one_restore_older(
    client, coin, fake_dump, runs, clock
):
    older = _stored(client)
    clock[0] += timedelta(minutes=1)
    newest = _stored(client)

    body = _phrase(client, newest)
    assert body["confirm_phrase"] == "RESTORE"
    assert body["provenance"]["made_here"] is True and body["provenance"]["newer"] == 0

    body = _phrase(client, older)
    assert body["confirm_phrase"] == "RESTORE OLDER"
    assert body["provenance"]["message"].startswith("Made by this Cabinet on 14 September 2026.")
    assert "1 newer backup exists." in body["provenance"]["message"]
    run = f"/api/restore/{body['restore_id']}/run"
    assert client.post(run, json={"confirm": "RESTORE"}).status_code == 422
    assert client.post(run, json={"confirm": "RESTORE OLDER"}).status_code == 202
    assert client.get("/api/restore/status").json()["last"]["ok"] is True


def test_renaming_or_redating_an_older_archive_does_not_make_it_newest(
    client, coin, fake_dump, runs, clock
):
    older = _stored(client)
    clock[0] += timedelta(minutes=5)
    newest = _stored(client)
    # renamed to a newer-looking name, with a newer file time
    disguised = _backups() / "cabinet-backup-20991231-235959.zip.age"
    (_backups() / older).rename(disguised)
    future = datetime(2099, 12, 31, tzinfo=UTC).timestamp()
    os.utime(disguised, (future, future))
    assert _phrase(client, disguised.name)["confirm_phrase"] == "RESTORE OLDER"
    # its own record pruned: still older, and no longer "made here"
    db = _session()
    db.query(BackupRecord).filter(BackupRecord.name == older).delete()
    db.commit()
    body = _phrase(client, disguised.name)
    assert body["confirm_phrase"] == "RESTORE OLDER"
    assert body["provenance"]["made_here"] is False
    assert body["provenance"]["message"].startswith("Not made by this Cabinet.")
    assert _phrase(client, newest)["confirm_phrase"] == "RESTORE"


def test_an_empty_record_says_it_cannot_tell(client, coin, fake_dump):
    name = _stored(client)
    db = _session()
    db.query(BackupRecord).delete()
    db.commit()
    body = _phrase(client, name)
    assert body["provenance"]["record_empty"] is True
    assert "cannot tell whether this is the newest" in body["provenance"]["message"]
    assert body["confirm_phrase"] == "RESTORE"


def test_the_run_rechecks_the_phrase_from_the_archive_itself(client, coin, fake_dump, runs, clock):
    older = _stored(client)
    body = _phrase(client, older)  # the newest, when inspected
    clock[0] += timedelta(minutes=1)
    _stored(client)  # now it isn't
    run = f"/api/restore/{body['restore_id']}/run"
    assert client.post(run, json={"confirm": "RESTORE"}).status_code == 202
    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is False and "RESTORE OLDER" in last["error"]


# --- restore: the decrypted copy lives only in staging -----------------------------


def test_a_restore_keeps_plain_text_off_the_share(client, coin, fake_dump, runs):
    name = _stored(client)
    seen = {}

    def during():
        staged = {p.suffix: p for p in _staging().iterdir()}
        seen["staged"] = sorted(staged)
        if sys.platform != "win32":
            seen["mode"] = stat.S_IMODE(staged[".zip"].stat().st_mode)
        _share_holds_only_ciphertext()

    runs["during"] = during
    body = _phrase(client, name)
    run = f"/api/restore/{body['restore_id']}/run"
    assert client.post(run, json={"confirm": body["confirm_phrase"]}).status_code == 202
    assert client.get("/api/restore/status").json()["last"]["ok"] is True
    assert seen["staged"] == [".dump", ".zip"]
    assert seen.get("mode", 0o600) == 0o600
    assert list(_staging().iterdir()) == []
    _share_holds_only_ciphertext()


def test_a_restore_that_fails_to_open_keeps_the_share_clean(client, coin, fake_dump, runs):
    name = _stored(client)
    body = _phrase(client, name)
    flipped = bytearray((_backups() / name).read_bytes())
    flipped[-5] ^= 0x01
    (_backups() / name).write_bytes(bytes(flipped))  # altered between inspect and run
    run = f"/api/restore/{body['restore_id']}/run"
    assert client.post(run, json={"confirm": body["confirm_phrase"]}).status_code == 202
    last = client.get("/api/restore/status").json()["last"]
    assert last["ok"] is False and restore.UNOPENABLE in last["error"]
    assert last["error"].endswith("Nothing was changed.")
    assert list(_staging().iterdir()) == []
    _share_holds_only_ciphertext()


# --- rotation ------------------------------------------------------------------------


def test_rotation_keeps_older_archives_readable_while_their_key_is_kept(
    client, coin, fake_dump, clock
):
    a = _stored(client)
    old = archive_keys.primary()
    fresh = archive_keys.rotate()
    assert archive_keys.primary() == fresh and old in archive_keys.identities()
    clock[0] += timedelta(minutes=1)
    b = _stored(client)
    with _plain_zip(_backups() / b) as zf:
        assert json.loads(zf.read("manifest.json"))["mac_recipient"] == fresh.recipient
    assert _inspect(client, a).status_code == 200
    assert _inspect(client, b).status_code == 200
    # the old identity removed: A can no longer be opened, B still can
    archive_keys.key_path().write_text(fresh.text + "\n", encoding="utf-8")
    assert _inspect(client, a).json()["detail"] == restore.UNOPENABLE
    assert _inspect(client, b).status_code == 200


# --- where the key lives ------------------------------------------------------------

LOCAL = (
    "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
    "40 22 8:1 /var/lib/docker/volumes/c_state/_data /data/state rw - ext4 /dev/sda1 rw\n"
    "41 22 8:1 /var/lib/docker/volumes/c_backups/_data /data/backups rw - ext4 /dev/sda1 rw\n"
)


@pytest.mark.parametrize(
    "mountinfo, expected",
    [
        # two named volumes on one disk: whether it is shared is the operator's to know
        (LOCAL, "not_verified"),
        (  # a bind mount of the backup folder's own parent as the state volume
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "40 22 8:1 /srv/cabinet /data/state rw - ext4 /dev/sda1 rw\n"
            "41 22 8:1 /srv/cabinet/backups /data/backups rw - ext4 /dev/sda1 rw\n",
            "shared",
        ),
        (  # both on one mount
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n40 22 0:50 / /data rw - ext4 /dev/sdb1 rw\n",
            "shared",
        ),
        (  # a network filesystem: only the operator knows what the server shares
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "40 22 0:60 /state /data/state rw - nfs4 nas:/export/cabinet rw\n"
            "41 22 0:61 /backups /data/backups rw - nfs4 nas:/export/cabinet rw\n",
            "not_verified",
        ),
        (None, "not_verified"),  # mountinfo unreadable
    ],
    ids=["named volumes", "bind inside", "one mount", "nfs", "unreadable"],
)
def test_key_location_three_states(mountinfo, expected):
    result = archive_keys.compare_locations(
        Path("/data/state/backup.key"), Path("/data/backups"), mountinfo
    )
    assert result == expected


def test_a_key_inside_the_backup_folder_is_shared_whatever_the_mounts():
    assert (
        archive_keys.compare_locations(
            Path("/data/backups/keys/backup.key"), Path("/data/backups"), LOCAL
        )
        == "shared"
    )


def test_settings_say_where_the_key_is(client, monkeypatch):
    monkeypatch.setattr(archive_keys, "_read_mountinfo", lambda: None)
    key = client.get("/api/backups").json()["key"]
    assert key["location"] == "not_verified"
    assert "cannot tell" in key["location_message"]


# --- the container commands ----------------------------------------------------------


def test_decrypt_and_verify_commands(client, coin, fake_dump, monkeypatch, capsys):
    name = _stored(client)
    blob = (_backups() / name).read_bytes()

    class Std:
        def __init__(self, data=b""):
            self.buffer = io.BytesIO(data)
            self.text = ""

        def write(self, text):
            self.text += text

        def flush(self):
            pass

    out = Std()
    monkeypatch.setattr(sys, "stdin", Std(blob))
    monkeypatch.setattr(sys, "stdout", out)
    assert cli.main(["decrypt-archive"]) == 0
    plain = out.buffer.getvalue()
    assert plain[:2] == b"PK"

    monkeypatch.setattr(sys, "stdin", Std(plain))
    monkeypatch.setattr(sys, "stdout", Std())
    assert cli.main(["verify-archive", "-"]) == 0
    assert list(_staging().iterdir()) == []  # the spooled copy is gone

    zin = zipfile.ZipFile(io.BytesIO(plain))
    tampered = io.BytesIO()
    with zipfile.ZipFile(tampered, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "manifest.json":
                m = json.loads(data)
                m["created_at"] = "2099-01-01T00:00:00+00:00"
                data = json.dumps(m).encode()
            zout.writestr(n, data)
    monkeypatch.setattr(sys, "stdin", Std(tampered.getvalue()))
    assert cli.main(["verify-archive", "-"]) == 1
    assert "not made with your backup key" in capsys.readouterr().err


# --- from the stage 5 review --------------------------------------------------------


def _members_of(name: str) -> dict[str, bytes]:
    with _plain_zip(_backups() / name) as src:
        return {n: src.read(n) for n in src.namelist()}


def _sealed_zip(entries: list[tuple[str, bytes]], name: str) -> str:
    """Entries as given (duplicates allowed), encrypted to this key, the
    manifest left as it is (its MAC still genuine)."""
    import warnings

    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about a duplicate name
        with zipfile.ZipFile(buf, "w") as out:
            for n, data in entries:
                out.writestr(n, data)
    return _put(name, seal(buf.getvalue(), sign=False)).name


def test_an_extra_member_is_refused_even_with_a_genuine_mac(client, coin, fake_dump):
    resp = client.post("/api/backups?photos=false")
    members = _members_of(resp.json()["file"])
    assert "photos.tar.gz" not in members
    entries = [*members.items(), ("photos.tar.gz", b"an attacker's photos")]
    resp = _inspect(client, _sealed_zip(entries, "cabinet-backup-20990101-000010.zip.age"))
    assert resp.status_code == 422 and "members don't match" in resp.json()["detail"]


def test_a_doubled_member_is_refused(client, coin, fake_dump):
    members = _members_of(_stored(client))
    entries = [("db.dump", b"evil dump"), *members.items()]  # evil first, genuine last
    resp = _inspect(client, _sealed_zip(entries, "cabinet-backup-20990101-000011.zip.age"))
    assert resp.status_code == 422 and "appears twice" in resp.json()["detail"]


def test_a_huge_unverified_manifest_is_not_read(client, coin, fake_dump):
    members = _members_of(_stored(client))
    members["manifest.json"] = b'{"pad": "' + b"x" * (backup.MAX_SMALL_MEMBER + 1) + b'"}'
    resp = _inspect(
        client, _sealed_zip(list(members.items()), "cabinet-backup-20990101-000012.zip.age")
    )
    assert resp.status_code == 422 and "too large" in resp.json()["detail"]


def test_the_key_is_never_regenerated_at_runtime(client, coin, fake_dump):
    path = archive_keys.key_path()
    before = path.read_bytes()
    path.unlink()  # a lost file, or a stat that failed
    resp = client.post("/api/backups")
    assert resp.status_code == 500 and "is missing" in resp.json()["detail"]
    assert not path.exists()  # not replaced by a new key
    assert client.get("/api/backups").status_code == 500
    path.write_bytes(before)
    assert client.post("/api/backups").status_code == 200


def test_starting_never_overwrites_an_existing_key(client):
    path = archive_keys.key_path()
    path.write_text(FIXED.text + "\n", encoding="utf-8")
    assert archive_keys.ensure_key() == [FIXED]
    assert archive_keys.ensure_key() == [FIXED]
    assert path.read_text(encoding="utf-8") == FIXED.text + "\n"


def test_a_lower_case_identity_is_refused_as_age_would():
    with pytest.raises(ValueError, match="in capitals"):
        archive_keys.parse_identity(FIXED.text.lower())


def test_staging_must_not_contain_another_data_folder(client, monkeypatch):
    monkeypatch.setenv("STAGING_DIR", str(_backups().parent))  # around the backups
    get_settings.cache_clear()
    with pytest.raises(backup.BackupError, match="must be apart from"):
        backup.staging_dir()
    backup.empty_staging(everything=True)  # refuses quietly rather than wiping
    assert _backups().parent.exists()


@pytest.mark.parametrize(
    "mountinfo, expected",
    [
        (  # two local disks
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "40 22 8:17 /state /data/state rw - ext4 /dev/sdb1 rw\n"
            "41 22 8:33 /backups /data/backups rw - xfs /dev/sdc1 rw\n",
            "separate",
        ),
        (  # different devices, but a filesystem Cabinet can't judge
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "40 22 0:70 /state /data/state rw - virtiofs share rw\n"
            "41 22 0:71 /backups /data/backups rw - fakeowner grpcfuse rw\n",
            "not_verified",
        ),
        (  # sibling folders on one filesystem
            "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
            "40 22 8:17 /srv/nas/state /data/state rw - ext4 /dev/sdb1 rw\n"
            "41 22 8:17 /srv/nas/backups /data/backups rw - ext4 /dev/sdb1 rw\n",
            "not_verified",
        ),
    ],
    ids=["two disks", "unknown fs", "siblings"],
)
def test_separate_is_said_only_when_it_is_known(mountinfo, expected):
    result = archive_keys.compare_locations(
        Path("/data/state/backup.key"), Path("/data/backups"), mountinfo
    )
    assert result == expected


def test_mountinfo_octal_escapes():
    [mount] = archive_keys.parse_mountinfo(
        r"40 22 8:17 /my\040disk /data/my\040disk rw - ext4 /dev/sdb1 rw" + "\n"
    )
    assert mount.point == "/data/my disk" and mount.root == "/my disk"


def test_a_plain_upload_is_refused_on_its_first_bytes(client, tmp_path):
    plain = tmp_path / "old.zip"
    plain.write_bytes(b"PK\x03\x04" + b"\0" * 200_000)
    with plain.open("rb") as fh:
        resp = client.post(
            "/api/restore/inspect", files={"file": ("old.zip", fh, "application/zip")}
        )
    assert resp.status_code == 422 and resp.json()["detail"] == restore.LEGACY_REFUSED
    assert list((_backups() / ".restore-staging").iterdir()) == []


def test_the_self_test_round_trips_and_the_record_check_notices_a_new_key(client, coin, fake_dump):
    backup.self_test()
    assert [p for p in _staging().iterdir()] == []
    _stored(client)
    assert backup.record_key_mismatch(_session()) is None
    old = archive_keys.primary()
    fresh = archive_keys.new_identity()
    archive_keys.key_path().write_text(fresh.text + "\n", encoding="utf-8")  # old key gone
    assert backup.record_key_mismatch(_session()) == old.recipient


def test_startup_clears_orphaned_uploads_and_all_staging(client):
    uploads = _backups() / ".restore-staging"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / ("a" * 32 + ".upload")).write_bytes(b"age-encryption.org/v1\n...")
    (_staging() / ".cli-leftover").write_bytes(b"plain")
    backup.empty_staging()  # an in-app check leaves another process's files
    assert (_staging() / ".cli-leftover").exists()
    restore.recover()
    assert list(uploads.iterdir()) == []
    assert list(_staging().iterdir()) == []


def test_a_stale_cli_spool_is_removed_by_the_in_app_cleanup(client):
    """A killed `verify-archive -` leaves its decrypted spool in staging; the
    next inspect or restore removes it once it is old, and leaves a fresh one
    (a command still running) alone."""
    import os
    import time

    staging = backup.staging_dir()
    fresh = staging / f"{backup.CLI_PREFIX}fresh"
    stale = staging / f"{backup.CLI_PREFIX}stale"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    old = time.time() - backup.CLI_STALE - 60
    os.utime(stale, (old, old))
    backup.empty_staging()
    assert fresh.exists() and not stale.exists()
    backup.empty_staging(everything=True)
    assert not fresh.exists()


# --- the key as a variable (stage 13) ------------------------------------------------


def test_an_environment_key_is_used_and_kept_off_the_state_volume(client, monkeypatch):
    other = archive_keys.identity_from_secret(bytes(range(33, 65)))
    monkeypatch.setenv("BACKUP_KEY", f"# mine\n{FIXED.text}, {other.text}\n")
    get_settings.cache_clear()
    assert archive_keys.ensure_key() == [FIXED, other]  # commas or newlines; first encrypts
    assert archive_keys.primary() == FIXED
    assert archive_keys.supplied() and archive_keys.location() == "environment"
    path = archive_keys.key_path()
    assert path.parent != archive_keys.state_dir()  # never beside the backups' share
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert archive_keys.rotate() is None  # a supplied key is the operator's to rotate
    assert archive_keys.ensure_key() == [FIXED, other]  # rewritten, not appended, each start


def test_a_bad_environment_key_stops_startup(monkeypatch):
    monkeypatch.setenv("BACKUP_KEY", "not a key")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="BACKUP_KEY: .*backup-key new"):
            with TestClient(app):
                pass
    finally:
        get_settings.cache_clear()


def test_a_key_file_and_a_key_variable_together_stop_startup(tmp_path, monkeypatch):
    key_file = tmp_path / "backup.key"
    key_file.write_text(f"{FIXED.text}\n", encoding="utf-8")
    monkeypatch.setenv("BACKUP_KEY_FILE", str(key_file))
    monkeypatch.setenv("BACKUP_KEY", FIXED.text)
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="not both"):
            with TestClient(app):
                pass
    finally:
        get_settings.cache_clear()


def test_backup_key_new_prints_a_usable_key_and_changes_nothing(capsys):
    """The documented way to make a key, for a secret file or BACKUP_KEY:
    no database, works before setup, touches no file."""
    assert cli.main(["backup-key", "new"]) == 0
    out = capsys.readouterr().out
    (identity,) = archive_keys.parse_identities(out)  # the whole output is a valid key file
    assert identity.text in out and f"# public key: {identity.recipient}" in out
    assert not (archive_keys.state_dir() / "backup.key").exists()
    assert cli.main(["backup-key", "new"]) == 0
    assert archive_keys.parse_identities(capsys.readouterr().out) != [identity]
