import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ItemType = Enum("coin", "note", name="item_type", native_enum=False, length=10)
ItemStatus = Enum("owned", "sold", "wishlist", name="item_status", native_enum=False, length=10)
PhotoAngle = Enum(
    "obverse", "reverse", "edge", "other", name="photo_angle", native_enum=False, length=10
)

item_tags = Table(
    "item_tags",
    Base.metadata,
    Column("item_id", Uuid, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

item_catalog_refs = Table(
    "item_catalog_refs",
    Base.metadata,
    Column("item_id", Uuid, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "catalog_ref_id",
        Integer,
        ForeignKey("catalog_refs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Grade(Base):
    """Reference table: grade scales (seeded by migration 0003)."""

    __tablename__ = "grades"
    __table_args__ = (UniqueConstraint("scale", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scale: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(100))
    rank: Mapped[int] = mapped_column(Integer)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class ItemSet(Base):
    """A set or lot: items grouped because they're held or sold together."""

    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)


class CatalogRef(Base):
    """Reference table: external catalog numbers (Krause, Numista, Red Book…)."""

    __tablename__ = "catalog_refs"
    __table_args__ = (UniqueConstraint("catalog", "ref_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog: Mapped[str] = mapped_column(String(50))
    ref_code: Mapped[str] = mapped_column(String(100))


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(ItemType, index=True)
    status: Mapped[str] = mapped_column(ItemStatus, default="owned", index=True)
    country: Mapped[str] = mapped_column(String(100), index=True)
    denomination: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer, index=True)
    mint_mark: Mapped[str | None] = mapped_column(String(20))
    series: Mapped[str | None] = mapped_column(String(200))
    variety: Mapped[str | None] = mapped_column(String(200))  # die variety, overdate…
    composition: Mapped[str | None] = mapped_column(String(100))
    weight_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    fineness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))  # e.g. 0.9000
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"))
    cert_service: Mapped[str | None] = mapped_column(String(50))  # PCGS, NGC, PMG…
    cert_number: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    acquisition_date: Mapped[date | None] = mapped_column(Date)
    acquisition_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    acquired_from: Mapped[str | None] = mapped_column(String(200))
    storage_location: Mapped[str | None] = mapped_column(String(200))
    sold_date: Mapped[date | None] = mapped_column(Date)
    sold_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    set_id: Mapped[int | None] = mapped_column(ForeignKey("sets.id", ondelete="SET NULL"))
    custom_fields: Mapped[dict | None] = mapped_column(JSON)  # user-defined key→value
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    grade: Mapped[Grade | None] = relationship(lazy="joined")
    set: Mapped[ItemSet | None] = relationship(lazy="joined")
    tags: Mapped[list[Tag]] = relationship(secondary=item_tags, order_by=Tag.name)
    catalog_refs: Mapped[list[CatalogRef]] = relationship(
        secondary=item_catalog_refs, order_by=CatalogRef.catalog
    )
    photos: Mapped[list["ItemPhoto"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemPhoto.position, ItemPhoto.uploaded_at",
    )
    estimates: Mapped[list["PriceEstimate"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="PriceEstimate.fetched_at.desc()",
    )


class ItemPhoto(Base):
    __tablename__ = "item_photos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    file_key: Mapped[str] = mapped_column(String(300))
    thumb_key: Mapped[str | None] = mapped_column(String(300))
    angle: Mapped[str | None] = mapped_column(PhotoAngle)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[Item] = relationship(back_populates="photos")


class ItemEvent(Base):
    """Append-only edit history for an item (created/updated). Integer PK so
    same-second events still order correctly."""

    __tablename__ = "item_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(String(20))  # created | updated
    changes: Mapped[dict | None] = mapped_column(JSON)  # {field: [old, new]}


class Checklist(Base):
    """A completeness target (e.g. a date/mint run) tracked as a slot list."""

    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    slots: Mapped[list["ChecklistSlot"]] = relationship(
        back_populates="checklist", cascade="all, delete-orphan", order_by="ChecklistSlot.position"
    )


class ChecklistSlot(Base):
    __tablename__ = "checklist_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checklist_id: Mapped[int] = mapped_column(
        ForeignKey("checklists.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    filled: Mapped[bool] = mapped_column(Boolean, default=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="SET NULL")
    )

    checklist: Mapped[Checklist] = relationship(back_populates="slots")


class AppSetting(Base):
    """Key/value application settings (display currency, source keys, toggles).
    Values are JSON so strings, numbers, and booleans store uniformly."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict | str | int | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExchangeRate(Base):
    """Cache of currency exchange rates, refreshed on demand (like spot prices)."""

    __tablename__ = "exchange_rates"

    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    source: Mapped[str] = mapped_column(String(100))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpotPrice(Base):
    """Cache of precious-metal spot prices (USD per gram), refreshed on demand."""

    __tablename__ = "spot_prices"

    metal: Mapped[str] = mapped_column(String(20), primary_key=True)
    price_per_gram: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    source: Mapped[str] = mapped_column(String(100))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriceEstimate(Base):
    __tablename__ = "price_estimates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(100))
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))  # null for manual entries
    sample_size: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[Item] = relationship(back_populates="estimates")
