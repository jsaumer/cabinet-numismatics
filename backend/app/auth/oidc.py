"""Single sign-on flows (v0.33.0, SPEC_0330 sections 5 and 5a): the
authorization code flow with PKCE, by hand, on httpx and PyJWT, for both
provider kinds.

- `oidc`: discovery, the code exchange, and an ID token verified against
  the provider's keys. The identity is `(iss, sub)`; `email` and
  `preferred_username` are read from the ID token for display only, never
  from userinfo or the access token.
- `oauth2_profile` (the `github` preset): no ID token; the access token is
  used for one profile request and dropped. The identity is the preset's
  fixed issuer string and the profile's numeric `id`.

The flow's state, nonce, PKCE verifier, intent, `next`, and (for link and
confirm) the hash of the session secret travel in one Fernet-encrypted
cookie, read back with a ten-minute limit. The provider a code is redeemed
at is the one in that cookie, never one a request names (the mix-up rule),
and a `state` is accepted once per process (CR-17).

The one cache: each issuer's discovery document, in memory for a day
(protocol data from the provider, not Cabinet configuration; a provider
row is still read from the database on every use), and PyJWT's own key
cache, refetched for an unknown `kid` at most once a minute.

No exception message, log line, or audit detail made here carries a token,
a code, a client secret, or the flow cookie.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import ssl
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode

import certifi
import httpx
import jwt
from cryptography.fernet import InvalidToken
from jwt import PyJWKClient

from app.auth import common
from app.auth import config as sso_config
from app.config import get_settings, public_origins
from app.services import crypto

PURPOSE = "oidc_flow"
FLOW_TTL = 600
DISCOVERY_TTL = 24 * 3600
# A discovery that failed is not tried again for this long, so a provider
# that is down can't hold every `GET /api/auth/me` for the full timeout.
DISCOVERY_RETRY = 60
TIMEOUT = 10.0
MAX_BODY = 64 * 1024
ALGORITHMS = ["RS256", "PS256", "ES256", "EdDSA"]
LEEWAY = 60
CONFIRM_MAX_AGE = 120
JWKS_COOLDOWN = 60
MAX_CONSUMED = 100_000
INTENTS = ("login", "link", "confirm")
CALLBACK_PATH = "/api/auth/oidc/callback"
NEXT_RE = re.compile(r"^/(?![/\\])[\x21-\x7e]*$")
NEXT_BLOCKED = ("/api/", "/photos/", "/s/")
# Token endpoint errors that mean Cabinet's own client id or secret is wrong
# (an expired Entra secret looks like this): an alert condition (Q13).
CREDENTIAL_ERRORS = {"invalid_client", "unauthorized_client"}
GITHUB_CREDENTIAL_ERRORS = {"incorrect_client_credentials"}


class FlowError(Exception):
    """A sign-on that can't finish. `code` is the short word the redirect
    carries (`/login?error=<code>`); `check` says which rule refused it, for
    the audit row."""

    def __init__(self, code: str, check: str | None = None):
        super().__init__(code)
        self.code = code
        self.check = check or code


class ProviderError(Exception):
    """The provider could not be reached, or answered something unusable."""

    code = "provider"

    def __init__(self, check: str = "unreachable"):
        super().__init__(check)
        self.check = check


class CredentialsRejected(ProviderError):
    """The token endpoint refused Cabinet's client credentials."""


@dataclass(frozen=True)
class Started:
    url: str
    cookie: str


@dataclass(frozen=True)
class Verified:
    """Who the provider says signed in."""

    issuer: str
    subject: str
    display: str | None
    email: str | None = None
    username: str | None = None


_lock = threading.Lock()
_discovered: dict[str, tuple[float, dict | None]] = {}
_keys: dict[str, PyJWKClient] = {}
_consumed: OrderedDict[bytes, float] = OrderedDict()


def reset_memory() -> None:
    with _lock:
        _discovered.clear()
        _keys.clear()
        _consumed.clear()


# --- small rules -------------------------------------------------------------------


def safe_next(value) -> str:
    """Where to land after the flow (CR-15, R2-16): a path on this origin,
    never another host, never the API, a photo, or a share page."""
    if not isinstance(value, str) or NEXT_RE.fullmatch(value) is None:
        return "/"
    # A dot segment, plain or encoded, would let the browser normalise the
    # path past the prefix check below (SR-03): refused outright.
    path = value.split("?", 1)[0].split("#", 1)[0]
    for segment in path.split("/"):
        if segment in (".", "..") or "%2e" in segment.lower():
            return "/"
    if value.startswith(NEXT_BLOCKED):
        return "/"
    return value


def _host_part(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.split(":", 1)[0]


def callback_origin(host: str | None) -> str:
    """The PUBLIC_ORIGINS entry whose host is the request's `Host` (CR-08: a
    top-level GET carries no Origin header), else the first https entry,
    else the first."""
    origins = public_origins(get_settings())
    want = _host_part(host or "")
    for origin in origins:
        if _host_part(origin.split("://", 1)[1]) == want:
            return origin
    return next((o for o in origins if o.startswith("https://")), origins[0])


def redirect_uri(origin: str) -> str:
    return f"{origin}{CALLBACK_PATH}"


_CALLBACK_TARGET = re.compile(r"/api/auth/oidc/callback[^\s\"]*")


def redact(text: str) -> str:
    """Any request target beginning with the callback path, whatever follows
    (a query, a trailing slash, an `error_description`), for a log line
    (CR-12): the code and state are in its query."""
    return _CALLBACK_TARGET.sub("/api/auth/oidc/callback?[redacted]", text)


def _urls_ok(url) -> bool:
    if not isinstance(url, str):
        return False
    if url.startswith("https://"):
        return True
    return url.startswith("http://") and get_settings().auth_insecure_http


# --- HTTP ---------------------------------------------------------------------------


def ssl_context() -> ssl.SSLContext:
    """The public roots, plus SSO_CA_FILE when set (CR-11): added to them,
    never in place of them, for a provider behind a homelab CA."""
    context = ssl.create_default_context(cafile=certifi.where())
    extra = get_settings().sso_ca_file.strip()
    if extra:
        context.load_verify_locations(cafile=extra)
    return context


def _client() -> httpx.Client:
    """Every outbound call: 10 s, no redirects followed. Tests replace this."""
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, verify=ssl_context())


def _fetch(method: str, url: str, **kwargs) -> tuple[int, bytes]:
    """One request; a redirect, a body over 64 KiB, or any transport error
    is a ProviderError. Nothing about the request goes into the error."""
    try:
        with _client() as client, client.stream(method, url, **kwargs) as response:
            if 300 <= response.status_code < 400:
                raise ProviderError("redirect")
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BODY:
                    raise ProviderError("too_large")
            return response.status_code, bytes(body)
    except httpx.HTTPError:
        raise ProviderError("unreachable") from None


def _json(body: bytes, error: Exception) -> dict:
    try:
        found = json.loads(body)
    except ValueError:
        raise error from None
    if not isinstance(found, dict):
        raise error
    return found


# --- discovery and keys ------------------------------------------------------------


def discover_issuer(issuer: str, *, fresh: bool = False) -> dict:
    """The issuer's discovery document, cached in memory for a day. Its
    `issuer` must equal the configured one exactly."""
    t = common.monotonic()
    with _lock:
        hit = _discovered.get(issuer)
    if hit is not None and not fresh:
        at, doc = hit
        if doc is not None and t - at < DISCOVERY_TTL:
            return doc
        if doc is None and t - at < DISCOVERY_RETRY:
            raise ProviderError("unreachable")
    try:
        status, body = _fetch(
            "GET",
            issuer.rstrip("/") + "/.well-known/openid-configuration",
            headers={"Accept": "application/json"},
        )
        if status != 200:
            raise ProviderError("status")
        doc = _json(body, ProviderError("invalid"))
        if doc.get("issuer") != issuer:
            raise ProviderError("issuer")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not _urls_ok(doc.get(name)):
                raise ProviderError("invalid")
    except ProviderError:
        with _lock:
            _discovered[issuer] = (t, None)
        raise
    with _lock:
        _discovered[issuer] = (t, doc)
    return doc


def discover(provider) -> dict:
    if provider.kind != "oidc":
        raise ProviderError("no_discovery")
    return discover_issuer(provider.issuer)


def confirm_capable(doc: dict) -> bool:
    """Q11: `auth_time` among the claims supported, and `login` among the
    prompt values if the provider publishes them."""
    claims = doc.get("claims_supported")
    if not isinstance(claims, list) or "auth_time" not in claims:
        return False
    prompts = doc.get("prompt_values_supported")
    return prompts is None or (isinstance(prompts, list) and "login" in prompts)


def qualifies_for_confirm(provider) -> bool:
    """Whether "Confirm at the provider" is offered for a session from this
    provider. An `oauth2_profile` provider never is (R2-11), and neither is
    the `microsoft` preset (SR-04): Entra lists `auth_time` among its
    supported claims but puts it in an ID token only as an optional claim
    the tenant has to configure, so the confirm would fail closed every
    time."""
    if provider.kind != "oidc" or provider.preset == "microsoft":
        return False
    try:
        return confirm_capable(discover(provider))
    except ProviderError:
        return False


class _Keys(PyJWKClient):
    """PyJWT's key client, fetching through the same client as everything
    else (10 s, no redirects, 64 KiB, the same trust as `ssl_context`). A
    fetch that failed is not tried again for JWKS_COOLDOWN (SR-02): a key
    host that hangs would otherwise cost every verification the full
    timeout, serialised on the client's lock."""

    _failed_at: float | None = None

    def fetch_data(self):
        if self._failed_at is not None and time.monotonic() - self._failed_at < JWKS_COOLDOWN:
            raise ProviderError("jwks_cooldown")
        try:
            status, body = _fetch("GET", self.uri, headers={"Accept": "application/json"})
            if status != 200:
                raise ProviderError("jwks")
            data = self._as_jwk_set_payload(_json(body, ProviderError("jwks")))
        except ProviderError:
            self._failed_at = time.monotonic()
            raise
        self._failed_at = None
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(data)
        self._last_successful_fetch = time.monotonic()
        return data


def _jwks(uri: str) -> PyJWKClient:
    with _lock:
        found = _keys.get(uri)
        if found is None:
            found = _Keys(
                uri, timeout=TIMEOUT, cooldown_duration=JWKS_COOLDOWN, ssl_context=ssl_context()
            )
            _keys[uri] = found
        return found


# --- start ------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _scopes(provider) -> str:
    words = provider.scopes.split()
    if provider.kind == "oidc" and "openid" not in words:
        words.insert(0, "openid")
    return " ".join(words)


def start(
    provider,
    *,
    intent: str,
    next_path: str,
    origin: str,
    session_hash: bytes | None = None,
    fresh: bool = False,
) -> Started:
    """The provider's authorize URL and the flow cookie. `session_hash` (the
    SHA-256 of the session secret) binds a link or confirm to the session
    that started it (CR-01). Runs discovery first (a ProviderError when the
    provider can't be reached)."""
    if intent not in INTENTS:
        raise ValueError(f"unknown intent {intent!r}")
    if provider.kind == "oidc":
        authorize = discover(provider)["authorization_endpoint"]
    else:
        authorize = sso_config.PRESETS[provider.preset]["authorize_url"]
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(32)  # 43 characters
    callback = redirect_uri(origin)
    flow = {
        "purpose": PURPOSE,
        "provider_id": provider.id,
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "intent": intent,
        "next": safe_next(next_path),
        "session": session_hash.hex() if session_hash is not None else None,
        "fresh": bool(fresh),
        "redirect_uri": callback,
        "issued": int(time.time()),
    }
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": callback,
        "state": state,
        "code_challenge": _b64(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
    }
    if scope := _scopes(provider):
        params["scope"] = scope
    if provider.kind == "oidc":
        params["nonce"] = nonce
        if intent == "confirm":
            params["prompt"] = "login"
            params["max_age"] = "0"
    sealed = crypto.get_cipher().encrypt(json.dumps(flow, separators=(",", ":")).encode())
    joiner = "&" if "?" in authorize else "?"
    return Started(f"{authorize}{joiner}{urlencode(params)}", sealed.decode("ascii"))


# --- callback ------------------------------------------------------------------------


def read_flow(value: str | None) -> dict:
    """The flow cookie's contents: `cookie` when absent, unreadable, or not
    a flow cookie; `expired` past ten minutes (CR-17)."""
    if not value or len(value) > 4096:
        raise FlowError("cookie")
    cipher = crypto.get_cipher()
    try:
        raw = cipher.decrypt(value.encode("ascii"), ttl=FLOW_TTL)
    except (InvalidToken, UnicodeEncodeError):
        try:
            cipher.decrypt(value.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError):
            raise FlowError("cookie") from None
        raise FlowError("expired") from None
    try:
        flow = json.loads(raw)
    except ValueError:
        raise FlowError("cookie") from None
    if (
        not isinstance(flow, dict)
        or flow.get("purpose") != PURPOSE
        or flow.get("intent") not in INTENTS
        or not isinstance(flow.get("provider_id"), int)
        or not all(isinstance(flow.get(k), str) for k in ("state", "nonce", "verifier", "next"))
        or not isinstance(flow.get("redirect_uri"), str)
    ):
        raise FlowError("cookie", "purpose")
    flow["next"] = safe_next(flow["next"])
    return flow


def consume(flow: dict, state) -> None:
    """The callback's `state` must be the cookie's (constant time), and each
    state is accepted once in this process, for ten minutes (CR-17)."""
    if not isinstance(state, str) or not hmac.compare_digest(
        state.encode("utf-8"), flow["state"].encode("utf-8")
    ):
        raise FlowError("state")
    key = hashlib.sha256(flow["state"].encode("ascii")).digest()
    t = common.monotonic()
    with _lock:
        while _consumed:
            oldest, at = next(iter(_consumed.items()))
            if t - at < FLOW_TTL and len(_consumed) < MAX_CONSUMED:
                break
            _consumed.pop(oldest)
        if key in _consumed:
            raise FlowError("state", "replay")
        _consumed[key] = t


def _exchange(provider, token_url: str, flow: dict, code: str, doc: dict | None) -> dict:
    """Redeem the code at this provider's token endpoint (the one in the
    flow cookie, never another). The secret goes in `Authorization: Basic`
    unless the provider advertises only `client_secret_post`."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": flow["redirect_uri"],
        "code_verifier": flow["verifier"],
    }
    headers = {"Accept": "application/json"}
    secret = sso_config.client_secret(provider)
    if doc is not None:
        methods = doc.get("token_endpoint_auth_methods_supported")
    else:
        # An `oauth2_profile` preset says how its token endpoint takes the
        # credentials (GitHub: form fields), since it has no discovery.
        methods = [sso_config.PRESETS[provider.preset].get("token_auth", "client_secret_basic")]
    if secret and (not isinstance(methods, list) or "client_secret_basic" in methods):
        pair = f"{quote_plus(provider.client_id)}:{quote_plus(secret)}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode("ascii")
    else:
        data["client_id"] = provider.client_id
        if secret:
            data["client_secret"] = secret
    status, body = _fetch("POST", token_url, data=data, headers=headers)
    answer = _json(body, FlowError("token", "not_json"))
    error = answer.get("error")
    if error is not None:
        # GitHub answers 200 with an error body (R2-12).
        rejected = CREDENTIAL_ERRORS | (
            GITHUB_CREDENTIAL_ERRORS if provider.preset == "github" else set()
        )
        if error in rejected:
            raise CredentialsRejected(str(error)[:40])
        raise FlowError("token", "token_error")
    if status != 200:
        raise FlowError("token", "token_status")
    if not isinstance(answer.get("access_token"), str) or not answer["access_token"]:
        raise FlowError("token", "access_token")
    token_type = answer.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise FlowError("token", "token_type")
    return answer


def _text(value, length: int) -> str | None:
    return value[:length] if isinstance(value, str) and value else None


# Google documents its ID token issuer as either form; the discovery
# document's `issuer` is the https one, so only the token's `iss` varies.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def accepted_issuers(provider) -> tuple[str, ...]:
    """The `iss` values an ID token from this provider may carry: the
    configured issuer, and for the `google` preset the scheme-less form
    Google also documents (a fail-closed gap the review's not-verified list
    named)."""
    if provider.preset == "google" and provider.issuer == GOOGLE_ISSUERS[0]:
        return GOOGLE_ISSUERS
    return (provider.issuer,)


def verify_id_token(provider, doc: dict, id_token: str, nonce: str, *, confirm: bool) -> dict:
    """The ID token's claims, verified (section 5, CR-13, CR-14)."""
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") not in ALGORITHMS:
            raise FlowError("token", "alg")
        key = _jwks(doc["jwks_uri"]).get_signing_key_from_jwt(id_token)
        if key.key_type == "oct" or key.algorithm_name not in ALGORITHMS:
            raise FlowError("token", "oct")
        claims = jwt.decode(
            id_token,
            key,
            algorithms=ALGORITHMS,
            audience=provider.client_id,
            issuer=accepted_issuers(provider),
            leeway=LEEWAY,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise FlowError("token", type(exc).__name__[:40]) from None
    # PyJWT accepts a list holding the client id beside others; OIDC Core
    # 3.1.3.7 doesn't (CR-14).
    aud = claims.get("aud")
    audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if not audiences or any(a != provider.client_id for a in audiences):
        raise FlowError("token", "aud")
    if "azp" in claims and claims["azp"] != provider.client_id:
        raise FlowError("token", "azp")
    got = claims.get("nonce")
    if not isinstance(got, str) or not hmac.compare_digest(got.encode(), nonce.encode()):
        raise FlowError("token", "nonce")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip() or len(sub) > 255:
        raise FlowError("token", "sub")
    if confirm:
        at = claims.get("auth_time")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            raise FlowError("token", "auth_time")
        now = time.time()
        if now - at > CONFIRM_MAX_AGE or at - now > LEEWAY:
            raise FlowError("token", "auth_time")
    return claims


def _profile(preset: dict, access_token: str) -> tuple[str, str | None]:
    """The `oauth2_profile` identity: one profile request with the access
    token, which is then dropped."""
    status, body = _fetch(
        "GET",
        preset["profile_url"],
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if status != 200:
        raise FlowError("profile", "profile_status")
    data = _json(body, FlowError("profile", "not_json"))
    subject = data.get(preset["subject_field"])
    # GitHub's `id` is a number; a string or anything else is refused.
    if isinstance(subject, bool) or not isinstance(subject, int) or subject < 0:
        raise FlowError("profile", "subject")
    return str(subject), _text(data.get(preset["display_field"]), 120)


def complete(provider, flow: dict, query) -> Verified:
    """After `read_flow` and `consume`: the provider's answer, the code
    exchange, and who signed in. `provider` must be the flow cookie's."""
    if provider.id != flow["provider_id"]:
        raise FlowError("provider", "mix_up")
    error = query.get("error")
    if error is not None:
        raise FlowError("denied" if error == "access_denied" else "provider", "provider_error")
    doc = discover(provider) if provider.kind == "oidc" else None
    if doc is not None and doc.get("authorization_response_iss_parameter_supported") is True:
        if query.get("iss") != provider.issuer:  # RFC 9207
            raise FlowError("token", "iss")
    code = query.get("code")
    if not isinstance(code, str) or not code or len(code) > 4096:
        raise FlowError("state", "no_code")
    if provider.kind != "oidc":
        if flow["intent"] == "confirm":
            raise FlowError("not_qualified")  # no ID token, no prompt=login (R2-11)
        preset = sso_config.PRESETS[provider.preset]
        answer = _exchange(provider, preset["token_url"], flow, code, None)
        subject, display = _profile(preset, answer["access_token"])
        return Verified(provider.issuer, subject, display)
    answer = _exchange(provider, doc["token_endpoint"], flow, code, doc)
    id_token = answer.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise FlowError("token", "no_id_token")
    claims = verify_id_token(
        provider, doc, id_token, flow["nonce"], confirm=flow["intent"] == "confirm"
    )
    email = _text(claims.get("email"), 255)
    username = _text(claims.get("preferred_username"), 255)
    display = (email or username or "")[:120] or None
    return Verified(provider.issuer, claims["sub"], display, email, username)


def check_link_subject(found: Verified) -> None:
    """R2-06: a `sub` that looks like an email, or equals the token's own
    `email` or `preferred_username`, is refused at link time. Authentik's
    subject mode can put those in `sub`, and an attacker able to set an
    unverified email at the provider would then receive the owner's."""
    sub = found.subject
    if "@" in sub or sub in {found.email, found.username} - {None}:
        raise FlowError("subject")


def logout_url(provider, origin: str) -> str | None:
    """RP-initiated logout (Q7), when the provider's switch is on and its
    discovery names an end-session endpoint. No `id_token_hint`: the token
    isn't kept."""
    if provider.kind != "oidc" or not provider.logout_at_provider:
        return None
    try:
        doc = discover(provider)
    except ProviderError:
        return None
    end = doc.get("end_session_endpoint")
    if not _urls_ok(end):
        return None
    params = {"client_id": provider.client_id, "post_logout_redirect_uri": f"{origin}/login"}
    return f"{end}{'&' if '?' in end else '?'}{urlencode(params)}"
