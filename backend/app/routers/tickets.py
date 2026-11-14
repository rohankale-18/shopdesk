from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.core.pagination import PageDep, apply_sort, paginate
from app.db import get_db
from app.models import (
    Customer,
    MessageAuthor,
    Order,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
    utcnow,
)
from app.schemas import (
    Page,
    TicketCreate,
    TicketMessageCreate,
    TicketMessageOut,
    TicketOut,
    TicketSummary,
    TicketUpdate,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
DB = Annotated[Session, Depends(get_db)]

SORTABLE = {"created_at": Ticket.created_at, "updated_at": Ticket.updated_at, "id": Ticket.id}


def _get(db: Session, ticket_id: int) -> Ticket:
    t = db.get(Ticket, ticket_id)
    if not t:
        raise NotFoundError(f"Ticket {ticket_id} not found.")
    return t


@router.get("", response_model=Page[TicketSummary])
def list_tickets(
    db: DB,
    pg: PageDep,
    q: Annotated[str | None, Query(description="Search ticket subjects")] = None,
    status_: Annotated[list[TicketStatus] | None, Query(alias="status")] = None,
    priority: Annotated[list[TicketPriority] | None, Query()] = None,
    category: TicketCategory | None = None,
    customer_id: int | None = None,
    order_id: int | None = None,
    assignee: str | None = None,
    sort: Annotated[str | None, Query(description="created_at, updated_at, id")] = None,
):
    """List tickets. `status` and `priority` can be repeated."""
    stmt = select(Ticket)
    if q:
        stmt = stmt.where(Ticket.subject.ilike(f"%{q.strip()}%"))
    if status_:
        stmt = stmt.where(Ticket.status.in_(status_))
    if priority:
        stmt = stmt.where(Ticket.priority.in_(priority))
    if category:
        stmt = stmt.where(Ticket.category == category)
    if customer_id:
        stmt = stmt.where(Ticket.customer_id == customer_id)
    if order_id:
        stmt = stmt.where(Ticket.order_id == order_id)
    if assignee:
        stmt = stmt.where(Ticket.assignee == assignee)
    stmt = apply_sort(stmt, sort, SORTABLE, "-created_at")
    return paginate(db, stmt, pg)


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(db: DB, body: TicketCreate):
    """Open a ticket on behalf of a customer, optionally linked to one of their orders."""
    if not db.get(Customer, body.customer_id):
        raise NotFoundError(f"Customer {body.customer_id} not found.")
    if body.order_id is not None:
        order = db.get(Order, body.order_id)
        if not order:
            raise NotFoundError(f"Order {body.order_id} not found.")
        if order.customer_id != body.customer_id:
            raise BusinessRuleError(
                f"Order {order.number} belongs to a different customer.",
                details={"order_customer_id": order.customer_id},
            )
    t = Ticket(**body.model_dump(exclude={"message"}))
    t.messages.append(TicketMessage(author=MessageAuthor.customer, body=body.message))
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(db: DB, ticket_id: int):
    """Full ticket with customer info and the message thread (oldest first)."""
    return _get(db, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(db: DB, ticket_id: int, body: TicketUpdate):
    """Change status, priority, category or assignee."""
    t = _get(db, ticket_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t


@router.post(
    "/{ticket_id}/messages",
    response_model=TicketMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def add_ticket_message(db: DB, ticket_id: int, body: TicketMessageCreate):
    """Reply on a ticket. A customer reply re-opens a pending/resolved ticket."""
    t = _get(db, ticket_id)
    if t.status == TicketStatus.closed:
        raise BusinessRuleError(
            f"Ticket {t.id} is closed.",
            details={"hint": "Reopen it with PATCH status=open first, or create a new ticket."},
        )
    msg = TicketMessage(author=body.author, body=body.body)
    t.messages.append(msg)
    if body.author == MessageAuthor.customer and t.status in (
        TicketStatus.pending,
        TicketStatus.resolved,
    ):
        t.status = TicketStatus.open
    t.updated_at = utcnow()
    db.commit()
    db.refresh(msg)
    return msg
