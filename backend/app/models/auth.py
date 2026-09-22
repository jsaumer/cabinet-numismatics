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
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
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
        UniqueConstraint("external_issuer", "external_subject", name="uq_users_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored lowercased; the sign-in compare is case-insensitive.
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # Null for an account that only signs in through a provider (A2).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    external_issuer: Mapped[str | None] = mapped_column(String(255))
    external_subject: Mapped[str | None] = mapped_column(String(255))
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
