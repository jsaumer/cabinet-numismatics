import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Item
from app.schemas import (
    ItemCreate,
    ItemDetail,
    ItemList,
    ItemListEntry,
    ItemOut,
    ItemUpdate,
)
from app.services import photos as photo_store

router = APIRouter(prefix="/api/items", tags=["items"])

SORTABLE = {
    "created_at": Item.created_at,
    "year": Item.year,
    "country": Item.country,
    "denomination": Item.denomination,
    "acquisition_date": Item.acquisition_date,
    "acquisition_price": Item.acquisition_price,
}


def get_item_or_404(db: Session, item_id: uuid.UUID, *, load_related: bool = False) -> Item:
    stmt = select(Item).where(Item.id == item_id)
    if load_related:
        stmt = stmt.options(selectinload(Item.photos), selectinload(Item.estimates))
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _filtered(stmt, type: str | None, country: str | None, year: int | None, q: str | None):
    if type:
        stmt = stmt.where(Item.type == type)
    if country:
        stmt = stmt.where(Item.country.ilike(country))
    if year is not None:
        stmt = stmt.where(Item.year == year)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Item.notes.ilike(like),
                Item.series.ilike(like),
                Item.country.ilike(like),
                Item.denomination.ilike(like),
            )
        )
    return stmt


def _list_entry(item: Item) -> ItemListEntry:
    primary = next((p for p in item.photos if p.is_primary), None)
    if primary is None and item.photos:
        primary = item.photos[0]
    latest = item.estimates[0] if item.estimates else None
    return ItemListEntry(
        **ItemOut.model_validate(item).model_dump(),
        primary_photo_key=primary.file_key if primary else None,
        latest_value=float(latest.estimated_value) if latest else None,
        latest_value_currency=latest.currency if latest else None,
    )


@router.get("", response_model=ItemList)
def list_items(
    type: str | None = Query(default=None, pattern="^(coin|note)$"),
    country: str | None = None,
    year: int | None = None,
    q: str | None = None,
    sort: str = "-created_at",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    field = sort.lstrip("-")
    if field not in SORTABLE:
        raise HTTPException(status_code=422, detail=f"Unknown sort field: {field}")
    order = SORTABLE[field].desc() if sort.startswith("-") else SORTABLE[field].asc()

    stmt = _filtered(select(Item), type, country, year, q)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.options(selectinload(Item.photos), selectinload(Item.estimates))
            .order_by(order, Item.id)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return ItemList(items=[_list_entry(i) for i in rows], total=total, limit=limit, offset=offset)


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    rows = (
        db.execute(select(Item).options(selectinload(Item.estimates)).order_by(Item.created_at))
        .scalars()
        .all()
    )

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "type",
                "country",
                "denomination",
                "year",
                "mint_mark",
                "series",
                "quantity",
                "acquisition_date",
                "acquisition_price",
                "currency",
                "notes",
                "latest_value",
                "latest_value_currency",
                "created_at",
            ]
        )
        for item in rows:
            latest = item.estimates[0] if item.estimates else None
            writer.writerow(
                [
                    item.id,
                    item.type,
                    item.country,
                    item.denomination,
                    item.year,
                    item.mint_mark or "",
                    item.series or "",
                    item.quantity,
                    item.acquisition_date or "",
                    item.acquisition_price or "",
                    item.currency,
                    item.notes or "",
                    latest.estimated_value if latest else "",
                    latest.currency if latest else "",
                    item.created_at.isoformat(),
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cabinet-items.csv"'},
    )


@router.post("", response_model=ItemOut, status_code=201)
def create_item(payload: ItemCreate, db: Session = Depends(get_db)):
    item = Item(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_item_or_404(db, item_id, load_related=True)


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(item_id: uuid.UUID, payload: ItemUpdate, db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    photo_store.delete_item_dir(item.id)
    db.delete(item)
    db.commit()
