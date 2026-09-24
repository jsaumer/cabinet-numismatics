"""Single sign-on routes (v0.33.0, SPEC_0330 sections 5, 5a, and 9): the two
flow routes and the admin's provider configuration, under `/api/auth`.

The start route is an ordinary anonymous pair in the gate. The callback is
passed by layer 1 with no credential lookup at all (CR-01): it is a
cross-site top-level navigation from the provider, and a Lax session
cookie rides along on it, which the gate's CSRF rule would refuse before
routing. Its CSRF protection is the `state` bound to the encrypted flow
cookie; for link and confirm the handler reads the session cookie itself,
without touching it, and requires it to be the session that started the
flow.
"""

import hmac
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.auth import accounts, audit, common, notify, oidc, sessions, throttle
from app.auth import config as sso_config
from app.auth.events import actor_of
from app.auth.permissions import ReauthRequired, permission, principal
from app.config import _shared_hosts, get_settings, public_origins
from app.db import get_db
from app.models.auth import AuthProvider, Identity, Session, User
from app.routers.auth import NO_STORE, client_of
from app.services import alerts

router = APIRouter(prefix="/api/auth", tags=["auth"])

TENANT = r"^[A-Za-z0-9.-]{1,64}$"
SCOPES = r"^[\x21-\x7e ]{0,255}$"
SETTINGS_PAGE = "/settings/signin"


def alert_key(provider_id: int) -> str:
    return f"sso_provider_{provider_id}"


def _redirect(url: str, status: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status, headers=NO_STORE)


def _with_query(path: str, name: str, value) -> str:
    return f"{path}{'&' if '?' in path else '?'}{name}={value}"


def destination(intent: str, next_path: str, error: str | None = None) -> str:
    """Where a flow lands (R2-09): only a sign-in uses `/login?error=`; a
    link lands in Settings, a confirm back on its page."""
    if intent == "link":
        return _with_query(SETTINGS_PAGE, "error", error) if error else SETTINGS_PAGE
    if intent == "confirm":
        return _with_query(next_path, "confirm_error", error) if error else next_path
    return _with_query("/login", "error", error) if error else next_path


# --- the flow ------------------------------------------------------------------------


@router.get("/oidc/start")
@permission("public")
def oidc_start(
    request: Request,
    provider: int = Query(ge=1, le=2_000_000_000),
    next: str = Query("/", max_length=2048),
    intent: Literal["login", "link", "confirm"] = "login",
    db: DbSession = Depends(get_db),
):
    """302 to the provider, with the flow cookie set. Linking needs a
    session inside its recent-password window; confirming needs a live
    session that signed in through this provider, fresh or not (CR-07)."""
    row = sso_config.provider(db, provider)
    if row is None or not row.enabled:
        raise HTTPException(404, "No such sign-in provider.")
    next_path = oidc.safe_next(next)
    who = principal(request)
    session_hash, fresh = None, False
    if intent in ("link", "confirm"):
        if who is None or who.kind != "session":
            raise HTTPException(401, "Sign in to continue.")
        session_hash = who.session_hash
    if intent == "link":
        if not who.confirmed:
            raise ReauthRequired()
        fresh = True
    if intent == "confirm":
        if row.kind != "oidc":
            return _refused("not_qualified", "This provider can't confirm; use the password.")
        current = db.get(Session, who.session_id)
        identity = db.get(Identity, current.identity_id) if current.identity_id else None
        if current.auth_method != "oidc" or identity is None or identity.provider_id != row.id:
            return _refused(
                "confirm_identity", "This session didn't sign in through that provider."
            )
        try:
            capable = oidc.confirm_capable(oidc.discover(row))
        except oidc.ProviderError:
            return _redirect(destination(intent, next_path, "provider"))
        if not capable:
            return _refused("not_qualified", "This provider can't confirm; use the password.")
    try:
        started = oidc.start(
            row,
            intent=intent,
            next_path=next_path,
            origin=oidc.callback_origin(request.headers.get("host")),
            session_hash=session_hash,
            fresh=fresh,
        )
    except oidc.ProviderError:
        return _redirect(destination(intent, next_path, "provider"))
    response = _redirect(started.url, 302)
    sessions.set_flow_cookie(response, started.cookie)
    return response


def _refused(code: str, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code}, 403, headers=NO_STORE)


def _navigation(request: Request) -> bool:
    """A fetch or an image can't complete a sign-in: when the browser says
    what the request is, it must be a top-level document navigation."""
    mode = request.headers.get("sec-fetch-mode")
    dest = request.headers.get("sec-fetch-dest")
    return (mode is None or mode == "navigate") and (dest is None or dest == "document")


def _bound_session(db: DbSession, request: Request, flow: dict) -> tuple[Session, User]:
    """The live session a link or confirm started from (CR-01): the cookie's
    hash must be the one the flow cookie recorded. Read without touching
    `last_seen_at`."""
    secret = request.cookies.get(sessions.cookie_names()[0])
    found = sessions.find(db, secret)
    recorded = flow.get("session")
    if found is None or not isinstance(recorded, str):
        raise oidc.FlowError("session")
    if not hmac.compare_digest(common.digest(secret).hex(), recorded):
        raise oidc.FlowError("session", "other_session")
    return found


def _lookup(db: DbSession, provider: AuthProvider, found: oidc.Verified) -> Identity | None:
    return db.scalar(
        select(Identity).where(
            Identity.kind == "provider",
            Identity.provider_id == provider.id,
            Identity.issuer == found.issuer,
            Identity.subject == found.subject,
        )
    )


def _sign_in(db, request, client, provider, found, flow) -> Response:
    identity = _lookup(db, provider, found)
    user = db.get(User, identity.user_id) if identity is not None else None
    if user is None or not user.is_active:
        raise oidc.FlowError("unlinked")
    started = accounts.start_external(
        db,
        user,
        identity,
        client,
        method="oidc",
        browser_secret=client.browser,
        presented=request.cookies.get(sessions.cookie_names()[0]),
        how=provider.display_name,
    )
    response = _redirect(flow["next"])
    sessions.set_cookies(response, started.session_secret, None)
    sessions.set_browser_cookie(response, started.browser_secret)
    return response


def _link(db, request, client, provider, found, flow) -> Response:
    _, user = _bound_session(db, request, flow)
    if not flow.get("fresh"):
        raise oidc.FlowError("session", "not_fresh")
    oidc.check_link_subject(found)
    taken = _lookup(db, provider, found) is not None or db.scalar(
        select(Identity.id).where(Identity.user_id == user.id, Identity.provider_id == provider.id)
    )
    if taken:
        raise oidc.FlowError("already_linked")
    identity = Identity(
        user_id=user.id,
        kind="provider",
        provider_id=provider.id,
        issuer=found.issuer,
        subject=found.subject,
        display=found.display,
        linked_at=common.now(),
    )
    try:
        db.add(identity)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise oidc.FlowError("already_linked") from None
    audit.record(
        db,
        "identity_linked",
        client.actor("session", user),
        target=f"identity {identity.id}",
        detail={
            "kind": "provider",
            "provider_id": provider.id,
            "issuer": found.issuer,
            "subject": found.subject,
        },
    )
    db.commit()
    notify.send(
        db,
        "identity_linked",
        f"An identity at {provider.display_name} was linked to {user.username}: "
        f"it can now sign in to Cabinet.",
    )
    return _redirect(_with_query(SETTINGS_PAGE, "linked", provider.id))


def _confirm(db, request, client, provider, found, flow) -> Response:
    row, user = _bound_session(db, request, flow)
    identity = db.get(Identity, row.identity_id) if row.identity_id is not None else None
    if (
        row.auth_method != "oidc"
        or identity is None
        or identity.provider_id != provider.id
        or identity.issuer != found.issuer
        or identity.subject != found.subject
    ):
        raise oidc.FlowError("confirm_identity")  # CR-02
    sessions.confirm(row)
    audit.record(db, "reauth", client.actor("session", user), detail={"method": "oidc"})
    db.commit()
    return _redirect(flow["next"])


INTENT_HANDLERS = {"login": _sign_in, "link": _link, "confirm": _confirm}


@router.get("/oidc/callback")
@permission("public")
def oidc_callback(request: Request, db: DbSession = Depends(get_db)):
    """The provider's redirect back. The flow cookie is cleared whatever
    happens; failures redirect with a short code and are audited, throttled
    per address in a map of their own (a refusal by the user at the
    provider excepted)."""
    client = client_of(request)
    query = request.query_params
    flow, provider, found = None, None, None
    try:
        flow = oidc.read_flow(request.cookies.get(sessions.flow_cookie_name()))
        oidc.consume(flow, query.get("state"))
        if not _navigation(request):
            raise oidc.FlowError("navigation")
        provider = sso_config.provider(db, flow["provider_id"])
        if provider is None or not provider.enabled:
            raise oidc.FlowError("provider", "disabled")
        try:
            found = oidc.complete(provider, flow, query)
        except oidc.CredentialsRejected:
            alerts.fail(
                db,
                alert_key(provider.id),
                f"{provider.display_name} rejected Cabinet's client id or secret. "
                "Check them in Settings, Sign-in.",
            )
            raise
        alerts.recover(db, alert_key(provider.id))
        response = INTENT_HANDLERS[flow["intent"]](db, request, client, provider, found, flow)
    except (oidc.FlowError, oidc.ProviderError) as exc:
        response = _failed(db, client, flow, provider, found, exc)
    sessions.clear_flow_cookie(response)
    return response


def _failed(db, client, flow, provider, found, exc) -> Response:
    db.rollback()
    code, check = exc.code, exc.check
    intent = flow["intent"] if flow else "login"
    if code != "denied":
        wait = throttle.oidc_failure(client.address or "unknown")
        if wait > 0:
            return JSONResponse(
                {"detail": "Too many attempts. Try again shortly."},
                429,
                headers={**NO_STORE, "Retry-After": str(max(1, int(wait) + 1))},
            )
    detail = {"reason": code, "check": check, "intent": intent}
    if provider is not None:
        detail["provider_id"] = provider.id
    if found is not None:
        detail["subject"] = found.subject  # names nothing secret; the owner needs it
    audit.record(db, audit.REJECTED_SSO, client.actor("anonymous", label="unknown"), detail=detail)
    db.commit()
    notify.rejected_sso(db)
    return _redirect(destination(intent, flow["next"] if flow else "/", code))


# --- configuration ------------------------------------------------------------------


def _callback_urls() -> list[str]:
    return [oidc.redirect_uri(origin) for origin in public_origins(get_settings())]


def _provider_out(db: DbSession, row: AuthProvider, failing: dict) -> dict:
    return {
        "id": row.id,
        "preset": row.preset,
        "kind": row.kind,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "issuer": row.issuer,
        "client_id": row.client_id,
        "scopes": row.scopes,
        "logout_at_provider": row.logout_at_provider,
        "has_secret": bool(row.client_secret),
        "credentials_failing": alert_key(row.id) in failing,
        "linked": sso_config.linked(db, row),
    }


def _presets() -> list[dict]:
    found = []
    for name, preset in sso_config.PRESETS.items():
        fixed = preset["issuer"] if name != "microsoft" else None
        found.append(
            {
                "name": name,
                "kind": preset["kind"],
                "issuer": fixed,
                "needs_tenant": name == "microsoft",
                "needs_issuer": preset["issuer"] is None,
                "scopes": preset["scopes"],
            }
        )
    return found


@router.get("/signin-config")
@permission("admin")
def signin_config(db: DbSession = Depends(get_db)):
    config = sso_config.get_config(db)
    failing = alerts.failing(db)
    identities = db.scalars(select(Identity).order_by(Identity.id)).all()
    body = {
        "providers": [_provider_out(db, row, failing) for row in sso_config.providers(db)],
        "identities": [accounts.identity_summary(db, row) for row in identities],
        "trusted_header": {
            "configured": sso_config.trusted_header_configured(get_settings()),
            "enabled": config.trusted_header_enabled,
        },
        "password_sign_in_alerts": config.password_sign_in_alerts,
        "presets": _presets(),
        "callback_urls": _callback_urls(),
    }
    db.commit()  # get_config may have made the row
    return JSONResponse(body, headers=NO_STORE)


class SigninConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password_sign_in_alerts: bool | None = None
    trusted_header_enabled: bool | None = None


@router.put("/signin-config")
@permission("admin", fresh=True)
def put_signin_config(body: SigninConfigBody, request: Request, db: DbSession = Depends(get_db)):
    """The alert switch, and the one way to switch the trusted-header mode
    back on after `disable-sso` (R2-02)."""
    config = sso_config.get_config(db)
    changed = []
    for name in ("password_sign_in_alerts", "trusted_header_enabled"):
        value = getattr(body, name)
        if value is not None and getattr(config, name) != value:
            setattr(config, name, value)
            changed.append(name)
    if changed:
        config.updated_at = common.now()
        audit.record(
            db, "sso_configured", actor_of(principal(request)), detail={"changed": changed}
        )
    db.commit()
    if changed:
        notify.send(
            db,
            "sso_configured",
            f"Sign-in settings changed in Settings: {', '.join(changed)}.",
        )
    return signin_config(db)


class ProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["google", "microsoft", "github", "custom"]
    display_name: str = Field(min_length=1, max_length=60)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str | None = Field(None, max_length=2000)
    issuer: str | None = Field(None, min_length=1, max_length=255)
    tenant: str | None = Field(None, pattern=TENANT)
    scopes: str | None = Field(None, pattern=SCOPES)
    logout_at_provider: bool = False
    enabled: bool = False
    dry_run: bool = False


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["google", "microsoft", "github", "custom"] | None = None
    display_name: str | None = Field(None, min_length=1, max_length=60)
    client_id: str | None = Field(None, min_length=1, max_length=255)
    client_secret: str | None = Field(None, max_length=2000)
    issuer: str | None = Field(None, min_length=1, max_length=255)
    tenant: str | None = Field(None, pattern=TENANT)
    scopes: str | None = Field(None, pattern=SCOPES)
    logout_at_provider: bool | None = None
    enabled: bool | None = None


_ISSUER = re.compile(r"^https?://[^\s?#]+$")


def _issuer(preset: str, issuer: str | None, tenant: str | None) -> str:
    """The issuer a provider will have: a custom one is given (https, or
    http beside AUTH_INSECURE_HTTP), Microsoft's takes the tenant, the
    others are fixed. 422 for anything else."""
    if issuer is not None and preset != "custom":
        raise HTTPException(422, f"The {preset} preset's issuer is fixed.")
    if tenant is not None and preset != "microsoft":
        raise HTTPException(422, "Only the microsoft preset takes a tenant id.")
    if issuer is not None and not (
        _ISSUER.fullmatch(issuer)
        and (issuer.startswith("https://") or get_settings().auth_insecure_http)
    ):
        raise HTTPException(422, "The issuer is an https:// URL with no query.")
    try:
        return sso_config.issuer_for(preset, issuer, tenant)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _one_host_per_origin() -> None:
    """R2-07: the callback origin is chosen by host, so two PUBLIC_ORIGINS
    entries with one host can't both be told apart. Refused here, never at
    startup."""
    if shared := _shared_hosts(public_origins(get_settings())):
        raise HTTPException(
            409,
            f"PUBLIC_ORIGINS lists {', '.join(shared)} more than once; a sign-in "
            "callback can't tell those origins apart. Remove one first.",
        )


def _saved(db: DbSession, row: AuthProvider) -> JSONResponse:
    out = _provider_out(db, row, alerts.failing(db))
    return JSONResponse({**out, "callback_urls": _callback_urls()}, headers=NO_STORE)


@router.post("/providers", status_code=201)
@permission("admin", fresh=True)
def add_provider(body: ProviderBody, request: Request, db: DbSession = Depends(get_db)):
    """Add a provider (off unless `enabled`). `dry_run` fetches the
    discovery document only and saves nothing."""
    issuer = _issuer(body.preset, body.issuer, body.tenant)
    if body.dry_run:
        if sso_config.kind_for(body.preset) != "oidc":
            raise HTTPException(422, "GitHub publishes no discovery document to test.")
        try:
            doc = oidc.discover_issuer(issuer, fresh=True)
        except oidc.ProviderError as exc:
            return JSONResponse(
                {"ok": False, "issuer": issuer, "error": exc.check}, headers=NO_STORE
            )
        claims = doc.get("claims_supported")
        prompts = doc.get("prompt_values_supported")
        return JSONResponse(
            {
                "ok": True,
                "issuer": issuer,
                "claims_supported_auth_time": isinstance(claims, list) and "auth_time" in claims,
                "prompt_login": isinstance(prompts, list) and "login" in prompts,
            },
            headers=NO_STORE,
        )
    _one_host_per_origin()
    actor = actor_of(principal(request))
    try:
        row = sso_config.add_provider(
            db,
            preset=body.preset,
            display_name=body.display_name,
            client_id=body.client_id,
            secret=body.client_secret or "",
            issuer=body.issuer,
            tenant=body.tenant,
            scopes=body.scopes,
            logout_at_provider=body.logout_at_provider,
        )
        if body.enabled:
            sso_config.enable_provider(db, row, actor)
        given = body.model_dump(exclude_unset=True, exclude={"dry_run"})
        audit.record(
            db,
            "sso_configured",
            actor,
            target=f"provider {row.id}",
            detail={"added": True, "provider_id": row.id, "changed": sorted(given)},
        )
        db.commit()
    except sso_config.TooManyProviders as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That issuer and client id are already configured.") from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    notify.send(
        db,
        "sso_configured",
        f"A sign-in provider, {row.display_name!r}, was added"
        f"{' and switched on' if row.enabled else ' (off)'}.",
    )
    response = _saved(db, row)
    response.status_code = 201
    return response


def _found(db: DbSession, provider_id: int) -> AuthProvider:
    row = sso_config.provider(db, provider_id)
    if row is None:
        raise HTTPException(404, "No such sign-in provider.")
    return row


@router.patch("/providers/{provider_id}")
@permission("admin", fresh=True)
def change_provider(
    provider_id: int, body: ProviderPatch, request: Request, db: DbSession = Depends(get_db)
):
    """Change a provider. A secret is replaced, never read back; `issuer`,
    `client_id`, `kind`, and `preset` can't change while an identity is
    linked through it (409, R2-13); switching it off ends its sessions."""
    row = _found(db, provider_id)
    actor = actor_of(principal(request))
    given = body.model_dump(exclude_unset=True)
    changes = {
        name: given[name]
        for name in ("display_name", "client_id", "scopes", "logout_at_provider")
        if given.get(name) is not None
    }
    if body.client_secret is not None:
        changes["client_secret"] = body.client_secret
    preset = body.preset or row.preset
    if body.preset is not None or body.issuer is not None or body.tenant is not None:
        if body.issuer is None and body.tenant is None and preset == row.preset:
            pass  # the preset named again, nothing to recompute
        else:
            issuer = body.issuer
            if issuer is None and preset == "custom" == row.preset:
                issuer = row.issuer
            changes["issuer"] = _issuer(preset, issuer, body.tenant)
        changes["preset"] = preset
        changes["kind"] = sso_config.kind_for(preset)
    if changes.get("issuer") or changes.get("preset"):
        _one_host_per_origin()
    try:
        changed = sso_config.update_provider(db, row, **changes)
        ended = 0
        if body.enabled is True and not row.enabled:
            sso_config.enable_provider(db, row, actor)
            changed.append("enabled")
        elif body.enabled is False and row.enabled:
            row.enabled = False
            row.updated_at = common.now()
            ids = db.scalars(select(Identity.id).where(Identity.provider_id == row.id)).all()
            ended = sessions.revoke_for_identities(db, ids)
            changed.append("enabled")
        if changed:
            detail = {"provider_id": row.id, "changed": changed}
            if ended:
                detail["sessions_ended"] = ended
            audit.record(db, "sso_configured", actor, target=f"provider {row.id}", detail=detail)
        db.commit()
    except sso_config.ProviderLinked as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That issuer and client id are already configured.") from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    if changed:
        notify.send(
            db,
            "sso_configured",
            f"The sign-in provider {row.display_name!r} was changed: {', '.join(changed)}.",
        )
    return _saved(db, row)


@router.delete("/providers/{provider_id}", status_code=204)
@permission("admin", fresh=True)
def delete_provider(provider_id: int, request: Request, db: DbSession = Depends(get_db)):
    """Remove a provider and the identities linked through it, after ending
    the sessions that came through them."""
    try:
        accounts.delete_provider(db, provider_id, actor_of(principal(request)))
    except accounts.NotFound:
        raise HTTPException(404, "No such sign-in provider.") from None
    alerts.forget(db, alert_key(provider_id))
    return Response(status_code=204, headers=NO_STORE)


@router.delete("/identities/{identity_id}", status_code=204)
@permission("admin", fresh=True)
def unlink_identity(identity_id: int, request: Request, db: DbSession = Depends(get_db)):
    """Unlink; the sessions that came through the identity end."""
    who = principal(request)
    try:
        accounts.unlink_identity(db, db.get(User, who.user_id), identity_id, actor_of(who))
    except accounts.NotFound:
        raise HTTPException(404, "No such linked identity.") from None
    return Response(status_code=204, headers=NO_STORE)
