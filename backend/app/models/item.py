import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, with_loader_criteria

from app.db import Base

ItemType = Enum("coin", "note", name="item_type", native_enum=False, length=10)
ItemStatus = Enum("owned", "sold", "wishlist", name="item_status", native_enum=False, length=10)
StrikeType = Enum("business", "proof", "specimen", name="strike_type", native_enum=False, length=10)
PhotoAngle = Enum(
    "obverse", "reverse", "edge", "other", name="photo_angle", native_enum=False, length=10
)

item_tags = Table(
    "item_tags",
    Base.metadata,
    Column("item_id", Uuid, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

# A document can belong to several items (one invoice for a lot of coins).
item_documents = Table(
    "item_documents",
    Base.metadata,
    Column("item_id", Uuid, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
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
    __table_args__ = (
        UniqueConstraint("import_source", "import_key", name="uq_items_import_origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(ItemType, index=True)
    status: Mapped[str] = mapped_column(ItemStatus, default="owned", index=True)
    country: Mapped[str] = mapped_column(String(100), index=True)
    denomination: Mapped[str] = mapped_column(String(100))
    # Null for an undated piece with no attributed year; `year_nd` says the
    # piece carries no date, and then `year` is the attributed one, if any.
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    year_nd: Mapped[bool] = mapped_column(Boolean, default=False)
    mint_mark: Mapped[str | None] = mapped_column(String(20))
    series: Mapped[str | None] = mapped_column(String(200))
    variety: Mapped[str | None] = mapped_column(String(200))  # die variety, overdate…
    strike: Mapped[str] = mapped_column(StrikeType, default="business")
    composition: Mapped[str | None] = mapped_column(String(100))
    weight_g: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))  # 31.1035 g is a troy ounce
    fineness: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))  # e.g. 0.9000
    diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    edge: Mapped[str | None] = mapped_column(String(100))  # reeded, plain, lettered…
    shape: Mapped[str | None] = mapped_column(String(50))
    mintage: Mapped[int | None] = mapped_column(BigInteger)
    die_axis: Mapped[int | None] = mapped_column(SmallInteger)  # degrees; 0 medal, 180 coin
    # The date as written on the piece, when it isn't Gregorian (services/calendars.py).
    struck_calendar: Mapped[str | None] = mapped_column(String(20))
    struck_year: Mapped[int | None] = mapped_column(Integer)
    struck_era: Mapped[str | None] = mapped_column(String(20))  # Japanese dates only
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"))
    cert_service: Mapped[str | None] = mapped_column(String(50))  # PCGS, NGC, PMG…
    cert_number: Mapped[str | None] = mapped_column(String(50))
    grade_plus: Mapped[bool] = mapped_column(Boolean, default=False)
    grade_star: Mapped[bool] = mapped_column(Boolean, default=False)  # NGC/PMG ★
    designations: Mapped[list[str] | None] = mapped_column(JSON)  # DCAM, RD, EPQ…
    grade_details: Mapped[str | None] = mapped_column(String(100))  # the problem, if any
    cac_sticker: Mapped[str | None] = mapped_column(String(10))  # green | gold
    # PCGS population report: graded at this grade, and higher. The server
    # stamps `population_as_of` whenever either changes.
    pcgs_population: Mapped[int | None] = mapped_column(Integer)
    pcgs_pop_higher: Mapped[int | None] = mapped_column(Integer)
    population_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Banknotes
    serial_number: Mapped[str | None] = mapped_column(String(50))
    prefix_block: Mapped[str | None] = mapped_column(String(50))
    signatures: Mapped[str | None] = mapped_column(String(200))
    issuer: Mapped[str | None] = mapped_column(String(200))  # issuing bank or authority
    replacement_note: Mapped[bool] = mapped_column(Boolean, default=False)  # star/replacement
    charter_number: Mapped[str | None] = mapped_column(String(10))  # National Bank Notes
    bank_city: Mapped[str | None] = mapped_column(String(100))
    bank_state: Mapped[str | None] = mapped_column(String(50))
    plate_position: Mapped[str | None] = mapped_column(String(20))
    # Fancy-serial traits as `,radar,binary,`, kept in step with the serial
    # number by the server (services/serials.py); never taken from the client.
    serial_traits: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    acquisition_date: Mapped[date | None] = mapped_column(Date)
    acquisition_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    acquisition_fees: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )  # premium, shipping, tax
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    acquired_from: Mapped[str | None] = mapped_column(String(200))
    storage_location: Mapped[str | None] = mapped_column(String(200))
    sold_date: Mapped[date | None] = mapped_column(Date)
    sold_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # gross, before fees
    sold_fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # commission, listing fees
    sold_to: Mapped[str | None] = mapped_column(String(200))  # venue or buyer
    # The metal's spot price per troy ounce on the day it was bought, in
    # `currency`. `spot_at_purchase_source` is server-set: "manual" for a
    # figure typed in, "auto" for one services/stack.py looked up.
    spot_at_purchase: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    spot_at_purchase_source: Mapped[str | None] = mapped_column(String(10))
    # Wish list: what to pay at most (in `currency`), and 1 high / 2 medium / 3 low.
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    set_id: Mapped[int | None] = mapped_column(ForeignKey("sets.id", ondelete="SET NULL"))
    custom_fields: Mapped[dict | None] = mapped_column(JSON)  # user-defined key→value
    notes: Mapped[str | None] = mapped_column(Text)
    # Where an imported item came from, so importing the same source again
    # skips it: e.g. ("numista", "<collected item id>"). Null for items entered here.
    import_source: Mapped[str | None] = mapped_column(String(30))
    import_key: Mapped[str | None] = mapped_column(String(300))
    # Set while the item is in the trash. Trashed items are hidden from every
    # ORM query unless it asks for them (see `_hide_trashed` below).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
    documents: Mapped[list["Document"]] = relationship(
        secondary=item_documents,
        back_populates="items",
        order_by="Document.created_at.desc()",
    )
    comparables: Mapped[list["Comparable"]] = relationship(
        cascade="all, delete-orphan",
        order_by="Comparable.sold_on.desc(), Comparable.id.desc()",
    )

    @property
    def year_label(self) -> str:
        """The year as catalogues write it: "1922", "ND", or "ND (1922)"."""
        if self.year is None:
            return "ND"
        return f"ND ({self.year})" if self.year_nd else str(self.year)

    @property
    def label(self) -> str:
        """Short display label, e.g. `United States 25 cents 1932 "D"`."""
        parts = [self.country, self.denomination, self.year_label]
        if self.mint_mark:
            parts.append(f'"{self.mint_mark}"')
        return " ".join(parts)

    @property
    def grade_code(self) -> str | None:
        """The grade code as a holder shows it: on the Sheldon scale a proof or
        specimen reads PR-/SP- with the same number, and a plus grade adds "+"."""
        if self.grade is None:
            return None
        code = self.grade.code
        if self.grade.scale == "sheldon" and self.strike in ("proof", "specimen"):
            code = f"{'PR' if self.strike == 'proof' else 'SP'}-{self.grade.rank}"
        return f"{code}+" if self.grade_plus else code

    @property
    def grade_label(self) -> str | None:
        """The full grade, e.g. `PR-69 DCAM ★`, `MS-64+ RD`, `VF-20 Details (Cleaned)`."""
        code = self.grade_code
        if code is None:
            return None
        parts = [code, *(self.designations or [])]
        if self.grade_star:
            parts.append("★")
        label = " ".join(parts)
        return f"{label} Details ({self.grade_details})" if self.grade_details else label

    @property
    def target_gap(self) -> Decimal | None:
        """The newest estimate less the target price; zero or less means the
        target is reached. None without both, or when their currencies differ
        (nothing is converted)."""
        if self.target_price is None or not self.estimates:
            return None
        latest = self.estimates[0]
        if latest.currency != self.currency:
            return None
        return Decimal(latest.estimated_value) - Decimal(self.target_price)

    @property
    def target_reached(self) -> bool:
        gap = self.target_gap
        return gap is not None and gap <= 0

    @property
    def cost_basis(self) -> Decimal | None:
        """Price paid plus fees, shipping, and tax: what gains are measured against."""
        if self.acquisition_price is None:
            return None
        return Decimal(self.acquisition_price) + Decimal(self.acquisition_fees or 0)

    @property
    def sale_proceeds(self) -> Decimal | None:
        """Sold price less selling fees."""
        if self.sold_price is None:
            return None
        return Decimal(self.sold_price) - Decimal(self.sold_fees or 0)

    @property
    def fine_oz(self) -> Decimal | None:
        """Fine troy ounces in the row: weight × fineness × quantity. None
        unless the composition names a precious metal and both are known,
        which is also what puts a piece in the bullion stack."""
        # Imported here: the pricing service imports this module.
        from app.services.pricing import TROY_OUNCE_G, detect_metal, effective_fineness

        if detect_metal(self.composition) is None or self.weight_g is None:
            return None
        fineness = effective_fineness(self)
        if fineness is None:
            return None
        return Decimal(self.weight_g) * fineness * self.quantity / TROY_OUNCE_G

    @property
    def premium_paid_pct(self) -> Decimal | None:
        """How far the cost basis ran over the metal's value on the purchase
        day, as a percentage. Computed in the item's own currency, so nothing
        is converted. None without a purchase-day spot price or a cost."""
        oz = self.fine_oz
        cost = self.cost_basis
        if oz is None or cost is None or self.spot_at_purchase is None:
            return None
        at_spot = oz * Decimal(self.spot_at_purchase)
        if at_spot <= 0:
            return None
        return (cost - at_spot) / at_spot * 100


class Document(Base):
    """An attached file: a receipt, certificate of authenticity, invoice…
    Stored under DOCUMENT_DIR (never the public photo volume) and served only
    through the API. Shared between items via `item_documents`."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(30), default="other")
    title: Mapped[str] = mapped_column(String(200))
    doc_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))  # as uploaded, for downloads
    content_type: Mapped[str] = mapped_column(String(50))  # detected, never the client's
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    pages: Mapped[int | None] = mapped_column(Integer)  # PDFs
    file_key: Mapped[str] = mapped_column(String(300))
    thumb_key: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list[Item]] = relationship(
        secondary=item_documents, back_populates="documents", order_by=Item.country
    )

    @property
    def has_thumb(self) -> bool:
        return self.thumb_key is not None


@event.listens_for(Session, "do_orm_execute")
def _hide_trashed(state) -> None:
    """Keep trashed items out of every ORM query (lists, stats, reports,
    exports, refreshes, relationships) unless the statement opts in with
    `.execution_options(include_deleted=True)`. One filter here instead of a
    `deleted_at IS NULL` in every query, where one missed spot would leak
    trashed items into the totals. (Relationship and column loads inherit the
    criteria from the statement that loaded their parent.)"""
    if (
        state.is_select
        and not state.is_column_load
        and not state.is_relationship_load
        and not state.execution_options.get("include_deleted", False)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(Item, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
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
    # What fills a generated checklist's slots: owned items carrying this
    # catalogue reference, or of this country and denomination.
    match_catalog: Mapped[str | None] = mapped_column(String(50))
    match_ref: Mapped[str | None] = mapped_column(String(100))
    match_country: Mapped[str | None] = mapped_column(String(100))
    match_denomination: Mapped[str | None] = mapped_column(String(100))

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
    filled: Mapped[bool] = mapped_column(Boolean, default=False)  # ticked by hand
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="SET NULL")
    )
    # Set on generated slots; an owned item of the same year and mint fills it.
    year: Mapped[int | None] = mapped_column(Integer)
    mint_mark: Mapped[str | None] = mapped_column(String(20))

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


class SourceCache(Base):
    """Cached raw responses from external price sources, keyed by source and
    request. Free-tier quotas are small (Numista: 2,000/month), so repeated
    estimates for the same item must not cost a request."""

    __tablename__ = "source_cache"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
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
    # What the source returned that produced this value (or a manual note).
    details: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[Item] = relationship(back_populates="estimates")


class Comparable(Base):
    """One sale of a piece like this item, in the sales log that the `comps`
    estimate takes its median from. Logged by hand, or fetched from Numista's
    auction records (`source = "numista"`, deduplicated by `external_id`)."""

    __tablename__ = "comparables"
    __table_args__ = (UniqueConstraint("item_id", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    sold_on: Mapped[date] = mapped_column(Date)
    venue: Mapped[str] = mapped_column(String(200))  # eBay, Heritage, a dealer…
    title: Mapped[str | None] = mapped_column(String(300))  # sale or listing title
    lot: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(1000))
    grade: Mapped[str | None] = mapped_column(String(100))  # as the lot described it
    grade_bucket: Mapped[str | None] = mapped_column(String(5))  # Numista's g…unc, if known
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # per piece
    currency: Mapped[str] = mapped_column(String(3))
    premium_included: Mapped[bool | None] = mapped_column(Boolean)  # null = unknown
    fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # premium/shipping on top
    included: Mapped[bool] = mapped_column(Boolean, default=True)  # counts toward comps
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | numista
    external_id: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def total(self) -> Decimal:
        """What the buyer paid: the price plus any fees recorded on top."""
        return Decimal(self.price) + Decimal(self.fees or 0)


class EstimateAttempt(Base):
    """The latest attempt to price an item from each automatic source. A
    failed fetch or an upstream "can't price this" leaves no estimate behind,
    so this is what lets the coverage report say why an item has none."""

    __tablename__ = "estimate_attempts"

    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(20))  # ok | not_applicable | unavailable
    message: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
