"""Request and response schemas.

Field descriptions here end up in the OpenAPI spec (/docs, /openapi.json).
Write them carefully: they're also exactly what you'll feed an AI agent as
tool documentation later.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models import (
    CustomerTier,
    MessageAuthor,
    OrderStatus,
    ProductCategory,
    RefundReason,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

Cents = Annotated[int, Field(ge=0, description="Amount in cents (USD). 1999 = $19.99")]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Total matching records across all pages")
    page: int
    page_size: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pages(self) -> int:
        return max((self.total + self.page_size - 1) // self.page_size, 1)


# ---------- Customers ----------


class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    tier: CustomerTier = CustomerTier.standard


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    tier: CustomerTier | None = None


class CustomerOut(CustomerBase, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class CustomerDetail(CustomerOut):
    order_count: int
    lifetime_value_cents: int = Field(description="Sum of non-cancelled order totals minus refunds")
    open_ticket_count: int


# ---------- Products ----------


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    category: ProductCategory
    price_cents: Cents
    stock: int = Field(default=0, ge=0)
    is_active: bool = True


class ProductCreate(ProductBase):
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9-]+$")


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: ProductCategory | None = None
    price_cents: Cents | None = None
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductOut(ProductBase, ORMModel):
    id: int
    sku: str
    created_at: datetime
    updated_at: datetime


# ---------- Orders ----------


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    customer_id: int
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)
    shipping_address: str = Field(min_length=5, max_length=300)


class OrderItemOut(ORMModel):
    id: int
    product_id: int
    product_name: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int


class RefundCreate(BaseModel):
    amount_cents: int = Field(
        gt=0,
        description="Amount to refund in cents. Must not exceed the order's refundable_cents.",
    )
    reason: RefundReason
    note: str = Field(default="", max_length=500)


class RefundOut(ORMModel):
    id: int
    order_id: int
    amount_cents: int
    reason: RefundReason
    note: str
    created_at: datetime


class OrderSummary(ORMModel):
    id: int
    number: str
    customer_id: int
    status: OrderStatus
    total_cents: int
    currency: str
    placed_at: datetime
    item_count: int = 0


class OrderOut(ORMModel):
    id: int
    number: str
    customer_id: int
    status: OrderStatus
    total_cents: int
    refunded_cents: int
    refundable_cents: int
    currency: str
    shipping_address: str
    tracking_number: str | None
    placed_at: datetime
    shipped_at: datetime | None
    delivered_at: datetime | None
    items: list[OrderItemOut]
    refunds: list[RefundOut]
    customer: CustomerOut


class OrderStatusUpdate(BaseModel):
    status: OrderStatus = Field(
        description=(
            "Target status. Allowed transitions: pending->paid, paid->shipped, "
            "shipped->delivered. Use the cancel and refund endpoints for those flows."
        )
    )
    tracking_number: str | None = Field(default=None, max_length=40)


# ---------- Tickets ----------


class TicketMessageCreate(BaseModel):
    author: MessageAuthor = MessageAuthor.agent
    body: str = Field(min_length=1, max_length=5000)


class TicketMessageOut(ORMModel):
    id: int
    author: MessageAuthor
    body: str
    created_at: datetime


class TicketCreate(BaseModel):
    customer_id: int
    order_id: int | None = None
    subject: str = Field(min_length=3, max_length=200)
    category: TicketCategory = TicketCategory.other
    priority: TicketPriority = TicketPriority.medium
    message: str = Field(min_length=1, max_length=5000, description="The customer's first message")


class TicketUpdate(BaseModel):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    assignee: str | None = Field(default=None, max_length=80)


class TicketSummary(ORMModel):
    id: int
    customer_id: int
    order_id: int | None
    subject: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    assignee: str | None
    created_at: datetime
    updated_at: datetime


class TicketOut(TicketSummary):
    customer: CustomerOut
    messages: list[TicketMessageOut]


# ---------- Stats ----------


class DailyRevenue(BaseModel):
    date: str
    revenue_cents: int
    orders: int


class StatsOverview(BaseModel):
    customers: int
    products: int
    orders: int
    revenue_cents: int = Field(description="Non-cancelled order totals minus refunds")
    refunded_cents: int
    open_tickets: int
    orders_by_status: dict[str, int]
    tickets_by_status: dict[str, int]
    revenue_last_30_days: list[DailyRevenue]
    low_stock_products: list[ProductOut]


# ---------- Admin ----------


class SeedRequest(BaseModel):
    seed: int = Field(default=42, description="Same seed -> exactly the same data every time")
    customers: int = Field(default=60, ge=1, le=5000)
    products: int = Field(default=40, ge=1, le=5000)
    orders: int = Field(default=250, ge=0, le=20000)
    tickets: int = Field(default=60, ge=0, le=5000)
    reset: bool = Field(default=True, description="Wipe existing data first")


class SeedResult(BaseModel):
    seed: int
    customers: int
    products: int
    orders: int
    tickets: int
    refunds: int
    scenarios: list[str] = Field(description="Hand-crafted records useful for testing agents")
