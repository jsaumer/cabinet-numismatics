import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ItemType = Enum("coin", "note", name="item_type", native_enum=False, length=10)
PhotoAngle = Enum(
    "obverse", "reverse", "edge", "other", name="photo_angle", native_enum=False, length=10
)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(ItemType, index=True)
    country: Mapped[str] = mapped_column(String(100), index=True)
    denomination: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer, index=True)
    mint_mark: Mapped[str | None] = mapped_column(String(20))
    series: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    acquisition_date: Mapped[date | None] = mapped_column(Date)
    acquisition_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    photos: Mapped[list["ItemPhoto"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemPhoto.uploaded_at"
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
    thumb_key: Mapped[str | None] = mapped_column(String(300))  # generated in Phase 2
    angle: Mapped[str | None] = mapped_column(PhotoAngle)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[Item] = relationship(back_populates="photos")


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
