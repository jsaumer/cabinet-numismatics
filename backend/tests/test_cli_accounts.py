"""The account commands in the container (`python -m app.cli`, v0.30.0): each
refuses until Cabinet is set up, does what SPEC_0300 section 6 says, and is
audited as `cli`. `reset-password` never takes the password as an argument."""

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import cli
from app import db as app_db
from app.auth import accounts, sessions, throttle, tokens
from app.auth.accounts import Client
from app.auth.audit import Actor
from app.db import get_db
from app.main import app
from app.models.auth import AuditEntry
from app.services import alerts, archive_keys

PASSWORD = "correct horse battery"
BROWSER = Client(address="192.0.2.10", user_agent="Firefox")


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    from app.auth import passwords

    monkeypatch.setattr(
        passwords, "HASHER", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


@pytest.fixture()
def db(client, monkeypatch):
    make = app.dependency_overrides[get_db]
    monkeypatch.setattr(app_db, "SessionLocal", lambda: next(make()))
    monkeypatch.setattr(alerts, "event", lambda *a: None)
    archive_keys.ensure_key()
    return next(make())


@pytest.fixture()
def owner(db):
    return accounts.create_admin(db, "owner", PASSWORD, BROWSER)


def run(*argv) -> int:
    return cli.main(list(argv))


def audited(db, action: str) -> list[AuditEntry]:
    db.expire_all()
    return list(db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all())


def passwords_typed(monkeypatch, *typed):
    answers = iter(typed)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))


COMMANDS = [
    ["status"],
    ["reset-password"],
    ["sign-out-everywhere"],
    ["revoke-tokens"],
    ["revoke-tokens", "--name", "ci"],
    ["backup-key", "show"],
    ["backup-key", "rotate"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=" ".join)
def test_every_account_command_refuses_before_setup(db, argv, capsys, monkeypatch):
    passwords_typed(monkeypatch, "a brand new password", "a brand new password")
    assert run(*argv) == 1
    captured = capsys.readouterr()
    assert accounts.NOT_CLAIMED in captured.err
    assert "AGE-SECRET-KEY" not in captured.out
    assert len(archive_keys.identities()) == 1  # rotate did nothing


def test_the_archive_commands_work_before_setup(db, capsys, tmp_path):
    """restore.sh and backup.sh can run on a fresh machine in either order."""
    missing = tmp_path / "none.zip"
    assert run("verify-archive", str(missing)) == 1
    assert accounts.NOT_CLAIMED not in capsys.readouterr().err


def test_reset_password_takes_no_argument(db, owner):
    with pytest.raises(SystemExit):
        run("reset-password", "the new password")


def test_reset_password(db, owner, capsys, monkeypatch):
    other = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    made, _ = accounts.create_token(db, owner.user, "grafana", "metrics", None, Actor.system())
    passwords_typed(monkeypatch, "reset from the shell", "reset from the shell")
    assert run("reset-password") == 0
    out = capsys.readouterr().out
    assert "grafana (metrics)" in out and "reset from the shell" not in out
    db.expire_all()
    assert sessions.find(db, owner.session_secret) is None
    assert sessions.find(db, other.session_secret) is None
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, made)
    assert accounts.sign_in(db, "owner", "reset from the shell", BROWSER)
    (row,) = audited(db, "password_reset")
    assert row.actor_kind == "cli" and row.detail == {"tokens_revoked": ["grafana"]}
    assert (archive_keys.state_dir() / throttle.RESET_FLAG).exists()


def test_reset_password_refuses_a_mismatch_or_a_short_password(db, owner, capsys, monkeypatch):
    passwords_typed(monkeypatch, "reset from the shell", "something else here")
    assert run("reset-password") == 1
    assert "differ" in capsys.readouterr().err
    passwords_typed(monkeypatch, "short", "short")
    assert run("reset-password") == 1
    assert "12 to 256" in capsys.readouterr().err
    assert audited(db, "password_reset") == []
    assert accounts.sign_in(db, "owner", PASSWORD, BROWSER)


def test_reset_password_clears_the_running_throttles(db, owner, monkeypatch):
    for _ in range(8):
        throttle.fail("user", "owner")
    assert throttle.wait("user", "owner") > 0
    passwords_typed(monkeypatch, "reset from the shell", "reset from the shell")
    assert run("reset-password") == 0
    assert throttle.wait("user", "owner") == 0


def test_sign_out_everywhere(db, owner, capsys):
    made, _ = accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    assert run("sign-out-everywhere") == 0
    assert "Ended 1 session(s)" in capsys.readouterr().out
    db.expire_all()
    assert sessions.find(db, owner.session_secret) is None
    tokens.authenticate(db, made)  # tokens have their own command
    (row,) = audited(db, "sessions_revoked_all")
    assert row.actor_kind == "cli" and row.detail == {"sessions": 1, "devices": 1}


def test_revoke_tokens(db, owner, capsys):
    ci, _ = accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    seed, _ = accounts.create_token(db, owner.user, "seed", "write", 1, Actor.system())
    assert run("revoke-tokens", "--name", "ci") == 0
    assert "ci (read)" in capsys.readouterr().out
    db.expire_all()
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, ci)
    tokens.authenticate(db, seed)
    assert run("revoke-tokens", "--name", "nothing") == 1
    assert run("revoke-tokens") == 0
    db.expire_all()
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, seed)
    assert [r.target for r in audited(db, "token_revoked")] == ["ci"]
    assert audited(db, "tokens_revoked_all")[0].detail == {"tokens": ["seed"]}


def test_status_says_everything_but_a_secret(db, owner, capsys):
    made, _ = accounts.create_token(db, owner.user, "grafana", "metrics", None, Actor.system())
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "owner (set up)" in out
    assert "grafana (metrics)" in out and "expires never" in out
    assert "Sessions (1)" in out and "192.0.2.10" in out
    assert archive_keys.primary().recipient in out
    assert "saved outside Cabinet: not confirmed" in out
    for secret in (made, owner.session_secret, owner.device_secret, "AGE-SECRET-KEY"):
        assert secret not in out
    assert audited(db, "backup_key_shown") == []


def test_backup_key_commands_are_audited(db, owner, capsys):
    assert run("backup-key", "show") == 0
    assert "AGE-SECRET-KEY-1" in capsys.readouterr().out
    assert [r.actor_kind for r in audited(db, "backup_key_shown")] == ["cli"]
    assert run("backup-key", "rotate") == 0
    assert len(audited(db, "backup_key_rotated")) == 1
    assert len(archive_keys.identities()) == 2
