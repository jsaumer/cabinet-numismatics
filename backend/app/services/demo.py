"""The demo collection: something to look at before entering real pieces.

`load` puts the seventeen pieces of `demo_data` into an empty collection in
one transaction, each marked as the demo's (`import_source = "demo"`), so
`remove` can later delete exactly those and nothing the owner entered. The
photos follow on a background thread through the URL import's own fetcher
(Wikimedia Commons refuses bursts, so they come one at a time); a photo that
can't be fetched is counted, never an error, and the pieces are there
either way.

Rules a change here has to keep:

- Loading never mixes with a real collection: it is refused unless there is
  no live piece, and while demo pieces sit in the trash.
- Nothing here fetches on the request itself: `load` commits and returns,
  and only the thread talks to Commons.
- The thread works one photo at a time under `maintenance.scheduled_task()`,
  so a restore never starts while a file is being written, and it stops
  when a restore begins or the demo is removed.
- Photo progress is per process and in memory: a restart mid-way leaves the
  photos fetched so far, which is fine for a demo.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Grade, Item, PriceEstimate
from app.schemas import ItemCreate
from app.services import maintenance, pricing, trash
from app.services import photos as photo_store
from app.services.demo_data import DEMO_ITEMS

logger = logging.getLogger(__name__)

SOURCE = "demo"

NOT_EMPTY = (
    "The demo collection only loads into an empty collection, so it can never mix with your own "
    "pieces."
)
IN_TRASH = (
    "The demo collection is in the trash. Restore it from the trash, or remove it, before "
    "loading it again."
)
BUSY = "The demo collection is being loaded or removed. Try again in a moment."

# Commons refuses bursts: one photo at a time with a pause, and a refusal is
# retried after these waits (seconds).
PHOTO_PAUSE = 2
RETRY_WAITS = (10, 30, 60)
# How long one photo waits for a scheduled task (a backup, the hourly tick)
# to finish before it is given up, in tries a second apart.
TASK_TRIES = 60

# The newest value of each piece is this many days old, plus a few more per
# piece so the dates differ; earlier values are a year or more behind it.
NEWEST_AGE_DAYS = 10
STAGGER_DAYS = 9
EARLIER_GAP_DAYS = 390


class Refused(Exception):
    """Loading isn't possible right now; the message says why (409)."""


_lock = threading.Lock()  # one load or removal at a time
_state_lock = threading.Lock()
_progress = {"state": "idle", "total": 0, "fetched": 0, "failed": 0}
_generation = 0  # moved by every load and removal; a photo thread stops when it moves


def reset_memory() -> None:
    """For tests, and after a restore: the photo progress describes a
    database that is no longer there."""
    global _generation
    with _state_lock:
        _generation += 1
        _progress.update(state="idle", total=0, fetched=0, failed=0)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True, name="demo-photos").start()


def count(db: Session) -> int:
    """Demo pieces, the trash included."""
    return db.execute(
        select(func.count())
        .select_from(Item)
        .where(Item.import_source == SOURCE)
        .execution_options(include_deleted=True)
    ).scalar_one()


def status(db: Session) -> dict:
    with _state_lock:
        progress = dict(_progress)
    return {"items": count(db), "photos": progress}


def _grade_ids(db: Session) -> dict[tuple[str, str], int]:
    return {(g.scale, g.code): g.id for g in db.execute(select(Grade)).scalars()}


def _estimate_times(index: int, values: int, now: datetime) -> list[datetime]:
    """When each of a piece's values was recorded, oldest first: spread out,
    so the value-over-time chart has a line to draw."""
    newest = now - timedelta(days=NEWEST_AGE_DAYS + STAGGER_DAYS * index)
    return [newest - timedelta(days=EARLIER_GAP_DAYS * (values - 1 - n)) for n in range(values)]


def load(db: Session, *, photos: bool = True) -> dict:
    """Create the demo pieces and their values, then start fetching the
    photos. `Refused` when the collection isn't empty or a load or removal
    is under way."""
    # The router's helpers are the one way an item is built; imported here
    # because the routers import the services.
    from app.routers.items import _build_item, record_event

    global _generation
    if not _lock.acquire(blocking=False):
        raise Refused(BUSY)
    try:
        if db.execute(select(func.count()).select_from(Item)).scalar_one():
            raise Refused(NOT_EMPTY)
        if count(db):
            raise Refused(IN_TRASH)
        grades = _grade_ids(db)
        now = datetime.now(timezone.utc)
        plan: list[tuple] = []
        try:
            for index, (fields, values) in enumerate(DEMO_ITEMS):
                fields = dict(fields)
                item_photos = fields.pop("photos", [])
                scale = fields.pop("grade_scale", "sheldon")
                code = fields.pop("grade_code", None)
                grade_id = grades.get((scale, code)) if code else None
                item = _build_item(db, ItemCreate(**fields), grade_id)
                item.import_source = SOURCE
                item.import_key = f"{index:02d}"
                db.add(item)
                db.flush()
                record_event(db, item.id, "created")
                for (value, source), at in zip(
                    values, _estimate_times(index, len(values), now), strict=True
                ):
                    pricing.add_estimate(
                        db,
                        item,
                        PriceEstimate(
                            item_id=item.id,
                            estimated_value=value,
                            currency=item.currency,
                            source=source,
                            fetched_at=at,
                        ),
                    )
                plan += [(item.id, photo["angle"], photo["url"]) for photo in item_photos]
            db.commit()
        except Exception:
            db.rollback()
            raise
        with _state_lock:
            _generation += 1
            generation = _generation
            _progress.update(
                state="running" if photos and plan else "idle",
                total=len(plan) if photos else 0,
                fetched=0,
                failed=0,
            )
        if photos and plan:
            make_session = sessionmaker(bind=db.get_bind(), autoflush=False)
            _spawn(lambda: _fetch_photos(plan, make_session, generation))
        return status(db)
    finally:
        _lock.release()


def remove(db: Session) -> int:
    """Delete every demo piece for good, the trash included, with its photos
    and values. Pieces the owner entered are never touched."""
    global _generation
    if not _lock.acquire(blocking=False):
        raise Refused(BUSY)
    try:
        with _state_lock:
            _generation += 1  # stops a photo thread before its next photo
            _progress.update(state="idle", total=0, fetched=0, failed=0)
        items = list(
            db.execute(
                select(Item)
                .where(Item.import_source == SOURCE)
                .execution_options(include_deleted=True)
            ).scalars()
        )
        for item in items:
            trash.purge(db, item)
        return len(items)
    finally:
        _lock.release()


# --- photos, on a thread -----------------------------------------------------


def _current(generation: int) -> bool:
    with _state_lock:
        return generation == _generation


def _note(generation: int, **changes) -> None:
    with _state_lock:
        if generation != _generation:
            return
        for key, value in changes.items():
            _progress[key] = _progress[key] + value if key in ("fetched", "failed") else value


def _busy(exc: Exception) -> bool:
    """Commons asking for a pause, or not answering: worth another try."""
    if isinstance(exc, photo_store.RemoteImageUnavailable):
        return True
    text = str(exc)
    return "HTTP 429" in text or "HTTP 5" in text


def _download(url: str) -> bytes | None:
    for wait in (*RETRY_WAITS, None):
        try:
            return photo_store.fetch_remote_image(url)
        except (ValueError, photo_store.RemoteImageUnavailable) as exc:
            if wait is None or not _busy(exc):
                logger.info("Demo photo not fetched: %s", exc)
                return None
            _sleep(wait)
    return None


def _attach(make_session, item_id, angle: str, url: str, generation: int) -> bool | None:
    """One photo, fetched and saved. True when saved, False when it couldn't
    be, None when the work should stop (a restore began, the demo was
    removed, or the piece is gone). The download holds nothing; only the
    save takes the scheduled-task turn, so a slow Commons never makes a
    backup or a restore wait."""
    from app.routers.photos import _create_photo

    if not _current(generation) or maintenance.active():
        return None
    data = _download(url)
    if data is None:
        return False
    for _ in range(TASK_TRIES):
        if not _current(generation):
            return None
        with maintenance.scheduled_task() as go:
            if go:
                db = make_session()
                try:
                    if trash.get_any(db, item_id) is None:
                        return None
                    _create_photo(db, item_id, data, angle)
                    return True
                except Exception:
                    db.rollback()
                    logger.exception("Demo photo not saved")
                    if trash.get_any(db, item_id) is None:
                        # Removed while its file was being written.
                        photo_store.delete_item_dir(item_id)
                    return False
                finally:
                    db.close()
        if maintenance.active():
            return None
        _sleep(1)  # a scheduled task holds the turn; wait for it
    return False


def _fetch_photos(plan: list[tuple], make_session, generation: int) -> None:
    try:
        for n, (item_id, angle, url) in enumerate(plan):
            if n:
                _sleep(PHOTO_PAUSE)
            saved = _attach(make_session, item_id, angle, url, generation)
            if saved is None:
                break
            _note(generation, **{"fetched" if saved else "failed": 1})
    except Exception:  # the last net: a demo photo is never worth a crash
        logger.exception("Demo photos: the fetch stopped")
    finally:
        _note(generation, state="done")
