from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PageDep, apply_sort, paginate
from app.db import get_db
from app.models import Customer, CustomerTier, Order, OrderStatus, Refund, Ticket, TicketStatus
from app.schemas import (
    CustomerCreate,
    CustomerDetail,
    CustomerOut,
    CustomerUpdate,
    OrderSummary,
    Page,
    TicketSummary,
)

router = APIRouter(prefix="/api/customers", tags=["customers"])
DB = Annotated[Session, Depends(get_db)]

SORTABLE = {"name": Customer.name, "created_at": Customer.created_at, "id": Customer.id}


def _get(db: Session, customer_id: int) -> Customer:
    c = db.get(Customer, customer_id)
    if not c:
        raise NotFoundError(
            f"Customer {customer_id} not found.",
            details={"hint": "Search with GET /api/customers?q=<name or email>."},
        )
    return c


@router.get("", response_model=Page[CustomerOut])
def list_customers(
    db: DB,
    pg: PageDep,
    q: Annotated[str | None, Query(description="Search by name or email (partial match)")] = None,
    tier: CustomerTier | None = None,
    sort: Annotated[str | None, Query(description="name, created_at, id; prefix - for desc")] = None,
):
    """List customers, with optional search and tier filter."""
    stmt = select(Customer)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.email.ilike(like)))
    if tier:
        stmt = stmt.where(Customer.tier == tier)
    stmt = apply_sort(stmt, sort, SORTABLE, "-created_at")
    return paginate(db, stmt, pg)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(db: DB, body: CustomerCreate):
    """Create a customer. Emails must be unique."""
    if db.scalar(select(Customer.id).where(Customer.email == body.email.lower())):
        raise ConflictError(f"A customer with email {body.email} already exists.")
    c = Customer(**body.model_dump() | {"email": body.email.lower()})
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(db: DB, customer_id: int):
    """Get one customer with order count, lifetime value and open tickets."""
    c = _get(db, customer_id)
    counted = Order.status.not_in([OrderStatus.cancelled])
    order_count = db.scalar(select(func.count(Order.id)).where(Order.customer_id == c.id)) or 0
    gross = db.scalar(
        select(func.coalesce(func.sum(Order.total_cents), 0)).where(Order.customer_id == c.id, counted)
    )
    refunded = db.scalar(
        select(func.coalesce(func.sum(Refund.amount_cents), 0))
        .join(Order, Refund.order_id == Order.id)
        .where(Order.customer_id == c.id)
    )
    open_tickets = db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.customer_id == c.id,
            Ticket.status.in_([TicketStatus.open, TicketStatus.pending]),
        )
    )
    return CustomerDetail(
        **CustomerOut.model_validate(c).model_dump(),
        order_count=order_count,
        lifetime_value_cents=(gross or 0) - (refunded or 0),
        open_ticket_count=open_tickets or 0,
    )


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(db: DB, customer_id: int, body: CustomerUpdate):
    """Update a customer. Only fields you send are changed."""
    c = _get(db, customer_id)
    data = body.model_dump(exclude_unset=True)
    if "email" in data:
        data["email"] = data["email"].lower()
        clash = db.scalar(select(Customer.id).where(Customer.email == data["email"], Customer.id != c.id))
        if clash:
            raise ConflictError(f"Email {data['email']} is already used by customer {clash}.")
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(db: DB, customer_id: int):
    """Delete a customer. Not allowed if they have orders or tickets (history must be kept)."""
    c = _get(db, customer_id)
    has_orders = db.scalar(select(Order.id).where(Order.customer_id == c.id).limit(1))
    has_tickets = db.scalar(select(Ticket.id).where(Ticket.customer_id == c.id).limit(1))
    if has_orders or has_tickets:
        raise ConflictError(
            f"Customer {c.id} has orders or tickets and can't be deleted.",
        )
    db.delete(c)
    db.commit()


@router.get("/{customer_id}/orders", response_model=Page[OrderSummary])
def list_customer_orders(db: DB, customer_id: int, pg: PageDep):
    """A customer's orders, newest first."""
    _get(db, customer_id)
    stmt = select(Order).where(Order.customer_id == customer_id).order_by(Order.placed_at.desc())
    page = paginate(db, stmt, pg)
    page["items"] = [
        OrderSummary.model_validate(o).model_copy(update={"item_count": len(o.items)}) for o in page["items"]
    ]
    return page


@router.get("/{customer_id}/tickets", response_model=Page[TicketSummary])
def list_customer_tickets(db: DB, customer_id: int, pg: PageDep):
    """A customer's support tickets, newest first."""
    _get(db, customer_id)
    stmt = select(Ticket).where(Ticket.customer_id == customer_id).order_by(Ticket.created_at.desc())
    return paginate(db, stmt, pg)
