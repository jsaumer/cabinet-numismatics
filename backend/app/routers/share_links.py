"""Managing share links (v0.32.0, SPEC_0320): the admin's side of the share
view. Making, regenerating, or revoking a link asks for the password again,
as an API token does; a link's token is shown once, in the answer that makes
it, and only its hash is kept. Each of those is audited and alerted."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import common, events
from app.auth.permissions import permission, principal
from app.db import get_db
from app.models import ShareLink
from app.services import share

router = APIRouter(prefix="/api/share-links", tags=["share"])

NO_STORE = {"Cache-Control": "no-store"}


class LinkBody(BaseModel):
    kind: Literal["collection", "set", "checklist"]
    set_id: int | None = None
    checklist_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    show_photos: bool = True
    show_grades: bool = True
    show_tags: bool = True
    show_notes: bool = False
    show_values: bool = False


class LinkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    show_photos: bool | None = None
    show_grades: bool | None = None
    show_tags: bool | None = None
    show_notes: bool | None = None
    show_values: bool | None = None


class LinkOut(BaseModel):
    id: str
    kind: str
    set_id: int | None
    checklist_id: int | None
    target_name: str | None
    name: str
    show_photos: bool
    show_grades: bool
    show_tags: bool
    show_notes: bool
    show_values: bool
    created_at: str | None
    created_by: str
    last_opened_at: str | None
    opens: int


class LinkCreated(LinkOut):
    url: str  # shown once, here only


def _iso(value: datetime | None) -> str | None:
    value = common.aware(value)
    return value.isoformat() if value else None


def _out(db: Session, row: ShareLink) -> dict:
    """Never the token or its hash."""
    return {
        "id": str(row.id),
        "kind": row.kind,
        "set_id": row.set_id,
        "checklist_id": row.checklist_id,
        "target_name": share.target_name(db, row),
        "name": row.name,
        **{option: bool(getattr(row, option)) for option in share.OPTIONS},
        "created_at": _iso(row.created_at),
        "created_by": row.created_by,
        "last_opened_at": _iso(row.last_opened_at),
        "opens": row.opens or 0,
    }


def _get_or_404(db: Session, link_id: uuid.UUID) -> ShareLink:
    row = db.get(ShareLink, link_id)
    if row is None:
        raise HTTPException(404, "No such share link.")
    return row


def _record(db: Session, request: Request, action: str, row: ShareLink, message: str) -> None:
    events.record(
        db,
        request,
        action,
        target=str(row.id),
        detail={"name": row.name, "kind": row.kind},
        alert=message,
    )


@router.get("", response_model=list[LinkOut])
@permission("admin")
def list_links(db: Session = Depends(get_db)):
    rows = db.scalars(select(ShareLink).order_by(ShareLink.created_at.desc(), ShareLink.name))
    return [_out(db, row) for row in rows]


@router.post("", status_code=201, response_model=LinkCreated)
@permission("admin", fresh=True)
def create_link(body: LinkBody, request: Request, db: Session = Depends(get_db)):
    try:
        token, row = share.create(
            db,
            kind=body.kind,
            set_id=body.set_id,
            checklist_id=body.checklist_id,
            name=body.name,
            options=body.model_dump(include=set(share.OPTIONS)),
            created_by=principal(request).username,
        )
    except share.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    except share.Rejected as exc:
        raise HTTPException(422, str(exc)) from None
    _record(
        db,
        request,
        "share_link_created",
        row,
        f"A share link ({row.kind}), {row.name!r}, was created. Anyone with it can see "
        "what it shares without signing in.",
    )
    db.refresh(row)
    return JSONResponse({**_out(db, row), "url": share.link_url(token)}, 201, headers=NO_STORE)


@router.patch("/{link_id}", response_model=LinkOut)
@permission("admin")
def update_link(link_id: uuid.UUID, body: LinkPatch, db: Session = Depends(get_db)):
    """Rename a link or change what it shows; the token stays."""
    row = _get_or_404(db, link_id)
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in fields:
        name = fields.pop("name").strip()
        if not name:
            raise HTTPException(422, "A link's name is 1 to 100 characters.")
        row.name = name
    for option, value in fields.items():
        setattr(row, option, bool(value))
    db.commit()
    db.refresh(row)
    return _out(db, row)


@router.post("/{link_id}/regenerate", response_model=LinkCreated)
@permission("admin", fresh=True)
def regenerate_link(link_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """A new link in place of a lost one; the old link stops working at once."""
    row = _get_or_404(db, link_id)
    try:
        token = share.regenerate(db, row)
    except share.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    _record(
        db,
        request,
        "share_link_regenerated",
        row,
        f"The share link {row.name!r} was replaced with a new one; the old one no longer works.",
    )
    db.refresh(row)
    return JSONResponse({**_out(db, row), "url": share.link_url(token)}, headers=NO_STORE)


@router.delete("/{link_id}", status_code=204)
@permission("admin", fresh=True)
def revoke_link(link_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Revoke for good: the row is deleted."""
    row = _get_or_404(db, link_id)
    db.delete(row)
    _record(db, request, "share_link_revoked", row, f"The share link {row.name!r} was revoked.")
    return Response(status_code=204, headers=NO_STORE)
