"""Database models.

Money is stored as integer cents (like Stripe) to avoid floating-point errors.
Timestamps are stored as timezone-aware UTC datetimes.
"""

import enum
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stores datetimes as UTC and always returns timezone-aware values.

    SQLite has no timezone support, so without this, values read back are naive.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class CustomerTier(StrEnum):
    standard = "standard"
    gold = "gold"
    platinum = "platinum"


class ProductCategory(StrEnum):
    electronics = "electronics"
    home = "home"
    apparel = "apparel"
    books = "books"
    sports = "sports"
    beauty = "beauty"


class OrderStatus(StrEnum):
    pending = "pending"  # placed, not yet paid
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"  # fully refunded


class TicketStatus(StrEnum):
    open = "open"
    pending = "pending"  # waiting on the customer
    resolved = "resolved"
    closed = "closed"


class TicketPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketCategory(StrEnum):
    billing = "billing"
    shipping = "shipping"
    product = "product"
    account = "account"
    other = "other"


class RefundReason(StrEnum):
    damaged = "damaged"
    not_received = "not_received"
    wrong_item = "wrong_item"
    not_as_described = "not_as_described"
    changed_mind = "changed_mind"
    other = "other"


class MessageAuthor(StrEnum):
    customer = "customer"
    agent = "agent"  # a human or AI support agent
    system = "system"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    # native_enum=False stores enums as VARCHAR + CHECK, which works everywhere.
    return Enum(e, name=name, native_enum=False, validate_strings=True, length=32)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    city: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(80))
    tier: Mapped[CustomerTier] = mapped_column(
        _enum(CustomerTier, "customer_tier"), default=CustomerTier.standard
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="customer")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="ck_product_price_nonneg"),
        CheckConstraint("stock >= 0", name="ck_product_stock_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[ProductCategory] = mapped_column(_enum(ProductCategory, "product_category"))
    price_cents: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # ORD-00001234
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        _enum(OrderStatus, "order_status"), default=OrderStatus.pending, index=True
    )
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    shipping_address: Mapped[str] = mapped_column(String(300), default="")
    tracking_number: Mapped[str | None] = mapped_column(String(40))
    placed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )
    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def refunded_cents(self) -> int:
        return sum(r.amount_cents for r in self.refunds)

    @property
    def refundable_cents(self) -> int:
        return max(self.total_cents - self.refunded_cents, 0)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_item_qty_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    # Snapshot name and price at purchase time, so later product edits don't rewrite history.
    product_name: Mapped[str] = mapped_column(String(200))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")

    @property
    def line_total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_refund_amount_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[RefundReason] = mapped_column(_enum(RefundReason, "refund_reason"))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="refunds")


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[TicketStatus] = mapped_column(
        _enum(TicketStatus, "ticket_status"), default=TicketStatus.open, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        _enum(TicketPriority, "ticket_priority"), default=TicketPriority.medium
    )
    category: Mapped[TicketCategory] = mapped_column(
        _enum(TicketCategory, "ticket_category"), default=TicketCategory.other
    )
    assignee: Mapped[str | None] = mapped_column(String(80))

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    order: Mapped[Order | None] = relationship()
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at",
        lazy="selectin",
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author: Mapped[MessageAuthor] = mapped_column(_enum(MessageAuthor, "message_author"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")
