"""Store-wide numbers: used by the dashboard and by the assistant's tools."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, Order, OrderStatus, Product, Refund, Ticket, TicketStatus
from app.schemas import DailyRevenue, ProductOut, StatsOverview

# One definition of "low stock" for the dashboard and the assistant: 1 to LOW_STOCK left.
LOW_STOCK = 5


def stock_status(product: Product) -> str:
    """'not_for_sale', 'out_of_stock', 'low' or 'in_stock'."""
    if not product.is_active:
        return "not_for_sale"
    if product.stock == 0:
        return "out_of_stock"
    return "low" if product.stock <= LOW_STOCK else "in_stock"


def store_overview(db: Session) -> StatsOverview:
    """Headline numbers for the dashboard (and the assistant's get_store_overview tool)."""
    count = lambda model: db.scalar(select(func.count()).select_from(model)) or 0  # noqa: E731

    gross = db.scalar(
        select(func.coalesce(func.sum(Order.total_cents), 0)).where(Order.status != OrderStatus.cancelled)
    )
    refunded = db.scalar(select(func.coalesce(func.sum(Refund.amount_cents), 0)))

    orders_by_status = {s.value: 0 for s in OrderStatus}
    for s, n in db.execute(select(Order.status, func.count()).group_by(Order.status)):
        orders_by_status[str(s)] = n

    tickets_by_status = {s.value: 0 for s in TicketStatus}
    for s, n in db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)):
        tickets_by_status[str(s)] = n

    today = datetime.now(UTC).date()
    start = today - timedelta(days=29)
    buckets = {start + timedelta(days=i): [0, 0] for i in range(30)}
    rows = db.execute(
        select(Order.placed_at, Order.total_cents).where(
            Order.placed_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
            Order.status != OrderStatus.cancelled,
        )
    )
    for placed_at, total in rows:
        d = placed_at.date()
        if d in buckets:
            buckets[d][0] += total
            buckets[d][1] += 1

    low_stock = db.scalars(
        select(Product)
        .where(Product.is_active.is_(True), Product.stock <= LOW_STOCK)
        .order_by(Product.stock.asc(), Product.name.asc())
        .limit(8)
    ).all()

    return StatsOverview(
        customers=count(Customer),
        products=count(Product),
        orders=count(Order),
        revenue_cents=(gross or 0) - (refunded or 0),
        refunded_cents=refunded or 0,
        open_tickets=tickets_by_status["open"] + tickets_by_status["pending"],
        orders_by_status=orders_by_status,
        tickets_by_status=tickets_by_status,
        revenue_last_30_days=[
            DailyRevenue(date=d.isoformat(), revenue_cents=v[0], orders=v[1]) for d, v in buckets.items()
        ],
        low_stock_products=[ProductOut.model_validate(p) for p in low_stock],
    )


@dataclass(frozen=True)
class SalesTotals:
    orders: int  # placed in the period, cancelled ones excluded
    revenue_cents: int  # of those orders, before refunds
    cancelled_orders: int  # placed in the period, then cancelled
    refunds: int  # refunds issued in the period (for orders from any date)
    refunded_cents: int


def sales_totals(db: Session, start: date, end: date) -> SalesTotals:
    """Sales from `start` to `end`, both inclusive (UTC).

    Cancelled orders don't count towards orders or revenue, the same rule as the dashboard's
    revenue chart. Refunds are counted by the day they were issued.
    """
    since = datetime.combine(start, time.min, tzinfo=UTC)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    placed = (Order.placed_at >= since, Order.placed_at < until)
    orders, revenue = db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_cents), 0)).where(
            *placed, Order.status != OrderStatus.cancelled
        )
    ).one()
    cancelled = db.scalar(select(func.count()).where(*placed, Order.status == OrderStatus.cancelled))
    refunds, refunded = db.execute(
        select(func.count(), func.coalesce(func.sum(Refund.amount_cents), 0)).where(
            Refund.created_at >= since, Refund.created_at < until
        )
    ).one()
    return SalesTotals(orders, revenue, cancelled or 0, refunds, refunded)
