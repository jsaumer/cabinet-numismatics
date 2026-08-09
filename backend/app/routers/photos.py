import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ItemPhoto
from app.routers.items import get_item_or_404
from app.schemas import AngleName, PhotoOut, PhotoUpdate
from app.services import photos as photo_store

router = APIRouter(prefix="/api", tags=["photos"])


def _get_photo_or_404(db: Session, photo_id: uuid.UUID) -> ItemPhoto:
    photo = db.get(ItemPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.get("/items/{item_id}/photos", response_model=list[PhotoOut])
def list_photos(item_id: uuid.UUID, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    return (
        db.execute(
            select(ItemPhoto).where(ItemPhoto.item_id == item_id).order_by(ItemPhoto.uploaded_at)
        )
        .scalars()
        .all()
    )


@router.post("/items/{item_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_photo(
    item_id: uuid.UUID,
    file: UploadFile,
    angle: AngleName | None = Form(default=None),
    db: Session = Depends(get_db),
):
    get_item_or_404(db, item_id)
    if file.content_type not in photo_store.EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type {file.content_type!r}; "
            f"use one of {sorted(photo_store.EXTENSIONS)}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")

    has_photos = (
        db.execute(select(ItemPhoto.id).where(ItemPhoto.item_id == item_id).limit(1)).first()
        is not None
    )
    photo = ItemPhoto(
        id=uuid.uuid4(),
        item_id=item_id,
        angle=angle,
        is_primary=not has_photos,  # first upload becomes the primary image
        file_key="",
    )
    photo.file_key = photo_store.save_photo(item_id, photo.id, file.content_type, data)
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


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
    photo_store.delete_photo_file(photo.file_key)
    db.delete(photo)
    db.flush()
    if was_primary:
        successor = db.execute(
            select(ItemPhoto)
            .where(ItemPhoto.item_id == item_id)
            .order_by(ItemPhoto.uploaded_at)
            .limit(1)
        ).scalar_one_or_none()
        if successor:
            successor.is_primary = True
    db.commit()
