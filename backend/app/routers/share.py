"""The share view's public routes (v0.32.0, SPEC_0320): anyone with a link,
no sign-in. While sharing is on, the gate passes a `GET` or `HEAD` under
`/api/share/` without looking up any credential, and every route here
declares `share`, so a signed-in admin sees exactly what a stranger sees.
While it is off the gate has no such rule, and an anonymous caller gets its
401 before anything here runs.

Every failure is the same `404 {"detail": "Not found"}` (a wrong, unknown,
or revoked token, a target gone, anything outside the share). The link is
resolved first, so a live link is never throttled; only a failed lookup
consults the throttle, which answers 429 (`Retry-After`, not counted) for
an address inside its wait or past the global limit, and otherwise counts
the failure and answers 404. The token is only ever read from the path and
is never logged. What an item shows is `share.item_view`'s allowlist.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.auth import common, throttle
from app.auth.permissions import permission
from app.db import get_db
from app.services import photos as photo_store
from app.services import share

router = APIRouter(prefix="/api/share", tags=["share"])

ROBOTS = {"X-Robots-Tag": "noindex, nofollow"}
HEADERS = {"Cache-Control": "no-store", **ROBOTS}
PHOTO_HEADERS = {
    "Cache-Control": "private, max-age=3600",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    **ROBOTS,
}
NOT_FOUND = {"detail": "Not found"}
VARIANTS = ("thumb", "full")
MAX_OFFSET = 1_000_000  # past bigint range is a database error, not a 422


class _PhotoFile(FileResponse):
    """No `Last-Modified` or `ETag`: both are built from the file's time,
    which is when the photo was uploaded, close to when the piece was bought.
    With neither, an `If-Range` can never match, so it gets the whole body
    (Starlette's own check would read the missing headers and fail)."""

    def set_stat_headers(self, stat_result) -> None:
        self.headers.setdefault("content-length", str(stat_result.st_size))

    def _should_use_range(self, http_if_range: str) -> bool:
        return False


def _address(request: Request) -> str:
    """The address nginx saw, as sign-in takes it (routers/auth.client_of)."""
    return (request.headers.get("x-real-ip") or "")[:45] or "unknown"


def _answer(request: Request, db: Session, token: str, work):
    """Resolve the link and run `work(link)`, or answer 429 or the one 404."""
    try:
        link = share.resolve(db, token)
    except share.NotFound:
        # Only a failed lookup reaches the throttle: a live link is never
        # refused, whoever else shares its viewer's address (behind a proxy
        # or a Swarm ingress, every viewer does).
        wait = throttle.share_failure(_address(request))
        if wait > 0:
            refused = throttle.Throttled(wait)
            return JSONResponse(
                {"detail": str(refused)},
                429,
                headers={**HEADERS, "Retry-After": str(refused.retry_after)},
            )
        return JSONResponse(NOT_FOUND, 404, headers=HEADERS)
    try:
        return work(link)
    except share.NotFound:
        return JSONResponse(NOT_FOUND, 404, headers=HEADERS)


@router.get("/{token}")
@permission("share")
def share_manifest(token: str, request: Request, db: Session = Depends(get_db)):
    """What the link shares and how many pieces; counts one open."""

    def work(link):
        body = share.manifest(db, link)
        link.opens = (link.opens or 0) + 1
        link.last_opened_at = common.now()
        db.commit()
        return JSONResponse(body, headers=HEADERS)

    return _answer(request, db, token, work)


@router.get("/{token}/items")
@permission("share")
def share_items(
    token: str,
    request: Request,
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """A page of the shared pieces, newest first; `offset` 0 to 1,000,000,
    `limit` 1 to 100."""

    def work(link):
        if not 0 <= offset <= MAX_OFFSET or not 1 <= limit <= 100:
            return JSONResponse(
                {"detail": "offset is 0 to 1000000, limit 1 to 100."}, 422, headers=HEADERS
            )
        values = share.value_context(db) if link.show_values else None
        rows = share.page_items(db, link, offset, limit)
        body = {
            "items": [share.item_view(item, link, values) for item in rows],
            "total": share.count_items(db, link),
        }
        return JSONResponse(body, headers=HEADERS)

    return _answer(request, db, token, work)


@router.get("/{token}/items/{item_id}")
@permission("share")
def share_item(token: str, item_id: str, request: Request, db: Session = Depends(get_db)):
    def work(link):
        item = share.get_item(db, link, item_id)
        values = share.value_context(db) if link.show_values else None
        return JSONResponse(share.item_view(item, link, values), headers=HEADERS)

    return _answer(request, db, token, work)


@router.get("/{token}/checklist")
@permission("share")
def share_checklist(token: str, request: Request, db: Session = Depends(get_db)):
    """A checklist link's filled slots; 404 for any other kind."""

    def work(link):
        if link.kind != "checklist":
            raise share.NotFound()
        return JSONResponse({"slots": share.filled_slots(db, link)}, headers=HEADERS)

    return _answer(request, db, token, work)


@router.get("/{token}/photos/{photo_id}/{variant}")
@permission("share")
def share_photo(
    token: str, photo_id: str, variant: str, request: Request, db: Session = Depends(get_db)
):
    """A shared piece's photo (`thumb` or `full`), served here rather than
    through nginx's `/photos/`, which stays for a session or a token. Sent
    from disk only when the one-time pass has written its marker and this
    file's own header shows nothing (`looks_clean`); otherwise re-encoded
    without metadata on the request, or the one 404 if it can't be decoded.
    The marker spares the work, it doesn't vouch for a file (v0.32.1)."""

    def work(link):
        if variant not in VARIANTS:
            raise share.NotFound()
        photo = share.get_photo(db, link, photo_id)
        key = photo.file_key if variant == "full" else (photo.thumb_key or photo.file_key)
        path = photo_store.path_of(key) if key else None
        if path is None or not path.is_file():
            raise share.NotFound()
        if photo_store.marker_exists() and photo_store.looks_clean(path):
            return _PhotoFile(path, headers=PHOTO_HEADERS)
        try:
            body, media_type = photo_store.cleaned_file(path)
        except ValueError:
            raise share.NotFound() from None
        return Response(body, media_type=media_type, headers=PHOTO_HEADERS)

    return _answer(request, db, token, work)
