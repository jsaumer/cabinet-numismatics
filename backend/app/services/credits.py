"""Credits a data source's terms ask for wherever its data is shown.

PCGS: its API End User Agreement (read by the account holder on 26 November
2026) asks that every page using its data link back to the source and state,
in at least 10-point type, the sentence in `PCGS_NOTICE`. The agreement also
names a logo in an "Exhibit A" that is not attached to it, and using a
Collectors mark needs a license, so no logo is shown. The credit is due
whenever this collection holds anything from PCGS, not only while the source
is switched on: a value fetched last year is still PCGS's data.

Numista's license asks only that its name sits with its data, which the
"Numista value" label and the N# beside a search hit already do."""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Item, SourceCache
from app.services import pricing
from app.services.app_settings import get_setting

# The agreement's own wording; don't rephrase it.
PCGS_NOTICE = (
    "The Data is obtained from and is subject to a license agreement with "
    "Collectors Universe, Inc. and its divisions PCGS and PSA."
)
PCGS = {"source": "pcgs", "name": "PCGS", "url": "https://www.pcgs.com", "notice": PCGS_NOTICE}


def holds_pcgs_data(db: Session) -> bool:
    """Whether anything from PCGS is here: the source switched on, a cached
    answer, an estimate, or a population on a piece (the trash included)."""
    if get_setting(db, "pcgs_enabled"):
        return True
    checks = (
        select(exists().where(SourceCache.source == "pcgs")),
        select(exists().where(pricing.source_is("pcgs"))),
        select(exists().where(Item.pcgs_population.is_not(None))),
    )
    return any(
        db.execute(check.execution_options(include_deleted=True)).scalar() for check in checks
    )


def due(db: Session) -> list[dict]:
    """The credits to show on every page, in order."""
    return [PCGS] if holds_pcgs_data(db) else []
