"""An in-process identity provider for the single sign-on tests (SPEC_0330
section 11), served through an httpx MockTransport patched into
`oidc._client`, so nothing ever leaves the process.

It plays two providers at once: an OpenID Connect issuer at
`https://idp.test` (discovery, JWKS with an RSA and an EC key, a token
endpoint checking PKCE and the client's credentials), and a GitHub-shaped
`oauth2_profile` provider at GitHub's fixed URLs (a token endpoint that
answers form-encoded unless asked for JSON, and a profile endpoint). Every
knob below makes it misbehave in one way, for one test.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qsl, unquote_plus, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

ISSUER = "https://idp.test"
CLIENT_ID = "cabinet-client"
CLIENT_SECRET = "fake client secret value, 32 bytes or more"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_PROFILE = "https://api.github.com/user"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class FakeIdP:
    def __init__(self, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET):
        self.client_id = client_id
        self.client_secret = client_secret
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.codes: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.jwks_fetches = 0
        # Knobs.
        self.discovery_extra: dict = {}
        self.discovery_issuer: str | None = None
        self.redirect: set[str] = set()  # "discovery", "token", "jwks"
        self.oversize: set[str] = set()
        self.claims: dict = {}  # merged into the ID token
        self.drop: set[str] = set()  # claims left out of the ID token
        self.sign = "rsa"  # rsa | ec | hs256 | none
        self.kid: str | None = None  # a kid to put in the header instead
        self.extra_keys: list[dict] = []
        self.token_type = "Bearer"
        self.token_status = 200
        self.token_body: dict | None = None  # the whole token answer, instead
        self.send_iss: str | None = None  # the callback's `iss` parameter
        self.profile: dict = {"id": 4242, "login": "octocat"}
        self.profile_status = 200

    # --- the browser's side -------------------------------------------------------------

    def authorize(self, url: str, *, sub: str = "owner-sub", auth_time=None) -> dict:
        """What the provider's authorize page would send back to the
        callback: a code for `sub`, and the state it was given."""
        params = dict(parse_qsl(urlsplit(url).query))
        assert params["response_type"] == "code"
        assert params["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(24)
        self.codes[code] = {
            **params,
            "sub": sub,
            "auth_time": int(time.time()) if auth_time is None else auth_time,
        }
        back = {"code": code, "state": params["state"]}
        if self.send_iss is not None:
            back["iss"] = self.send_iss
        return back

    # --- keys and tokens -------------------------------------------------------------------

    def jwks(self) -> dict:
        rsa_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.rsa.public_key()))
        ec_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.ec.public_key()))
        rsa_jwk.update(kid="rsa-1", alg="RS256", use="sig")
        ec_jwk.update(kid="ec-1", alg="ES256", use="sig")
        return {"keys": [rsa_jwk, ec_jwk, *self.extra_keys]}

    def id_token(self, grant: dict) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": grant["sub"],
            "aud": self.client_id,
            "iat": now,
            "exp": now + 300,
            "nonce": grant.get("nonce"),
            "auth_time": grant["auth_time"],
            "email": "owner@example.com",
            "preferred_username": "owner",
        }
        claims.update(self.claims)
        for name in self.drop:
            claims.pop(name, None)
        if self.sign == "none":
            header = {"alg": "none", "kid": self.kid or "rsa-1"}
            head = _b64(json.dumps(header).encode())
            return f"{head}.{_b64(json.dumps(claims).encode())}."
        if self.sign == "hs256":
            return jwt.encode(
                claims, self.client_secret, "HS256", headers={"kid": self.kid or "rsa-1"}
            )
        if self.sign == "ec":
            return jwt.encode(claims, self.ec, "ES256", headers={"kid": self.kid or "ec-1"})
        return jwt.encode(claims, self.rsa, "RS256", headers={"kid": self.kid or "rsa-1"})

    def discovery(self) -> dict:
        doc = {
            "issuer": self.discovery_issuer or ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks",
            "end_session_endpoint": f"{ISSUER}/logout",
            "claims_supported": ["sub", "iss", "auth_time", "email"],
            "prompt_values_supported": ["none", "login"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }
        doc.update(self.discovery_extra)
        return doc

    # --- the transport ---------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport(), follow_redirects=False)

    def _answer(self, what: str, body, status: int = 200, form: bool = False) -> httpx.Response:
        if what in self.redirect:
            return httpx.Response(302, headers={"Location": "https://elsewhere.test/"})
        if what in self.oversize:
            return httpx.Response(200, content=b"{" + b" " * (70 * 1024) + b"}")
        if form:
            from urllib.parse import urlencode

            return httpx.Response(status, content=urlencode(body).encode())
        return httpx.Response(status, json=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return self._answer("discovery", self.discovery())
        if url == f"{ISSUER}/jwks":
            self.jwks_fetches += 1
            return self._answer("jwks", self.jwks())
        if url == f"{ISSUER}/token" and request.method == "POST":
            return self._token(request, oidc=True)
        if url == GITHUB_TOKEN and request.method == "POST":
            return self._token(request, oidc=False)
        if url == GITHUB_PROFILE:
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer at-"):
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(self.profile_status, json=self.profile)
        return httpx.Response(404, json={"error": "not_found"})

    def _client_auth(self, request: httpx.Request, form: dict) -> tuple[str, str]:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            pair = base64.b64decode(auth[6:]).decode()
            name, _, secret = pair.partition(":")
            return unquote_plus(name), unquote_plus(secret)
        return form.get("client_id", ""), form.get("client_secret", "")

    def _token(self, request: httpx.Request, *, oidc: bool) -> httpx.Response:
        wants_json = request.headers.get("accept") == "application/json"
        form_answer = not oidc and not wants_json  # GitHub's classic trap
        if self.token_body is not None:
            return self._answer("token", self.token_body, self.token_status, form_answer)
        form = dict(parse_qsl(request.content.decode()))
        client_id, secret = self._client_auth(request, form)
        if client_id != self.client_id or secret != self.client_secret:
            error = "invalid_client" if oidc else "incorrect_client_credentials"
            return self._answer("token", {"error": error}, 401 if oidc else 200, form_answer)
        grant = self.codes.pop(form.get("code", ""), None)
        if grant is None or form.get("redirect_uri") != grant["redirect_uri"]:
            return self._answer("token", {"error": "invalid_grant"}, 400, form_answer)
        challenge = _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
        if challenge != grant["code_challenge"]:
            return self._answer("token", {"error": "invalid_grant"}, 400, form_answer)
        body = {"access_token": "at-" + secrets.token_urlsafe(12), "token_type": self.token_type}
        if oidc:
            body["id_token"] = self.id_token(grant)
        else:
            body["scope"] = ""
        return self._answer("token", body, self.token_status, form_answer)
