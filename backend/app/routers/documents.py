"""Documents attached to items (v0.19.0). See services/documents.py.

A document is uploaded on one item and can be linked to others; removing it
from an item unlinks it, and the file goes only when no item holds it any
more (or it's deleted outright).

Files are served here, never by nginx, with headers set from the type detected
at upload: `nosniff`, a CSP with no sources, and `sandbox` for images. PDFs get
no `sandbox`, which stops Chrome's built-in viewer rendering them at all; their
scripts run in the browser viewer's own sandbox, not this origin.
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Document, Item
from app.routers.items import get_item_or_404, record_event
from app.schemas import DocumentKind, DocumentLink, DocumentOut, DocumentUpdate
from app.services import documents as store
from app.services import trash

router = APIRouter(prefix="/api", tags=["documents"])

IMAGE_CSP = "default-src 'none'; sandbox"
PDF_CSP = "default-src 'none'; frame-ancestors 'self'"


def _get_or_404(db: Session, document_id: uuid.UUID) -> Document:
    document = db.execute(
        select(Document).where(Document.id == document_id).options(selectinload(Document.items))
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _delete(db: Session, document: Document) -> None:
    document_id = document.id
    db.delete(document)
    db.commit()
    store.delete_files(document_id)


@router.get("/items/{item_id}/documents", response_model=list[DocumentOut])
def list_documents(item_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_item_or_404(db, item_id, load_related=True).documents


@router.post("/items/{item_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    item_id: uuid.UUID,
    file: UploadFile,
    kind: DocumentKind = Form(default="other"),
    title: str | None = Form(default=None, max_length=200),
    doc_date: str | None = Form(default=None),
    note: str | None = Form(default=None, max_length=2000),
    db: Session = Depends(get_db),
):
    """Attach a PDF, JPEG, PNG, or WebP (25 MB at most) to an item."""
    item = get_item_or_404(db, item_id)
    try:
        store.require_storage()
    except store.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    data = await file.read(store.MAX_BYTES + 1)
    try:
        info = store.inspect(data)
    except ValueError as exc:
        status = 413 if len(data) > store.MAX_BYTES else 415
        raise HTTPException(status_code=status, detail=str(exc)) from None
    filename = store.clean_filename(file.filename, info["ext"])
    try:
        parsed_date = DocumentUpdate(doc_date=doc_date or None).doc_date
    except ValueError:
        raise HTTPException(status_code=422, detail="doc_date must be YYYY-MM-DD") from None
    document = Document(
        id=uuid.uuid4(),
        kind=kind,
        title=(title or "").strip() or filename.rsplit(".", 1)[0],
        doc_date=parsed_date,
        note=(note or "").strip() or None,
        filename=filename,
        content_type=info["content_type"],
        size=len(data),
        sha256=store.sha256(data),
        pages=info["pages"],
        file_key="",
    )
    document.file_key, document.thumb_key = store.save(document.id, data, info)
    document.items = [item]
    db.add(document)
    record_event(db, item.id, "updated", {"document": [None, document.title]})
    try:
        db.commit()
    except Exception:
        db.rollback()
        store.delete_files(document.id)
        raise
    return _get_or_404(db, document.id)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(document_id: uuid.UUID, payload: DocumentUpdate, db: Session = Depends(get_db)):
    document = _get_or_404(db, document_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in ("kind", "title") and value is None:
            raise HTTPException(status_code=422, detail=f"{key} can't be empty")
        setattr(document, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return _get_or_404(db, document_id)


@router.post("/documents/{document_id}/items", response_model=DocumentOut)
def link_document(document_id: uuid.UUID, payload: DocumentLink, db: Session = Depends(get_db)):
    """Attach the document to more items (already-linked ones are left as they are)."""
    document = _get_or_404(db, document_id)
    have = {item.id for item in document.items}
    for item_id in payload.item_ids:
        if item_id in have:
            continue
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
        document.items.append(item)
        have.add(item_id)
        record_event(db, item.id, "updated", {"document": [None, document.title]})
    db.commit()
    return _get_or_404(db, document_id)


@router.delete("/items/{item_id}/documents/{document_id}", status_code=204)
def unlink_document(item_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Remove the document from this item; the file goes when no item holds it."""
    document = _get_or_404(db, document_id)
    item = next((i for i in document.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="That document isn't attached to this item")
    document.items.remove(item)
    record_event(db, item_id, "updated", {"document": [document.title, None]})
    db.commit()
    # Count links on the table: an item in the trash still holds the document,
    # though the relationship above doesn't show it.
    if trash.links(db, document_id) == 0:
        _delete(db, document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete the document from every item it's attached to, and its file."""
    document = _get_or_404(db, document_id)
    for item in document.items:
        record_event(db, item.id, "updated", {"document": [document.title, None]})
    _delete(db, document)


def _serve(path_key: str | None, content_type: str, disposition: str, filename: str):
    if not path_key:
        raise HTTPException(status_code=404, detail="Nothing to show")
    try:
        path = store.path_of(path_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File missing") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    headers = {
        "Content-Disposition": (
            f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": PDF_CSP if content_type == store.PDF else IMAGE_CSP,
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(path, media_type=content_type, headers=headers)


@router.get("/documents/{document_id}/file")
def document_file(document_id: uuid.UUID, download: bool = False, db: Session = Depends(get_db)):
    """The document itself — shown in the browser, or `?download=true` to save it."""
    document = _get_or_404(db, document_id)
    disposition = "attachment" if download else "inline"
    return _serve(document.file_key, document.content_type, disposition, document.filename)


@router.get("/documents/{document_id}/thumb")
def document_thumb(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = _get_or_404(db, document_id)
    return _serve(document.thumb_key, "image/jpeg", "inline", "thumbnail.jpg")
