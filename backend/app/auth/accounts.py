"""The one account, end to end: what the sign-in routes (stage 7) and the
container commands call. Each function is one unit of work and commits
itself, so a failed sign-in's audit row and counters persist even though
the caller answers with an error.

A password is only ever checked through `_check_password`, which applies
the throttles before any Argon2 work, uses the reserved slot for a known
device, and counts, audits, and alerts a failure.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    audit,
    browsers,
    common,
    devices,
    notify,
    passwords,
    sessions,
    throttle,
    tokens,
)
from app.auth import config as sso_config
from app.auth.audit import Actor
from app.auth.passwords import Busy, PasswordRejected  # noqa: F401 (re-exported)
from app.auth.throttle import Throttled  # noqa: F401 (re-exported)
from app.auth.tokens import TokenRejected  # noqa: F401 (re-exported)
from app.config import get_settings
from app.models.auth import ApiToken, AuthProvider, Claim, Identity, KnownDevice, Session, User

WRONG_CREDENTIALS = "Wrong username or password."
WRONG_PASSWORD = "Wrong password."
ALREADY_CLAIMED = "Cabinet is already set up."
NOT_CLAIMED = "Cabinet is not set up yet: open it in a browser and use the setup page."


class WrongPassword(Exception):
    def __init__(self, message: str = WRONG_CREDENTIALS):
        super().__init__(message)


class AlreadyClaimed(Exception):
    def __init__(self):
        super().__init__(ALREADY_CLAIMED)


class NotClaimed(Exception):
    def __init__(self):
        super().__init__(NOT_CLAIMED)


class NotFound(Exception):
    pass


@dataclass(frozen=True)
class Client:
    """What a request says about who is asking: the address nginx saw
    (`X-Real-IP`), the browser, and its known-device cookie, if any."""

    address: str | None = None
    user_agent: str | None = None
    device: str | None = None

    def actor(self, kind: str = "anonymous", user: User | None = None, label=None) -> Actor:
        return Actor(
            kind,
            getattr(user, "id", None),
            label or getattr(user, "username", None),
            self.address,
            self.user_agent,
        )


@dataclass
class Started:
    """A session just opened: the two cookie values to set, and for a
    sign-in, what the notice after it says."""

    user: User
    session: Session
    session_secret: str
    device_secret: str
    previous_sign_in_at: datetime | None = None
    failed_since_previous: int = 0
    new_device: bool = True


@dataclass
class PasswordChanged:
    started: Started
    revoked_tokens: list[dict] = field(default_factory=list)


def token_summary(row: ApiToken) -> dict:
    return {"id": row.id, "name": row.name, "scope": row.scope}


def _address(client: Client) -> str:
    return client.address or "unknown"


# --- the claim ------------------------------------------------------------------


def claimed(db: DbSession) -> bool:
    return db.get(Claim, 1) is not None


def admin(db: DbSession) -> User | None:
    claim = db.get(Claim, 1)
    return db.get(User, claim.user_id) if claim is not None else None


def require_admin(db: DbSession) -> User:
    user = admin(db)
    if user is None:
        raise NotClaimed()
    return user


def _start(db: DbSession, user: User, client: Client) -> Started:
    session_secret, row = sessions.create(
        db, user, address=client.address, user_agent=client.user_agent
    )
    return Started(user, row, session_secret, devices.issue(db, user.id))


def create_admin(db: DbSession, username: str, password: str, client: Client) -> Started:
    """The claim: the admin and `claim(id=1)` in one transaction, so of two
    at once exactly one wins (the other is AlreadyClaimed). The setup code is
    the caller's to check first."""
    name = passwords.normalize_username(username)
    passwords.check_password_rules(password)
    if claimed(db):
        raise AlreadyClaimed()
    hashed = passwords.hash_password(password)
    at = common.now()
    user = User(
        username=name,
        password_hash=hashed,
        role="admin",
        is_active=True,
        created_at=at,
        last_login_at=at,
        password_changed_at=at,
    )
    try:
        db.add(user)
        db.flush()
        db.add(Claim(id=1, user_id=user.id, claimed_at=at))
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AlreadyClaimed() from None
    started = _start(db, user, client)
    audit.record(db, "setup", client.actor("session", user))
    db.commit()
    return started


# --- checking a password -------------------------------------------------------------


def _check_password(
    db: DbSession,
    account: User | None,
    key: str,
    password: str,
    client: Client,
    device: KnownDevice | None,
    *,
    during: str = "sign_in",
    kind: str = "anonymous",
) -> bool:
    """`account` None (unknown or inactive) still costs one Argon2 check. A
    known device lifts the user, address, and global limits and takes the
    reserved slot; everything else is throttled before hashing."""
    address = _address(client)
    # Every attempt is counted before Argon2 runs, so a burst waiting for the
    # check slot can't all read the count as it was (review, stage 11).
    if device is not None and not devices.reserve(db, device):
        device = None  # its attempts are used up: throttled like anyone
    if device is None:
        throttle.attempt(("user", key), ("addr", address))
        throttle.check_global()
    stored = account.password_hash if account is not None and account.is_active else None
    if passwords.verify(stored, password, reserved=device is not None):
        throttle.succeed("user", key)
        throttle.succeed("addr", address)
        if device is not None:
            devices.release(db, device)
        return True
    if device is not None:
        # The limits it lifts still hear of the failure, for when it's gone.
        throttle.fail("user", key)
        throttle.fail("addr", address)
        devices.failed(db, device)
    # The name typed is recorded only when it is the account's; anything else
    # is `unknown`, so the log never collects other people's guesses.
    label = account.username if account is not None else "unknown"
    audit.record(
        db,
        audit.FAILED,
        client.actor(kind, account if kind != "anonymous" else None, label),
        detail=None if during == "sign_in" else {"during": during},
    )
    db.commit()
    notify.failed_sign_in(db)
    return False


def sign_in(db: DbSession, username: str, password: str, client: Client) -> Started:
    typed = username if isinstance(username, str) else ""
    try:
        name = passwords.normalize_username(typed)
    except PasswordRejected:
        name = None
    key = (name or typed.lower())[:64] or "-"
    account = db.scalar(select(User).where(User.username == name)) if name else None
    active = account if account is not None and account.is_active else None
    # A cheap hash lookup, before any Argon2 work, decides the reserved slot.
    device = devices.find(db, client.device, active.id) if active is not None else None
    if not _check_password(db, account, key, password, client, device):
        raise WrongPassword()

    user = active
    previous = common.aware(user.last_login_at)
    failed = audit.count(db, audit.FAILED, label=user.username, since=previous)
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password, reserved=device is not None)
    if device is not None:
        devices.forget(db, device)  # a success replaces row and cookie
    started = _start(db, user, client)
    started.previous_sign_in_at = previous
    started.failed_since_previous = failed
    started.new_device = device is None
    user.last_login_at = common.now()
    audit.record(
        db, "sign_in", client.actor("session", user), detail={"new_device": device is None}
    )
    alert_every = sso_config.get_config(db).password_sign_in_alerts
    db.commit()
    if device is None:
        notify.send(
            db,
            "sign_in_new_device",
            f"Signed in as {user.username} from {_address(client)} "
            "on a browser Cabinet had not seen before.",
        )
    elif alert_every:
        # The new-device alert says more, so this one only when it wasn't sent.
        notify.send(
            db,
            "password_sign_in",
            f"Signed in as {user.username} with the password from {_address(client)}.",
        )
    return started


def confirm(db: DbSession, row: Session, user: User, password: str, client: Client) -> None:
    """Open this session's 5-minute recent-password window."""
    _verify_current(db, user, password, client, "confirm")
    sessions.confirm(row)
    audit.record(db, "reauth", client.actor("session", user))
    db.commit()


def _verify_current(db: DbSession, user: User, password: str, client: Client, during: str):
    device = devices.find(db, client.device, user.id)
    if not _check_password(
        db, user, user.username, password, client, device, during=during, kind="session"
    ):
        raise WrongPassword(WRONG_PASSWORD)


# --- changing the account -------------------------------------------------------------


def _end_everything(db: DbSession, user: User) -> list[ApiToken]:
    """Every session, every known device and browser, every token of every
    scope."""
    sessions.revoke_all(db, user.id)
    devices.revoke_all(db, user.id)
    browsers.revoke_all(db, user.id)
    return tokens.revoke_all(db, user.id)


def change_password(
    db: DbSession, row: Session, user: User, current: str, new: str, client: Client
) -> PasswordChanged:
    """Ends everything else, tokens included, and opens a new session (and
    known device) for this browser."""
    passwords.check_password_rules(new)
    _verify_current(db, user, current, client, "password_change")
    user.password_hash = passwords.hash_password(new)
    user.password_changed_at = common.now()
    revoked = [token_summary(t) for t in _end_everything(db, user)]
    started = _start(db, user, client)
    audit.record(
        db,
        "password_changed",
        client.actor("session", user),
        detail={"tokens_revoked": [t["name"] for t in revoked]},
    )
    db.commit()
    notify.send(
        db,
        "password_changed",
        f"The password of {user.username} was changed. Every other session and "
        f"{len(revoked)} API token(s) were ended.",
    )
    return PasswordChanged(started, revoked)


def change_username(
    db: DbSession, row: Session, user: User, current: str, username: str, client: Client
) -> None:
    name = passwords.normalize_username(username)
    _verify_current(db, user, current, client, "username_change")
    taken = db.scalar(select(User).where(User.username == name, User.id != user.id))
    if taken is not None:
        raise PasswordRejected("That username is taken.")
    old = user.username
    user.username = name
    audit.record(
        db, "username_changed", client.actor("session", user), detail={"from": old, "to": name}
    )
    db.commit()


def reset_password(db: DbSession, new: str, actor: Actor) -> list[dict]:
    """The container's break-glass reset: no current password, everything
    ended, and the running backend's throttles cleared."""
    user = require_admin(db)
    passwords.check_password_rules(new)
    user.password_hash = passwords.hash_password(new)
    user.password_changed_at = common.now()
    user.is_active = True
    revoked = [token_summary(t) for t in _end_everything(db, user)]
    audit.record(
        db, "password_reset", actor, detail={"tokens_revoked": [t["name"] for t in revoked]}
    )
    db.commit()
    throttle.request_reset()
    notify.send(
        db,
        "password_reset",
        f"The password of {user.username} was reset from the container. Every session and "
        f"{len(revoked)} API token(s) were ended.",
    )
    return revoked


# --- sessions ---------------------------------------------------------------------


def sign_out(db: DbSession, row: Session, user: User, client: Client) -> None:
    sessions.revoke(row)
    if (device := devices.find(db, client.device, user.id)) is not None:
        devices.forget(db, device)
    audit.record(db, "sign_out", client.actor("session", user))
    db.commit()


def end_session(db: DbSession, user: User, session_id: int, actor: Actor) -> None:
    row = db.get(Session, session_id)
    if row is None or row.user_id != user.id or not sessions.valid(row, user):
        raise NotFound()
    sessions.revoke(row)
    audit.record(db, "session_revoked", actor, target=f"session {session_id}")
    db.commit()


def sign_out_everywhere(db: DbSession, user: User, actor: Actor) -> dict:
    ended = {
        "sessions": sessions.revoke_all(db, user.id),
        "devices": devices.revoke_all(db, user.id),
        "browsers": browsers.revoke_all(db, user.id),
    }
    audit.record(db, "sessions_revoked_all", actor, detail=ended)
    db.commit()
    return ended


# --- single sign-on (v0.33.0) ------------------------------------------------------


def unlink_identity(db: DbSession, user: User, identity_id: int, actor: Actor) -> dict:
    """Remove one way in: its live sessions are revoked, then the identity is
    deleted, in one transaction (CR-04), so a failure leaves both as they
    were. Password sessions are untouched."""
    row = db.get(Identity, identity_id)
    if row is None or row.user_id != user.id:
        raise NotFound()
    summary = identity_summary(db, row)
    try:
        ended = sessions.revoke_for_identities(db, [row.id])
        db.delete(row)
        db.flush()
        audit.record(
            db,
            "identity_unlinked",
            actor,
            target=f"identity {identity_id}",
            detail={
                "kind": summary["kind"],
                "provider_id": summary["provider_id"],
                "issuer": summary["issuer"],
                "subject": summary["subject"],
                "sessions_ended": ended,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    how = summary["provider"] or "the trusted header"
    notify.send(
        db,
        "identity_unlinked",
        f"An identity linked through {how} was unlinked from {user.username}; "
        f"{ended} session(s) that came through it were ended.",
    )
    return {**summary, "sessions_ended": ended}


def delete_provider(db: DbSession, provider_id: int, actor: Actor) -> dict:
    """Remove a provider and the identities linked through it, after
    revoking their sessions, in one transaction. Header sessions stay."""
    row = db.get(AuthProvider, provider_id)
    if row is None:
        raise NotFound()
    name = row.display_name
    try:
        ids = list(db.scalars(select(Identity.id).where(Identity.provider_id == row.id)))
        ended = sessions.revoke_for_identities(db, ids)
        db.execute(
            delete(Identity).where(Identity.id.in_(ids)),
            execution_options={"synchronize_session": "fetch"},
        )
        db.delete(row)
        db.flush()
        audit.record(
            db,
            "sso_configured",
            actor,
            target=f"provider {provider_id}",
            detail={"removed": True, "identities_removed": len(ids), "sessions_ended": ended},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    notify.send(
        db,
        "sso_configured",
        f"The sign-in provider {name!r} was removed, with {len(ids)} linked identity(ies); "
        f"{ended} session(s) that came through it were ended.",
    )
    return {"identities_removed": len(ids), "sessions_ended": ended}


def disable_sso(db: DbSession, actor: Actor) -> dict:
    """The container's switch-off: every provider disabled, the trusted-header
    mode switched off, and every `oidc` and `trusted_header` session revoked,
    in one transaction. Linked identities stay, for when it is switched back
    on. The running backend sees it on its next request (nothing is cached)."""
    try:
        rows = sso_config.providers(db, enabled_only=True)
        at = common.now()
        for row in rows:
            row.enabled = False
            row.updated_at = at
        config = sso_config.get_config(db)
        header_was_on = config.trusted_header_enabled
        config.trusted_header_enabled = False
        config.updated_at = at
        ended = sessions.revoke_external(db)
        db.flush()
        done = {
            "providers_disabled": len(rows),
            "trusted_header_switched_off": header_was_on,
            "sessions_ended": ended,
        }
        audit.record(db, "sso_disabled", actor, detail=done)
        db.commit()
    except Exception:
        db.rollback()
        raise
    notify.send(
        db,
        "sso_disabled",
        f"Single sign-on was switched off from the container: {len(rows)} provider(s) "
        f"disabled, the trusted-header mode off, {ended} session(s) ended. "
        "Password sign-in is unchanged.",
    )
    return done


def identity_summary(db: DbSession, row: Identity) -> dict:
    provider = db.get(AuthProvider, row.provider_id) if row.provider_id is not None else None
    return {
        "id": row.id,
        "kind": row.kind,
        "provider_id": row.provider_id,
        "provider": provider.display_name if provider is not None else None,
        "issuer": row.issuer,
        "subject": row.subject,
        "display": row.display,
    }


def _sign_in_methods(db: DbSession, user: User) -> dict:
    config = sso_config.get_config(db)
    identities = db.scalars(
        select(Identity).where(Identity.user_id == user.id).order_by(Identity.id)
    ).all()
    return {
        "providers": [
            {
                "id": row.id,
                "display_name": row.display_name,
                "preset": row.preset,
                "kind": row.kind,
                "enabled": row.enabled,
            }
            for row in sso_config.providers(db)
        ],
        "identities": [identity_summary(db, row) for row in identities],
        "trusted_header": {
            "configured": sso_config.trusted_header_configured(get_settings()),
            "enabled": config.trusted_header_enabled,
        },
        "password_sign_in_alerts": config.password_sign_in_alerts,
    }


# --- tokens -----------------------------------------------------------------------


def create_token(
    db: DbSession, user: User, name: str, scope: str, days: int | None, actor: Actor
) -> tuple[str, ApiToken]:
    plaintext, row = tokens.create(db, user, name, scope, days)
    audit.record(
        db,
        "token_created",
        actor,
        target=row.name,
        detail={"scope": scope, "days": days},
    )
    db.commit()
    lasts = f"for {days} day(s)" if days else "with no expiry"
    notify.send(db, "token_created", f"A {scope} API token, {row.name!r}, was created {lasts}.")
    return plaintext, row


def revoke_token(db: DbSession, user: User, token_id: int, actor: Actor) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id or not tokens.is_live(row):
        raise NotFound()
    tokens.revoke(row)
    audit.record(db, "token_revoked", actor, target=row.name)
    db.commit()


def revoke_tokens(db: DbSession, actor: Actor, name: str | None = None) -> list[dict]:
    """Every live token, or the one with this name."""
    user = require_admin(db)
    if name is None:
        ended = [token_summary(t) for t in tokens.revoke_all(db, user.id)]
        audit.record(db, "tokens_revoked_all", actor, detail={"tokens": [t["name"] for t in ended]})
    else:
        ended = []
        for row in tokens.live(db, user.id):
            if row.name == name:
                tokens.revoke(row)
                ended.append(token_summary(row))
                audit.record(db, "token_revoked", actor, target=row.name)
    db.commit()
    return ended


# --- reading ----------------------------------------------------------------------


def status(db: DbSession) -> dict:
    """What `cli status` prints; no secrets."""
    user = admin(db)
    if user is None:
        return {"claimed": False}
    return {
        "claimed": True,
        "username": user.username,
        "last_sign_in_at": common.aware(user.last_login_at),
        "failed_sign_ins_24h": audit.count(
            db, audit.FAILED, since=common.now() - timedelta(days=1)
        ),
        "sessions": [
            {
                "id": row.id,
                "created_at": common.aware(row.created_at),
                "last_seen_at": common.aware(row.last_seen_at),
                "address": row.address,
                "user_agent": row.user_agent,
            }
            for row in sessions.live(db, user.id)
        ],
        "tokens": [
            {
                **token_summary(row),
                "created_at": common.aware(row.created_at),
                "last_used_at": common.aware(row.last_used_at),
                "expires_at": common.aware(row.expires_at),
            }
            for row in tokens.live(db, user.id)
        ],
        **_sign_in_methods(db, user),
    }


def prune(db: DbSession) -> None:
    """Hourly: drop sessions, devices, and tokens that can never work again,
    and age out the audit log. A revoked or expired token is kept 30 days so
    the token list can still say what happened to it."""
    at = common.now()
    # "fetch", not the default in-Python evaluation: rows loaded from SQLite
    # carry naive times, which can't be compared with an aware one.
    fetch = {"synchronize_session": "fetch"}
    db.execute(
        delete(Session).where(
            or_(
                Session.expires_at < at,
                Session.last_seen_at < at - sessions.IDLE,
                Session.revoked_at.is_not(None),
            )
        ),
        execution_options=fetch,
    )
    db.execute(delete(KnownDevice).where(KnownDevice.expires_at < at), execution_options=fetch)
    browsers.prune(db)
    old = at - timedelta(days=30)
    db.execute(
        delete(ApiToken).where(or_(ApiToken.revoked_at < old, ApiToken.expires_at < old)),
        execution_options=fetch,
    )
    audit.prune(db)
    db.commit()
