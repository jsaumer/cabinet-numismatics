import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://numis:changeme@localhost:5432/numismatics"
    photo_dir: str = "./photos"
    # Re-run stale melt estimates this often (days); 0 disables the scheduler.
    reestimate_days: int = 7
    # Fernet key(s) encrypting stored secrets; comma-separated to rotate (the
    # first encrypts, any decrypts). Unset → a key is generated into
    # secret_key_file, which must stay off the publicly served photo volume.
    secret_key: str = ""
    secret_key_file: str = "/data/state/secret.key"
    # Apply pending database migrations when the backend starts. Set false to
    # run `alembic upgrade head` yourself instead.
    auto_migrate: bool = True
    # Where scheduled and on-demand backups are written. Mount a volume (or a
    # NAS path) here to get archives off the container.
    backup_dir: str = "/data/backups"
    # Where attached documents (receipts, certificates…) are stored. Never
    # inside PHOTO_DIR, which nginx serves publicly.
    document_dir: str = "/data/documents"
    # Refuse document uploads unless DOCUMENT_DIR is a mounted volume, so a
    # deployment that forgot the mount doesn't keep them in the container,
    # where the next redeploy would lose them. Off for tests and local dev.
    require_document_mount: bool = True
    # Where uploaded import files wait between preview and import (a day at
    # most). Empty = a folder in the system temp directory.
    import_dir: str = ""
    # In-app restore (Settings → Backups). It replaces the whole collection and
    # the app has no login, so a deployment can switch it off: every restore
    # endpoint then answers 404.
    restore_enabled: bool = True
    # Largest archive an upload to the restore page may be, in GB.
    restore_max_gb: float = 20
    # Sign-in (v0.30.0). The exact origins browsers use to reach Cabinet,
    # comma-separated (`https://cabinet.example.com`): the only list a
    # cookie-authenticated request's Origin is checked against. Required.
    public_origins: str = ""
    # Cookies without `Secure` (and without the `__Host-` prefix), for a plain
    # http deployment such as the local stack. Refused beside an https origin.
    auth_insecure_http: bool = False
    # The one-time setup code, from a file (a Docker secret) or the
    # environment; unset, one is generated and logged. See check_startup.
    setup_code: str = ""
    setup_code_file: str = ""

    @property
    def sqlalchemy_url(self) -> str:
        # Compose/.env use the generic scheme; SQLAlchemy needs the psycopg 3 driver.
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ConfigError(RuntimeError):
    """A deployment setting is missing or wrong. The message names the
    variable; startup stops rather than running half-configured."""


_ORIGIN = re.compile(
    r"(https?)://([a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*)(:(\d{1,5}))?"
)
_DEFAULT_PORTS = {"http": "80", "https": "443"}
SETUP_CODE_MIN = 32


def normalize_origin(value: str) -> str | None:
    """`scheme://host[:port]`, lowercased, with a default port dropped; None
    for anything else (a path, a query, userinfo, a bad host or port)."""
    match = _ORIGIN.fullmatch(value.strip().lower())
    if match is None:
        return None
    scheme, host, port = match.group(1), match.group(2), match.group(7)
    if port is not None:
        if not 0 < int(port) < 65536:
            return None
        if port == _DEFAULT_PORTS[scheme]:
            port = None
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def public_origins(config: Settings) -> list[str]:
    """PUBLIC_ORIGINS as normalized origins, raising ConfigError when it is
    missing or holds anything that isn't an exact origin."""
    entries = [e.strip() for e in config.public_origins.split(",") if e.strip()]
    if not entries:
        raise ConfigError(
            "PUBLIC_ORIGINS is required: the address browsers use for Cabinet, "
            "for example PUBLIC_ORIGINS=https://cabinet.example.com"
        )
    origins = []
    for entry in entries:
        origin = normalize_origin(entry)
        if origin is None:
            raise ConfigError(
                f"PUBLIC_ORIGINS: {entry!r} is not an origin. Each entry is "
                "scheme://host[:port] (http or https), with no path"
            )
        origins.append(origin)
    return origins


def normalize_setup_code(code: str) -> str:
    """The form a setup code is compared in: spaces and dashes dropped."""
    return re.sub(r"[\s-]", "", code)


def _check_setup_code(code: str, name: str) -> None:
    compact = normalize_setup_code(code)
    if len(compact) < SETUP_CODE_MIN:
        raise ConfigError(
            f"{name} must be at least {SETUP_CODE_MIN} characters (spaces and dashes "
            "not counted). Generate one with: openssl rand -hex 32"
        )
    _, most = Counter(compact).most_common(1)[0]
    if most * 4 > len(compact):
        raise ConfigError(
            f"{name} repeats one character too often to be a real secret. "
            "Generate one with: openssl rand -hex 32"
        )


def supplied_setup_code(config: Settings) -> str | None:
    """The operator's setup code (SETUP_CODE_FILE before SETUP_CODE), checked,
    or None when neither is set. Raises ConfigError for an unreadable file or
    a code that fails the mistake checks; nothing here proves randomness."""
    if config.setup_code_file:
        try:
            code = Path(config.setup_code_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(
                f"SETUP_CODE_FILE {config.setup_code_file!r} cannot be read "
                f"({type(exc).__name__}); it must be readable by the app's user"
            ) from None
        _check_setup_code(code, "SETUP_CODE_FILE")
        return code
    if config.setup_code:
        _check_setup_code(config.setup_code, "SETUP_CODE")
        return config.setup_code
    return None


def check_startup(config: Settings) -> list[str]:
    """Validate the deployment settings before anything else starts. Raises
    ConfigError naming the variable; returns warnings to log on every start."""
    origins = public_origins(config)
    warnings = []
    if config.auth_insecure_http:
        if any(o.startswith("https://") for o in origins):
            raise ConfigError(
                "AUTH_INSECURE_HTTP is only allowed when every PUBLIC_ORIGINS entry is "
                "http; remove it for an https deployment"
            )
        warnings.append(
            "AUTH_INSECURE_HTTP is on: sign-in cookies are sent without Secure. "
            "Only for a plain-http local stack; never on a network you don't trust."
        )
    supplied_setup_code(config)
    return warnings
