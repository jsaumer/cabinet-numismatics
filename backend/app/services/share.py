"""The share view (v0.32.0, SPEC_0320): read-only public links to the
collection, a set, or a checklist.

A link's token is `share_` plus 32 random bytes as base64url, shown once and
stored only as its SHA-256. `resolve` answers one `NotFound` for every way a
lookup can fail (sharing off, a malformed, unknown, or revoked token, a
target gone), so a caller can't tell them apart. Everything a public route
shows goes through `item_view`, an allowlist pinned by tests/test_share.py: a
field not named there never reaches a share, whatever the item holds.
Nothing here makes a network call: values convert at cached rates only.
"""

import hashlib
import re
import secrets
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings, public_origins
from app.models import Checklist, Item, ItemPhoto, ItemSet, ShareLink
from app.services import app_settings, checklists, pricing
from app.services.currency import Converter

PREFIX = "share_"
TOKEN_RE = re.compile(r"^share_[A-Za-z0-9_-]{43}$")
KINDS = ("collection", "set", "checklist")
OPTIONS = ("show_photos", "show_grades", "show_tags", "show_notes", "show_values")
MAX_LINKS = 20
SWITCHED_OFF = "Switch sharing on in Settings first."
SHARE_PATH = re.compile(r"(/api/share/)[^/?#\s]+")

# The allowlist: every key a shared item can carry. Nothing else, ever.
FIELDS = (
    "type",
    "country",
    "denomination",
    "mint_mark",
    "series",
    "variety",
    "composition",
    "weight_g",
    "fineness",
    "diameter_mm",
    "width_mm",
    "height_mm",
    "shape",
    "issuer",
    "quantity",
)
GRADE_FIELDS = ("grade_details", "cac_sticker", "cert_service", "cert_number")
# Said outright, not left to the ORM listener: a count or a column select
# must hide the trash too.
_OWNED = (Item.status == "owned", Item.deleted_at.is_(None))
ITEM_LOAD = (selectinload(Item.photos), selectinload(Item.tags), selectinload(Item.estimates))


class NotFound(Exception):
    """Any share lookup that fails; every public route answers the same 404."""


class Rejected(ValueError):
    """A link the admin asked for that can't be made (422)."""


class Refused(Exception):
    """Sharing is off, or too many links exist (409)."""


def redact(text: str) -> str:
    """A path with its share token taken out, for a log line."""
    return SHARE_PATH.sub(r"\1[token]", text)


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def link_url(token: str) -> str:
    return f"{public_origins(get_settings())[0]}/s/{token}"


def enabled(db: Session) -> bool:
    return bool(app_settings.get_setting(db, "share_enabled"))


def target(db: Session, link: ShareLink) -> ItemSet | Checklist | None:
    if link.kind == "set" and link.set_id is not None:
        return db.get(ItemSet, link.set_id)
    if link.kind == "checklist" and link.checklist_id is not None:
        return db.get(Checklist, link.checklist_id)
    return None


def resolve(db: Session, token: str) -> ShareLink:
    if not enabled(db) or not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
        raise NotFound()
    link = db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash(token)))
    if link is None or link.kind not in KINDS:
        raise NotFound()
    if link.kind != "collection" and target(db, link) is None:
        raise NotFound()
    return link


# --- what a link covers --------------------------------------------------------------


def checklist_view(db: Session, link: ShareLink) -> tuple[list[dict], set[uuid.UUID]]:
    """The checklist's slots, as matched on read, and the owned pieces that
    fill them: a slot's match, else the piece linked to a ticked slot."""
    views = checklists.slot_views(db, target(db, link))
    wanted = {v["matched_item_id"] or v["item_id"] for v in views if v["filled"]} - {None}
    owned = set()
    if wanted:
        owned = set(db.scalars(select(Item.id).where(Item.id.in_(wanted), *_OWNED)))
    return views, owned


def _conditions(db: Session, link: ShareLink) -> list:
    """Owned pieces only, never the trash."""
    conditions = list(_OWNED)
    if link.kind == "set":
        conditions.append(Item.set_id == link.set_id)
    elif link.kind == "checklist":
        conditions.append(Item.id.in_(checklist_view(db, link)[1]))
    return conditions


def count_items(db: Session, link: ShareLink) -> int:
    return db.scalar(select(func.count()).select_from(Item).where(*_conditions(db, link))) or 0


def page_items(db: Session, link: ShareLink, offset: int, limit: int) -> list[Item]:
    """In the collection list's default order: newest first."""
    stmt = (
        select(Item)
        .where(*_conditions(db, link))
        .options(*ITEM_LOAD)
        .order_by(Item.created_at.desc(), Item.id)
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_item(db: Session, link: ShareLink, item_id: str) -> Item:
    try:
        wanted = uuid.UUID(item_id)
    except (TypeError, ValueError):
        raise NotFound() from None
    stmt = select(Item).where(Item.id == wanted, *_conditions(db, link)).options(*ITEM_LOAD)
    item = db.scalar(stmt)
    if item is None:
        raise NotFound()
    return item


def get_photo(db: Session, link: ShareLink, photo_id: str) -> ItemPhoto:
    if not link.show_photos:
        raise NotFound()
    try:
        wanted = uuid.UUID(photo_id)
    except (TypeError, ValueError):
        raise NotFound() from None
    photo = db.get(ItemPhoto, wanted)
    if photo is None:
        raise NotFound()
    get_item(db, link, str(photo.item_id))
    return photo


def manifest(db: Session, link: ShareLink) -> dict:
    out = {
        "kind": link.kind,
        "name": link.name,
        **{option: bool(getattr(link, option)) for option in OPTIONS},
        "item_count": count_items(db, link),
    }
    if link.kind == "checklist":
        views, _ = checklist_view(db, link)
        out["filled"] = sum(1 for v in views if v["filled"])
        out["total"] = len(views)
    return out


def filled_slots(db: Session, link: ShareLink) -> list[dict]:
    """A checklist's filled slots only: a share never shows a want list."""
    views, owned = checklist_view(db, link)
    slots = []
    for v in views:
        if not v["filled"]:
            continue
        piece = v["matched_item_id"] or v["item_id"]
        slots.append(
            {
                "position": v["position"],
                "label": v["label"],
                "year": v["year"],
                "mint_mark": v["mint_mark"],
                "item_id": str(piece) if piece in owned else None,
            }
        )
    return slots


# --- the item view -------------------------------------------------------------------


def value_context(db: Session) -> tuple[str, str | None, Converter]:
    """The value settings, read once a request, with a converter that reads
    cached exchange rates and never fetches one."""
    strategy = str(app_settings.get_setting(db, "value_strategy"))
    preferred = app_settings.get_setting(db, "preferred_source")
    converter = Converter(db, app_settings.display_currency(db), fetch=False)
    return strategy, preferred, converter


def shown_value(item: Item, values: tuple[str, str | None, Converter]) -> dict | None:
    """The list's shown value in the display currency, or None when there
    is none or it can't be converted from the cache."""
    strategy, preferred, converter = values
    resolved = pricing.resolve_display_value(item.estimates, strategy, preferred, converter)
    if resolved is None:
        return None
    amount = converter.convert(resolved[0], resolved[1])
    if amount is None:
        return None
    return {"amount": round(float(amount), 2), "currency": converter.display}


def _plain(value):
    return float(value) if isinstance(value, Decimal) else value


def item_view(item: Item, link: ShareLink, values=None) -> dict:
    """The allowlist. Never add a cost, a price, a location, a document, a
    serial number, or anything else the owner hasn't chosen to show."""
    view = {
        "id": str(item.id),
        "year_label": item.year_label,
        **{name: _plain(getattr(item, name)) for name in FIELDS},
    }
    if link.show_photos:
        view["photos"] = [
            {"id": str(p.id), "angle": p.angle, "has_thumbnail": p.thumb_key is not None}
            for p in item.photos
        ]
    if link.show_grades:
        view["grade_label"] = item.grade_label
        view["designations"] = list(item.designations or [])
        for name in GRADE_FIELDS:
            view[name] = getattr(item, name)
    if link.show_tags:
        view["tags"] = [tag.name for tag in item.tags]
    if link.show_notes:
        view["notes"] = item.notes
    if link.show_values:
        view["value"] = shown_value(item, values)
    return view


# --- the admin's side ---------------------------------------------------------------


def check_target(
    db: Session, kind: str, set_id: int | None, checklist_id: int | None
) -> ItemSet | Checklist | None:
    if kind == "collection":
        if set_id is not None or checklist_id is not None:
            raise Rejected("A collection link takes no set or checklist.")
        return None
    if kind == "set":
        if checklist_id is not None:
            raise Rejected("A set link takes a set_id, not a checklist_id.")
        found = db.get(ItemSet, set_id) if set_id is not None else None
        if found is None:
            raise Rejected("No such set.")
        return found
    if set_id is not None:
        raise Rejected("A checklist link takes a checklist_id, not a set_id.")
    found = db.get(Checklist, checklist_id) if checklist_id is not None else None
    if found is None:
        raise Rejected("No such checklist.")
    return found


def create(
    db: Session,
    *,
    kind: str,
    set_id: int | None,
    checklist_id: int | None,
    name: str,
    options: dict,
    created_by: str,
) -> tuple[str, ShareLink]:
    """A new link and its token (the caller shows it once). The caller commits."""
    if not enabled(db):
        raise Refused(SWITCHED_OFF)
    name = (name or "").strip()
    if not 1 <= len(name) <= 100:
        raise Rejected("A link's name is 1 to 100 characters.")
    check_target(db, kind, set_id, checklist_id)
    live = db.scalar(select(func.count()).select_from(ShareLink)) or 0
    if live >= MAX_LINKS:
        raise Refused(f"At most {MAX_LINKS} share links can exist; revoke one first.")
    token = new_token()
    row = ShareLink(
        id=uuid.uuid4(),
        token_hash=token_hash(token),
        kind=kind,
        set_id=set_id,
        checklist_id=checklist_id,
        name=name,
        created_by=created_by[:100],
        opens=0,
        **{option: bool(options[option]) for option in OPTIONS},
    )
    db.add(row)
    db.flush()
    return token, row


def regenerate(db: Session, row: ShareLink) -> str:
    """A new token; the old one stops working at once. The caller commits."""
    if not enabled(db):
        raise Refused(SWITCHED_OFF)
    token = new_token()
    row.token_hash = token_hash(token)
    return token


def target_name(db: Session, row: ShareLink) -> str | None:
    found = target(db, row)
    return found.name if found is not None else None
