"""The assistant's tools: what the model may ask us to run, and the code that runs it.

Each tool has two halves:
- a *definition* the model sees (name, description, JSON schema of the arguments);
  the description is effectively part of the prompt, so it says when to use the tool;
- a Python function we run when the model asks for it. Tools call the service layer
  directly (not ShopDesk's HTTP API) and return small, JSON-friendly dicts.

To add a tool: write the function, add a `Tool(...)` to `TOOLS`. Nothing else changes.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Customer,
    MessageAuthor,
    Order,
    Ticket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from app.services.stats import sales_totals, store_overview

logger = logging.getLogger("shopdesk.tools")


class ToolError(Exception):
    """A problem the model can fix or explain (bad date, missing argument...).

    The message goes back to the model as the tool's result, so write it for the model.
    """


def _usd(cents: int) -> float:
    return round(cents / 100, 2)


# ---------- shared helpers (reuse these in new tools) ----------


def _parse_date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a real date in YYYY-MM-DD format, got {value!r}.") from None


def parse_period(
    start: Any, end: Any, names: tuple[str, str] = ("start_date", "end_date")
) -> tuple[date, date]:
    """Validate a date range. Days after today are cut off (they can't have data yet)."""
    start_d, end_d = _parse_date(start, names[0]), _parse_date(end, names[1])
    today = datetime.now(UTC).date()
    if end_d < start_d:
        raise ToolError(f"{names[1]} ({end_d}) is before {names[0]} ({start_d}).")
    if start_d > today:
        raise ToolError(f"{names[0]} ({start_d}) is in the future. Today is {today}.")
    return start_d, min(end_d, today)


def compare(current: dict[str, Any], previous: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """The change between two periods, computed here so the model never does the arithmetic.

    For each field: the difference, and the % change (None when the previous value is 0).
    A field missing in either period (None, e.g. no orders to average) has no change.
    """
    change: dict[str, Any] = {}
    for f in fields:
        if current[f] is None or previous[f] is None:
            change[f] = change[f"{f}_pct"] = None
            continue
        diff = current[f] - previous[f]
        change[f] = round(diff, 2) if isinstance(diff, float) else diff
        change[f"{f}_pct"] = round(diff / previous[f] * 100, 1) if previous[f] else None
    return change


# ---------- the tools ----------


def get_store_overview(db: Session) -> dict[str, Any]:
    # Grouped by period with explicit names: the model reads these keys, and a vague name like
    # "revenue" gets reported for the wrong period or with the wrong meaning.
    o = store_overview(db)
    last_30 = o.revenue_last_30_days
    return {
        "all_time": {
            "customers": o.customers,
            "products": o.products,
            "orders": o.orders,
            "orders_by_status": o.orders_by_status,
            "revenue_after_refunds_usd": _usd(o.revenue_cents),
            "refunded_usd": _usd(o.refunded_cents),
        },
        "last_30_days": {
            "from": last_30[0].date,
            "to": last_30[-1].date,
            "orders_placed": sum(d.orders for d in last_30),
            "revenue_before_refunds_usd": _usd(sum(d.revenue_cents for d in last_30)),
        },
        "tickets_now": {
            # ShopDesk's meaning of "open": still needs work, i.e. status open OR pending.
            "open_tickets": o.open_tickets,
            "by_status": o.tickets_by_status,
        },
        "low_stock_products": [
            {"sku": p.sku, "name": p.name, "stock": p.stock} for p in o.low_stock_products
        ],
    }


def _sales(db: Session, start: date, end: date) -> dict[str, Any]:
    s = sales_totals(db, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": (end - start).days + 1,
        "orders_placed": s.orders,
        "revenue_before_refunds_usd": _usd(s.revenue_cents),
        # Computed here, not by the model: it's a division, and models get those wrong.
        "average_order_value_usd": _usd(round(s.revenue_cents / s.orders)) if s.orders else None,
        "cancelled_orders": s.cancelled_orders,
        "refunds_issued": s.refunds,
        "refunded_usd": _usd(s.refunded_cents),
    }


SALES_FIELDS = [
    "orders_placed",
    "revenue_before_refunds_usd",
    "average_order_value_usd",
    "cancelled_orders",
    "refunds_issued",
    "refunded_usd",
]


def get_sales(
    db: Session,
    start_date: str,
    end_date: str,
    compare_start_date: str | None = None,
    compare_end_date: str | None = None,
) -> dict[str, Any]:
    result = {"period": _sales(db, *parse_period(start_date, end_date))}
    if compare_start_date or compare_end_date:
        if not (compare_start_date and compare_end_date):
            raise ToolError("To compare, give both compare_start_date and compare_end_date.")
        names = ("compare_start_date", "compare_end_date")
        result["comparison"] = _sales(db, *parse_period(compare_start_date, compare_end_date, names))
        p, c = result["period"], result["comparison"]
        # Spelled out, because the model mixed up the direction when the periods were passed
        # earlier-first: it reported September minus October as "October vs September".
        result["change_means"] = (
            f"{p['from']} to {p['to']} compared with {c['from']} to {c['to']}: "
            "positive means higher in the first."
        )
        result["change"] = compare(p, c, SALES_FIELDS)
    return result


ORDER_NUMBER = re.compile(r"(?:ORD)?[\s#-]*(\d{1,8})", re.IGNORECASE)


def normalize_order_number(value: Any) -> str:
    """'ORD-00000002', 'ord-2', '#2', '2' -> 'ORD-00000002'. The code fixes the format, not the model."""
    match = ORDER_NUMBER.fullmatch(str(value).strip())
    if not match:
        raise ToolError(f"order_number should look like ORD-00001234, got {value!r}.")
    return f"ORD-{int(match[1]):08d}"


def _day(when: datetime | None, today: date) -> dict[str, Any] | None:
    # "days_ago" is computed here so the model can say "shipped 12 days ago" without date math.
    return None if when is None else {"on": when.date().isoformat(), "days_ago": (today - when.date()).days}


# Delivery takes 2-6 days after shipping. Past this, the order counts as late. It's a business
# rule, so it lives here: left to itself, the model called an order shipped 12 days ago "on its way".
LATE_AFTER_DAYS = 7


def _delivery_late(order: Order, today: date) -> bool:
    if order.shipped_at is None or order.delivered_at is not None:
        return False
    return (today - order.shipped_at.date()).days > LATE_AFTER_DAYS


def get_order(db: Session, order_number: str) -> dict[str, Any]:
    number = normalize_order_number(order_number)
    order = db.scalar(select(Order).where(Order.number == number))
    if order is None:
        raise ToolError(f"There is no order {number}. Check the number with the user.")
    today = datetime.now(UTC).date()
    tickets = db.scalars(select(Ticket).where(Ticket.order_id == order.id).order_by(Ticket.id))
    return {
        "number": order.number,
        "status": order.status,
        "customer": {"id": order.customer_id, "name": order.customer.name, "tier": order.customer.tier},
        "placed": _day(order.placed_at, today),
        "shipped": _day(order.shipped_at, today),
        "delivered": _day(order.delivered_at, today),
        "delivery_late": _delivery_late(order, today),
        "tracking_number": order.tracking_number,
        "items": [
            {
                "product": i.product_name,
                "quantity": i.quantity,
                "unit_price_usd": _usd(i.unit_price_cents),
                "line_total_usd": _usd(i.line_total_cents),
            }
            for i in order.items
        ],
        "total_usd": _usd(order.total_cents),
        "refunded_usd": _usd(order.refunded_cents),
        "still_refundable_usd": _usd(order.refundable_cents),
        "refunds": [
            {"on": r.created_at.date().isoformat(), "amount_usd": _usd(r.amount_cents), "reason": r.reason}
            for r in order.refunds
        ],
        "tickets": [{"id": t.id, "subject": t.subject, "status": t.status} for t in tickets],
    }


CUSTOMER_MATCHES = 5  # enough to choose from; more is noise the model has to read
ORDERS_SHOWN = 10


def find_customer(db: Session, query: str) -> dict[str, Any]:
    text = str(query).strip()
    if len(text) < 2:
        raise ToolError("query needs at least 2 characters of a name or email.")
    where = or_(Customer.name.ilike(f"%{text}%"), Customer.email.ilike(f"%{text}%"))
    total = db.scalar(select(func.count()).select_from(Customer).where(where)) or 0
    order_count = select(func.count()).where(Order.customer_id == Customer.id).scalar_subquery()
    rows = db.execute(
        select(Customer, order_count).where(where).order_by(Customer.name).limit(CUSTOMER_MATCHES)
    ).all()
    result: dict[str, Any] = {
        "total_matches": total,
        "matches": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "tier": c.tier,
                "location": ", ".join(p for p in (c.city, c.country) if p),
                "orders": n,
            }
            for c, n in rows
        ],
    }
    # A search that finds nothing, or too much, isn't an error: say what to do next instead.
    if total == 0:
        result["next_step"] = f"No customer matches {text!r}. Ask the user for an email or another spelling."
    elif total > 1:
        shown = f"the first {len(rows)} of {total}" if total > len(rows) else f"all {total}"
        result["next_step"] = (
            f"Several customers match ({shown} shown). Ask the user which one they mean "
            "(by email or location) before looking up anything else."
        )
    return result


def list_customer_orders(db: Session, customer_id: Any) -> dict[str, Any]:
    try:
        customer = db.get(Customer, int(customer_id))
    except (TypeError, ValueError):
        customer = None
    if customer is None:
        raise ToolError(f"No customer with id {customer_id!r}. Get the id from find_customer first.")
    total = db.scalar(select(func.count()).where(Order.customer_id == customer.id)) or 0
    orders = db.scalars(
        select(Order)
        .where(Order.customer_id == customer.id)
        .order_by(Order.placed_at.desc())
        .limit(ORDERS_SHOWN)
    ).all()
    tickets: dict[int, list[dict[str, Any]]] = {}
    for t in db.scalars(
        select(Ticket).where(Ticket.order_id.in_([o.id for o in orders])).order_by(Ticket.id)
    ):
        tickets.setdefault(t.order_id, []).append({"id": t.id, "subject": t.subject, "status": t.status})
    today = datetime.now(UTC).date()
    return {
        "customer": {"id": customer.id, "name": customer.name},
        "total_orders": total,
        "showing": f"newest {len(orders)}" if total > len(orders) else f"all {total}",
        "orders": [
            {
                "number": o.number,
                "status": o.status,
                "placed": _day(o.placed_at, today),
                "items": sum(i.quantity for i in o.items),
                "total_usd": _usd(o.total_cents),
                "refunded_usd": _usd(o.refunded_cents),
                "tickets": tickets.get(o.id, []),
            }
            for o in orders
        ],
    }


MESSAGES_SHOWN = 20  # the latest ones; long threads are rare, and their start matters less
TICKETS_SHOWN = 10
PRIORITY_RANK = {p: i for i, p in enumerate(reversed(TicketPriority))}  # urgent first


def _waiting_on(ticket: Ticket) -> str | None:
    """Who has to act next: whoever didn't write the last message. None once it's done."""
    if ticket.status in (TicketStatus.resolved, TicketStatus.closed):
        return None
    authors = [m.author for m in ticket.messages if m.author != MessageAuthor.system]
    return "support" if not authors or authors[-1] == MessageAuthor.customer else "customer"


def get_ticket(db: Session, ticket_id: Any) -> dict[str, Any]:
    try:
        ticket = db.get(Ticket, int(ticket_id))
    except (TypeError, ValueError):
        ticket = None
    if ticket is None:
        raise ToolError(f"There is no ticket {ticket_id!r}. Check the number with the user.")
    today = datetime.now(UTC).date()
    order = ticket.order
    messages = ticket.messages[-MESSAGES_SHOWN:]
    result: dict[str, Any] = {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "category": ticket.category,
        "assignee": ticket.assignee,
        "opened": _day(ticket.created_at, today),
        "waiting_on": _waiting_on(ticket),
        "customer": {
            "id": ticket.customer_id,
            "name": ticket.customer.name,
            "email": ticket.customer.email,
            "tier": ticket.customer.tier,
        },
        "order": order
        and {
            "number": order.number,
            "status": order.status,
            "placed": _day(order.placed_at, today),
            "shipped": _day(order.shipped_at, today),
            "delivered": _day(order.delivered_at, today),
            "delivery_late": _delivery_late(order, today),
            "total_usd": _usd(order.total_cents),
            "refunded_usd": _usd(order.refunded_cents),
            "still_refundable_usd": _usd(order.refundable_cents),
        },
        "messages": [{"from": m.author, "sent": _day(m.created_at, today), "text": m.body} for m in messages],
    }
    if len(ticket.messages) > len(messages):
        result["earlier_messages_not_shown"] = len(ticket.messages) - len(messages)
    return result


def _enum_values(values: Any, enum: type, name: str) -> list[str]:
    """Check a list of filter values against the allowed ones, so a typo can be fixed by the model."""
    if values is None:
        return []
    values = [values] if isinstance(values, str) else list(values)
    allowed = [e.value for e in enum]
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ToolError(f"{name} can only be {', '.join(allowed)}; got {bad}.")
    return values


def list_tickets(
    db: Session,
    status: Any = None,
    priority: Any = None,
    category: Any = None,
    customer_id: Any = None,
    limit: Any = TICKETS_SHOWN,
) -> dict[str, Any]:
    # No status means ShopDesk's "open tickets": everything that still needs work.
    statuses = _enum_values(status, TicketStatus, "status") or [TicketStatus.open, TicketStatus.pending]
    priorities = _enum_values(priority, TicketPriority, "priority")
    categories = _enum_values(category, TicketCategory, "category")
    try:
        limit = max(1, min(int(limit), TICKETS_SHOWN))
    except (TypeError, ValueError):
        raise ToolError(f"limit must be a number from 1 to {TICKETS_SHOWN}.") from None

    where = [Ticket.status.in_(statuses)]
    if priorities:
        where.append(Ticket.priority.in_(priorities))
    if categories:
        where.append(Ticket.category.in_(categories))
    if customer_id is not None:
        where.append(Ticket.customer_id == customer_id)

    by_priority = dict(
        db.execute(select(Ticket.priority, func.count()).where(*where).group_by(Ticket.priority)).all()
    )
    total = sum(by_priority.values())
    # Most urgent first; within a priority, the one waiting longest first.
    rank = case(PRIORITY_RANK, value=Ticket.priority)
    tickets = db.scalars(select(Ticket).where(*where).order_by(rank, Ticket.created_at).limit(limit)).all()
    today = datetime.now(UTC).date()
    return {
        "total_matches": total,
        "by_priority": {p.value: by_priority.get(p, 0) for p in reversed(TicketPriority)},
        "showing": f"the {len(tickets)} most urgent, oldest first"
        if total > len(tickets)
        else f"all {total}",
        "tickets": [
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status,
                "priority": t.priority,
                "category": t.category,
                "customer": t.customer.name,
                "order": t.order.number if t.order else None,
                "opened": _day(t.created_at, today),
                "waiting_on": _waiting_on(t),
            }
            for t in tickets
        ],
    }


def _tickets_label(a: dict[str, Any]) -> str:
    filters = [a.get("status") or "open, pending", a.get("priority"), a.get("category")]
    text = "; ".join(", ".join(f) if isinstance(f, list) else str(f) for f in filters if f)
    if a.get("customer_id") is not None:
        text += f"; customer {a['customer_id']}"
    return f"Looked up tickets ({text})"


# ---------- the registry ----------


@dataclass(frozen=True)
class Tool:
    name: str
    # Shown in the chat, e.g. "Looked up store overview". A function gets the arguments.
    label: str | Callable[[dict[str, Any]], str]
    description: str  # read by the model to decide when (and when not) to call it
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[..., dict[str, Any]]  # run(db, **arguments) -> result


NO_ARGUMENTS: dict[str, Any] = {"type": "object", "properties": {}}


def _date_param(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _sales_label(a: dict[str, Any]) -> str:
    text = f"Looked up sales, {a['start_date']} to {a['end_date']}"
    if a.get("compare_start_date"):
        text += f" vs {a['compare_start_date']} to {a['compare_end_date']}"
    return text


TOOLS = {
    t.name: t
    for t in [
        Tool(
            name="get_store_overview",
            label="Looked up store overview",
            description=(
                "Store-wide headline numbers. All time: customer, product and order counts, orders by "
                "status, revenue after refunds, total refunded. Last 30 days: orders placed and revenue "
                "(before refunds). Right now: open tickets and tickets by status, low-stock products. "
                "Use it for questions like 'How are we doing?' or 'How many open tickets are there?'. "
                "For sales in a specific period (last week, last 10 days, a month...), use get_sales. "
                "It has no details about individual orders (use get_order), customers or tickets "
                "(use list_tickets or get_ticket)."
            ),
            parameters=NO_ARGUMENTS,
            run=get_store_overview,
        ),
        Tool(
            name="get_sales",
            label=_sales_label,
            description=(
                "Sales for any period: orders placed and revenue (before refunds; cancelled orders "
                "excluded), average order value, cancelled orders, and refunds issued in the period "
                "(count and amount). It has nothing on tickets or stock. "
                "Use it whenever a question names a period: 'last 10 days', 'last week', 'in October', "
                "'since the 1st'. To compare two periods, put the later period in start_date/end_date "
                "and the earlier one in compare_start_date/compare_end_date: the result then "
                "includes `change` (later minus earlier, and % change) and `change_means`, which "
                "says which way round it is, so you never need to calculate it. "
                "Dates are YYYY-MM-DD, inclusive, UTC; weeks run "
                "Monday to Sunday. For headline numbers without a period, use get_store_overview."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "start_date": _date_param("First day, YYYY-MM-DD."),
                    "end_date": _date_param("Last day (inclusive), YYYY-MM-DD."),
                    "compare_start_date": _date_param("Optional: first day of the earlier period."),
                    "compare_end_date": _date_param("Optional: last day of the earlier period."),
                },
                "required": ["start_date", "end_date"],
            },
            run=get_sales,
        ),
        Tool(
            name="get_order",
            label=lambda a: f"Looked up order {a['order_number']}",
            description=(
                "One order by its number: status, customer, when it was placed, shipped and delivered "
                f"(with days ago), delivery_late (shipped more than {LATE_AFTER_DAYS} days ago and not "
                "delivered), tracking number, items, total, refunds and what can still be "
                "refunded, and any support tickets about it (get_ticket has a ticket's messages). "
                "Use it whenever the user refers to a "
                "specific order by number, in any form: ORD-00001234, #1234, 'order 1234'. It can't "
                "search: without a number, ask the user for one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "order_number": {
                        "type": "string",
                        "description": (
                            "The order number as the user gave it: 'ORD-00001234', '#1234' and '1234' "
                            "all work, the tool fills in the rest."
                        ),
                    }
                },
                "required": ["order_number"],
            },
            run=get_order,
        ),
        Tool(
            name="find_customer",
            label=lambda a: f"Searched customers for “{a['query']}”",
            description=(
                "Search customers by part of their name or email. Returns up to 5 matches with "
                "their id, email, tier, location and number of orders. Use it first whenever the "
                "user names a customer, then pass the id to other tools (e.g. list_customer_orders). "
                "If several customers match, ask the user which one they mean; don't pick one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name or email, or part of one, e.g. 'priya'."}
                },
                "required": ["query"],
            },
            run=find_customer,
        ),
        Tool(
            name="list_customer_orders",
            label=lambda a: f"Looked up orders of customer {a['customer_id']}",
            description=(
                "A customer's orders, newest first (up to 10): number, status, date placed (with days "
                "ago), item count, total, amount refunded, and any support tickets about each order. "
                "Also the customer's total order count. Needs the customer id from find_customer. "
                "For full details of one order (items, tracking), use get_order."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "integer",
                        "description": "The customer's id, from find_customer.",
                    }
                },
                "required": ["customer_id"],
            },
            run=list_customer_orders,
        ),
        Tool(
            name="get_ticket",
            label=lambda a: f"Looked up ticket #{a['ticket_id']}",
            description=(
                "One support ticket by its number, with the full conversation (oldest message first): "
                "subject, status, priority, category, assignee, when it was opened, waiting_on (who "
                "has to act next: 'support' or 'customer'), the customer, and the order it's about "
                "(status, dates, delivery_late, total, what can still be refunded). Use it to "
                "summarize a ticket, work out what the customer wants, or draft a reply. For the "
                "order's items or tracking number, use get_order."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "The ticket number, e.g. 12 for '#12'."}
                },
                "required": ["ticket_id"],
            },
            run=get_ticket,
        ),
        Tool(
            name="list_tickets",
            label=_tickets_label,
            description=(
                "The support queue: tickets matching the filters, most urgent first and then the one "
                f"waiting longest. Returns up to {TICKETS_SHOWN} tickets (subject, status, priority, "
                "category, customer, order, when opened, waiting_on), the total that match, and how "
                "many there are of each priority. Without a status it lists the open tickets (open "
                "or pending). Use it for 'what's urgent?', 'what's in the queue?' or a customer's "
                "tickets (customer_id from find_customer). For one ticket's messages, use get_ticket."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "array",
                        "items": {"type": "string", "enum": [s.value for s in TicketStatus]},
                        "description": "Optional. Default: open and pending (the open tickets).",
                    },
                    "priority": {
                        "type": "array",
                        "items": {"type": "string", "enum": [p.value for p in TicketPriority]},
                        "description": "Optional, e.g. ['urgent', 'high'].",
                    },
                    "category": {
                        "type": "array",
                        "items": {"type": "string", "enum": [c.value for c in TicketCategory]},
                        "description": "Optional.",
                    },
                    "customer_id": {"type": "integer", "description": "Optional: only this customer's."},
                    "limit": {"type": "integer", "description": f"How many to show, 1 to {TICKETS_SHOWN}."},
                },
            },
            run=list_tickets,
        ),
    ]
}


def definitions() -> list[dict[str, Any]]:
    """The tool list in the format the chat-completions API expects."""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOLS.values()
    ]


def label(name: str, arguments: str = "{}") -> str:
    tool = TOOLS.get(name)
    if tool is None:
        return f"Used {name}"
    if isinstance(tool.label, str):
        return tool.label
    try:
        return tool.label(json.loads(arguments or "{}"))
    except Exception:  # odd arguments must never break the chat
        return f"Used {name}"


def run(name: str, arguments: str) -> dict[str, Any]:
    """Run a tool the model asked for. Never raises: problems go back to the model as an error."""
    tool = TOOLS.get(name)
    if tool is None:
        result: dict[str, Any] = {"error": f"There is no tool called {name!r}."}
    else:
        try:
            args = json.loads(arguments or "{}")
            with SessionLocal() as db:
                result = tool.run(db, **args)
        except ToolError as e:  # a mistake the model can fix: tell it what was wrong
            result = {"error": str(e)}
        except (json.JSONDecodeError, TypeError) as e:  # broken JSON, missing or unknown arguments
            result = {"error": f"Invalid arguments for {name}: {e}"}
        except Exception:
            logger.exception("Tool %s failed (arguments: %s)", name, arguments)
            result = {"error": f"{name} failed. Tell the user the lookup didn't work."}
    logger.info("tool %s(%s) -> %s", name, arguments, json.dumps(result)[:500])
    return result
