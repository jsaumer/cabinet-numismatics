"""A mock identity provider for CI (SPEC_0330 section 11, stage 5).

CI tooling only: started by docker-compose.ci.yml from the backend image
(which carries PyJWT and cryptography), never referenced by the app and
never in a published image. It mirrors backend/tests/fake_idp.py over real
HTTP, so the smoke script and Playwright can sign in through the compose
stack.

Two bases, on purpose: the backend reaches the issuer (discovery, token,
JWKS, end session) by service name, `MOCK_IDP_ISSUER`, while the browser is
sent to the authorize page at `MOCK_IDP_PUBLIC_URL`, the published port as
the runner sees it (or the service name, for a browser on the compose
network).

The authorize page auto-approves as the mock's current subject: one
"Approve" button for a browser, or `auto=1` for curl, which redirects at
once. `POST /control` makes the next token (or discovery document)
misbehave in one way, then everything is normal again; `GET /mint` signs a
trusted-header assertion.
"""

import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = int(os.environ.get("MOCK_IDP_PORT", "8555"))
ISSUER = os.environ.get("MOCK_IDP_ISSUER", "http://mock_idp:8555").rstrip("/")
PUBLIC = os.environ.get("MOCK_IDP_PUBLIC_URL", ISSUER).rstrip("/")
CLIENT_ID = os.environ.get("MOCK_IDP_CLIENT_ID", "cabinet-ci")
CLIENT_SECRET = os.environ.get("MOCK_IDP_CLIENT_SECRET", "cabinet-ci-secret")
GITHUB_ID = os.environ.get("MOCK_IDP_GITHUB_CLIENT_ID", "cabinet-ci-github")
GITHUB_SECRET = os.environ.get("MOCK_IDP_GITHUB_CLIENT_SECRET", "cabinet-ci-github-secret")
TRUSTED_AUDIENCE = os.environ.get("MOCK_IDP_TRUSTED_AUDIENCE", "cabinet-gateway")
DEFAULT_SUBJECT = "ci-user-1"
DEFAULT_EMAIL = "ci-user@example.com"
MISBEHAVIOURS = {
    "wrong_nonce", "wrong_aud", "extra_aud", "expired", "no_exp", "unknown_kid",
    "alg_none", "hs256", "iss_mismatch", "wrong_issuer_discovery", "redirect_token",
    "too_large",
}  # fmt: skip

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
UNPUBLISHED = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# The mock's "session": an hour old, so a confirm without prompt=login
# fails Cabinet's 120 s auth_time rule, as it should.
SESSION_START = int(time.time()) - 3600

lock = threading.Lock()
codes: dict[str, dict] = {}
access_tokens: set[str] = set()
control = {"subject": DEFAULT_SUBJECT, "email": DEFAULT_EMAIL, "misbehave": None}
last_end_session: dict | None = None


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def take_misbehaviour(kinds: set[str]) -> str | None:
    """The misbehaviour set, if it is one of `kinds`, used up."""
    with lock:
        found = control["misbehave"]
        if found in kinds:
            control["misbehave"] = None
            return found
        return None


def sign(claims: dict, *, kid: str = "ci-1", alg: str = "RS256", secret: str = CLIENT_SECRET) -> str:
    if alg == "none":
        head = b64(json.dumps({"alg": "none", "kid": kid, "typ": "JWT"}).encode())
        return f"{head}.{b64(json.dumps(claims).encode())}."
    if alg.startswith("HS"):
        return jwt.encode(claims, secret, alg, headers={"kid": kid})
    key = UNPUBLISHED if kid == "ci-unknown" else KEY
    return jwt.encode(claims, key, alg, headers={"kid": kid})


def id_token(grant: dict) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": grant["subject"],
        "aud": CLIENT_ID,
        "exp": now + 300,
        "iat": now,
        "nonce": grant.get("nonce"),
        "auth_time": grant["auth_time"],
        "email": grant["email"],
        "preferred_username": grant["subject"].rsplit("-", 1)[0],
    }
    kid, alg = "ci-1", "RS256"
    bad = take_misbehaviour(MISBEHAVIOURS - {"wrong_issuer_discovery", "redirect_token", "too_large"})
    if bad == "wrong_nonce":
        claims["nonce"] = "not-the-nonce"
    elif bad == "wrong_aud":
        claims["aud"] = "someone-else"
    elif bad == "extra_aud":
        claims["aud"] = [CLIENT_ID, "someone-else"]
    elif bad == "expired":
        claims.update(exp=now - 600, iat=now - 900)
    elif bad == "no_exp":
        del claims["exp"]
    elif bad == "unknown_kid":
        kid = "ci-unknown"
    elif bad == "alg_none":
        alg = "none"
    elif bad == "hs256":
        alg = "HS256"
    elif bad == "iss_mismatch":
        claims["iss"] = ISSUER + "/other"
    return sign(claims, kid=kid, alg=alg)


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-idp"

    # --- plumbing ---------------------------------------------------------------------

    def log_request(self, code="-", size="-"):
        # One line a request, the path only: a query holds codes and states.
        print(f"{self.command} {urlsplit(self.path).path} {code}", flush=True)

    def send(self, status: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, body, status: int = 200) -> None:
        self.send(status, json.dumps(body).encode(), "application/json")

    def page(self, text: str, status: int = 200) -> None:
        self.send(status, text.encode(), "text/html; charset=utf-8")

    def redirect(self, url: str, status: int = 303) -> None:
        self.send(status, b"", "text/plain", {"Location": url})

    def query(self) -> dict:
        return dict(parse_qsl(urlsplit(self.path).query))

    def form(self) -> dict:
        size = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(size).decode("utf-8") if size else ""
        return dict(parse_qsl(raw))

    # --- routes -----------------------------------------------------------------------

    def do_GET(self):
        path = urlsplit(self.path).path
        routes = {
            "/.well-known/openid-configuration": self.discovery,
            "/jwks": self.jwks,
            "/authorize": self.authorize,
            "/user": self.user,
            "/mint": self.mint,
            "/control": lambda: self.json(dict(control, end_session=last_end_session)),
            "/end_session": self.end_session,
            "/health": lambda: self.json({"status": "ok"}),
        }
        routes.get(path, lambda: self.json({"error": "not_found"}, 404))()

    def do_POST(self):
        path = urlsplit(self.path).path
        routes = {"/authorize/approve": self.approve, "/token": self.token, "/control": self.set_control}
        routes.get(path, lambda: self.json({"error": "not_found"}, 404))()

    def discovery(self):
        issuer = ISSUER
        if take_misbehaviour({"wrong_issuer_discovery"}):
            issuer = ISSUER + "/other"
        self.json(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{PUBLIC}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "end_session_endpoint": f"{ISSUER}/end_session",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                "claims_supported": ["sub", "iss", "aud", "exp", "iat", "nonce", "auth_time", "email", "preferred_username"],
                "prompt_values_supported": ["none", "login"],
                "authorization_response_iss_parameter_supported": True,
            }
        )  # fmt: skip

    def jwks(self):
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
        key.update(kid="ci-1", alg="RS256", use="sig")
        self.json({"keys": [key]})

    def authorize(self):
        q = self.query()
        if q.get("client_id") not in (CLIENT_ID, GITHUB_ID) or not q.get("redirect_uri"):
            return self.page("<p>Unknown client or no redirect_uri.</p>", 400)
        if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
            return self.page("<p>Only the code flow with S256 is supported.</p>", 400)
        code = secrets.token_urlsafe(24)
        with lock:
            codes[code] = {
                "client_id": q["client_id"],
                "redirect_uri": q["redirect_uri"],
                "state": q.get("state", ""),
                "nonce": q.get("nonce"),
                "challenge": q.get("code_challenge", ""),
                "login": q.get("prompt") == "login",
                "subject": control["subject"],
                "email": control["email"],
                "approved": False,
            }
            subject = control["subject"]
        if q.get("auto") == "1":
            return self.redirect(self.approved(code))
        self.page(
            "<!doctype html><title>Mock provider</title>"
            f"<h1>Mock provider</h1><p>Sign in to Cabinet as {html.escape(subject)}?</p>"
            '<form method="post" action="/authorize/approve">'
            f'<input type="hidden" name="code" value="{html.escape(code)}">'
            '<button type="submit">Approve</button></form>'
        )

    def approved(self, code: str) -> str:
        """Where the browser goes back to once `code` is approved."""
        with lock:
            grant = codes[code]
            grant["approved"] = True
            grant["auth_time"] = int(time.time()) if grant["login"] else SESSION_START
        back = {"code": code, "state": grant["state"], "iss": ISSUER}
        joiner = "&" if "?" in grant["redirect_uri"] else "?"
        return f"{grant['redirect_uri']}{joiner}{urlencode(back)}"

    def approve(self):
        code = self.form().get("code", "")
        with lock:
            known = code in codes and not codes[code]["approved"]
        if not known:
            return self.page("<p>Unknown or used code.</p>", 400)
        self.redirect(self.approved(code))

    def client(self, form: dict) -> tuple[str, str]:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            name, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
            return unquote_plus(name), unquote_plus(secret)
        return form.get("client_id", ""), form.get("client_secret", "")

    def token_answer(self, body: dict, status: int, github: bool) -> None:
        if github and self.headers.get("Accept") != "application/json":
            return self.send(status, urlencode(body).encode(), "application/x-www-form-urlencoded")
        self.json(body, status)

    def token(self):
        form = self.form()
        client_id, secret = self.client(form)
        github = client_id == GITHUB_ID
        if (client_id, secret) not in ((CLIENT_ID, CLIENT_SECRET), (GITHUB_ID, GITHUB_SECRET)):
            if github:
                return self.token_answer({"error": "incorrect_client_credentials"}, 200, True)
            return self.json({"error": "invalid_client"}, 401)
        bad = take_misbehaviour({"redirect_token", "too_large"})
        if bad == "redirect_token":
            return self.redirect("http://elsewhere.invalid/", 302)
        if bad == "too_large":
            return self.send(200, b"{" + b" " * (70 * 1024) + b"}", "application/json")
        with lock:
            grant = codes.pop(form.get("code", ""), None)
        if (
            form.get("grant_type") != "authorization_code"
            or grant is None
            or not grant["approved"]
            or grant["client_id"] != client_id
            or form.get("redirect_uri") != grant["redirect_uri"]
            or b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != grant["challenge"]
        ):
            return self.token_answer({"error": "invalid_grant"}, 400, github)
        access = "at-" + secrets.token_urlsafe(16)
        if github:
            with lock:
                access_tokens.add(access)
            return self.token_answer({"access_token": access, "token_type": "bearer", "scope": ""}, 200, True)
        self.json({"access_token": access, "token_type": "Bearer", "id_token": id_token(grant)})

    def user(self):
        auth = self.headers.get("Authorization", "")
        with lock:
            known = auth.startswith("Bearer ") and auth[7:] in access_tokens
        if not known:
            return self.json({"message": "Bad credentials"}, 401)
        self.json({"id": 424242, "login": "ci-user"})

    def mint(self):
        q = self.query()
        now = int(time.time())
        try:
            offset = int(q.get("exp", "300"))
        except ValueError:
            return self.json({"error": "exp is seconds from now"}, 400)
        with lock:
            subject = control["subject"]
        claims = {
            "iss": q.get("iss", ISSUER),
            "aud": q.get("aud", TRUSTED_AUDIENCE),
            "sub": q.get("sub", subject),
            "iat": now,
            # Any exp at or below zero is well past Cabinet's 60 s leeway.
            "exp": now + offset if offset > 0 else now - 600,
            "email": DEFAULT_EMAIL,
            "preferred_username": "ci-user",
        }
        token = sign(claims, kid=q.get("kid", "ci-1"), alg=q.get("alg", "RS256"))
        self.send(200, token.encode(), "text/plain")

    def set_control(self):
        size = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            return self.json({"error": "not JSON"}, 400)
        bad = body.get("misbehave")
        if bad is not None and bad not in MISBEHAVIOURS:
            return self.json({"error": f"unknown misbehave {bad!r}"}, 400)
        with lock:
            control["subject"] = body.get("subject") or control["subject"]
            control["email"] = body.get("email") or control["email"]
            if "misbehave" in body:
                control["misbehave"] = bad
            now = dict(control)
        self.json(now)

    def end_session(self):
        global last_end_session
        last_end_session = self.query()
        self.page("<!doctype html><title>Mock provider</title><p>Signed out at the mock provider.</p>")


if __name__ == "__main__":
    print(f"mock provider on :{PORT}, issuer {ISSUER}, authorize at {PUBLIC}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
