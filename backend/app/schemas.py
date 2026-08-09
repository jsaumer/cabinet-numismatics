import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ItemTypeName = Literal["coin", "note"]
ItemStatusName = Literal["owned", "sold", "wishlist"]
AngleName = Literal["obverse", "reverse", "edge", "other"]


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


class ItemBase(BaseModel):
    type: ItemTypeName
    status: ItemStatusName = "owned"
    country: str = Field(min_length=1, max_length=100)
    denomination: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=-700, le=2100)  # numismatics goes back a while
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    variety: str | None = Field(default=None, max_length=200)
    composition: str | None = Field(default=None, max_length=100)
    weight_g: float | None = Field(default=None, gt=0)
    fineness: float | None = Field(default=None, gt=0, le=1)
    cert_service: str | None = Field(default=None, max_length=50)
    cert_number: str | None = Field(default=None, max_length=50)
    quantity: int = Field(default=1, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    acquired_from: str | None = Field(default=None, max_length=200)
    storage_location: str | None = Field(default=None, max_length=200)
    sold_date: date | None = None
    sold_price: float | None = Field(default=None, ge=0)
    custom_fields: dict[str, str] | None = None
    notes: str | None = None

    _cf = field_validator("custom_fields")(_validate_custom_fields)


class ItemCreate(ItemBase):
    grade_id: int | None = None
    set_id: int | None = None
    tags: list[str] = []
    catalog_refs: list[CatalogRefIn] = []


class ItemUpdate(BaseModel):
    type: ItemTypeName | None = None
    status: ItemStatusName | None = None
    country: str | None = Field(default=None, min_length=1, max_length=100)
    denomination: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=-700, le=2100)
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    variety: str | None = Field(default=None, max_length=200)
    composition: str | None = Field(default=None, max_length=100)
    weight_g: float | None = Field(default=None, gt=0)
    fineness: float | None = Field(default=None, gt=0, le=1)
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

    _cf = field_validator("custom_fields")(_validate_custom_fields)


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


class PhotoUpdate(BaseModel):
    angle: AngleName | None = None
    is_primary: bool | None = None


class PhotoOrder(BaseModel):
    order: list[uuid.UUID] = Field(min_length=1)


class EstimateCreate(BaseModel):
    estimated_value: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source: str = Field(default="manual", min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    source: str
    estimated_value: float
    currency: str
    confidence: float | None
    sample_size: int | None
    fetched_at: datetime


class ItemOut(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grade: GradeOut | None = None
    set: SetOut | None = None
    tags: list[str] = []
    catalog_refs: list[CatalogRefOut] = []
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tag_names(cls, value):
        return [t.name if hasattr(t, "name") else t for t in value]


class BulkUpdate(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    set: ItemUpdate | None = None  # scalar fields applied to every item
    add_tags: list[str] = []
    remove_tags: list[str] = []


class BulkResult(BaseModel):
    updated: int


class ItemListEntry(ItemOut):
    """List view: item plus its primary photo and latest estimate, if any."""

    primary_photo_key: str | None = None
    primary_thumb_key: str | None = None
    latest_value: float | None = None
    latest_value_currency: str | None = None


class ItemDetail(ItemOut):
    photos: list[PhotoOut] = []
    estimates: list[EstimateOut] = []


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
    cost_basis: float  # owned items with a price in the display currency
    estimated_value: float  # owned items' latest estimates in the display currency
    unrealized_gain: float  # over owned items having BOTH price and estimate
    realized_gain: float  # sold items: sold_price - acquisition_price
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


class RefreshResult(BaseModel):
    updated: int
    skipped: int
    failed: int
