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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Order, Ticket
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
                "In ShopDesk, 'open tickets' means tickets that still need work: status open or pending "
                "(the same number as the Tickets badge in the app). When asked how many tickets are "
                "open, answer with open_tickets; give the by_status breakdown only if it helps. "
                "Use it for questions like 'How are we doing?' or 'How many open tickets are there?'. "
                "For sales in a specific period (last week, last 10 days, a month...), use get_sales. "
                "It has no details about individual orders (use get_order), customers or tickets."
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
                "(with days ago), tracking number, items, total, refunds and what can still be "
                "refunded, and any support tickets about it. Use it whenever the user refers to a "
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
