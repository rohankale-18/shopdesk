from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.core.pagination import PageDep, apply_sort, paginate
from app.db import get_db
from app.models import Order, OrderStatus
from app.schemas import (
    OrderCreate,
    OrderOut,
    OrderStatusUpdate,
    OrderSummary,
    Page,
    RefundCreate,
    RefundOut,
)
from app.services import orders as svc

router = APIRouter(prefix="/api/orders", tags=["orders"])
DB = Annotated[Session, Depends(get_db)]

SORTABLE = {"placed_at": Order.placed_at, "total": Order.total_cents, "id": Order.id}


def _summary(o: Order) -> OrderSummary:
    return OrderSummary.model_validate(o).model_copy(update={"item_count": len(o.items)})


@router.get("", response_model=Page[OrderSummary])
def list_orders(
    db: DB,
    pg: PageDep,
    q: Annotated[str | None, Query(description="Order number, e.g. ORD-00000042")] = None,
    customer_id: int | None = None,
    status_: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    placed_from: datetime | None = None,
    placed_to: datetime | None = None,
    sort: Annotated[str | None, Query(description="placed_at, total, id; prefix - for desc")] = None,
):
    """List orders. `status` can be repeated: ?status=paid&status=shipped"""
    stmt = select(Order)
    if q:
        stmt = stmt.where(Order.number.ilike(f"%{q.strip()}%"))
    if customer_id:
        stmt = stmt.where(Order.customer_id == customer_id)
    if status_:
        stmt = stmt.where(Order.status.in_(status_))
    if placed_from:
        stmt = stmt.where(Order.placed_at >= placed_from)
    if placed_to:
        stmt = stmt.where(Order.placed_at <= placed_to)
    stmt = apply_sort(stmt, sort, SORTABLE, "-placed_at")
    page = paginate(db, stmt, pg)
    page["items"] = [_summary(o) for o in page["items"]]
    return page


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(db: DB, body: OrderCreate):
    """Place an order. Checks stock, snapshots prices and decrements inventory.
    New orders start as 'pending'."""
    return svc.create_order(
        db,
        customer_id=body.customer_id,
        items=[(i.product_id, i.quantity) for i in body.items],
        shipping_address=body.shipping_address,
    )


@router.get("/by-number/{number}", response_model=OrderOut)
def get_order_by_number(db: DB, number: str):
    """Look up an order by its human-facing number (e.g. ORD-00000042)."""
    order = db.scalar(
        select(Order).options(selectinload(Order.customer)).where(Order.number == number.upper())
    )
    if not order:
        raise NotFoundError(
            f"No order with number {number}.",
            details={"hint": "Order numbers look like ORD-00000042."},
        )
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(db: DB, order_id: int):
    """Full order details: items, refunds, customer, and how much is still refundable."""
    return svc.get_order_or_404(db, order_id)


@router.post("/{order_id}/status", response_model=OrderOut)
def update_order_status(db: DB, order_id: int, body: OrderStatusUpdate):
    """Move an order forward: pending -> paid -> shipped -> delivered."""
    order = svc.get_order_or_404(db, order_id)
    return svc.transition_order(db, order, body.status, body.tracking_number)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(db: DB, order_id: int):
    """Cancel a pending or paid order and restock its items."""
    order = svc.get_order_or_404(db, order_id)
    return svc.cancel_order(db, order)


@router.get("/{order_id}/refunds", response_model=list[RefundOut])
def list_refunds(db: DB, order_id: int):
    return svc.get_order_or_404(db, order_id).refunds


@router.post("/{order_id}/refunds", response_model=RefundOut, status_code=status.HTTP_201_CREATED)
def create_refund(db: DB, order_id: int, body: RefundCreate):
    """Refund part or all of an order. The total refunded can never exceed the
    order total. When fully refunded, the order status becomes 'refunded'."""
    order = svc.get_order_or_404(db, order_id)
    return svc.refund_order(db, order, amount_cents=body.amount_cents, reason=body.reason, note=body.note)
