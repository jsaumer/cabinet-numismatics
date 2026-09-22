"""The credential services (v0.30.0, SPEC_0300 section 5): passwords and the
reserved slot, sessions, the recent-password window, tokens, known devices,
the throttles, the audit log, and the alert events. The routes that put
these on the wire arrive with the gate (stage 7)."""

import json
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import func, select

from app.auth import accounts, audit, common, devices, notify, passwords, sessions, throttle, tokens
from app.auth.accounts import Client
from app.auth.audit import Actor
from app.db import get_db
from app.main import app
from app.models.auth import ApiToken, AuditEntry, KnownDevice, Session, User
from app.services import alerts

PASSWORD = "correct horse battery"
REAL_HASHER = passwords.HASHER  # before any test swaps in a fast one
BROWSER = Client(address="192.0.2.10", user_agent="Firefox")


class Clock:
    """Frozen wall and monotonic time, moved by hand."""

    def __init__(self):
        self.wall = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        self.mono = 1_000_000.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(common, "now", lambda: c.wall)
    monkeypatch.setattr(common, "monotonic", lambda: c.mono)
    return c


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    """Argon2 at the real 64 MiB is slow; tests that need it swap it back."""
    monkeypatch.setattr(
        passwords, "HASHER", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        alerts, "event", lambda db, key, title, message: calls.append((key, message))
    )
    return calls


@pytest.fixture()
def db(client):
    return next(app.dependency_overrides[get_db]())


@pytest.fixture()
def owner(db, sent):
    started = accounts.create_admin(db, "Owner", PASSWORD, BROWSER)
    sent.clear()
    return started


def with_device(started, **changes) -> Client:
    fields = {"address": BROWSER.address, "user_agent": BROWSER.user_agent}
    fields.update(changes)
    return Client(device=started.device_secret, **fields)


def failed_rows(db) -> int:
    return db.scalar(
        select(func.count()).select_from(AuditEntry).where(AuditEntry.action == "sign_in_failed")
    )


# --- passwords --------------------------------------------------------------------


def test_hashing_parameters_are_pinned():
    assert (passwords.TIME_COST, passwords.MEMORY_COST, passwords.PARALLELISM) == (3, 65536, 4)
    real = PasswordHasher(
        time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID
    )
    encoded = REAL_HASHER.hash(PASSWORD)
    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert real.verify(encoded, PASSWORD)
    assert not REAL_HASHER.check_needs_rehash(encoded)


def test_sign_in_rehashes_an_old_hash(db, owner, monkeypatch):
    user = owner.user
    user.password_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    db.commit()
    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    monkeypatch.setattr(passwords, "HASHER", stronger)
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    assert "m=16,t=2" in db.get(User, user.id).password_hash


def test_password_and_username_rules():
    for bad in ("short", "x" * 11, "x" * 257):
        with pytest.raises(passwords.PasswordRejected):
            passwords.check_password_rules(bad)
    passwords.check_password_rules("x" * 12)
    passwords.check_password_rules("x" * 256)
    assert passwords.normalize_username("Jay.S_1-a") == "jay.s_1-a"
    for bad in ("", "x" * 65, "has space", "émile", "a/b"):
        with pytest.raises(passwords.PasswordRejected):
            passwords.normalize_username(bad)


def test_unknown_name_and_wrong_password_fail_alike(db, owner, monkeypatch):
    checked = []
    real_verify = passwords.verify
    monkeypatch.setattr(
        passwords, "verify", lambda s, p, reserved=False: checked.append(s) or real_verify(s, p)
    )
    answers = []
    for name, password in (("nobody", PASSWORD), ("owner", "wrong password!"), ("bad name", "x")):
        with pytest.raises(accounts.WrongPassword) as caught:
            accounts.sign_in(db, name, password, BROWSER)
        answers.append(str(caught.value))
    assert set(answers) == {"Wrong username or password."}
    # The unknown name still cost one Argon2 check, against the dummy hash.
    assert checked[0] is None and checked[1] is not None and checked[2] is None


def test_sign_in_is_case_insensitive(db, owner):
    assert accounts.sign_in(db, "OWNER", PASSWORD, BROWSER).user.username == "owner"


# --- the reserved slot ------------------------------------------------------------------


def test_known_device_gets_the_reserved_slot_while_the_public_one_is_flooded(
    db, owner, monkeypatch
):
    monkeypatch.setattr(passwords, "SLOT_WAIT", 0.3)
    public = passwords._slots[False]
    assert public.acquire(timeout=1)  # a flood holding the public slot
    try:
        # Unknown names and a stranger's browser wait, then get 503.
        with pytest.raises(passwords.Busy):
            accounts.sign_in(db, "nobody", PASSWORD, BROWSER)
        with pytest.raises(passwords.Busy):
            accounts.sign_in(db, "owner", PASSWORD, BROWSER)
        # A forged device cookie is only a hash lookup that misses.
        forged = Client(address=BROWSER.address, device=common.new_secret())
        with pytest.raises(passwords.Busy):
            accounts.sign_in(db, "owner", PASSWORD, forged)
        began = time.monotonic()
        started = accounts.sign_in(db, "owner", PASSWORD, with_device(owner))
        assert time.monotonic() - began < 10
        assert started.new_device is False
    finally:
        public.release()


def test_a_device_cookie_for_another_name_never_gets_the_reserved_slot(db, owner, monkeypatch):
    monkeypatch.setattr(passwords, "SLOT_WAIT", 0.3)
    public = passwords._slots[False]
    assert public.acquire(timeout=1)
    try:
        with pytest.raises(passwords.Busy):
            accounts.sign_in(db, "nobody", PASSWORD, with_device(owner))
    finally:
        public.release()


def test_busy_answers_with_retry_after():
    assert passwords.Busy().retry_after == 5


# --- throttles --------------------------------------------------------------------


def test_user_bucket_curve(clock):
    for _ in range(5):
        throttle.check(("user", "owner"))
        throttle.fail("user", "owner")
    waits = []
    for _ in range(9):
        waits.append(throttle.wait("user", "owner"))
        clock.advance(waits[-1])
        throttle.fail("user", "owner")
    assert waits == [1, 2, 4, 8, 16, 32, 60, 60, 60]  # 2^(n-5), capped at 60 s
    with pytest.raises(throttle.Throttled) as caught:
        throttle.check(("user", "owner"))
    assert caught.value.retry_after == 60


def test_address_bucket_is_free_for_twenty(clock):
    for _ in range(20):
        throttle.check(("addr", "192.0.2.1"))
        throttle.fail("addr", "192.0.2.1")
    assert throttle.wait("addr", "192.0.2.1") == 1


def test_buckets_forget_after_fifteen_minutes_and_on_success(clock):
    for _ in range(8):
        throttle.fail("user", "owner")
    assert throttle.wait("user", "owner") > 0
    clock.advance(15 * 60)
    assert throttle.wait("user", "owner") == 0
    for _ in range(8):
        throttle.fail("user", "owner")
    throttle.succeed("user", "owner")
    assert throttle.wait("user", "owner") == 0


def test_global_limit_is_sixty_checks_a_minute(clock):
    for _ in range(60):
        throttle.check_global()
    with pytest.raises(throttle.Throttled):
        throttle.check_global()
    clock.advance(60)
    throttle.check_global()


def test_setup_bucket_waits_out_the_window(clock):
    for _ in range(5):
        throttle.check(("setup", "192.0.2.1"))
        throttle.fail("setup", "192.0.2.1")
    assert throttle.wait("setup", "192.0.2.1") == 15 * 60
    clock.advance(14 * 60)
    assert throttle.wait("setup", "192.0.2.1") == 60
    clock.advance(60)
    assert throttle.wait("setup", "192.0.2.1") == 0


def test_the_map_holds_at_most_ten_thousand_keys(clock):
    for n in range(throttle.MAX_KEYS + 5):
        throttle.fail("addr", f"10.0.{n // 256}.{n % 256}")
    assert throttle.size() == throttle.MAX_KEYS
    assert throttle.wait("addr", "10.0.0.0") == 0  # the oldest went first


def test_throttled_sign_in_does_no_argon2_work(db, owner, clock, monkeypatch):
    for _ in range(5):
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, "owner", "wrong password!", BROWSER)
    monkeypatch.setattr(passwords, "verify", lambda *a, **k: pytest.fail("hashed"))
    with pytest.raises(throttle.Throttled):
        accounts.sign_in(db, "owner", PASSWORD, BROWSER)


def test_reset_flag_clears_the_running_throttles(clock):
    for _ in range(8):
        throttle.fail("user", "owner")
    assert throttle.wait("user", "owner") > 0  # first look only notes the flag
    throttle.request_reset()
    assert throttle.wait("user", "owner") == 0


# --- known devices ----------------------------------------------------------------


def test_a_known_device_lifts_the_user_address_and_global_limits(db, owner, clock):
    for _ in range(5):  # the user bucket's free failures
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, "owner", "wrong password!", BROWSER)
    for n in range(15):  # the address reaches its twenty
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, f"guess{n}", "wrong password!", BROWSER)
    assert throttle.wait("user", "owner") > 0 and throttle.wait("addr", BROWSER.address) > 0
    for _ in range(40):  # and the global minute is used up
        throttle.check_global()
    with pytest.raises(throttle.Throttled):
        throttle.check_global()
    with pytest.raises(throttle.Throttled):
        accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    assert accounts.sign_in(db, "owner", PASSWORD, with_device(owner)).new_device is False


def test_a_known_device_never_lifts_the_setup_throttle(clock):
    for _ in range(5):
        throttle.fail("setup", "192.0.2.10")
    # Setup takes no device into account at all: its bucket is checked alone.
    with pytest.raises(throttle.Throttled):
        throttle.check(("setup", "192.0.2.10"))


def test_forged_expired_and_other_account_devices_do_not_count(db, owner, clock):
    user = owner.user
    assert devices.find(db, owner.device_secret, user.id) is not None
    assert devices.find(db, common.new_secret(), user.id) is None
    assert devices.find(db, "not-a-secret", user.id) is None
    assert devices.find(db, owner.device_secret, user.id + 1) is None
    clock.advance(7 * 24 * 3600)
    assert devices.find(db, owner.device_secret, user.id) is None


def test_five_failures_forget_a_device_and_the_sixth_is_delayed(db, owner, clock):
    device = with_device(owner)
    for _ in range(5):
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, "owner", "wrong password!", device)
    assert db.scalar(select(func.count()).select_from(KnownDevice)) == 0
    with pytest.raises(throttle.Throttled):
        accounts.sign_in(db, "owner", PASSWORD, device)


def test_a_success_replaces_the_device(db, owner):
    started = accounts.sign_in(db, "owner", PASSWORD, with_device(owner))
    assert started.device_secret != owner.device_secret
    assert devices.find(db, owner.device_secret, owner.user.id) is None
    assert devices.find(db, started.device_secret, owner.user.id) is not None


def test_password_change_reset_and_sign_out_everywhere_make_devices_inert(db, owner):
    user = owner.user
    changed = accounts.change_password(
        db, owner.session, user, PASSWORD, "a brand new password", with_device(owner)
    )
    assert devices.find(db, owner.device_secret, user.id) is None
    assert devices.find(db, changed.started.device_secret, user.id) is not None  # re-issued

    accounts.reset_password(db, "reset from the shell", Actor.cli(user))
    assert db.scalar(select(func.count()).select_from(KnownDevice)) == 0

    again = accounts.sign_in(db, "owner", "reset from the shell", BROWSER)
    accounts.sign_out_everywhere(db, user, Actor.cli(user))
    assert devices.find(db, again.device_secret, user.id) is None
    assert sessions.find(db, again.session_secret) is None


# --- sessions ---------------------------------------------------------------------


def test_session_idle_and_absolute_expiry(db, owner, clock):
    started = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    secret = started.session_secret
    assert sessions.find(db, secret) is not None
    clock.advance(24 * 3600 - 1)
    assert sessions.find(db, secret) is not None
    clock.advance(1)
    assert sessions.find(db, secret) is None  # a day unused

    started = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    for _ in range(7):  # used every 23 hours: 161 hours and still valid
        clock.advance(23 * 3600)
        found = sessions.find(db, started.session_secret)
        assert found is not None
        assert sessions.touch(found[0])
        db.commit()
    clock.advance(23 * 3600)
    assert sessions.find(db, started.session_secret) is None  # 7 days from creation
    assert common.aware(started.session.expires_at) == common.aware(
        started.session.created_at
    ) + timedelta(days=7)


def test_touch_writes_at_most_once_a_minute(db, owner, clock):
    row = owner.session
    assert not sessions.touch(row)
    clock.advance(59)
    assert not sessions.touch(row)
    clock.advance(1)
    assert sessions.touch(row)


def test_sessions_rotate_and_are_stored_hashed(db, owner):
    first = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    second = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    assert first.session_secret != second.session_secret
    assert common.SECRET_RE.fullmatch(first.session_secret)
    stored = db.scalars(select(Session.secret_hash)).all()
    assert common.digest(first.session_secret) in stored
    assert all(first.session_secret.encode() not in h for h in stored)


def test_a_session_ends_with_its_account(db, owner):
    owner.user.is_active = False
    db.commit()
    assert sessions.find(db, owner.session_secret) is None


def test_password_change_rotates_this_session_and_ends_the_others(db, owner):
    other = accounts.sign_in(db, "owner", PASSWORD, Client(address="198.51.100.7"))
    changed = accounts.change_password(
        db, owner.session, owner.user, PASSWORD, "a brand new password", BROWSER
    )
    assert sessions.find(db, owner.session_secret) is None
    assert sessions.find(db, other.session_secret) is None
    assert sessions.find(db, changed.started.session_secret) is not None
    with pytest.raises(accounts.WrongPassword):
        accounts.sign_in(db, "owner", PASSWORD, BROWSER)


def test_password_change_needs_the_current_password(db, owner):
    with pytest.raises(accounts.WrongPassword) as caught:
        accounts.change_password(
            db, owner.session, owner.user, "not the password", "a brand new password", BROWSER
        )
    assert str(caught.value) == "Wrong password."
    with pytest.raises(passwords.PasswordRejected):
        accounts.change_password(db, owner.session, owner.user, PASSWORD, "short", BROWSER)
    assert sessions.find(db, owner.session_secret) is not None


def test_username_change_needs_the_current_password(db, owner):
    with pytest.raises(accounts.WrongPassword):
        accounts.change_username(db, owner.session, owner.user, "nope nope nope", "jay", BROWSER)
    accounts.change_username(db, owner.session, owner.user, PASSWORD, "Jay", BROWSER)
    assert db.get(User, owner.user.id).username == "jay"
    assert accounts.sign_in(db, "jay", PASSWORD, BROWSER)


def test_sign_out_ends_the_session_and_forgets_this_device(db, owner):
    accounts.sign_out(db, owner.session, owner.user, with_device(owner))
    assert sessions.find(db, owner.session_secret) is None
    assert devices.find(db, owner.device_secret, owner.user.id) is None


def test_end_one_session(db, owner):
    other = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    accounts.end_session(db, owner.user, other.session.id, Actor.cli(owner.user))
    assert sessions.find(db, other.session_secret) is None
    assert sessions.find(db, owner.session_secret) is not None
    with pytest.raises(accounts.NotFound):
        accounts.end_session(db, owner.user, other.session.id, Actor.cli(owner.user))


# --- the recent-password window -------------------------------------------------------


def test_confirmation_window(db, owner, clock):
    row = owner.session
    assert not sessions.confirmed(row)
    with pytest.raises(accounts.WrongPassword):
        accounts.confirm(db, row, owner.user, "wrong password!", BROWSER)
    assert not sessions.confirmed(row)
    accounts.confirm(db, row, owner.user, PASSWORD, BROWSER)
    assert sessions.confirmed(row)
    clock.advance(5 * 60 - 1)
    assert sessions.confirmed(row)
    clock.advance(1)
    assert not sessions.confirmed(row)


def test_confirmation_is_for_one_session_and_cleared_on_sign_out_and_password_change(db, owner):
    other = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    accounts.confirm(db, owner.session, owner.user, PASSWORD, BROWSER)
    assert not sessions.confirmed(other.session)
    accounts.sign_out(db, owner.session, owner.user, BROWSER)
    assert not sessions.confirmed(owner.session)

    accounts.confirm(db, other.session, owner.user, PASSWORD, BROWSER)
    changed = accounts.change_password(
        db, other.session, owner.user, PASSWORD, "a brand new password", BROWSER
    )
    assert not sessions.confirmed(other.session)
    assert not sessions.confirmed(changed.started.session)


def test_a_token_has_no_confirmation_window():
    assert not hasattr(ApiToken, "confirmed_until")


# --- tokens -----------------------------------------------------------------------


def test_token_format_and_lookup(db, owner):
    plaintext, row = accounts.create_token(db, owner.user, "ci", "write", 1, Actor.cli(owner.user))
    assert tokens.TOKEN_RE.fullmatch(plaintext)
    assert plaintext.startswith(f"cabinet_{row.public_id}_")
    assert row.secret_hash == common.digest(plaintext[len("cabinet_") + 11 :])
    found, user = tokens.authenticate(db, plaintext)
    assert found.id == row.id and user.id == owner.user.id
    assert plaintext not in json.dumps([r.detail for r in db.scalars(select(AuditEntry))])


def test_token_lifetimes(db, owner, clock):
    for scope in ("read", "write"):
        with pytest.raises(tokens.TokenRejected):
            accounts.create_token(db, owner.user, f"{scope}-forever", scope, None, Actor.system())
        with pytest.raises(tokens.TokenRejected):
            accounts.create_token(db, owner.user, f"{scope}-month", scope, 30, Actor.system())
    with pytest.raises(tokens.TokenRejected):
        accounts.create_token(db, owner.user, "admin", "admin", 1, Actor.system())
    plaintext, row = accounts.create_token(
        db, owner.user, "grafana", "metrics", None, Actor.system()
    )
    assert row.expires_at is None
    week, _ = accounts.create_token(db, owner.user, "seed", "read", 7, Actor.system())
    clock.advance(7 * 24 * 3600 - 1)
    tokens.authenticate(db, week)
    clock.advance(1)
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, week)
    tokens.authenticate(db, plaintext)


def test_token_names_and_the_live_limit(db, owner, monkeypatch):
    accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    with pytest.raises(tokens.TokenRejected):
        accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    monkeypatch.setattr(tokens, "MAX_LIVE", 2)
    accounts.create_token(db, owner.user, "two", "read", 1, Actor.system())
    with pytest.raises(tokens.TokenRejected):
        accounts.create_token(db, owner.user, "three", "read", 1, Actor.system())


def test_invalid_tokens_are_refused(db, owner):
    plaintext, row = accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    public_id = row.public_id
    wrong_secret = f"cabinet_{public_id}_{common.new_secret()}"
    unknown = f"cabinet_{'a' * 10}_{common.new_secret()}"
    for bad in (wrong_secret, unknown, "cabinet_short", plaintext + "x", plaintext.upper()):
        with pytest.raises(tokens.InvalidToken):
            tokens.authenticate(db, bad)
    accounts.revoke_token(db, owner.user, row.id, Actor.system())
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, plaintext)


def test_a_token_ends_with_its_account(db, owner):
    plaintext, _ = accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    owner.user.is_active = False
    db.commit()
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, plaintext)


def test_only_a_cabinet_bearer_is_a_token():
    """Anything else in Authorization is some other proxy's business: the
    request is treated as a cookie request. A Cabinet token that doesn't
    check out is 401, with no fall back to the cookie (the gate, stage 7)."""
    assert tokens.bearer(None) is None
    assert tokens.bearer("Basic dXNlcjpwYXNz") is None
    assert tokens.bearer("Bearer eyJhbGciOi.jwt.from-authentik") is None
    assert tokens.bearer("cabinet_abc") is None  # no scheme
    assert tokens.bearer("bearer cabinet_anything") == "cabinet_anything"
    assert tokens.bearer("Bearer  cabinet_x ") == "cabinet_x"


def test_password_change_and_reset_revoke_every_token_of_every_scope(db, owner):
    made = [
        accounts.create_token(db, owner.user, scope, scope, days, Actor.system())[0]
        for scope, days in (("read", 1), ("write", 7), ("metrics", None))
    ]
    changed = accounts.change_password(
        db, owner.session, owner.user, PASSWORD, "a brand new password", BROWSER
    )
    assert sorted(t["scope"] for t in changed.revoked_tokens) == ["metrics", "read", "write"]
    for plaintext in made:
        with pytest.raises(tokens.InvalidToken):
            tokens.authenticate(db, plaintext)

    metrics, _ = accounts.create_token(db, owner.user, "grafana", "metrics", None, Actor.system())
    revoked = accounts.reset_password(db, "reset from the shell", Actor.cli(owner.user))
    assert [t["name"] for t in revoked] == ["grafana"]
    with pytest.raises(tokens.InvalidToken):
        tokens.authenticate(db, metrics)


def test_token_last_use_is_written_at_most_once_a_minute(db, owner, clock):
    _, row = accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    assert tokens.touch(row)
    clock.advance(59)
    assert not tokens.touch(row)
    clock.advance(1)
    assert tokens.touch(row)


def test_no_token_is_committed_to_the_repository():
    root = Path(__file__).resolve().parents[2]
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.split(b"\0")
    pattern = tokens.TOKEN_RE.pattern.encode()
    import re

    found = []
    for name in filter(None, listed):
        path = root / name.decode()
        if path.is_file() and re.search(pattern, path.read_bytes()):
            found.append(name.decode())
    assert found == []


# --- the audit log ------------------------------------------------------------------


def test_failed_names_are_recorded_only_when_they_are_the_account(db, owner):
    for name in ("owner", "OWNER", "someone-else", "not valid!"):
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, name, "wrong password!", BROWSER)
    labels = db.scalars(
        select(AuditEntry.actor_label)
        .where(AuditEntry.action == "sign_in_failed")
        .order_by(AuditEntry.id)
    ).all()
    assert labels == ["owner", "owner", "unknown", "unknown"]


def test_failures_have_a_cap_of_their_own(db, owner, monkeypatch, clock):
    monkeypatch.setattr(audit, "FAILED_CAP", 3)
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)  # a sign_in row to keep
    for _ in range(6):
        with pytest.raises((accounts.WrongPassword, throttle.Throttled)):
            accounts.sign_in(db, "nobody", "wrong password!", Client(address="203.0.113.9"))
        clock.advance(120)
    assert failed_rows(db) == 3
    actions = db.scalars(select(AuditEntry.action)).all()
    assert "setup" in actions and "sign_in" in actions  # never pushed out


def test_other_events_are_kept_180_days_or_the_row_cap(db, owner, monkeypatch, clock):
    monkeypatch.setattr(audit, "KEEP_ROWS", 4)
    for _ in range(6):
        audit.record(db, "reauth", Actor.system())
    db.commit()
    assert db.scalar(select(func.count()).select_from(AuditEntry)) == 4
    clock.advance(181 * 24 * 3600)
    audit.record(db, "reauth", Actor.system())
    db.commit()
    assert db.scalar(select(func.count()).select_from(AuditEntry)) == 1


def test_audit_refuses_unknown_events_and_secret_details(db):
    with pytest.raises(ValueError):
        audit.record(db, "made_up", Actor.system())
    with pytest.raises(ValueError):
        audit.record(db, "reauth", Actor.system(), detail={"password": "x"})


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def events(self):
        return [json.loads(r.getMessage()) for r in self.records]

    @property
    def text(self):
        return " ".join(r.getMessage() for r in self.records)


@pytest.fixture()
def audit_lines():
    """The `cabinet` logger doesn't propagate (main.py), so caplog misses it."""
    handler = Lines()
    logger = logging.getLogger("cabinet.audit")
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(level)


def test_stdout_is_one_line_per_event_and_sampled_for_failures(db, owner, clock, audit_lines):
    for _ in range(4):
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, "nobody", "wrong password!", Client(address=f"203.0.113.{_}"))
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    lines = audit_lines.events
    assert [line["event"] for line in lines] == ["sign_in_failed", "sign_in"]
    assert lines[0]["count"] == 1 and lines[0]["user"] == "unknown"
    clock.advance(15 * 60)
    audit_lines.records.clear()
    with pytest.raises(accounts.WrongPassword):
        accounts.sign_in(db, "nobody", "wrong password!", BROWSER)
    assert audit_lines.events[0]["count"] == 4  # three held back, and this one
    assert PASSWORD not in audit_lines.text and "wrong password!" not in audit_lines.text


def test_audit_page_is_newest_first(db, owner):
    for _ in range(3):
        audit.record(db, "reauth", Actor.system())
    db.commit()
    rows = audit.page(db, limit=2)
    assert [r.id for r in rows] == sorted((r.id for r in rows), reverse=True)
    assert audit.page(db, before=rows[-1].id, limit=500)[0].id < rows[-1].id
    assert len(audit.page(db, limit=1000)) <= 200


# --- the sign-in answer and alerts ---------------------------------------------------------


def test_failed_since_previous_sign_in(db, owner, clock):
    first = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    clock.advance(60)
    for _ in range(3):
        with pytest.raises(accounts.WrongPassword):
            accounts.sign_in(db, "owner", "wrong password!", BROWSER)
    with pytest.raises(accounts.WrongPassword):
        accounts.sign_in(db, "nobody", "wrong password!", BROWSER)  # not this account
    clock.advance(60)
    second = accounts.sign_in(db, "owner", PASSWORD, with_device(first))
    assert second.failed_since_previous == 3
    assert second.previous_sign_in_at is not None
    third = accounts.sign_in(db, "owner", PASSWORD, with_device(second))
    assert third.failed_since_previous == 0


def test_alert_events_fire_once_and_carry_no_collection_data(db, owner, sent, coin, clock):
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    accounts.sign_in(db, "owner", PASSWORD, with_device(owner))  # known: no alert
    accounts.create_token(db, owner.user, "ci", "read", 1, Actor.system())
    accounts.change_password(
        db, owner.session, owner.user, PASSWORD, "a brand new password", BROWSER
    )
    accounts.reset_password(db, "reset from the shell", Actor.cli(owner.user))
    assert [key for key, _ in sent] == [
        "sign_in_new_device",
        "token_created",
        "password_changed",
        "password_reset",
    ]
    item = coin
    for _, message in sent:
        assert item["country"] not in message and item["denomination"] not in message


def test_repeated_failures_alert_at_most_once_an_hour(db, owner, sent, clock):
    def fail_many(n):
        for i in range(n):
            with pytest.raises((accounts.WrongPassword, throttle.Throttled)):
                accounts.sign_in(db, f"guess{i}", "wrong password!", Client(address=f"10.1.0.{i}"))
            clock.advance(1)

    fail_many(19)
    assert sent == []
    fail_many(1)
    assert [key for key, _ in sent] == ["sign_in_failures"]
    fail_many(20)
    assert len(sent) == 1
    clock.advance(3600)
    fail_many(20)
    assert len(sent) == 2
    assert all(notify.TITLES[key] for key, _ in sent)


# --- the claim ------------------------------------------------------------------------


def test_one_claim_only(db, owner):
    assert accounts.claimed(db)
    with pytest.raises(accounts.AlreadyClaimed):
        accounts.create_admin(db, "someone", PASSWORD, BROWSER)


def test_the_claim_is_atomic_in_the_database(db, owner, monkeypatch):
    """Two setups at once both pass the `claimed` check; the claim row's key
    (id is always 1) lets only one commit. Postgres gets two real requests in
    CI; here the race is set up by hand."""
    monkeypatch.setattr(accounts, "claimed", lambda db: False)
    for name in ("someone", "owner"):
        with pytest.raises(accounts.AlreadyClaimed):
            accounts.create_admin(db, name, PASSWORD, BROWSER)
    assert db.scalar(select(func.count()).select_from(User)) == 1


# --- housekeeping ---------------------------------------------------------------------


def test_prune_drops_what_can_never_work_again(db, owner, clock):
    live = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    ended = accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    accounts.sign_out(db, ended.session, owner.user, BROWSER)
    _, token = accounts.create_token(db, owner.user, "old", "read", 1, Actor.system())
    live_id, ended_id, token_id = live.session.id, ended.session.id, token.id
    accounts.prune(db)
    ids = set(db.scalars(select(Session.id)).all())
    assert live_id in ids and ended_id not in ids
    assert db.get(ApiToken, token_id) is not None
    clock.advance(32 * 24 * 3600)  # the token expired a day in, kept 30 days after
    accounts.prune(db)
    assert db.scalar(select(func.count()).select_from(Session)) == 0
    assert db.scalar(select(func.count()).select_from(KnownDevice)) == 0
    assert db.scalar(select(func.count()).select_from(ApiToken)) == 0
