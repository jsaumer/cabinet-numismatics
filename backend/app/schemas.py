import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services import calendars

ItemTypeName = Literal["coin", "note"]
ItemStatusName = Literal["owned", "sold", "wishlist"]
AngleName = Literal["obverse", "reverse", "edge", "other"]
StrikeName = Literal["business", "proof", "specimen"]
CacStickerName = Literal["green", "gold"]

# Strike and surface designations as grading services print them. EPQ is PMG's.
DESIGNATIONS = (
    "PL", "DMPL", "CAM", "DCAM", "UCAM", "RD", "RB", "BN",
    "FB", "FBL", "FH", "FS", "FT", "EPQ",
)  # fmt: skip


class GradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scale: str
    code: str
    label: str
    rank: int


class CatalogRefIn(BaseModel):
    catalog: str = Field(min_length=1, max_length=50)
    ref_code: str = Field(min_length=1, max_length=100)


class CatalogRefOut(CatalogRefIn):
    model_config = ConfigDict(from_attributes=True)


class TagOut(BaseModel):
    name: str
    count: int


class SetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    notes: str | None = None


class SetOut(SetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class SetWithCount(SetOut):
    item_count: int


def _validate_custom_fields(value: dict | None) -> dict | None:
    if value is None:
        return None
    if len(value) > 20:
        raise ValueError("At most 20 custom fields")
    for k, v in value.items():
        if not k.strip() or len(k) > 50:
            raise ValueError("Custom field names must be 1-50 characters")
        if not isinstance(v, str) or len(v) > 500:
            raise ValueError("Custom field values must be strings of at most 500 characters")
    return {k.strip(): v for k, v in value.items()}


def _validate_designations(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned: list[str] = []
    for raw in value:
        code = raw.strip().upper()
        if code not in DESIGNATIONS:
            raise ValueError(
                f"Unknown designation {raw!r}; expected one of {', '.join(DESIGNATIONS)}"
            )
        if code not in cleaned:
            cleaned.append(code)
    return cleaned or None


def _trimmed(value):
    """Strip a text field; blank becomes null."""
    if isinstance(value, str):
        return value.strip() or None
    return value


def _validate_calendar(value: str | None) -> str | None:
    if value is not None and value not in calendars.CALENDARS:
        raise ValueError(
            f"Unknown calendar {value!r}; expected one of {', '.join(calendars.CALENDARS)}"
        )
    return value


YEAR_ZERO = "There is no year 0. Tick ND for a piece with no date."
YEAR_REQUIRED = "Enter the year, or tick ND for a piece with no date."


def _validate_year(value: int | None) -> int | None:
    if value == 0:
        raise ValueError(YEAR_ZERO)
    return value


def _validate_era(value: str | None) -> str | None:
    if value is not None and value not in calendars.ERAS:
        raise ValueError(f"Unknown era {value!r}; expected one of {', '.join(calendars.ERAS)}")
    return value


TRIMMED_FIELDS = ("charter_number", "bank_city", "bank_state", "plate_position")
LOWERED_FIELDS = ("struck_calendar", "struck_era")


def _lowered(value):
    value = _trimmed(value)
    return value.lower() if isinstance(value, str) else value


class ItemBase(BaseModel):
    type: ItemTypeName
    status: ItemStatusName = "owned"
    country: str = Field(min_length=1, max_length=100)
    denomination: str = Field(min_length=1, max_length=100)
    # Numismatics goes back a while. Null only on an undated piece (`year_nd`),
    # where a year that is given is the attributed one: "ND (1951)".
    year: int | None = Field(default=None, ge=-700, le=2100)
    year_nd: bool = False  # the piece carries no date
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    variety: str | None = Field(default=None, max_length=200)
    strike: StrikeName = "business"
    composition: str | None = Field(default=None, max_length=100)
    weight_g: float | None = Field(default=None, gt=0)
    fineness: float | None = Field(default=None, gt=0, le=1)
    diameter_mm: float | None = Field(default=None, gt=0, le=1000)
    thickness_mm: float | None = Field(default=None, gt=0, le=100)
    edge: str | None = Field(default=None, max_length=100)
    shape: str | None = Field(default=None, max_length=50)
    mintage: int | None = Field(default=None, ge=0)
    cert_service: str | None = Field(default=None, max_length=50)
    cert_number: str | None = Field(default=None, max_length=50)
    grade_plus: bool = False
    grade_star: bool = False
    designations: list[str] | None = None
    grade_details: str | None = Field(default=None, max_length=100)
    cac_sticker: CacStickerName | None = None
    serial_number: str | None = Field(default=None, max_length=50)
    prefix_block: str | None = Field(default=None, max_length=50)
    signatures: str | None = Field(default=None, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    replacement_note: bool = False
    quantity: int = Field(default=1, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    acquisition_fees: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    acquired_from: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    sold_date: date | None = None
    sold_price: float | None = Field(default=None, ge=0)
    sold_fees: float | None = Field(default=None, ge=0)
    sold_to: str | None = Field(default=None, max_length=200)
    custom_fields: dict[str, str] | None = None
    notes: str | None = None
    # v0.25.0: population, wish-list target, paper money depth, die axis, date as struck
    pcgs_population: int | None = Field(default=None, ge=0, le=2_000_000_000)
    pcgs_pop_higher: int | None = Field(default=None, ge=0, le=2_000_000_000)
    target_price: float | None = Field(default=None, gt=0, lt=10**10)  # in `currency`
    priority: int | None = Field(default=None, ge=1, le=3)  # 1 high, 2 medium, 3 low
    charter_number: str | None = Field(default=None, max_length=10)
    bank_city: str | None = Field(default=None, max_length=100)
    bank_state: str | None = Field(default=None, max_length=50)
    plate_position: str | None = Field(default=None, max_length=20)
    die_axis: int | None = Field(default=None, ge=0, le=359)  # 0 medal, 180 coin alignment
    struck_calendar: str | None = Field(default=None, max_length=20)
    struck_year: int | None = Field(default=None, ge=1, le=9999)
    struck_era: str | None = Field(default=None, max_length=20)
    # v0.28.0: the metal's spot price per troy ounce on the purchase day, in
    # `currency`. Not bulk-editable; the router drops it there.
    spot_at_purchase: float | None = Field(default=None, gt=0, lt=10**8)

    _cf = field_validator("custom_fields")(_validate_custom_fields)
    _dz = field_validator("designations")(_validate_designations)
    _trim = field_validator(*TRIMMED_FIELDS, mode="before")(_trimmed)
    _lower = field_validator(*LOWERED_FIELDS, mode="before")(_lowered)
    _cal = field_validator("struck_calendar")(_validate_calendar)
    _era = field_validator("struck_era")(_validate_era)
    _yr = field_validator("year")(_validate_year)

    @model_validator(mode="after")
    def _year_or_nd(self):
        """A year is required unless the piece carries no date."""
        if self.year is None and not self.year_nd:
            raise ValueError(YEAR_REQUIRED)
        return self


class ItemCreate(ItemBase):
    grade_id: int | None = None
    set_id: int | None = None
    tags: list[str] = []
    catalog_refs: list[CatalogRefIn] = []

    @model_validator(mode="before")
    @classmethod
    def _year_from_struck_date(cls, data):
        """Without a year, a date as struck supplies it; a year that is given
        stands (the owner may know better). The era rule holds either way."""
        if not isinstance(data, dict):
            return data
        calendar, era = _lowered(data.get("struck_calendar")), _lowered(data.get("struck_era"))
        if calendar not in calendars.CALENDARS:
            if calendar is None and era is not None:
                raise ValueError("struck_era is only for the Japanese calendar")
            return data  # the field validator names an unknown calendar
        calendars.check_era(calendar, era)
        struck_year = data.get("struck_year")
        if data.get("year") in (None, "") and struck_year not in (None, ""):
            try:
                struck = int(struck_year)
            except (TypeError, ValueError):
                return data
            data = {**data, "year": calendars.to_gregorian(calendar, struck, era)}
        return data


class ItemUpdate(BaseModel):
    type: ItemTypeName | None = None
    status: ItemStatusName | None = None
    country: str | None = Field(default=None, min_length=1, max_length=100)
    denomination: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=-700, le=2100)
    year_nd: bool | None = None  # not bulk-editable; the router drops it there
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    variety: str | None = Field(default=None, max_length=200)
    strike: StrikeName | None = None
    composition: str | None = Field(default=None, max_length=100)
    weight_g: float | None = Field(default=None, gt=0)
    fineness: float | None = Field(default=None, gt=0, le=1)
    diameter_mm: float | None = Field(default=None, gt=0, le=1000)
    thickness_mm: float | None = Field(default=None, gt=0, le=100)
    edge: str | None = Field(default=None, max_length=100)
    shape: str | None = Field(default=None, max_length=50)
    mintage: int | None = Field(default=None, ge=0)
    grade_plus: bool | None = None
    grade_star: bool | None = None
    designations: list[str] | None = None
    grade_details: str | None = Field(default=None, max_length=100)
    cac_sticker: CacStickerName | None = None
    serial_number: str | None = Field(default=None, max_length=50)
    prefix_block: str | None = Field(default=None, max_length=50)
    signatures: str | None = Field(default=None, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    replacement_note: bool | None = None
    acquisition_fees: float | None = Field(default=None, ge=0)
    sold_fees: float | None = Field(default=None, ge=0)
    sold_to: str | None = Field(default=None, max_length=200)
    grade_id: int | None = None
    set_id: int | None = None
    custom_fields: dict[str, str] | None = None
    cert_service: str | None = Field(default=None, max_length=50)
    cert_number: str | None = Field(default=None, max_length=50)
    quantity: int | None = Field(default=None, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    acquired_from: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    sold_date: date | None = None
    sold_price: float | None = Field(default=None, ge=0)
    notes: str | None = None
    tags: list[str] | None = None
    catalog_refs: list[CatalogRefIn] | None = None
    # v0.25.0: population, wish-list target, paper money depth, die axis, date as struck
    pcgs_population: int | None = Field(default=None, ge=0, le=2_000_000_000)
    pcgs_pop_higher: int | None = Field(default=None, ge=0, le=2_000_000_000)
    target_price: float | None = Field(default=None, gt=0, lt=10**10)  # in `currency`
    priority: int | None = Field(default=None, ge=1, le=3)  # 1 high, 2 medium, 3 low
    charter_number: str | None = Field(default=None, max_length=10)
    bank_city: str | None = Field(default=None, max_length=100)
    bank_state: str | None = Field(default=None, max_length=50)
    plate_position: str | None = Field(default=None, max_length=20)
    die_axis: int | None = Field(default=None, ge=0, le=359)  # 0 medal, 180 coin alignment
    struck_calendar: str | None = Field(default=None, max_length=20)
    struck_year: int | None = Field(default=None, ge=1, le=9999)
    struck_era: str | None = Field(default=None, max_length=20)
    # v0.28.0: not bulk-editable; the router drops it there.
    spot_at_purchase: float | None = Field(default=None, gt=0, lt=10**8)

    _cf = field_validator("custom_fields")(_validate_custom_fields)
    _dz = field_validator("designations")(_validate_designations)
    _trim = field_validator(*TRIMMED_FIELDS, mode="before")(_trimmed)
    _lower = field_validator(*LOWERED_FIELDS, mode="before")(_lowered)
    _cal = field_validator("struck_calendar")(_validate_calendar)
    _era = field_validator("struck_era")(_validate_era)
    _yr = field_validator("year")(_validate_year)


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    file_key: str
    thumb_key: str | None
    angle: AngleName | None
    is_primary: bool
    position: int
    width: int | None
    height: int | None
    uploaded_at: datetime


DocumentKind = Literal[
    "receipt", "invoice", "certificate", "grading_label", "appraisal", "correspondence", "other"
]


class DocumentItemRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: DocumentKind
    title: str
    doc_date: date | None
    note: str | None
    filename: str
    content_type: str
    size: int
    pages: int | None
    has_thumb: bool = False
    items: list[DocumentItemRef] = []
    created_at: datetime


class DocumentUpdate(BaseModel):
    kind: DocumentKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    doc_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class TrashEntry(BaseModel):
    id: uuid.UUID
    label: str
    type: ItemTypeName
    status: ItemStatusName
    grade_label: str | None = None
    series: str | None = None
    thumb_key: str | None = None
    deleted_at: datetime
    purge_at: datetime | None = None  # deleted for good then, when auto-empty is on


class TrashList(BaseModel):
    retention_days: int  # 0 = never emptied automatically
    items: list[TrashEntry]


class ItemIds(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)


class TrashResult(BaseModel):
    count: int


class DocumentLink(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class PhotoUpdate(BaseModel):
    angle: AngleName | None = None
    is_primary: bool | None = None


class PhotoFromUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    angle: AngleName | None = None


class PhotoOrder(BaseModel):
    order: list[uuid.UUID] = Field(min_length=1)


class EstimateCreate(BaseModel):
    estimated_value: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source: str = Field(default="manual", min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=500)


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    source: str
    estimated_value: float
    currency: str
    confidence: float | None
    sample_size: int | None
    details: dict | None = None
    fetched_at: datetime


class ComparableBase(BaseModel):
    sold_on: date
    venue: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    lot: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=1000)
    grade: str | None = Field(default=None, max_length=100)
    price: float = Field(gt=0, lt=10**10)  # per piece
    currency: str = Field(default="USD", min_length=3, max_length=3)
    premium_included: bool | None = None  # null = unknown
    fees: float | None = Field(default=None, ge=0, lt=10**10)
    included: bool = True
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ComparableCreate(ComparableBase):
    pass


class ComparableUpdate(BaseModel):
    sold_on: date | None = None
    venue: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    lot: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=1000)
    grade: str | None = Field(default=None, max_length=100)
    price: float | None = Field(default=None, gt=0, lt=10**10)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    premium_included: bool | None = None
    fees: float | None = Field(default=None, ge=0, lt=10**10)
    included: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class ComparableOut(ComparableBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: uuid.UUID
    grade_bucket: str | None = None
    source: str
    created_at: datetime


class SalesFetchResult(BaseModel):
    found: int  # sales Numista returned for the item's issue
    added: int
    already_logged: int
    issue_id: int | None = None


ImportFormatName = Literal["spreadsheet", "cabinet", "numista_file", "opennumismat"]


class ImportDefaults(BaseModel):
    """What a file doesn't say: applied to every row that lacks it."""

    type: ItemTypeName = "coin"
    status: ItemStatusName = "owned"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    country: str | None = Field(default=None, max_length=100)

    @field_validator("currency")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ImportOptions(BaseModel):
    format: ImportFormatName | None = None  # None = as detected
    mapping: dict[str, str] | None = None  # spreadsheet: Cabinet field → column
    skip_rows: int | None = Field(default=None, ge=0, le=1000)  # None = find the header
    defaults: ImportDefaults = ImportDefaults()


class NumistaImportOptions(BaseModel):
    catalogue_details: bool = True  # look types up (one request each, cached 7 days)
    fetch_photos: bool = False  # download the pictures linked from Numista


class ImportUpload(BaseModel):
    upload_id: str
    filename: str
    size: int
    format: ImportFormatName


class ImportField(BaseModel):
    key: str
    label: str


class ImportPreviewRow(BaseModel):
    row: int
    status: Literal["new", "duplicate", "error"]
    label: str
    grade: str | None = None
    status_value: str | None = None
    type: str | None = None
    quantity: int | None = None
    price: float | None = None
    currency: str | None = None
    photos: int = 0
    messages: list[str] = []
    error: str | None = None


class ImportPreview(BaseModel):
    format: str
    filename: str | None = None
    total: int
    new: int
    duplicates: int
    errors: int
    warnings: int
    photos: int
    rows: list[ImportPreviewRow]
    # spreadsheet only: the columns found, where the header was, and the mapping used
    headers: list[str] | None = None
    header_row: int | None = None
    mapping: dict[str, str] | None = None
    fields: list[ImportField] | None = None
    # Numista account only: types to look up on import (one request each)
    types: int | None = None
    types_to_fetch: int | None = None
    fetched_at: datetime | None = None


class ImportRunError(BaseModel):
    row: int
    error: str


class ImportRunResult(BaseModel):
    created: int
    skipped: int  # already imported
    errors: list[ImportRunError]
    photos_added: int
    photos_failed: int


class ItemOut(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year_label: str = ""  # "1922", "ND", or "ND (1922)"
    grade: GradeOut | None = None
    grade_label: str | None = None  # e.g. "PR-69 DCAM ★"
    cost_basis: float | None = None  # price paid plus fees
    sale_proceeds: float | None = None  # sold price less fees
    population_as_of: datetime | None = None  # server-set with the population
    serial_traits: list[str] = []  # fancy-serial traits, server-set from the serial
    target_gap: float | None = None  # newest estimate less target_price; same currency only
    target_reached: bool = False  # target_gap is zero or less
    spot_at_purchase_source: str | None = None  # manual | auto, server-set
    fine_oz: float | None = None  # fine troy ounces, null when not in the stack's terms
    premium_paid_pct: float | None = None  # cost over the metal's value on the purchase day
    set: SetOut | None = None
    tags: list[str] = []
    catalog_refs: list[CatalogRefOut] = []
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None  # in the trash since

    @field_validator("tags", mode="before")
    @classmethod
    def _tag_names(cls, value):
        return [t.name if hasattr(t, "name") else t for t in value]

    @field_validator("serial_traits", mode="before")
    @classmethod
    def _trait_list(cls, value):
        """Stored as `,radar,binary,`."""
        if value is None or isinstance(value, str):
            return [key for key in (value or "").split(",") if key]
        return value


class BulkUpdate(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    set: ItemUpdate | None = None  # scalar fields applied to every item
    add_tags: list[str] = []
    remove_tags: list[str] = []


class BulkResult(BaseModel):
    updated: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    action: str
    changes: dict | None


class ChecklistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slots: list[str] = Field(min_length=1, max_length=500)


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    position: int
    filled: bool  # ticked by hand, or matched by an owned item
    item_id: uuid.UUID | None
    year: int | None = None
    mint_mark: str | None = None
    matched_item_id: uuid.UUID | None = None  # the owned item filling it
    matched_label: str | None = None


class SlotUpdate(BaseModel):
    filled: bool | None = None
    item_id: uuid.UUID | None = None


class ChecklistSummary(BaseModel):
    id: int
    name: str
    total: int
    filled: int
    generated: bool = False  # slots fill themselves from owned items


class ChecklistGenerate(BaseModel):
    """From a Numista type's issues, or a year × mint-mark range."""

    source: Literal["numista", "range"]
    name: str | None = Field(default=None, max_length=100)
    type_id: int | None = Field(default=None, ge=1)
    country: str | None = Field(default=None, max_length=100)
    denomination: str | None = Field(default=None, max_length=100)
    year_from: int | None = Field(default=None, ge=-700, le=2100)
    year_to: int | None = Field(default=None, ge=-700, le=2100)
    mint_marks: list[str] = Field(default=[""], max_length=20)  # "" = no mint mark
    skip: list[str] = Field(default=[], max_length=500)  # labels to leave out


class RunIssue(BaseModel):
    year: int | None = Field(default=None, ge=-700, le=2100)
    nd: bool = False  # an undated issue; `year` is then the attributed one
    mint_mark: str | None = Field(default=None, max_length=20)
    mintage: int | None = Field(default=None, ge=0)

    _yr = field_validator("year")(_validate_year)

    @model_validator(mode="after")
    def _year_or_nd(self):
        if self.year is None and not self.nd:
            raise ValueError(YEAR_REQUIRED)
        return self


class RunShared(BaseModel):
    """What every item of the run has in common. Prices are per item."""

    status: ItemStatusName = "owned"
    grade_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    acquisition_fees: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    acquired_from: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    set_id: int | None = None
    tags: list[str] = []
    notes: str | None = None


class RunCreate(BaseModel):
    type_id: int = Field(ge=1)
    issues: list[RunIssue] = Field(min_length=1, max_length=200)
    shared: RunShared = RunShared()
    skip_owned: bool = True


class RunResult(BaseModel):
    created: int
    skipped: int  # issues already owned
    item_ids: list[uuid.UUID]


class ChecklistDetail(BaseModel):
    id: int
    name: str
    match_catalog: str | None = None
    match_ref: str | None = None
    match_country: str | None = None
    match_denomination: str | None = None
    total: int
    filled: int
    slots: list[SlotOut]


class NumistaSearchResult(BaseModel):
    type_id: int
    title: str
    category: str | None = None
    issuer: str | None = None
    min_year: int | None = None
    max_year: int | None = None
    thumbnail: str | None = None


class NumistaSearch(BaseModel):
    count: int
    results: list[NumistaSearchResult]


class NumistaIssue(BaseModel):
    year: int | None = None
    nd: bool = False  # the issue carries no date; `year` is then attributed
    mint_letter: str | None = None
    mintage: int | None = None
    comment: str | None = None
    reference: str | None = None  # the issue's own references, e.g. "P# M22a"
    owned: bool = False  # an owned item carries this type, year, and mint mark


class NumistaType(BaseModel):
    type_id: int
    title: str
    url: str | None = None
    category: str | None = None
    fields: dict[str, bool | str | int | float]  # item fields, keyed like ItemCreate
    catalog_refs: list[CatalogRefIn]
    issues: list[NumistaIssue]


class PcgsGrade(BaseModel):
    rank: int  # Sheldon number
    strike: Literal["business", "proof", "specimen"]
    plus: bool
    designations: list[str]


class PcgsCert(BaseModel):
    """A PCGS cert as item fields ready to fill in, plus what PCGS knows."""

    cert: str
    pcgs_number: str | None = None
    name: str | None = None
    fields: dict[str, str | int | float]  # item fields, keyed like ItemCreate
    grade: PcgsGrade | None = None
    catalog_refs: list[CatalogRefIn]
    population: int | None = None
    pop_higher: int | None = None
    price_guide_value: float | None = None
    coinfacts_url: str | None = None


class SerialTraitOut(BaseModel):
    key: str
    label: str
    description: str


class CalendarOut(BaseModel):
    key: str
    label: str


class EraOut(CalendarOut):
    offset: int  # year 1 of the era is offset + 1


class CalendarReference(BaseModel):
    calendars: list[CalendarOut]
    eras: list[EraOut]


class ConvertedDate(BaseModel):
    calendar: str
    year: int
    era: str | None = None
    gregorian_year: int


class SignatureNote(BaseModel):
    id: uuid.UUID
    label: str
    serial_number: str | None = None
    grade_label: str | None = None


class SignatureGroup(BaseModel):
    series: str | None
    signatures: str | None
    count: int  # items
    quantity: int  # pieces
    items: list[SignatureNote]


class NotesBySignature(BaseModel):
    """Owned notes grouped by series and signature pair."""

    groups: list[SignatureGroup]
    total: int


class SimilarItem(BaseModel):
    """An item that looks like one about to be added, and why."""

    id: uuid.UUID
    label: str
    grade_label: str | None = None
    status: ItemStatusName
    in_trash: bool
    reason: str


class ItemListEntry(ItemOut):
    """List view: item plus its primary photo and latest estimate, if any."""

    primary_photo_key: str | None = None
    primary_thumb_key: str | None = None
    latest_value: float | None = None
    latest_value_currency: str | None = None
    latest_value_source: str | None = None


class ItemDetail(ItemOut):
    photos: list[PhotoOut] = []
    estimates: list[EstimateOut] = []
    comparables: list[ComparableOut] = []
    documents: list[DocumentOut] = []


class ItemList(BaseModel):
    items: list[ItemListEntry]
    total: int
    limit: int
    offset: int


class ImportError_(BaseModel):
    row: int
    error: str


class ImportResult(BaseModel):
    created: int
    skipped: int  # rows whose id already exists (re-importing an export is safe)
    errors: list[ImportError_]


class BreakdownEntry(BaseModel):
    key: str
    count: int
    cost_basis: float
    estimated_value: float


class Breakdowns(BaseModel):
    """Owned items grouped along each dimension. Sums follow the display
    currency rule (mismatched rows count but don't sum)."""

    currency: str
    by_country: list[BreakdownEntry]
    by_type: list[BreakdownEntry]
    by_decade: list[BreakdownEntry]
    by_grade: list[BreakdownEntry]
    by_tag: list[BreakdownEntry]
    acquisitions_by_year: list[BreakdownEntry]


class GainEntry(BaseModel):
    item_id: uuid.UUID
    label: str
    cost_basis: float
    value: float  # latest estimate (unrealized) or sold price (realized)
    gain: float


class Gains(BaseModel):
    currency: str
    unrealized: list[GainEntry]  # owned items with both price and estimate
    realized: list[GainEntry]  # sold items with both prices


class CollectionStats(BaseModel):
    """Totals in a single declared display currency; rows in other currencies
    are excluded and counted, never silently mixed."""

    currency: str
    counts: dict[str, int]  # owned / sold / wishlist / coins / notes / total
    cost_basis: float  # owned items: price paid plus fees, in the display currency
    estimated_value: float  # owned items' latest estimates in the display currency
    unrealized_gain: float  # over owned items having BOTH price and estimate
    realized_gain: float  # sold items: (sold price - fees) - (price paid + fees)
    estimated_items: int  # owned items contributing to estimated_value
    converted_other_currency: int  # amounts converted into the display currency
    excluded_other_currency: int  # amounts skipped (no exchange rate obtainable)


class ValuePoint(BaseModel):
    date: date
    value: float
    estimated_items: int


class ValueHistory(BaseModel):
    currency: str
    points: list[ValuePoint]


CoverageStatusName = Literal["priced", "not_applicable", "failed", "not_tried", "disabled"]


class SourceCoverage(BaseModel):
    source: str
    status: CoverageStatusName
    reason: str | None = None  # why it isn't priced (or a later attempt's outcome)
    estimated_at: datetime | None = None  # this source's latest estimate
    attempted_at: datetime | None = None  # this source's latest recorded attempt


class CoverageItem(BaseModel):
    item_id: uuid.UUID
    label: str
    has_estimate: bool
    sources: list[SourceCoverage]


class SourceCoverageSummary(BaseModel):
    source: str
    enabled: bool
    priced: int
    not_applicable: int
    failed: int
    not_tried: int


class PricingCoverage(BaseModel):
    owned_items: int
    estimated_items: int  # at least one estimate from any source
    manual_only_items: int
    sources: list[SourceCoverageSummary]
    items: list[CoverageItem]  # owned items needing attention


class StaleEstimate(BaseModel):
    item_id: uuid.UUID
    label: str
    source: str  # melt | numista | pcgs | manual
    source_label: str  # the estimate's own source text
    estimated_value: float
    currency: str
    fetched_at: datetime
    age_days: int
    upstream_stale: bool  # built from source data past its cache window
    in_totals: bool  # feeds the item's shown value


class StaleReport(BaseModel):
    days: int
    checked: int  # latest estimates examined, one per item and source
    stale: list[StaleEstimate]


class SourceBreakdown(BaseModel):
    source: str
    items: int
    total_value: float
    avg_confidence: float | None
    median_age_days: float | None
    in_totals: int  # items whose shown value comes from this source


class Disagreement(BaseModel):
    item_id: uuid.UUID
    label: str
    values: dict[str, float]
    spread_pct: float  # (highest - lowest) / lowest


class SourcesReport(BaseModel):
    currency: str
    strategy: str
    preferred_source: str | None
    sources: list[SourceBreakdown]
    averaged_items: int
    disagreements: list[Disagreement]
    excluded_other_currency: int


class AccuracyEstimate(BaseModel):
    source: str
    value: float
    error_pct: float  # (estimate - sold) / sold; positive = estimate was high
    estimated_at: datetime | None = None


class AccuracyItem(BaseModel):
    item_id: uuid.UUID
    label: str
    sold_date: date | None
    sold_price: float
    blended: AccuracyEstimate | None  # the shown value as of the sale
    by_source: list[AccuracyEstimate]


class AccuracySummary(BaseModel):
    source: str  # "blended" or a source key
    sales: int
    median_abs_error_pct: float
    mean_error_pct: float
    within_20_pct: int


class AccuracyReport(BaseModel):
    currency: str
    sold_items: int  # sold items with a sold price
    compared_items: int
    summary: list[AccuracySummary]
    items: list[AccuracyItem]
    excluded_other_currency: int


class RefreshResult(BaseModel):
    updated: int
    skipped: int
    failed: int


# The bullion stack (roadmap Phase 7, P7). All money is in the report's
# currency; ounces and each item's own spot at purchase are not converted.
class StackMetal(BaseModel):
    metal: str
    items: int
    pieces: int  # quantity, summed
    fine_oz: float
    fine_g: float
    spot_per_oz: float | None = None
    spot_fetched_at: datetime | None = None
    spot_stale: bool = False
    melt_value: float | None = None
    cost_basis: float
    costed_oz: float  # ounces of the pieces that have a cost
    cost_per_oz: float | None = None  # also the break-even spot price
    gain: float | None = None  # melt value of the costed ounces less their cost
    gain_pct: float | None = None
    premium_paid_pct: float | None = None
    premium_known_oz: float


class StackItem(BaseModel):
    item_id: uuid.UUID
    label: str
    metal: str
    quantity: int
    fine_oz: float
    cost_basis: float | None = None
    cost_per_oz: float | None = None
    spot_at_purchase: float | None = None  # in the item's own currency
    spot_at_purchase_source: str | None = None
    premium_paid_pct: float | None = None
    melt_value: float | None = None
    gain: float | None = None
    currency: str  # the item's own currency
    converted: bool  # its money was converted into the report's currency


class StackTotals(BaseModel):
    melt_value: float
    cost_basis: float
    gain: float
    fine_oz_by_metal: dict[str, float]


class StackReport(BaseModel):
    currency: str
    metals: list[StackMetal]
    totals: StackTotals
    items: list[StackItem]
    missing_spot: int  # pieces whose purchase-day spot could be looked up
    skipped: int  # precious-metal pieces with no weight or fineness
    excluded_other_currency: int
    history_start: date


class BackfillResult(BaseModel):
    filled: int
    failed: int
    remaining: int


class HistoricSpot(BaseModel):
    metal: str
    date: date
    currency: str
    per_oz: float
    source: str
