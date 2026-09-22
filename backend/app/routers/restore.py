"""Restore from inside the app. Destructive and, like the rest of the API,
unauthenticated: the archive is verified, a safety backup is taken first, the
caller has to send the confirmation phrase, and a deployment can switch the
whole feature off with RESTORE_ENABLED=false (every endpoint but the status
then answers 404)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import backup, restore


def _require_enabled() -> None:
    if not restore.enabled():
        raise HTTPException(404, "Restore is switched off on this deployment")


router = APIRouter(prefix="/api/restore", tags=["restore"])
guarded = APIRouter(dependencies=[Depends(_require_enabled)])


class RunRequest(BaseModel):
    confirm: str = ""


@router.get("/status")
def restore_status() -> dict:
    """Always answers: during a restore (when the rest of the API says 503)
    and when the feature is off (`enabled: false`)."""
    return restore.status()


async def _stage_upload(request: Request) -> tuple[str, Path, str] | None:
    """Stream the multipart field `file` straight into the staging folder.
    FastAPI's own UploadFile would spool a 20 GB archive through the
    container's temp folder first. None when the request carries no file."""
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    if content_type != b"multipart/form-data" or not options.get(b"boundary"):
        return None
    part = {"field": b"", "value": b"", "headers": {}, "wanted": False, "filename": None}
    seen = {"file": False}
    chunks: list[bytes] = []

    def on_part_begin():
        part.update(field=b"", value=b"", headers={}, wanted=False)

    def on_header_field(data, start, end):
        part["field"] += data[start:end]

    def on_header_value(data, start, end):
        part["value"] += data[start:end]

    def on_header_end():
        part["headers"][part["field"].lower()] = part["value"]
        part.update(field=b"", value=b"")

    def on_headers_finished():
        _kind, params = parse_options_header(part["headers"].get(b"content-disposition", b""))
        if params.get(b"name") == b"file" and not seen["file"]:
            part["wanted"] = seen["file"] = True
            part["filename"] = (params.get(b"filename") or b"").decode(errors="replace")

    def on_part_data(data, start, end):
        if part["wanted"]:
            chunks.append(data[start:end])

    def on_part_end():
        part["wanted"] = False

    parser = MultipartParser(
        options[b"boundary"],
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    restore_id, path = await run_in_threadpool(restore.new_staging_file)
    limit = restore.upload_limit()
    size = 0
    # Nothing is written to the backup share until the upload has shown it is
    # an age file: a plain archive (the whole collection, unencrypted) is
    # refused on its first bytes rather than stored while it arrives.
    head = b""
    try:
        with open(path, "wb") as out:
            async for block in request.stream():
                parser.write(block)
                if chunks:
                    data = b"".join(chunks)
                    chunks.clear()
                    size += len(data)
                    if size > limit:
                        raise restore.too_large()
                    if head is not None:
                        head += data
                        if len(head) < len(backup.AGE_MAGIC):
                            continue
                        restore.require_age_header(head)
                        data, head = head, None
                    await run_in_threadpool(out.write, data)
            parser.finalize()
            if head:  # shorter than the header: not an archive at all
                restore.require_age_header(head)
    except MultipartParseError as exc:
        path.unlink(missing_ok=True)
        raise restore.RestoreError(f"The upload could not be read: {exc}") from exc
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if not seen["file"]:
        path.unlink(missing_ok=True)
        return None
    return restore_id, path, restore.shown_name(part["filename"])


@guarded.post(
    "/inspect",
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def inspect_archive(
    request: Request, name: str | None = None, db: Session = Depends(get_db)
) -> dict:
    """Check an uploaded archive (multipart `file`) or one already in the
    backup directory (`?name=`, no body), and say what restoring it would
    replace. Nothing is changed."""
    try:
        staged = await _stage_upload(request)
        if staged is not None:
            restore_id, path, shown = staged
            return await run_in_threadpool(
                restore.inspect, db, path, shown, staged=True, restore_id=restore_id
            )
        if name:
            await run_in_threadpool(restore.clean_staging)
            stored = restore.stored_archive(name)
            return await run_in_threadpool(restore.inspect, db, stored, name, staged=False)
    except restore.TooLarge as exc:
        raise HTTPException(413, str(exc)) from None
    except restore.Unknown as exc:
        raise HTTPException(404, str(exc)) from None
    except restore.Busy as exc:
        raise HTTPException(409, str(exc)) from None
    except (restore.RestoreError, backup.BackupError) as exc:
        raise HTTPException(422, str(exc)) from None
    raise HTTPException(422, "Send an archive as `file`, or the `name` of a stored one.")


@guarded.post("/{restore_id}/run", status_code=202)
def run_restore(restore_id: str, body: RunRequest, db: Session = Depends(get_db)) -> dict:
    """Start the restore in the background; poll `/api/restore/status`."""
    entry = restore._pending.get(restore_id)
    if entry is None:
        raise HTTPException(404, "No such restore; inspect the archive again.")
    # RESTORE, or RESTORE OLDER for an archive older than the newest recorded.
    phrase = entry.get("phrase", restore.CONFIRM_PHRASE)
    if body.confirm != phrase:
        raise HTTPException(422, f"Type {phrase} to confirm.")
    engine = db.get_bind()
    db.close()  # the restore replaces the database; hold nothing open on it
    try:
        restore.start(restore_id, engine, body.confirm)
    except restore.Unknown as exc:
        raise HTTPException(404, str(exc)) from None
    except restore.Busy as exc:
        raise HTTPException(409, str(exc)) from None
    return {"state": "running"}


@guarded.delete("/{restore_id}", status_code=204)
def discard_restore(restore_id: str) -> Response:
    """Discard a staged upload. An archive in the backup directory is never
    deleted here; its restore id is just forgotten."""
    try:
        restore.discard(restore_id)
    except restore.Unknown as exc:
        raise HTTPException(404, str(exc)) from None
    except backup.BackupError as exc:
        raise HTTPException(500, str(exc)) from None
    return Response(status_code=204)


router.include_router(guarded)
