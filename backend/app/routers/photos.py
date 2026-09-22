import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.permissions import permission
from app.db import get_db
from app.models import ItemPhoto
from app.routers.items import get_item_or_404
from app.schemas import AngleName, PhotoFromUrl, PhotoOrder, PhotoOut, PhotoUpdate
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
@permission("read")
def list_photos(item_id: uuid.UUID, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    return _item_photos(db, item_id)


def _create_photo(db: Session, item_id: uuid.UUID, data: bytes, angle: str | None) -> ItemPhoto:
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


@router.post("/items/{item_id}/photos", response_model=PhotoOut, status_code=201)
@permission("write")
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
    return _create_photo(db, item_id, data, angle)


@router.post("/items/{item_id}/photos/url", response_model=PhotoOut, status_code=201)
@permission("write")
def import_photo(item_id: uuid.UUID, payload: PhotoFromUrl, db: Session = Depends(get_db)):
    """Fetch an image from a public URL and add it like an upload."""
    get_item_or_404(db, item_id)
    try:
        data = photo_store.fetch_remote_image(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except photo_store.RemoteImageUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return _create_photo(db, item_id, data, payload.angle)


@router.put("/photos/{photo_id}/image", response_model=PhotoOut)
@permission("write")
async def replace_photo_image(photo_id: uuid.UUID, file: UploadFile, db: Session = Depends(get_db)):
    """Swap a photo's image for an edited one, keeping its angle, primary
    flag, and position. The new file gets a fresh name so cached copies of the
    old image aren't shown; the old files are deleted."""
    photo = _get_photo_or_404(db, photo_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    old_keys = (photo.file_key, photo.thumb_key)
    try:
        photo.file_key, photo.thumb_key, photo.width, photo.height = photo_store.save_photo(
            photo.item_id, photo.id, data, stem=f"{photo.id}-{uuid.uuid4().hex[:8]}"
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    db.commit()
    photo_store.delete_photo_files(*old_keys)
    db.refresh(photo)
    return photo


@router.post("/items/{item_id}/photos/order", response_model=list[PhotoOut])
@permission("write")
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
@permission("write")
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
@permission("write")
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
