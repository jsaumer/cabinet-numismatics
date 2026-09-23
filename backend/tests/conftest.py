import base64
import io
import os
import tempfile

# Point PHOTO_DIR somewhere disposable before app.config is imported,
# so the lifespan hook doesn't create a photos/ dir in the repo.
os.environ.setdefault("PHOTO_DIR", os.path.join(tempfile.gettempdir(), "cabinet-test-photos"))
# Tests build their schema with create_all on SQLite; never migrate at startup.
os.environ.setdefault("AUTO_MIGRATE", "false")
# Required at startup since v0.30.0; the TestClient's own origin.
os.environ.setdefault("PUBLIC_ORIGINS", "https://testserver")
# Deterministic encryption key so tests never generate or read a key file.
os.environ.setdefault(
    "SECRET_KEY", base64.urlsafe_b64encode(b"cabinet-test-key-32-bytes-long!!").decode()
)

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Grade
from app.models.auth import SCHEMA as AUTH_SCHEMA
from app.models.auth import AuthBase
from app.models.grades_seed import seed_rows
from app.services import crypto


@pytest.fixture(autouse=True)
def _no_network_rates(monkeypatch):
    """Exchange-rate fetches never hit the network in tests; individual tests
    monkeypatch a working rate when they need conversion."""
    from app.services import currency

    def unavailable(base, quote):
        raise currency.RateUnavailable("offline in tests")

    monkeypatch.setattr(currency, "fetch_rate", unavailable)


@pytest.fixture(autouse=True)
def _private_paths(tmp_path_factory, monkeypatch):
    """Every test's data folders are temporary, including tests that start the
    app without the `client` fixture: the defaults under /data would write a
    real key there (or fail, where /data isn't writable, as on CI)."""
    base = tmp_path_factory.mktemp("data")
    monkeypatch.setenv("PHOTO_DIR", str(base / "photos"))
    monkeypatch.setenv("DOCUMENT_DIR", str(base / "documents"))
    monkeypatch.setenv("BACKUP_DIR", str(base / "backups"))
    monkeypatch.setenv("STAGING_DIR", str(base / "staging"))
    monkeypatch.setenv("SECRET_KEY_FILE", str(base / "state" / "secret.key"))
    monkeypatch.delenv("BACKUP_KEY_FILE", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_monitoring_state():
    """Alert outcomes, the metrics cache, the sign-in throttles, and the
    sharing switch live in memory, per process."""
    from app.auth import audit, notify, throttle
    from app.services import alerts, metrics, restore, share

    alerts.reset_memory()
    metrics.reset_cache()
    restore.reset_memory()
    share.reset_memory()
    throttle.clear()
    audit.reset_memory()
    notify.reset_memory()
    yield


@pytest.fixture(autouse=True)
def _no_background_photo_pass(monkeypatch):
    """Every app start runs the photo-metadata pass on a thread (v0.32.0,
    whatever AUTO_MIGRATE says); in tests it would race the files a test
    plants. Tests that want it patch `photos._spawn` themselves."""
    from app.services import photos

    monkeypatch.setattr(photos, "_spawn", lambda fn: None)


BASE_URL = "https://testserver"  # PUBLIC_ORIGINS, so CSRF's Origin rule matches
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
PASSWORD = "correct horse battery"
# How the cookie jar files a dotless host, so a Set-Cookie replaces ours.
COOKIE_DOMAIN = "testserver.local"


def _cheap_argon2(monkeypatch):
    from argon2 import PasswordHasher

    from app.auth import passwords

    monkeypatch.setattr(
        passwords, "HASHER", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


def _session_db():
    return next(app.dependency_overrides[get_db]())


def _with_session(secret: str, **headers) -> TestClient:
    from app.auth import sessions

    c = TestClient(app, base_url=BASE_URL, headers={**SAME_ORIGIN, **headers})
    c.cookies.set(sessions.cookie_names()[0], secret, domain=COOKIE_DOMAIN)
    return c


@pytest.fixture()
def unclaimed_client(tmp_path, monkeypatch):
    """TestClient backed by a fresh in-memory SQLite DB (grades seeded) and a
    temp photo dir, before anyone has set Cabinet up: no credentials."""
    raw_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(raw_engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        # Make SQLite honor ON DELETE CASCADE / SET NULL like postgres does.
        dbapi_conn.execute("pragma foreign_keys=on")

    # SQLite has no schemas: the sign-in tables (cabinet_auth on Postgres)
    # live beside the collection's here, mapped by schema_translate_map.
    engine = raw_engine.execution_options(schema_translate_map={AUTH_SCHEMA: None})

    Base.metadata.create_all(engine)
    AuthBase.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(Grade), seed_rows())
    TestSession = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path.with_name(tmp_path.name + "-documents")))
    monkeypatch.setenv("REQUIRE_DOCUMENT_MOUNT", "false")
    # Beside the photo dir, never inside it (the backup service refuses that).
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path.with_name(tmp_path.name + "-backups")))
    # The private staging volume (an archive's dump is only ever unpacked here).
    monkeypatch.setenv("STAGING_DIR", str(tmp_path.with_name(tmp_path.name + "-staging")))
    # The restore outcome file is written beside the key file.
    monkeypatch.setenv(
        "SECRET_KEY_FILE", str(tmp_path.with_name(tmp_path.name + "-state") / "secret.key")
    )
    get_settings.cache_clear()
    crypto.reset_cache()
    app.dependency_overrides[get_db] = override_get_db
    _cheap_argon2(monkeypatch)
    from app.auth import setup

    setup.reset_memory()
    try:
        with TestClient(app, base_url=BASE_URL, headers=SAME_ORIGIN) as c:
            yield c
    finally:
        setup.reset_memory()
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        crypto.reset_cache()
        raw_engine.dispose()


@pytest.fixture()
def client(unclaimed_client):
    """The admin's browser: signed in over https://testserver, sending
    `Sec-Fetch-Site: same-origin`, inside its recent-password window. The
    `Started` sign-in is on `client.admin`."""
    from app.auth import accounts, sessions

    db = _session_db()
    try:
        started = accounts.create_admin(db, "owner", PASSWORD, accounts.Client())
        sessions.confirm(started.session)
        db.commit()
    finally:
        db.close()
    unclaimed_client.cookies.set(
        sessions.cookie_names()[0], started.session_secret, domain=COOKIE_DOMAIN
    )
    unclaimed_client.admin = started
    return unclaimed_client


@pytest.fixture()
def anon_client(client):
    """Nobody signed in, against the claimed instance `client` set up."""
    with TestClient(app, base_url=BASE_URL, headers=SAME_ORIGIN) as c:
        yield c


@pytest.fixture()
def stale_client(client):
    """The admin signed in on another browser, outside its recent-password
    window."""
    from app.auth import accounts

    db = _session_db()
    try:
        started = accounts.sign_in(db, "owner", PASSWORD, accounts.Client(address="198.51.100.2"))
    finally:
        db.close()
    with _with_session(started.session_secret) as c:
        yield c


@pytest.fixture()
def token_client(client):
    """A factory: `token_client("read")` is a TestClient sending a fresh
    token of that scope as Bearer, with no cookie."""
    from app.auth import accounts
    from app.auth.audit import Actor

    made = []

    def make(scope: str) -> TestClient:
        db = _session_db()
        try:
            user = accounts.admin(db)
            days = None if scope == "metrics" else 1
            plaintext, _ = accounts.create_token(
                db, user, f"{scope}-{len(made)}", scope, days, Actor.system()
            )
        finally:
            db.close()
        c = TestClient(app, base_url=BASE_URL, headers={"Authorization": f"Bearer {plaintext}"})
        c.token = plaintext
        made.append(c)
        return c

    yield make
    for c in made:
        c.close()


def image_bytes(fmt: str = "PNG", size=(60, 40), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


COIN = {
    "type": "coin",
    "country": "United States",
    "denomination": "25 cents",
    "year": 1932,
    "mint_mark": "D",
    "series": "Washington Quarter",
    "quantity": 1,
    "acquisition_price": 120.0,
    "currency": "USD",
}


@pytest.fixture()
def cli_admin(client, monkeypatch):
    """The admin exists, and container commands (`app.cli`) reach the test
    database. Account commands refuse before setup."""
    from app import db as app_db

    make = app.dependency_overrides[get_db]
    monkeypatch.setattr(app_db, "SessionLocal", lambda: next(make()))
    return client.admin


@pytest.fixture()
def coin(client):
    """A created item, for tests that need one to exist."""
    resp = client.post("/api/items", json=COIN)
    assert resp.status_code == 201
    return resp.json()


def import_cabinet_csv(client, text, name: str = "items.csv") -> dict:
    """Import a CSV in Cabinet's export format through `/api/imports` (upload,
    preview, run), read as the `cabinet` format whatever its columns, so a
    hand-written CSV with only a few export columns reads as one. Returns the
    run result: `created`, `skipped`, `errors` (`{row, error}`, `row` counting
    data rows from 1), `photos_added`, `photos_failed`. Rows whose exported id
    is already here, trash included, are skipped."""
    body = text.encode() if isinstance(text, str) else text
    upload = client.post("/api/imports", files={"file": (name, body, "text/csv")})
    assert upload.status_code == 201, upload.text
    upload_id = upload.json()["upload_id"]
    options = {"format": "cabinet"}
    preview = client.post(f"/api/imports/{upload_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    run = client.post(f"/api/imports/{upload_id}/run", json=options)
    assert run.status_code == 200, run.text
    return run.json()


# --- a stand-in for the age program (not installed on the dev machine) ---------

FAKE_AGE_HEADER = b"age-encryption.org/v1\n-> cabinet-test "
_FLIP = bytes(range(256)).translate(bytes((b ^ 0xA5) for b in range(256)))


class _PipeLike:
    """Unseekable, like age's stdin: zipfile has to stream into it."""

    def __init__(self):
        self.chunks = []

    def write(self, data) -> int:
        self.chunks.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass


def fake_age_encrypt(payload: bytes, recipient: str) -> bytes:
    import hashlib

    digest = hashlib.sha256(payload).hexdigest().encode()
    return (
        FAKE_AGE_HEADER + recipient.encode() + b" " + digest + b"\n---\n" + payload.translate(_FLIP)
    )


def fake_age_decrypt(blob: bytes, recipients: set[str]) -> bytes:
    import hashlib

    from app.services import backup

    head, sep, body = blob.partition(b"\n---\n")
    if not sep or not head.startswith(FAKE_AGE_HEADER):
        raise backup.BackupError("age could not open the archive: not an age file")
    recipient, _, digest = head[len(FAKE_AGE_HEADER) :].decode().partition(" ")
    if recipient not in recipients:
        raise backup.BackupError("age could not open the archive: no identity matched")
    payload = body.translate(_FLIP)
    if hashlib.sha256(payload).hexdigest() != digest:
        raise backup.BackupError("age could not open the archive: failed to decrypt")
    return payload


@pytest.fixture(autouse=True)
def fake_age(monkeypatch):
    """Authenticated and bound to the recipient, like age: a wrong key or a
    flipped byte fails. Only ciphertext is ever written."""
    from contextlib import contextmanager
    from pathlib import Path

    from app.services import archive_keys, backup

    @contextmanager
    def encrypt_stream(dst, recipient):
        pipe = _PipeLike()
        yield pipe
        blob = fake_age_encrypt(b"".join(pipe.chunks), recipient)
        if isinstance(dst, (str, Path)):
            Path(dst).write_bytes(blob)
        else:
            dst.write(blob)

    def decrypt_stream(src, dst, key_file):
        blob = Path(src).read_bytes() if isinstance(src, (str, Path)) else src.read()
        recipients = {
            i.recipient
            for i in archive_keys.parse_identities(Path(key_file).read_text(encoding="utf-8"))
        }
        dst.write(fake_age_decrypt(blob, recipients))

    monkeypatch.setattr(backup, "encrypt_stream", encrypt_stream)
    monkeypatch.setattr(backup, "decrypt_stream", decrypt_stream)


def open_archive(path) -> bytes:
    """The decrypted zip bytes of an archive Cabinet wrote (tests only)."""
    from pathlib import Path

    from app.services import archive_keys

    return fake_age_decrypt(
        Path(path).read_bytes(), {i.recipient for i in archive_keys.identities()}
    )


def seal(zip_bytes: bytes, sign: bool = True, identity=None) -> bytes:
    """Encrypt a zip as an archive, re-signing its manifest (so tests can
    build well-formed archives around odd contents); `sign=False` keeps the
    manifest as it is, to test that a stale or missing MAC is refused."""
    import io as _io
    import json as _json
    import zipfile as _zipfile

    from app.services import archive_keys

    identity = identity or archive_keys.primary()
    if sign:
        src = _zipfile.ZipFile(_io.BytesIO(zip_bytes))
        manifest = _json.loads(src.read("manifest.json"))
        sums = src.read("SHA256SUMS") if "SHA256SUMS" in src.namelist() else b""
        archive_keys.sign(manifest, sums, identity)
        out = _io.BytesIO()
        with _zipfile.ZipFile(out, "w") as dst:
            for name in src.namelist():
                data = _json.dumps(manifest).encode() if name == "manifest.json" else src.read(name)
                dst.writestr(name, data)
        zip_bytes = out.getvalue()
    return fake_age_encrypt(zip_bytes, identity.recipient)
