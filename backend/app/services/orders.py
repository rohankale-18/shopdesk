"""Order business logic, kept out of the routers so it can be reused
(e.g. by an agent's tools calling Python directly instead of over HTTP)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    Refund,
    RefundReason,
    utcnow,
)

# Forward-only lifecycle. Cancel and refund have their own endpoints.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.pending: {OrderStatus.paid},
    OrderStatus.paid: {OrderStatus.shipped},
    OrderStatus.shipped: {OrderStatus.delivered},
}

CANCELLABLE = {OrderStatus.pending, OrderStatus.paid}
REFUNDABLE = {OrderStatus.paid, OrderStatus.shipped, OrderStatus.delivered}


def next_order_number(db: Session) -> str:
    max_id = db.scalar(select(func.max(Order.id))) or 0
    return f"ORD-{max_id + 1:08d}"


def get_order_or_404(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise NotFoundError(
            f"Order {order_id} not found.",
            details={"hint": "Use GET /api/orders?q=ORD-... or ?customer_id=... to find it."},
        )
    return order


def create_order(
    db: Session,
    *,
    customer_id: int,
    items: list[tuple[int, int]],
    shipping_address: str,
) -> Order:
    if not db.get(Customer, customer_id):
        raise NotFoundError(f"Customer {customer_id} not found.")

    # Merge duplicate product lines so stock checks are correct.
    qty_by_product: dict[int, int] = {}
    for product_id, qty in items:
        qty_by_product[product_id] = qty_by_product.get(product_id, 0) + qty

    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(qty_by_product))).all()}

    problems = []
    for product_id, qty in qty_by_product.items():
        p = products.get(product_id)
        if p is None:
            problems.append({"product_id": product_id, "problem": "not_found"})
        elif not p.is_active:
            problems.append({"product_id": product_id, "problem": "inactive"})
        elif p.stock < qty:
            problems.append(
                {
                    "product_id": product_id,
                    "problem": "insufficient_stock",
                    "requested": qty,
                    "available": p.stock,
                }
            )
    if problems:
        raise BusinessRuleError("Some items can't be ordered.", details={"items": problems})

    order = Order(
        number=next_order_number(db),
        customer_id=customer_id,
        status=OrderStatus.pending,
        shipping_address=shipping_address,
    )
    total = 0
    for product_id, qty in qty_by_product.items():
        p = products[product_id]
        p.stock -= qty
        order.items.append(
            OrderItem(
                product_id=p.id,
                product_name=p.name,
                unit_price_cents=p.price_cents,
                quantity=qty,
            )
        )
        total += p.price_cents * qty
    order.total_cents = total

    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def transition_order(
    db: Session, order: Order, target: OrderStatus, tracking_number: str | None = None
) -> Order:
    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if target not in allowed:
        raise BusinessRuleError(
            f"Can't move order {order.number} from '{order.status}' to '{target}'.",
            details={
                "current_status": str(order.status),
                "allowed_targets": sorted(str(s) for s in allowed),
                "hint": "Use POST /cancel to cancel, or POST /refunds to refund.",
            },
        )
    now = utcnow()
    if target == OrderStatus.shipped:
        order.shipped_at = now
        order.tracking_number = tracking_number or f"TRK{order.id:010d}"
    elif target == OrderStatus.delivered:
        order.delivered_at = now
    order.status = target
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order: Order) -> Order:
    if order.status not in CANCELLABLE:
        raise BusinessRuleError(
            f"Order {order.number} is '{order.status}' and can't be cancelled.",
            details={
                "cancellable_statuses": sorted(str(s) for s in CANCELLABLE),
                "hint": "Shipped or delivered orders should be refunded instead.",
            },
        )
    for item in order.items:  # put stock back
        product = db.get(Product, item.product_id)
        if product:
            product.stock += item.quantity
    order.status = OrderStatus.cancelled
    db.commit()
    db.refresh(order)
    return order


def refund_order(
    db: Session, order: Order, *, amount_cents: int, reason: RefundReason, note: str = ""
) -> Refund:
    if order.status not in REFUNDABLE:
        raise BusinessRuleError(
            f"Order {order.number} is '{order.status}' and can't be refunded.",
            details={"refundable_statuses": sorted(str(s) for s in REFUNDABLE)},
        )
    if amount_cents > order.refundable_cents:
        raise BusinessRuleError(
            f"Refund of {amount_cents} cents exceeds what's refundable on {order.number}.",
            details={
                "requested_cents": amount_cents,
                "refundable_cents": order.refundable_cents,
                "already_refunded_cents": order.refunded_cents,
            },
        )
    refund = Refund(order=order, amount_cents=amount_cents, reason=reason, note=note)
    db.add(refund)
    db.flush()
    if order.refundable_cents == 0:
        order.status = OrderStatus.refunded
    db.commit()
    db.refresh(refund)
    return refund
