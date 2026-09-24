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
    # Where an archive's database dump is unpacked to be checked and restored:
    # a private volume of its own (0700), never inside the backup, photo, or
    # document directories. Fixed by the image; placed by the volume mount.
    staging_dir: str = "/data/staging"
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
    # The backup key (v0.30.0): a file of age identities, typically a Docker
    # secret, never modified by Cabinet. Unset, one is generated into
    # backup.key on the state volume. See services/archive_keys.py.
    backup_key_file: str = ""
    # The same key as a variable: the identity text itself, for a deployment
    # whose secret manager delivers environment variables. Written to a
    # container-local file at start (never the state volume). Not with
    # BACKUP_KEY_FILE.
    backup_key: str = ""
    # Single sign-on (v0.33.0). The trusted-header mode: the header carrying a
    # gateway's signed JWT, where its public keys are, and the `iss` and `aud`
    # it must carry. All four or none; see check_startup.
    trusted_assertion_header: str = ""
    trusted_assertion_jwks_url: str = ""
    trusted_assertion_issuer: str = ""
    trusted_assertion_audience: str = ""
    # A PEM file of CA certificates added to the public roots, for a provider
    # or gateway behind a local CA.
    sso_ca_file: str = ""

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


TRUSTED_HEADER_VARIABLES = {
    "TRUSTED_ASSERTION_HEADER": "trusted_assertion_header",
    "TRUSTED_ASSERTION_JWKS_URL": "trusted_assertion_jwks_url",
    "TRUSTED_ASSERTION_ISSUER": "trusted_assertion_issuer",
    "TRUSTED_ASSERTION_AUDIENCE": "trusted_assertion_audience",
}
TRUSTED_HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,60}")
# Headers nginx sets or the gate reads (R2-14), lowercased; a trailing `-`
# is a prefix. The proxy's start script refuses the same list.
TRUSTED_HEADER_FORBIDDEN = (
    "host",
    "cookie",
    "authorization",
    "origin",
    "referer",
    "sec-fetch-",
    "content-length",
    "content-type",
    "transfer-encoding",
    "connection",
    "upgrade",
    "x-real-ip",
    "x-forwarded-",
    "forwarded",
    # Hop-by-hop headers nginx's proxy module sets itself (SR-06), and the
    # one more header the audit log reads.
    "proxy-connection",
    "te",
    "keep-alive",
    "expect",
    "user-agent",
)


def forbidden_header(name: str) -> bool:
    lowered = name.lower()
    return any(
        lowered.startswith(entry) if entry.endswith("-") else lowered == entry
        for entry in TRUSTED_HEADER_FORBIDDEN
    )


def _check_trusted_header(config: Settings) -> None:
    """All four TRUSTED_ASSERTION_* set, or none (the mode off)."""
    values = {
        name: getattr(config, attr).strip() for name, attr in TRUSTED_HEADER_VARIABLES.items()
    }
    missing = [name for name, value in values.items() if not value]
    if len(missing) == len(values):
        return
    if missing:
        raise ConfigError(
            "The trusted-header mode needs all four TRUSTED_ASSERTION_* variables, or none; "
            f"missing: {', '.join(missing)}. TRUSTED_ASSERTION_AUDIENCE may never be empty"
        )
    header = values["TRUSTED_ASSERTION_HEADER"]
    if TRUSTED_HEADER_NAME.fullmatch(header) is None:
        raise ConfigError(
            f"TRUSTED_ASSERTION_HEADER {header!r} is not a header name: letters, digits, "
            "and dashes, starting with a letter, at most 61 characters"
        )
    if forbidden_header(header):
        raise ConfigError(
            f"TRUSTED_ASSERTION_HEADER may not be {header!r}: nginx sets that header or "
            "Cabinet reads it. Use the header your gateway puts its signed JWT in"
        )
    url = values["TRUSTED_ASSERTION_JWKS_URL"].lower()
    if not (
        url.startswith("https://") or (config.auth_insecure_http and url.startswith("http://"))
    ):
        raise ConfigError(
            "TRUSTED_ASSERTION_JWKS_URL must be an https:// URL "
            "(http:// only beside AUTH_INSECURE_HTTP)"
        )


def _check_ca_file(config: Settings) -> None:
    if not config.sso_ca_file:
        return
    path = Path(config.sso_ca_file)
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise ConfigError(
            f"SSO_CA_FILE {config.sso_ca_file!r} cannot be read ({type(exc).__name__}); "
            "it must be a file readable by the app's user"
        ) from None


def _shared_hosts(origins: list[str]) -> list[str]:
    """Hosts listed more than once, whatever the scheme or port: nginx's
    `$host` carries no port, and the callback origin is chosen by it (CR-08)."""
    hosts = Counter(o.split("://", 1)[1].split(":", 1)[0] for o in origins)
    return sorted(host for host, n in hosts.items() if n > 1)


def check_startup(config: Settings) -> list[str]:
    """Validate the deployment settings before anything else starts. Raises
    ConfigError naming the variable; returns warnings to log on every start.
    Reads the environment and files only, never the database (R2-07), so a
    setting can't crash-loop the backend out of reach of the recovery
    commands."""
    origins = public_origins(config)
    warnings = []
    _check_trusted_header(config)
    _check_ca_file(config)
    if shared := _shared_hosts(origins):
        warnings.append(
            f"PUBLIC_ORIGINS lists {', '.join(shared)} more than once: a "
            "single sign-on callback can't tell those origins apart, so a provider can't "
            "be saved while both are listed."
        )
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
    # Once Cabinet has its admin (the claimed marker), the setup code is
    # ignored for good, so a leftover SETUP_CODE can't stop a start.
    if not (Path(config.secret_key_file).resolve().parent / "auth_claimed").exists():
        supplied_setup_code(config)
    return warnings
