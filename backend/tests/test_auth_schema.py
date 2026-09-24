"""The sign-in schema (v0.30.0, single sign-on's a0002 in v0.33.0):
cabinet_auth apart from the collection, its own migration chain, and
backups and restores that never touch it."""

import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.db import Base
from app.models import *  # noqa: F401,F403  # every collection table on Base.metadata
from app.models.auth import SCHEMA, AuthBase
from app.services import backup, restore, schema

BACKEND = Path(__file__).parents[1]
REPO = BACKEND.parent


def test_no_foreign_key_crosses_between_the_schemas():
    for table in Base.metadata.tables.values():
        assert table.schema is None, table.name
        for fk in table.foreign_keys:
            assert fk.column.table.schema is None, (table.name, fk.target_fullname)
    for table in AuthBase.metadata.tables.values():
        assert table.schema == SCHEMA, table.name
        for fk in table.foreign_keys:
            assert fk.column.table.schema == SCHEMA, (table.name, fk.target_fullname)
    assert not set(Base.metadata.tables) & set(AuthBase.metadata.tables)


def test_the_auth_tables_are_the_spec_s():
    assert {t.name for t in AuthBase.metadata.tables.values()} == {
        "claim", "users", "sessions", "api_tokens", "known_devices", "audit_log",
        "backup_ledger", "auth_providers", "identities", "known_browsers", "auth_config",
    }  # fmt: skip


# `public` as a schema name: quoted, qualifying a table, or a schema= value.
# Prose (a comment about a public client) is not a schema reference (R2-15).
PUBLIC_SCHEMA = re.compile(r"[\"']public[\"']|\bpublic\.\w|schema\s*=\s*[\"']?public\b")


def test_each_chain_stays_in_its_own_schema():
    for path in (BACKEND / "alembic" / "versions").glob("*.py"):
        assert "cabinet_auth" not in path.read_text(encoding="utf-8"), path.name
    auth_versions = list((BACKEND / "alembic_auth" / "versions").glob("*.py"))
    assert auth_versions
    for path in auth_versions:
        assert not PUBLIC_SCHEMA.search(path.read_text(encoding="utf-8")), path.name


@pytest.mark.parametrize(
    "text, found",
    [
        ('op.create_table("x", schema="public")', True),
        ("schema='public'", True),
        ("schema=public", True),
        ("SELECT * FROM public.items", True),
        ('"public"', True),
        ("# a public client has no secret", False),
        ("the public profile needs no scope", False),
    ],
)
def test_the_public_check_matches_the_schema_name_only(text, found):
    assert bool(PUBLIC_SCHEMA.search(text)) is found


def test_the_auth_migration_creates_every_table_the_model_has():
    created = set()
    for path in (BACKEND / "alembic_auth" / "versions").glob("*.py"):
        text = path.read_text("utf-8")
        created |= set(re.findall(r'op\.create_table\(\s*"(\w+)"', text))
    assert created == {t.name for t in AuthBase.metadata.tables.values()}


def test_two_chains_with_their_own_heads():
    assert schema.script_revisions()[0] == "0022"
    head, known = schema.auth_script_revisions()
    assert head == "a0002" and known == frozenset({"a0001", "a0002"})


def test_startup_migrates_both_chains_in_order_and_a_restore_only_one(monkeypatch):
    from sqlalchemy import create_engine

    seen = []
    monkeypatch.setattr(schema, "_upgrade", lambda conn, auth: seen.append(auth))
    monkeypatch.setattr(schema, "current_auth_revision", lambda conn: None)
    engine = create_engine("sqlite://")
    schema.upgrade_to_head(engine)
    assert seen == [False, True]  # the collection first, then sign-in
    seen.clear()
    schema.upgrade_to_head(engine, auth=False)
    assert seen == [False]


def test_health_reports_the_auth_schema(client):
    body = client.get("/api/health").json()
    assert body["auth_schema"]["expected"] == "a0002"
    assert body["auth_schema"]["status"] in ("ok", "pending", "unknown")


def test_dumps_leave_the_auth_schema_out(monkeypatch):
    assert "--exclude-schema=cabinet_auth" in backup.dump_command("pg_dump")
    seen = {}

    class Proc:
        def __init__(self, args, **kwargs):
            seen["args"] = args
            self.stdout = io.BytesIO(b"dump")

        def wait(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(backup, "pg_tool", lambda name, major: name)
    monkeypatch.setattr(backup.subprocess, "Popen", Proc)
    monkeypatch.setattr(
        backup.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "pg 16", "")
    )
    out = io.BytesIO()
    backup.dump_database(out, 16)
    assert seen["args"] == ["pg_dump", "--format=custom", "--exclude-schema=cabinet_auth"]


def test_restores_take_the_collection_only():
    args = restore.restore_command("pg_restore", "cabinet", Path("db.dump"))
    assert "--schema=public" in args and "--single-transaction" in args
    assert not any("cabinet_auth" in a for a in args)


@pytest.mark.parametrize(
    "script, needle",
    [
        ("backup.sh", "write-archive"),  # the backend dumps, with the same exclusion
        ("restore.sh", "--schema=public"),
        ("restore.sh", "cabinet_auth"),  # the refusal
    ],
)
def test_the_scripts_follow_the_same_rules(script, needle):
    assert needle in (REPO / "scripts" / script).read_text(encoding="utf-8")


def test_new_archives_say_auth_is_excluded(client, coin, monkeypatch):
    from tests.conftest import open_archive
    from tests.test_backup import FAKE_DUMP

    monkeypatch.setattr(
        backup, "dump_database", lambda out, major: out.write(FAKE_DUMP) and "pg_dump (fake)"
    )
    monkeypatch.setattr(schema, "current_revision", lambda conn: "0022")
    name = client.post("/api/backups").json()["file"]
    with zipfile.ZipFile(io.BytesIO(open_archive(backup.backup_dir() / name))) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["auth_excluded"] is True
