import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemTypeName = Literal["coin", "note"]
AngleName = Literal["obverse", "reverse", "edge", "other"]


class ItemBase(BaseModel):
    type: ItemTypeName
    country: str = Field(min_length=1, max_length=100)
    denomination: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=-700, le=2100)  # numismatics goes back a while
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: str | None = None


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    type: ItemTypeName | None = None
    country: str | None = Field(default=None, min_length=1, max_length=100)
    denomination: str | None = Field(default=None, min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=-700, le=2100)
    mint_mark: str | None = Field(default=None, max_length=20)
    series: str | None = Field(default=None, max_length=200)
    quantity: int | None = Field(default=None, ge=1)
    acquisition_date: date | None = None
    acquisition_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    file_key: str
    thumb_key: str | None
    angle: AngleName | None
    is_primary: bool
    uploaded_at: datetime


class PhotoUpdate(BaseModel):
    angle: AngleName | None = None
    is_primary: bool | None = None


class EstimateCreate(BaseModel):
    estimated_value: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source: str = Field(default="manual", min_length=1, max_length=100)


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
    created_at: datetime
    updated_at: datetime


class ItemListEntry(ItemOut):
    """List view: item plus its primary photo and latest estimate, if any."""

    primary_photo_key: str | None = None
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
