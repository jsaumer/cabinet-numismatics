"""Sign-in data (v0.30.0): its own Postgres schema, `cabinet_auth`, its own
declarative base, and its own Alembic chain (`alembic_auth/`).

Kept apart from the collection on purpose. Backups dump `public` only and
restores replace `public` only, so an archive never carries a credential and
a restore never adds, changes, or revokes one. No foreign key crosses
between the two schemas in either direction; the collection never stores a
user id. `Base.metadata` (the collection) never includes these tables, so
autogenerate on either chain can't see the other.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "cabinet_auth"


class AuthBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _fk(column: str, ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.{column}", ondelete=ondelete)


class User(AuthBase):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored lowercased; the sign-in compare is case-insensitive.
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # Null for an account that only signs in through a provider (A2).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Claim(AuthBase):
    """The singleton whose insert is the atomic claim: a row means the
    instance has its admin. `id` can only ever be 1."""

    __tablename__ = "claim"
    __table_args__ = (CheckConstraint("id = 1", name="ck_claim_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int] = mapped_column(_fk("users.id"))


class Session(AuthBase):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)  # SHA-256
    user_id: Mapped[int] = mapped_column(_fk("users.id"), index=True)
    auth_method: Mapped[str] = mapped_column(String(16), default="password")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # created + 7 days
    confirmed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    address: Mapped[str | None] = mapped_column(String(45))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The identity an `oidc` or `trusted_header` session came through (v0.33.0),
    # so removing that way in revokes exactly its sessions.
    identity_id: Mapped[int | None] = mapped_column(
        _fk("identities.id", ondelete="SET NULL"), index=True
    )


class ApiToken(AuthBase):
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("scope IN ('read', 'write', 'metrics')", name="ck_api_tokens_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32))  # SHA-256
    user_id: Mapped[int] = mapped_column(_fk("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Required for read and write (7 days at most); a metrics token may have none.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnownDevice(AuthBase):
    __tablename__ = "known_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)  # SHA-256
    user_id: Mapped[int] = mapped_column(_fk("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # created + 7 days
    failures: Mapped[int] = mapped_column(Integer, default=0)


class AuditEntry(AuthBase):
    """One row per event. Nothing from the collection is ever written here."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(_fk("users.id", ondelete="SET NULL"))
    actor_label: Mapped[str | None] = mapped_column(String(64))
    # session | token | anonymous | cli | system
    actor_kind: Mapped[str] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict | None] = mapped_column(JSON)
    address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(256))


class BackupRecord(AuthBase):
    """Every archive this Cabinet writes (the `backup_ledger`), identified by
    its verified MAC, never its file name. Here rather than in `public` so a
    restore can never rewrite the record of what came before it."""

    __tablename__ = "backup_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # scheduled | manual | download | prerestore
    kind: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mac_recipient: Mapped[str] = mapped_column(String(80))
    mac_digest: Mapped[bytes] = mapped_column(LargeBinary(32))  # SHA-256 of the archive's MAC
    size: Mapped[int] = mapped_column(BigInteger)


# --- single sign-on (v0.33.0, migration a0002) -----------------------------------

# Written so SQLite and Postgres read them the same way (no boolean `=`).
PRESET_KIND_CHECK = (
    "(preset = 'github' AND kind = 'oauth2_profile') "
    "OR (preset <> 'github' AND kind <> 'oauth2_profile')"
)
IDENTITY_KIND_CHECK = (
    "(kind = 'provider' AND provider_id IS NOT NULL) "
    "OR (kind <> 'provider' AND provider_id IS NULL)"
)
HEADER_ONLY = "kind = 'trusted_header'"


class AuthProvider(AuthBase):
    """One sign-in button. Read through `app/auth/config.py`, never cached."""

    __tablename__ = "auth_providers"
    __table_args__ = (
        CheckConstraint("kind IN ('oidc', 'oauth2_profile')", name="ck_auth_providers_kind"),
        CheckConstraint(
            "preset IN ('google', 'microsoft', 'github', 'custom')",
            name="ck_auth_providers_preset",
        ),
        CheckConstraint(PRESET_KIND_CHECK, name="ck_auth_providers_preset_kind"),
        UniqueConstraint("issuer", "client_id", name="uq_auth_providers_issuer_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    preset: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    issuer: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[str] = mapped_column(String(255))
    # Fernet ciphertext (services/crypto.py), write-only through the API.
    client_secret: Mapped[str] = mapped_column(Text, default="")
    scopes: Mapped[str] = mapped_column(String(255), default="")
    logout_at_provider: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Identity(AuthBase):
    """An outside identity linked to an account: `(issuer, subject)`, through a
    provider or the trusted-header mode. Never an email."""

    __tablename__ = "identities"
    __table_args__ = (
        CheckConstraint("kind IN ('provider', 'trusted_header')", name="ck_identities_kind"),
        CheckConstraint(IDENTITY_KIND_CHECK, name="ck_identities_provider"),
        UniqueConstraint("user_id", "provider_id", name="uq_identities_user_provider"),
        UniqueConstraint("provider_id", "issuer", "subject", name="uq_identities_provider_subject"),
        Index(
            "uq_identities_header_user",
            "user_id",
            unique=True,
            postgresql_where=text(HEADER_ONLY),
            sqlite_where=text(HEADER_ONLY),
        ),
        Index(
            "uq_identities_header_subject",
            "issuer",
            "subject",
            unique=True,
            postgresql_where=text(HEADER_ONLY),
            sqlite_where=text(HEADER_ONLY),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(_fk("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    provider_id: Mapped[int | None] = mapped_column(_fk("auth_providers.id"))
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    # An email or username at link time, for the Settings list only.
    display: Mapped[str | None] = mapped_column(String(120))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnownBrowser(AuthBase):
    """The new-browser alert's cookie (R2-04). No role in authentication or
    throttling: nothing but the alert ever reads it."""

    __tablename__ = "known_browsers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(_fk("users.id"), index=True)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)  # SHA-256
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthConfig(AuthBase):
    """The sign-in switches: one row, `id` always 1."""

    __tablename__ = "auth_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_auth_config_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    password_sign_in_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    # The trusted-header mode also needs its four variables (R2-02).
    trusted_header_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
