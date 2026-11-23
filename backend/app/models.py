"""Database models.

Money is stored as integer cents (like Stripe) to avoid floating-point errors.
Timestamps are stored as timezone-aware UTC datetimes.
"""

import enum
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
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
    # A reply waiting in the ticket's reply box (put there by an approved assistant draft).
    # Cleared when an agent replies.
    draft_reply: Mapped[str | None] = mapped_column(Text)

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


# ---------- AI chat ----------


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class ChatConversation(TimestampMixin, Base):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    # The ticket it was opened from ("Ask about this ticket"). Not a foreign key: chats survive a
    # reseed, which recreates the tickets, so the id may then point at a different ticket or none.
    ticket_id: Mapped[int | None] = mapped_column(Integer)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )
    traces: Mapped[list["ChatTrace"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    actions: Mapped[list["ChatAction"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="ChatAction.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole, "chat_role"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
    # The trace of the reply that produced this message (assistant messages only).
    trace: Mapped["ChatTrace | None"] = relationship(viewonly=True, lazy="selectin")

    @property
    def tool_calls(self) -> list["ChatToolRun"]:
        """Tools the assistant ran for this message (shown as chips)."""
        return self.trace.tool_runs if self.trace else []

    @property
    def trace_id(self) -> int | None:
        return self.trace.id if self.trace else None


class ChatTrace(Base):
    """Everything behind one assistant reply: each model call and tool run, with timings and tokens.

    Saved for every reply, including ones that failed or were stopped (those have no message).
    """

    __tablename__ = "chat_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))  # "ok", "error" or "stopped"
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)  # until the first word reached the user
    steps: Mapped[int] = mapped_column(Integer)  # model calls (passes round the loop)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)  # includes reasoning tokens
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)

    model_calls: Mapped[list["ChatModelCall"]] = relationship(
        cascade="all, delete-orphan", order_by="ChatModelCall.step"
    )
    tool_runs: Mapped[list["ChatToolRun"]] = relationship(
        cascade="all, delete-orphan", order_by="ChatToolRun.id", lazy="selectin"
    )


class ChatModelCall(Base):
    """One call to the model: one pass round the agent loop."""

    __tablename__ = "chat_model_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[int] = mapped_column(ForeignKey("chat_traces.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer)
    request: Mapped[str] = mapped_column(Text)  # JSON: the exact messages, tools offered, tool_choice
    response_text: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")  # JSON: the tools it asked for
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Groq's own timings: waiting in its queue, reading the input, writing the output
    queue_ms: Mapped[int | None] = mapped_column(Integer)
    input_ms: Mapped[int | None] = mapped_column(Integer)
    output_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)


class ChatToolRun(Base):
    """One tool the assistant ran."""

    __tablename__ = "chat_tool_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[int] = mapped_column(ForeignKey("chat_traces.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer)  # the model call that asked for it
    name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[str] = mapped_column(Text)  # JSON, exactly as the model sent it
    result: Mapped[str] = mapped_column(Text)  # JSON, exactly as the model received it
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer)


class ActionStatus(StrEnum):
    pending = "pending"  # proposed by the assistant, waiting for a person
    done = "done"  # approved and carried out
    rejected = "rejected"
    failed = "failed"  # approved, but the store's rules refused it (e.g. already refunded)


class ChatAction(Base):
    """Something the assistant proposed to change. Nothing happens until a person approves it.

    The arguments are checked again on approval, because the data may have changed since.
    Orders are kept by number, not id: chats survive a reseed, and the check then fails cleanly.
    """

    __tablename__ = "chat_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # create_refund, cancel_order, draft_ticket_reply
    arguments: Mapped[str] = mapped_column(Text)  # JSON, already checked (amounts in cents)
    summary: Mapped[str] = mapped_column(String(300))  # the card's title, e.g. "Refund $199.99 on ..."
    status: Mapped[ActionStatus] = mapped_column(
        _enum(ActionStatus, "action_status"), default=ActionStatus.pending
    )
    outcome: Mapped[str | None] = mapped_column(Text)  # what happened, or why it failed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
