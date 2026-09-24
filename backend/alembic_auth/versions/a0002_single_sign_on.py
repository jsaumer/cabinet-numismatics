"""v0.33.0 single sign-on: providers, linked identities, the new-browser
alert's rows, the sign-in switches, and each session's identity, in the
cabinet_auth schema. The unused external columns on users go.

Revision ID: a0002
Revises: a0001
Create Date: 2026-09-24
"""

import sqlalchemy as sa

from alembic import op

revision = "a0002"
down_revision = "a0001"
branch_labels = None
depends_on = None

SCHEMA = "cabinet_auth"

# Portable across Postgres and SQLite: no boolean `=` between comparisons.
PRESET_KIND_CHECK = (
    "(preset = 'github' AND kind = 'oauth2_profile') "
    "OR (preset <> 'github' AND kind <> 'oauth2_profile')"
)
IDENTITY_KIND_CHECK = (
    "(kind = 'provider' AND provider_id IS NOT NULL) "
    "OR (kind <> 'provider' AND provider_id IS NULL)"
)
HEADER_ONLY = "kind = 'trusted_header'"


def _when(name: str, nullable: bool = True, now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if now else None,
    )


def _fk(name: str, target: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Integer,
        sa.ForeignKey(f"{SCHEMA}.{target}", ondelete="CASCADE"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "auth_providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("preset", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(60), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret", sa.Text, nullable=False, server_default=""),
        sa.Column("scopes", sa.String(255), nullable=False, server_default=""),
        sa.Column("logout_at_provider", sa.Boolean, nullable=False, server_default=sa.false()),
        _when("created_at", nullable=False, now=True),
        _when("updated_at", nullable=False, now=True),
        sa.CheckConstraint("kind IN ('oidc', 'oauth2_profile')", name="ck_auth_providers_kind"),
        sa.CheckConstraint(
            "preset IN ('google', 'microsoft', 'github', 'custom')",
            name="ck_auth_providers_preset",
        ),
        sa.CheckConstraint(PRESET_KIND_CHECK, name="ck_auth_providers_preset_kind"),
        sa.UniqueConstraint("issuer", "client_id", name="uq_auth_providers_issuer_client"),
        schema=SCHEMA,
    )
    op.create_table(
        "identities",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("user_id", "users.id"),
        sa.Column("kind", sa.String(16), nullable=False),
        _fk("provider_id", "auth_providers.id", nullable=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("display", sa.String(120), nullable=True),
        _when("linked_at", nullable=False, now=True),
        _when("last_used_at"),
        sa.CheckConstraint("kind IN ('provider', 'trusted_header')", name="ck_identities_kind"),
        sa.CheckConstraint(IDENTITY_KIND_CHECK, name="ck_identities_provider"),
        sa.UniqueConstraint("user_id", "provider_id", name="uq_identities_user_provider"),
        sa.UniqueConstraint(
            "provider_id", "issuer", "subject", name="uq_identities_provider_subject"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_identities_user_id", "identities", ["user_id"], schema=SCHEMA)
    # One header identity per account, and one account per header identity.
    op.create_index(
        "uq_identities_header_user",
        "identities",
        ["user_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(HEADER_ONLY),
        sqlite_where=sa.text(HEADER_ONLY),
    )
    op.create_index(
        "uq_identities_header_subject",
        "identities",
        ["issuer", "subject"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(HEADER_ONLY),
        sqlite_where=sa.text(HEADER_ONLY),
    )
    op.create_table(
        "known_browsers",
        sa.Column("id", sa.Integer, primary_key=True),
        _fk("user_id", "users.id"),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False, unique=True),
        _when("created_at", nullable=False, now=True),
        _when("last_seen_at", nullable=False, now=True),
        _when("expires_at", nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_known_browsers_user_id", "known_browsers", ["user_id"], schema=SCHEMA)
    op.create_table(
        "auth_config",
        sa.Column("id", sa.SmallInteger, primary_key=True, autoincrement=False),
        sa.Column("password_sign_in_alerts", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("trusted_header_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        # When the first enabled provider switched the alerts on; set once.
        _when("alerts_defaulted_at"),
        _when("updated_at", nullable=False, now=True),
        sa.CheckConstraint("id = 1", name="ck_auth_config_singleton"),
        schema=SCHEMA,
    )
    config = sa.table("auth_config", sa.column("id", sa.SmallInteger), schema=SCHEMA)
    op.bulk_insert(config, [{"id": 1}])

    with op.batch_alter_table("sessions", schema=SCHEMA) as batch:
        batch.add_column(sa.Column("identity_id", sa.Integer, nullable=True))
        batch.create_foreign_key(
            "fk_sessions_identity_id",
            "identities",
            ["identity_id"],
            ["id"],
            referent_schema=SCHEMA,
            ondelete="SET NULL",
        )
        batch.create_index("ix_sessions_identity_id", ["identity_id"])

    with op.batch_alter_table("users", schema=SCHEMA) as batch:
        batch.drop_constraint("uq_users_external", type_="unique")
        batch.drop_column("external_subject")
        batch.drop_column("external_issuer")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=SCHEMA) as batch:
        batch.add_column(sa.Column("external_issuer", sa.String(255), nullable=True))
        batch.add_column(sa.Column("external_subject", sa.String(255), nullable=True))
        batch.create_unique_constraint("uq_users_external", ["external_issuer", "external_subject"])

    with op.batch_alter_table("sessions", schema=SCHEMA) as batch:
        batch.drop_index("ix_sessions_identity_id")
        batch.drop_constraint("fk_sessions_identity_id", type_="foreignkey")
        batch.drop_column("identity_id")

    op.drop_table("auth_config", schema=SCHEMA)
    op.drop_index("ix_known_browsers_user_id", table_name="known_browsers", schema=SCHEMA)
    op.drop_table("known_browsers", schema=SCHEMA)
    op.drop_index("uq_identities_header_subject", table_name="identities", schema=SCHEMA)
    op.drop_index("uq_identities_header_user", table_name="identities", schema=SCHEMA)
    op.drop_index("ix_identities_user_id", table_name="identities", schema=SCHEMA)
    op.drop_table("identities", schema=SCHEMA)
    op.drop_table("auth_providers", schema=SCHEMA)
