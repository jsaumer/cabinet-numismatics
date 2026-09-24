"""Single sign-on configuration (v0.33.0): the provider rows and the sign-in
switches in `auth_config`, the one place either is read.

Read from the database on every call, never cached (R2-01): the container
commands (`disable-sso`, `unlink-identity`) write from another process, and
a cache would keep a disabled provider's button, or the trusted-header
mode, alive until a restart. A few rows on a rare request cost nothing.

A preset is data: the fixed issuer (or, for the `oauth2_profile` kind, the
URLs and profile fields) comes from `PRESETS`, so the database never holds
an authorize or profile URL a client chose. A client secret is stored only
as Fernet ciphertext and read back only by `client_secret`, for the token
exchange.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.auth import audit, common
from app.auth.audit import Actor
from app.config import TRUSTED_HEADER_VARIABLES, Settings
from app.models.auth import AuthConfig, AuthProvider, Identity
from app.services import crypto

MAX_PROVIDERS = 8
MICROSOFT_ISSUER = "https://login.microsoftonline.com/{tenant}/v2.0"

PRESETS: dict[str, dict] = {
    "google": {
        "kind": "oidc",
        "issuer": "https://accounts.google.com",
        "scopes": "openid email",
    },
    "microsoft": {
        # Pinned to the tenant: `common` returns a tenant issuer that fails
        # validation.
        "kind": "oidc",
        "issuer": MICROSOFT_ISSUER,
        "scopes": "openid email profile",
    },
    "github": {
        "kind": "oauth2_profile",
        "issuer": "https://github.com",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "profile_url": "https://api.github.com/user",
        "subject_field": "id",  # a number, stable for the account's life
        "display_field": "login",  # can change; shown, never matched
        "scopes": "",  # the public profile needs none (CR-16)
    },
    "custom": {
        "kind": "oidc",
        "issuer": None,  # supplied: any OpenID Connect issuer
        "scopes": "openid email profile",
    },
}
# What can't change once an identity is linked through the provider (R2-13).
PINNED = ("issuer", "client_id", "kind", "preset")


class ProviderLinked(Exception):
    """A linked provider can't be repointed; delete it and add it again."""

    def __init__(self, fields):
        super().__init__(
            f"{', '.join(fields)} can't change while an account is linked through this "
            "provider. Remove the provider and add it again."
        )
        self.fields = list(fields)


class TooManyProviders(Exception):
    def __init__(self):
        super().__init__(f"At most {MAX_PROVIDERS} sign-in providers.")


def kind_for(preset: str) -> str:
    if preset not in PRESETS:
        raise ValueError(f"unknown provider preset {preset!r}")
    return PRESETS[preset]["kind"]


def check_preset(kind: str, preset: str) -> None:
    """The rule the database's check constraint also holds: `github` is the
    one `oauth2_profile` preset, and every other preset is `oidc`."""
    if kind_for(preset) != kind:
        raise ValueError(f"the {preset} preset is {kind_for(preset)}, not {kind}")


def issuer_for(preset: str, issuer: str | None = None, tenant: str | None = None) -> str:
    """The preset's fixed issuer; Microsoft's takes the tenant id, and
    `custom` takes the issuer given."""
    kind_for(preset)
    fixed = PRESETS[preset]["issuer"]
    if preset == "microsoft":
        if not tenant:
            raise ValueError("the microsoft preset needs a tenant id")
        return fixed.format(tenant=tenant)
    if fixed is not None:
        return fixed
    if not issuer:
        raise ValueError("a custom provider needs its issuer")
    return issuer


# --- auth_config ------------------------------------------------------------------


def get_config(db: DbSession) -> AuthConfig:
    """The singleton row; created (and flushed, the caller commits) if the
    migration's own insert is missing, as under `create_all`."""
    row = db.get(AuthConfig, 1)
    if row is not None:
        return row
    try:
        with db.begin_nested():
            db.add(AuthConfig(id=1, updated_at=common.now()))
    except IntegrityError:
        pass  # another request made it first
    return db.get(AuthConfig, 1)


def trusted_header_configured(settings: Settings) -> bool:
    """All four TRUSTED_ASSERTION_* variables set (check_startup refuses a
    partial set, so any one set means all four)."""
    return all(getattr(settings, attr).strip() for attr in TRUSTED_HEADER_VARIABLES.values())


def trusted_header_on(db: DbSession, settings: Settings) -> bool:
    """The variables set and the stored switch on (R2-02): `disable-sso`
    turns the mode off whatever the environment says."""
    return trusted_header_configured(settings) and get_config(db).trusted_header_enabled


# --- providers --------------------------------------------------------------------


def providers(db: DbSession, enabled_only: bool = False) -> list[AuthProvider]:
    query = select(AuthProvider).order_by(AuthProvider.id)
    if enabled_only:
        query = query.where(AuthProvider.enabled.is_(True))
    return list(db.scalars(query).all())


def provider(db: DbSession, provider_id: int) -> AuthProvider | None:
    return db.get(AuthProvider, provider_id)


def linked(db: DbSession, row: AuthProvider) -> bool:
    found = db.scalar(
        select(func.count()).select_from(Identity).where(Identity.provider_id == row.id)
    )
    return bool(found)


def set_client_secret(row: AuthProvider, plaintext: str) -> None:
    row.client_secret = crypto.encrypt(plaintext)


def client_secret(row: AuthProvider) -> str:
    """For the token exchange only; "" when unset or undecryptable."""
    return crypto.decrypt(row.client_secret)


def add_provider(
    db: DbSession,
    *,
    preset: str,
    display_name: str,
    client_id: str,
    secret: str = "",
    issuer: str | None = None,
    tenant: str | None = None,
    scopes: str | None = None,
    logout_at_provider: bool = False,
) -> AuthProvider:
    """A new provider, disabled until `enable_provider`. The caller audits
    and commits."""
    if db.scalar(select(func.count()).select_from(AuthProvider)) >= MAX_PROVIDERS:
        raise TooManyProviders()
    at = common.now()
    row = AuthProvider(
        kind=kind_for(preset),
        preset=preset,
        display_name=display_name,
        enabled=False,
        issuer=issuer_for(preset, issuer, tenant),
        client_id=client_id,
        scopes=PRESETS[preset]["scopes"] if scopes is None else scopes,
        logout_at_provider=logout_at_provider,
        created_at=at,
        updated_at=at,
    )
    set_client_secret(row, secret)
    db.add(row)
    db.flush()
    return row


def update_provider(db: DbSession, row: AuthProvider, **changes) -> list[str]:
    """Apply `changes` (column names; `client_secret` as plaintext) and
    return the names that changed, never their values. Refuses repointing a
    provider something is linked through (ProviderLinked)."""
    if "enabled" in changes:
        raise ValueError("switch a provider on with enable_provider")
    changed = [
        name
        for name, value in changes.items()
        if name == "client_secret" or getattr(row, name) != value
    ]
    pinned = [name for name in PINNED if name in changed]
    if pinned and linked(db, row):
        raise ProviderLinked(pinned)
    check_preset(changes.get("kind", row.kind), changes.get("preset", row.preset))
    for name in changed:
        if name == "client_secret":
            set_client_secret(row, changes[name])
        else:
            setattr(row, name, changes[name])
    if changed:
        row.updated_at = common.now()
        db.flush()
    return changed


def enable_provider(db: DbSession, row: AuthProvider, actor: Actor) -> None:
    """Switch a provider on. The first provider ever enabled also turns on
    the password sign-in alerts (R2-17, decision 10), audited, **once**:
    `alerts_defaulted_at` remembers it, so the switch is left where the
    owner puts it afterwards, even if every provider is later disabled and
    one enabled again. The caller commits."""
    if row.enabled:
        return
    check_preset(row.kind, row.preset)
    row.enabled = True
    row.updated_at = common.now()
    config = get_config(db)
    if config.alerts_defaulted_at is None:
        config.alerts_defaulted_at = common.now()
        if not config.password_sign_in_alerts:
            config.password_sign_in_alerts = True
            config.updated_at = common.now()
            audit.record(
                db, "sso_configured", actor, detail={"changed": ["password_sign_in_alerts"]}
            )
    db.flush()
