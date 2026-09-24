"""The trusted-header mode (v0.33.0, SPEC_0330 section 7): a gateway in
front of Cabinet (Authentik's proxy outpost, Cloudflare Access, Pomerium,
Google IAP) signs a JWT and sends it in one header; nginx passes that one
header only when `TRUSTED_ASSERTION_HEADER` names it, and blanks it
otherwise (the generated `cabinet-identity.conf`).

The assertion is read and verified only by `POST /api/auth/trusted` and the
header link route, never by `GET /api/auth/state` (R2-03), and it never
authenticates a request on its own: it only ever starts a session. The keys
come from `TRUSTED_ASSERTION_JWKS_URL` alone, never from a header the
request carries (`X-authentik-meta-jwks`, CR-05), fetched through the same
key client as the provider flows (10 s, no redirects, 64 KiB, the same
trust, at most one refetch a minute).

The assertion is a credential: no part of it reaches an exception message,
a log line, or an audit detail. Every refusal is one `TrustedRefused` with a
short `check` word.
"""

import re
from dataclasses import dataclass

import jwt
from sqlalchemy.orm import Session as DbSession

from app.auth import config as sso_config
from app.auth import oidc
from app.config import Settings, get_settings

MAX_ASSERTION = 8 * 1024
# Three base64url parts. A duplicated header arrives from nginx joined with
# ", ", which this refuses before anything else looks at it.
SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class TrustedRefused(Exception):
    """The request's assertion can't start a session. `check` names the rule
    that refused it, for the audit row; the message is never the assertion."""

    def __init__(self, check: str):
        super().__init__(check)
        self.check = check


class TrustedUnavailable(TrustedRefused):
    """The gateway's keys could not be fetched (a 502 with the password as
    the way in, never a longer wait than the 10 s timeout)."""


@dataclass(frozen=True)
class Assertion:
    issuer: str
    subject: str
    # An email or username from the assertion, for the Settings list only.
    display: str | None
    email: str | None = None
    username: str | None = None


def configured(settings: Settings | None = None) -> bool:
    return sso_config.trusted_header_configured(settings or get_settings())


def on(db: DbSession, settings: Settings | None = None) -> bool:
    """The variables set and the stored switch on (R2-02)."""
    return sso_config.trusted_header_on(db, settings or get_settings())


def present(headers, settings: Settings | None = None) -> bool:
    """Whether the request carries the configured header at all. Reads
    nothing from it; never a reason to trust anything."""
    settings = settings or get_settings()
    name = settings.trusted_assertion_header.strip()
    return bool(name) and bool(headers.get(name))


def _header(headers, name: str) -> str:
    getlist = getattr(headers, "getlist", None)
    if getlist is not None:
        values = getlist(name)
    else:
        values = [v for k, v in headers.items() if k.lower() == name.lower()]
    if not values:
        raise TrustedRefused("absent")
    if len(values) > 1:
        raise TrustedRefused("duplicate")
    value = values[0]
    if not value:
        raise TrustedRefused("absent")
    if len(value) > MAX_ASSERTION:
        raise TrustedRefused("too_large")
    if any(ch.isspace() for ch in value):
        raise TrustedRefused("whitespace")
    if SHAPE.fullmatch(value) is None:
        raise TrustedRefused("malformed")
    return value


def _text(value, length: int) -> str | None:
    return value[:length] if isinstance(value, str) and value else None


def verify(headers, settings: Settings | None = None) -> Assertion:
    """The request's assertion, verified against the configured gateway:
    signature by `TRUSTED_ASSERTION_JWKS_URL`, `iss`, `aud` (exactly the
    configured audience), `exp`, `nbf` when present, 60 s leeway, never
    `none` or HMAC."""
    settings = settings or get_settings()
    if not sso_config.trusted_header_configured(settings):
        raise TrustedRefused("not_configured")
    token = _header(headers, settings.trusted_assertion_header.strip())
    issuer = settings.trusted_assertion_issuer.strip()
    audience = settings.trusted_assertion_audience.strip()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in oidc.ALGORITHMS:
            raise TrustedRefused("alg")
        try:
            key = oidc._jwks(settings.trusted_assertion_jwks_url.strip()).get_signing_key_from_jwt(
                token
            )
        except oidc.ProviderError as exc:
            raise TrustedUnavailable(f"jwks_{exc.check}"[:40]) from None
        if key.key_type == "oct" or key.algorithm_name not in oidc.ALGORITHMS:
            raise TrustedRefused("oct")
        claims = jwt.decode(
            token,
            key,
            algorithms=oidc.ALGORITHMS,
            audience=audience,
            issuer=issuer,
            leeway=oidc.LEEWAY,
            # `iat` is not required here, unlike an ID token: some gateways
            # leave it out of their assertions, and `exp` bounds the replay.
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TrustedRefused(type(exc).__name__[:40]) from None
    except (ValueError, TypeError, KeyError):
        # A header PyJWT could not even parse into a mapping; never a crash.
        raise TrustedRefused("malformed") from None
    # PyJWT accepts a list holding the audience beside others; a gateway's
    # assertion for Cabinet names Cabinet alone (as CR-14 for ID tokens).
    aud = claims.get("aud")
    audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if not audiences or any(a != audience for a in audiences):
        raise TrustedRefused("aud")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip() or len(sub) > 255:
        raise TrustedRefused("sub")
    email = _text(claims.get("email"), 255)
    username = _text(claims.get("preferred_username"), 255)
    display = (email or username or _text(claims.get("name"), 120) or "")[:120] or None
    return Assertion(issuer, sub, display, email, username)


def check_link_subject(found: Assertion) -> None:
    """R2-06, as for a provider: a `sub` holding `@`, or equal to the
    assertion's own `email` or `preferred_username`, is refused at link
    time."""
    sub = found.subject
    if "@" in sub or sub in {found.email, found.username} - {None}:
        raise TrustedRefused("subject")
