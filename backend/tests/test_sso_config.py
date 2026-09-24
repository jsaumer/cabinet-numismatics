"""Single sign-on, stage 1 (v0.33.0, SPEC_0330 sections 4, 7, 8): the a0002
tables and their constraints, the configuration read on every use, the
trusted-header deployment checks, removing a way in, the container
commands, and the audit caps and alerts that come with them."""

from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import cli
from app import db as app_db
from app.auth import accounts, audit, common, notify, passwords, sessions
from app.auth import config as sso_config
from app.auth.accounts import Client
from app.auth.audit import Actor
from app.config import (
    TRUSTED_HEADER_FORBIDDEN,
    ConfigError,
    Settings,
    check_startup,
    forbidden_header,
)
from app.db import get_db
from app.main import app
from app.models.auth import (
    AuditEntry,
    AuthConfig,
    AuthProvider,
    Identity,
    KnownBrowser,
    Session,
    User,
)
from app.services import alerts, crypto

PASSWORD = "correct horse battery"
BROWSER = Client(address="192.0.2.10", user_agent="Firefox")
TRUSTED = {
    "trusted_assertion_header": "X-authentik-jwt",
    "trusted_assertion_jwks_url": "https://auth.example.com/application/o/cabinet/jwks/",
    "trusted_assertion_issuer": "https://auth.example.com/application/o/cabinet/",
    "trusted_assertion_audience": "cabinet-client-id",
}


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
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
def db(unclaimed_client, monkeypatch):
    make = app.dependency_overrides[get_db]
    monkeypatch.setattr(app_db, "SessionLocal", lambda: next(make()))
    return next(make())


@pytest.fixture()
def fresh(unclaimed_client):
    """Another session on the same database, as another request would get."""
    make = app.dependency_overrides[get_db]
    return lambda: next(make())


@pytest.fixture()
def owner(db, sent):
    started = accounts.create_admin(db, "owner", PASSWORD, BROWSER)
    sent.clear()
    return started


def settings(**values) -> Settings:
    return Settings(**{"public_origins": "https://cabinet.example.com", **values})


def add(db, preset="custom", **values) -> AuthProvider:
    fields = {
        "display_name": preset.title(),
        "client_id": f"client-{preset}-{values.get('issuer', '')}",
        "secret": "client secret value",
    }
    if preset == "custom":
        fields["issuer"] = "https://idp.example.com"
    if preset == "microsoft":
        fields["tenant"] = "0000-tenant"
    fields.update(values)
    row = sso_config.add_provider(db, preset=preset, **fields)
    db.commit()
    return row


def link(db, user, provider=None, subject="subject-1", issuer=None) -> Identity:
    row = Identity(
        user_id=user.id,
        kind="provider" if provider is not None else "trusted_header",
        provider_id=provider.id if provider is not None else None,
        issuer=issuer or (provider.issuer if provider is not None else "https://gateway"),
        subject=subject,
        linked_at=common.now(),
    )
    db.add(row)
    db.commit()
    return row


def session_via(db, user, identity=None) -> Session:
    method = "password"
    if identity is not None:
        method = "oidc" if identity.kind == "provider" else "trusted_header"
    _, row = sessions.create(
        db, user, method=method, identity_id=identity.id if identity is not None else None
    )
    db.commit()
    return row


def live_ids(db) -> set[int]:
    db.expire_all()
    return set(db.scalars(select(Session.id).where(Session.revoked_at.is_(None))).all())


# --- the tables ----------------------------------------------------------------------


def test_preset_kind_constraint(db):
    db.add(
        AuthProvider(
            kind="oidc",
            preset="github",
            display_name="x",
            issuer="https://github.com",
            client_id="c",
            client_secret="",
            scopes="",
        )  # fmt: skip
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(
        AuthProvider(
            kind="oauth2_profile",
            preset="custom",
            display_name="x",
            issuer="https://i",
            client_id="c",
            client_secret="",
            scopes="",
        )  # fmt: skip
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    with pytest.raises(ValueError):
        sso_config.check_preset("oidc", "github")
    sso_config.check_preset("oauth2_profile", "github")
    for preset in ("google", "microsoft", "custom"):
        sso_config.check_preset("oidc", preset)


def test_identities_check_ties_kind_to_provider(db, owner):
    db.add(Identity(user_id=owner.user.id, kind="provider", issuer="i", subject="s"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    provider = add(db)
    db.add(
        Identity(
            user_id=owner.user.id,
            kind="trusted_header",
            provider_id=provider.id,
            issuer="i",
            subject="s",
        )  # fmt: skip
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_one_header_identity_per_user_sqlite(db, owner):
    link(db, owner.user, subject="first")
    db.add(Identity(user_id=owner.user.id, kind="trusted_header", issuer="g", subject="second"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    # The same header identity can't belong to two accounts either.
    other = User(username="other", role="admin", is_active=True)
    db.add(other)
    db.commit()
    db.add(
        Identity(user_id=other.id, kind="trusted_header", issuer="https://gateway", subject="first")
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_provider_identities_for_one_user_on_two_providers(db, owner):
    a, b = add(db, issuer="https://a.example.com"), add(db, issuer="https://b.example.com")
    link(db, owner.user, a)
    link(db, owner.user, b)
    assert db.scalar(select(func.count()).select_from(Identity)) == 2
    # One identity per provider per account.
    db.add(
        Identity(user_id=owner.user.id, kind="provider", provider_id=a.id, issuer="x", subject="y")
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_one_identity_in_two_modes(db, owner):
    """One Authentik user in global-issuer mode can be linked through a
    provider and the header mode at once (CR-16)."""
    provider = add(db, issuer="https://auth.example.com")
    link(db, owner.user, provider, subject="same", issuer="https://auth.example.com")
    link(db, owner.user, None, subject="same", issuer="https://auth.example.com")
    assert db.scalar(select(func.count()).select_from(Identity)) == 2


def test_the_config_row_is_made_when_missing(db):
    assert db.get(AuthConfig, 1) is None  # create_all has no migration insert
    row = sso_config.get_config(db)
    db.commit()
    assert row.id == 1
    assert row.password_sign_in_alerts is False and row.trusted_header_enabled is True
    assert sso_config.get_config(db) is row
    with pytest.raises(IntegrityError):
        db.add(AuthConfig(id=2))
        db.flush()
    db.rollback()


# --- providers -----------------------------------------------------------------------


def test_presets_fix_what_a_client_may_not_choose(db):
    github = add(db, "github")
    assert (github.kind, github.issuer) == ("oauth2_profile", "https://github.com")
    assert github.scopes == ""
    google = add(db, "google")
    assert google.issuer == "https://accounts.google.com" and google.kind == "oidc"
    microsoft = add(db, "microsoft", tenant="abc-123")
    assert microsoft.issuer == "https://login.microsoftonline.com/abc-123/v2.0"
    with pytest.raises(ValueError):
        sso_config.issuer_for("microsoft")
    with pytest.raises(ValueError):
        sso_config.issuer_for("custom")
    with pytest.raises(ValueError):
        sso_config.issuer_for("apple")
    assert "profile_url" in sso_config.PRESETS["github"]
    assert all(p["kind"] in ("oidc", "oauth2_profile") for p in sso_config.PRESETS.values())


def test_client_secret_is_stored_encrypted(db):
    row = add(db, secret="s3cret-value")
    assert crypto.is_encrypted(row.client_secret)
    assert "s3cret-value" not in row.client_secret
    assert sso_config.client_secret(row) == "s3cret-value"
    assert sso_config.update_provider(db, row, client_secret="another") == ["client_secret"]
    assert sso_config.client_secret(row) == "another"


def test_at_most_eight_providers(db):
    for n in range(sso_config.MAX_PROVIDERS):
        add(db, issuer=f"https://idp{n}.example.com")
    with pytest.raises(sso_config.TooManyProviders):
        add(db, issuer="https://one-more.example.com")


def test_linked_provider_cannot_be_repointed(db, owner):
    row = add(db)
    assert sso_config.update_provider(db, row, issuer="https://new.example.com") == ["issuer"]
    link(db, owner.user, row)
    for field, value in (
        ("issuer", "https://elsewhere.example.com"),
        ("client_id", "another-client"),
        ("preset", "google"),
        ("kind", "oauth2_profile"),
    ):
        with pytest.raises(sso_config.ProviderLinked) as refused:
            sso_config.update_provider(db, row, **{field: value})
        assert refused.value.fields == [field]
    assert row.issuer == "https://new.example.com"
    # What doesn't repoint it still changes.
    assert sso_config.update_provider(db, row, display_name="Authentik", issuer=row.issuer) == [
        "display_name"
    ]
    with pytest.raises(ValueError):
        sso_config.update_provider(db, row, enabled=True)


def test_first_provider_switches_alerts_on(db, owner):
    first, second = add(db, issuer="https://a.example.com"), add(db, issuer="https://b.example.com")
    assert sso_config.get_config(db).password_sign_in_alerts is False
    sso_config.enable_provider(db, first, Actor.system())
    db.commit()
    assert sso_config.get_config(db).password_sign_in_alerts is True
    rows = db.scalars(select(AuditEntry).where(AuditEntry.action == "sso_configured")).all()
    assert [r.detail for r in rows] == [{"changed": ["password_sign_in_alerts"]}]
    # The owner switches it off; enabling a second provider leaves it off.
    sso_config.get_config(db).password_sign_in_alerts = False
    db.commit()
    sso_config.enable_provider(db, second, Actor.system())
    db.commit()
    assert sso_config.get_config(db).password_sign_in_alerts is False
    rows = db.scalars(select(AuditEntry).where(AuditEntry.action == "sso_configured")).all()
    assert len(rows) == 1


def test_configuration_is_read_fresh_every_time(db, fresh):
    row = add(db)
    other = fresh()
    assert sso_config.providers(other, enabled_only=True) == []
    sso_config.enable_provider(db, row, Actor.system())
    db.commit()
    assert [p.id for p in sso_config.providers(fresh(), enabled_only=True)] == [row.id]


# --- deployment settings -------------------------------------------------------------


def test_startup_accepts_all_four_or_none():
    check_startup(settings())
    check_startup(settings(**TRUSTED))


@pytest.mark.parametrize("missing", sorted(TRUSTED))
def test_startup_refuses_a_partial_set(missing):
    values = {**TRUSTED, missing: ""}
    with pytest.raises(ConfigError, match=missing.upper()):
        check_startup(settings(**values))
    lone = {missing: TRUSTED[missing]}
    with pytest.raises(ConfigError, match="all four"):
        check_startup(settings(**lone))


def test_startup_warns_once_per_host_whatever_the_port():
    """nginx's $host has no port, and the callback origin is chosen by it
    (CR-08), so two origins on one host are the same host to the warning."""
    warnings = check_startup(
        settings(
            public_origins="http://cabinet.lan:8080,http://cabinet.lan:9090",
            auth_insecure_http=True,
        )
    )
    assert any("cabinet.lan" in w and "more than once" in w for w in warnings)
    warnings = check_startup(settings(public_origins="https://a.example.com,https://b.example.com"))
    assert not any("more than once" in w for w in warnings)


def test_startup_refuses_empty_audience():
    with pytest.raises(ConfigError) as refused:
        check_startup(settings(**{**TRUSTED, "trusted_assertion_audience": "  "}))
    message = str(refused.value)
    assert "TRUSTED_ASSERTION_AUDIENCE" in message and "never be empty" in message


FORBIDDEN_NAMES = [
    "Host", "host", "HOST", "Cookie", "Authorization", "Origin", "Referer",
    "Sec-Fetch-Site", "Sec-Fetch-Mode", "sec-fetch-dest", "Content-Length", "Content-Type",
    "Transfer-Encoding", "Connection", "Upgrade", "X-Real-IP", "x-real-ip",
    "X-Forwarded-For", "X-Forwarded-Proto", "x-forwarded-host", "Forwarded",
]  # fmt: skip


@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_header_name_blocklist(name):
    assert forbidden_header(name)
    with pytest.raises(ConfigError, match="may not be"):
        check_startup(settings(**{**TRUSTED, "trusted_assertion_header": name}))


def test_header_name_blocklist_host_specifically():
    with pytest.raises(ConfigError, match="'Host'"):
        check_startup(settings(**{**TRUSTED, "trusted_assertion_header": "Host"}))
    assert "host" in TRUSTED_HEADER_FORBIDDEN


@pytest.mark.parametrize(
    "name",
    ["X-authentik-jwt", "Cf-Access-Jwt-Assertion", "X-Pomerium-Jwt-Assertion",
     "X-Goog-IAP-JWT-Assertion", "X-Hosted-By", "Forwarded-Jwt"],
)  # fmt: skip
def test_supported_assertion_headers_pass(name):
    assert not forbidden_header(name)
    check_startup(settings(**{**TRUSTED, "trusted_assertion_header": name}))


@pytest.mark.parametrize("name", ["1-Header", "X", "X_Jwt", "X Jwt", "X-" + "a" * 60, "X-Jwt:"])
def test_header_name_shape(name):
    with pytest.raises(ConfigError, match="not a header name"):
        check_startup(settings(**{**TRUSTED, "trusted_assertion_header": name}))


def test_jwks_url_needs_https_unless_insecure():
    plain = {**TRUSTED, "trusted_assertion_jwks_url": "http://auth:9000/jwks/"}
    with pytest.raises(ConfigError, match="TRUSTED_ASSERTION_JWKS_URL"):
        check_startup(settings(**plain))
    with pytest.raises(ConfigError, match="TRUSTED_ASSERTION_JWKS_URL"):
        check_startup(settings(**{**TRUSTED, "trusted_assertion_jwks_url": "ftp://x/jwks"}))
    check_startup(settings(public_origins="http://localhost", auth_insecure_http=True, **plain))


def test_sso_ca_file_must_be_readable(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n", encoding="ascii")
    check_startup(settings(sso_ca_file=str(ca)))
    with pytest.raises(ConfigError, match="SSO_CA_FILE"):
        check_startup(settings(sso_ca_file=str(tmp_path / "missing.pem")))
    with pytest.raises(ConfigError, match="SSO_CA_FILE"):
        check_startup(settings(sso_ca_file=str(tmp_path)))  # a folder


def test_two_origins_with_one_host_only_warn():
    warnings = check_startup(
        settings(public_origins="https://cabinet.example.com,http://cabinet.example.com:443")
    )
    assert warnings == [] or all("sign-on" in w for w in warnings)
    warnings = check_startup(
        settings(
            public_origins="http://cabinet.lan:8080,http://cabinet.lan:8080",
        )
    )
    assert any("cabinet.lan" in w for w in warnings)  # the host alone: nginx's $host has no port


def test_startup_never_reads_database(monkeypatch, tmp_path):
    from sqlalchemy.engine import Engine

    def refuse(*args, **kwargs):
        raise AssertionError("check_startup touched the database")

    monkeypatch.setattr(Engine, "connect", refuse)
    monkeypatch.setattr(app_db, "SessionLocal", refuse)
    ca = tmp_path / "ca.pem"
    ca.write_text("pem", encoding="ascii")
    check_startup(settings(**TRUSTED, sso_ca_file=str(ca)))
    with pytest.raises(ConfigError):
        check_startup(settings(trusted_assertion_header="X-authentik-jwt"))


def test_trusted_header_configured_and_on(db):
    assert not sso_config.trusted_header_configured(settings())
    assert sso_config.trusted_header_configured(settings(**TRUSTED))
    assert sso_config.trusted_header_on(db, settings(**TRUSTED))
    assert not sso_config.trusted_header_on(db, settings())
    sso_config.get_config(db).trusted_header_enabled = False
    db.commit()
    assert not sso_config.trusted_header_on(db, settings(**TRUSTED))


# --- removing a way in ----------------------------------------------------------------


@pytest.fixture()
def ways_in(db, owner):
    """Sessions through two providers, the header, and the password."""
    user = owner.user
    a, b = add(db, issuer="https://a.example.com"), add(db, issuer="https://b.example.com")
    for row in (a, b):
        sso_config.enable_provider(db, row, Actor.system())
    db.commit()
    ids = {"a": link(db, user, a), "b": link(db, user, b), "header": link(db, user)}
    found = {name: session_via(db, user, identity).id for name, identity in ids.items()}
    found["password"] = owner.session.id
    found["password2"] = session_via(db, user).id
    return {"user": user, "providers": (a, b), "identities": ids, "sessions": found}


def test_removing_a_way_in_ends_its_sessions(db, ways_in, sent, monkeypatch):
    user, found = ways_in["user"], ways_in["sessions"]
    identity = {name: row.id for name, row in ways_in["identities"].items()}
    provider_b = ways_in["providers"][1].id
    everyone = set(found.values())
    assert live_ids(db) == everyone

    # A failure between the revoke and the delete leaves everything live.
    def broken_delete(row):
        raise RuntimeError("the delete failed")

    with monkeypatch.context() as m:
        m.setattr(db, "delete", broken_delete)
        with pytest.raises(RuntimeError):
            accounts.unlink_identity(db, user, identity["a"], Actor.cli(user))
        with pytest.raises(RuntimeError):
            accounts.delete_provider(db, provider_b, Actor.system())
    assert live_ids(db) == everyone
    assert db.get(Identity, identity["a"]) is not None
    assert db.get(Identity, identity["b"]) is not None

    accounts.unlink_identity(db, user, identity["a"], Actor.cli(user))
    assert live_ids(db) == everyone - {found["a"]}
    assert db.get(Identity, identity["a"]) is None

    accounts.delete_provider(db, provider_b, Actor.system())
    assert live_ids(db) == everyone - {found["a"], found["b"]}
    assert db.get(Identity, identity["b"]) is None
    assert db.get(AuthProvider, provider_b) is None

    accounts.disable_sso(db, Actor.cli(user))
    assert live_ids(db) == {found["password"], found["password2"]}
    keys = [key for key, _ in sent]
    assert keys == ["identity_unlinked", "sso_configured", "sso_disabled"]
    assert all(notify.TITLES[key] for key in keys)


def test_unlinking_records_what_was_removed(db, ways_in):
    user, identity = ways_in["user"], ways_in["identities"]["header"]
    with pytest.raises(accounts.NotFound):
        accounts.unlink_identity(db, user, 9999, Actor.cli(user))
    accounts.unlink_identity(db, user, identity.id, Actor.cli(user))
    row = db.scalar(select(AuditEntry).where(AuditEntry.action == "identity_unlinked"))
    assert row.actor_kind == "cli"
    assert row.detail["kind"] == "trusted_header" and row.detail["sessions_ended"] == 1


def test_disable_sso_switches_header_mode_off(db, ways_in, monkeypatch):
    found, config = ways_in["sessions"], settings(**TRUSTED)
    assert sso_config.trusted_header_on(db, config)
    everyone = set(found.values())

    # A failure before the commit changes nothing.
    real = audit.record

    def failing(db_, action, *args, **kwargs):
        if action == "sso_disabled":
            raise RuntimeError("audit failed")
        return real(db_, action, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(audit, "record", failing)
        with pytest.raises(RuntimeError):
            accounts.disable_sso(db, Actor.cli(ways_in["user"]))
    assert live_ids(db) == everyone
    assert sso_config.trusted_header_on(db, config)
    assert len(sso_config.providers(db, enabled_only=True)) == 2

    done = accounts.disable_sso(db, Actor.cli(ways_in["user"]))
    assert done == {
        "providers_disabled": 2,
        "trusted_header_switched_off": True,
        "sessions_ended": 3,
    }
    assert not sso_config.trusted_header_on(db, config)
    assert sso_config.providers(db, enabled_only=True) == []
    assert live_ids(db) == {found["password"], found["password2"]}
    # Linked identities stay; password sign-in still works.
    assert db.scalar(select(func.count()).select_from(Identity)) == 3
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    row = db.scalar(select(AuditEntry).where(AuditEntry.action == "sso_disabled"))
    assert row.detail["sessions_ended"] == 3


# --- the container commands ------------------------------------------------------------


def test_cli_disable_sso_takes_effect_without_restart(db, ways_in, fresh, capsys):
    config = settings(**TRUSTED)
    running = fresh()  # the backend's own session, opened before the command
    assert len(sso_config.providers(running, enabled_only=True)) == 2
    running.close()
    assert cli.main(["disable-sso"]) == 0
    out = capsys.readouterr().out
    assert "Disabled 2 provider(s)" in out and "Ended 3" in out
    after = fresh()  # the next request
    assert sso_config.providers(after, enabled_only=True) == []
    assert not sso_config.trusted_header_on(after, config)
    row = after.scalar(select(AuditEntry).where(AuditEntry.action == "sso_disabled"))
    assert row.actor_kind == "cli"


def test_cli_unlink_identity(db, ways_in, fresh, capsys):
    identity = ways_in["identities"]["b"]
    assert cli.main(["unlink-identity", "9999"]) == 1
    assert "no linked identity" in capsys.readouterr().err
    assert cli.main(["unlink-identity", str(identity.id)]) == 0
    out = capsys.readouterr().out
    assert f"#{identity.id}" in out and "Ended 1 session(s)" in out
    after = fresh()
    assert after.get(Identity, identity.id) is None
    assert ways_in["sessions"]["b"] not in live_ids(after)


def test_cli_status_prints_the_ways_in(db, ways_in, capsys, monkeypatch):
    from app.services import archive_keys

    archive_keys.ensure_key()
    for name, value in TRUSTED.items():
        monkeypatch.setenv(name.upper(), value)
    from app.config import get_settings

    get_settings.cache_clear()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Sign-in methods: password, Custom (provider #" in out
    assert "trusted header: configured, on" in out
    assert "Providers (2):" in out and "custom (oidc), enabled" in out
    assert "Linked identities (3):" in out and "trusted_header via header" in out
    assert "client secret value" not in out and "enc:v1:" not in out
    accounts.disable_sso(db, Actor.system())
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "Sign-in methods: password\n" in out
    assert "trusted header: configured, switched off" in out


@pytest.mark.parametrize("argv", [["unlink-identity", "1"], ["disable-sso"]], ids=" ".join)
def test_the_sso_commands_refuse_before_setup(db, argv, capsys):
    assert cli.main(argv) == 1
    assert accounts.NOT_CLAIMED in capsys.readouterr().err


def test_the_sso_commands_refuse_without_a_database(monkeypatch, capsys):
    from sqlalchemy.exc import OperationalError

    class Unreachable:
        def get(self, *args, **kwargs):
            raise OperationalError("select", {}, Exception("no route"))

        def close(self):
            pass

    monkeypatch.setattr(app_db, "SessionLocal", Unreachable)
    for argv in (["disable-sso"], ["unlink-identity", "1"]):
        assert cli.main(argv) == 1
        assert "can't be reached" in capsys.readouterr().err


# --- audit caps and alerts -------------------------------------------------------------


def test_rejected_sso_rows_are_capped(db, owner, monkeypatch):
    monkeypatch.setattr(audit, "REJECTED_SSO_CAP", 3)
    monkeypatch.setattr(audit, "FAILED_CAP", 2)
    monkeypatch.setattr(audit, "KEEP_ROWS", 5)
    audit.record(db, "password_changed", Actor.system())
    for _ in range(6):
        audit.record(db, "sso_sign_in_rejected", Actor("anonymous"), detail={"reason": "unlinked"})
    for _ in range(4):
        audit.record(db, "sign_in_failed", Actor("anonymous", label="unknown"))
    db.commit()

    def count(action):
        return db.scalar(
            select(func.count()).select_from(AuditEntry).where(AuditEntry.action == action)
        )

    assert count("sso_sign_in_rejected") == 3
    assert count("sign_in_failed") == 2
    assert count("password_changed") == 1 and count("setup") == 1  # never pushed out
    # Other events fill their own cap without touching the rejected rows.
    for _ in range(8):
        audit.record(db, "reauth", Actor.system())
    db.commit()
    assert count("sso_sign_in_rejected") == 3


def test_rejected_sso_stdout_is_sampled(db, clock):
    import logging

    lines = []

    class Grab(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("cabinet.audit")
    handler, level = Grab(logging.INFO), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        for _ in range(5):
            audit.record(db, "sso_sign_in_rejected", Actor("anonymous"))
        audit.record(db, "sign_in_failed", Actor("anonymous"))
        clock.advance(16 * 60)
        audit.record(db, "sso_sign_in_rejected", Actor("anonymous"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    events = [line for line in lines if "sso_sign_in_rejected" in line]
    assert len(events) == 2 and '"count": 5' in events[1]
    assert any("sign_in_failed" in line for line in lines)  # sampled apart


def test_rejected_sso_burst_alerts(db, sent, clock):
    def reject(n):
        for _ in range(n):
            notify.rejected_sso(db)
            clock.advance(1)

    reject(19)
    assert sent == []
    for _ in range(19):
        notify.failed_sign_in(db)  # counted apart
    assert sent == []
    reject(1)
    assert [key for key, _ in sent] == ["sso_sign_in_failures"]
    reject(20)
    assert len(sent) == 1  # once an hour
    clock.advance(3600)
    reject(20)
    assert [key for key, _ in sent] == ["sso_sign_in_failures"] * 2
    assert notify.TITLES["sso_sign_in_failures"] == "Repeated rejected single sign-ons to Cabinet"


# --- browsers and the password sign-in alert -------------------------------------------


def browser_rows(db, user) -> int:
    db.expire_all()
    return db.scalar(
        select(func.count()).select_from(KnownBrowser).where(KnownBrowser.user_id == user.id)
    )


def remember_browsers(db, user, n=2) -> None:
    for _ in range(n):
        db.add(
            KnownBrowser(
                user_id=user.id,
                secret_hash=common.digest(common.new_secret()),
                created_at=common.now(),
                last_seen_at=common.now(),
                expires_at=common.now() + timedelta(days=90),
            )
        )
    db.commit()


def test_browser_rows_cleared_on_password_change(db, owner):
    user = owner.user
    remember_browsers(db, user)
    accounts.change_password(db, owner.session, user, PASSWORD, "another long password", BROWSER)
    assert browser_rows(db, user) == 0

    remember_browsers(db, user)
    accounts.reset_password(db, "a third long password", Actor.cli(user))
    assert browser_rows(db, user) == 0

    remember_browsers(db, user)
    ended = accounts.sign_out_everywhere(db, user, Actor.cli(user))
    assert ended["browsers"] == 2 and browser_rows(db, user) == 0


def test_expired_browser_rows_are_pruned(db, owner, clock):
    remember_browsers(db, owner.user, 1)
    clock.advance(91 * 24 * 3600)
    accounts.prune(db)
    assert browser_rows(db, owner.user) == 0


def test_password_sign_in_alert_when_switched_on(db, owner, sent):
    known = Client(device=owner.device_secret, **{"address": "192.0.2.10"})
    started = accounts.sign_in(db, "owner", PASSWORD, known)
    assert sent == []  # a known device, the switch off

    sso_config.get_config(db).password_sign_in_alerts = True
    db.commit()
    again = Client(device=started.device_secret, address="192.0.2.10")
    accounts.sign_in(db, "owner", PASSWORD, again)
    assert [key for key, _ in sent] == ["password_sign_in"]
    assert notify.TITLES["password_sign_in"] == "Password sign-in to Cabinet"

    # A new device gets the new-device alert, which says more, and not both.
    sent.clear()
    accounts.sign_in(db, "owner", PASSWORD, BROWSER)
    assert [key for key, _ in sent] == ["sign_in_new_device"]
