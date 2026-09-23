"""v0.30.0 sign-in: the admin, sessions, API tokens, known devices, the audit
log, and the archive record, in the cabinet_auth schema.

Revision ID: a0001
Revises:
Create Date: 2026-09-22
"""

import sqlalchemy as sa

from alembic import op

revision = "a0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "cabinet_auth"


def _when(name: str, nullable: bool = True, now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if now else None,
    )


def _user_fk(name: str = "user_id", ondelete: str = "CASCADE", nullable: bool = False):
    return sa.Column(
        name,
        sa.Integer,
        sa.ForeignKey(f"{SCHEMA}.users.id", ondelete=ondelete),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("external_issuer", sa.String(255), nullable=True),
        sa.Column("external_subject", sa.String(255), nullable=True),
        _when("created_at", nullable=False, now=True),
        _when("last_login_at"),
        _when("password_changed_at"),
        sa.CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="ck_users_role"),
        sa.UniqueConstraint("external_issuer", "external_subject", name="uq_users_external"),
        schema=SCHEMA,
    )
    op.create_table(
        "claim",
        sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
        _when("claimed_at", nullable=False, now=True),
        _user_fk(),
        sa.CheckConstraint("id = 1", name="ck_claim_singleton"),
        schema=SCHEMA,
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False, unique=True),
        _user_fk(),
        sa.Column("auth_method", sa.String(16), nullable=False),
        _when("created_at", nullable=False, now=True),
        _when("last_seen_at", nullable=False, now=True),
        _when("expires_at", nullable=False),
        _when("confirmed_until"),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column("address", sa.String(45), nullable=True),
        _when("revoked_at"),
        schema=SCHEMA,
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], schema=SCHEMA)
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("public_id", sa.String(10), nullable=False, unique=True),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False),
        _user_fk(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        _when("created_at", nullable=False, now=True),
        _when("last_used_at"),
        _when("expires_at"),
        _when("revoked_at"),
        sa.CheckConstraint("scope IN ('read', 'write', 'metrics')", name="ck_api_tokens_scope"),
        schema=SCHEMA,
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"], schema=SCHEMA)
    op.create_table(
        "known_devices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False, unique=True),
        _user_fk(),
        _when("created_at", nullable=False, now=True),
        _when("expires_at", nullable=False),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_index("ix_known_devices_user_id", "known_devices", ["user_id"], schema=SCHEMA)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        _when("at", nullable=False, now=True),
        _user_fk("actor_user_id", ondelete="SET NULL", nullable=True),
        sa.Column("actor_label", sa.String(64), nullable=True),
        sa.Column("actor_kind", sa.String(12), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target", sa.String(200), nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
        sa.Column("address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"], schema=SCHEMA)
    op.create_index("ix_audit_log_action", "audit_log", ["action"], schema=SCHEMA)
    op.create_table(
        "backup_ledger",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("kind", sa.String(12), nullable=False),
        _when("created_at", nullable=False),
        sa.Column("mac_recipient", sa.String(80), nullable=False),
        sa.Column("mac_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_backup_ledger_created_at", "backup_ledger", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    for table in ("backup_ledger", "audit_log", "known_devices", "api_tokens", "sessions", "claim"):
        op.drop_table(table, schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
