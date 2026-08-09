import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ItemPhoto
from app.routers.items import get_item_or_404
from app.schemas import AngleName, PhotoOrder, PhotoOut, PhotoUpdate
from app.services import photos as photo_store

router = APIRouter(prefix="/api", tags=["photos"])


def _get_photo_or_404(db: Session, photo_id: uuid.UUID) -> ItemPhoto:
    photo = db.get(ItemPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


def _item_photos(db: Session, item_id: uuid.UUID) -> list[ItemPhoto]:
    return (
        db.execute(
            select(ItemPhoto)
            .where(ItemPhoto.item_id == item_id)
            .order_by(ItemPhoto.position, ItemPhoto.uploaded_at)
        )
        .scalars()
        .all()
    )


@router.get("/items/{item_id}/photos", response_model=list[PhotoOut])
def list_photos(item_id: uuid.UUID, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    return _item_photos(db, item_id)


@router.post("/items/{item_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_photo(
    item_id: uuid.UUID,
    file: UploadFile,
    angle: AngleName | None = Form(default=None),
    db: Session = Depends(get_db),
):
    get_item_or_404(db, item_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")

    count = db.execute(
        select(func.count()).select_from(ItemPhoto).where(ItemPhoto.item_id == item_id)
    ).scalar_one()
    photo = ItemPhoto(
        id=uuid.uuid4(),
        item_id=item_id,
        angle=angle,
        is_primary=count == 0,  # first upload becomes the primary image
        position=count,
        file_key="",
    )
    try:
        photo.file_key, photo.thumb_key, photo.width, photo.height = photo_store.save_photo(
            item_id, photo.id, data
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


@router.post("/items/{item_id}/photos/order", response_model=list[PhotoOut])
def reorder_photos(item_id: uuid.UUID, payload: PhotoOrder, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    photos = {p.id: p for p in _item_photos(db, item_id)}
    if set(payload.order) != set(photos):
        raise HTTPException(
            status_code=422, detail="Order must list each of the item's photo ids exactly once"
        )
    for position, photo_id in enumerate(payload.order):
        photos[photo_id].position = position
    db.commit()
    return _item_photos(db, item_id)


@router.patch("/photos/{photo_id}", response_model=PhotoOut)
def update_photo(photo_id: uuid.UUID, payload: PhotoUpdate, db: Session = Depends(get_db)):
    photo = _get_photo_or_404(db, photo_id)
    if payload.angle is not None:
        photo.angle = payload.angle
    if payload.is_primary:
        for other in db.execute(
            select(ItemPhoto).where(ItemPhoto.item_id == photo.item_id)
        ).scalars():
            other.is_primary = False
        photo.is_primary = True
    db.commit()
    db.refresh(photo)
    return photo


@router.delete("/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: uuid.UUID, db: Session = Depends(get_db)):
    photo = _get_photo_or_404(db, photo_id)
    was_primary = photo.is_primary
    item_id = photo.item_id
    photo_store.delete_photo_files(photo.file_key, photo.thumb_key)
    db.delete(photo)
    db.flush()
    remaining = _item_photos(db, item_id)
    for position, p in enumerate(remaining):  # compact positions
        p.position = position
    if was_primary and remaining:
        remaining[0].is_primary = True
    db.commit()
