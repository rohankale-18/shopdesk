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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
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
    """
    change: dict[str, Any] = {}
    for f in fields:
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
    orders, revenue_cents = sales_totals(db, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": (end - start).days + 1,
        "orders_placed": orders,
        "revenue_before_refunds_usd": _usd(revenue_cents),
    }


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
        result["change"] = compare(
            result["period"], result["comparison"], ["orders_placed", "revenue_before_refunds_usd"]
        )
    return result


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
                "It has no details about individual orders, customers or tickets."
            ),
            parameters=NO_ARGUMENTS,
            run=get_store_overview,
        ),
        Tool(
            name="get_sales",
            label=_sales_label,
            description=(
                "Orders placed and revenue (before refunds; cancelled orders excluded) for any period. "
                "Use it whenever a question names a period: 'last 10 days', 'last week', 'in October', "
                "'since the 1st'. To compare two periods, also pass compare_start_date and "
                "compare_end_date: the result then includes `change` (difference and % change), so "
                "you never need to calculate it. Dates are YYYY-MM-DD, inclusive, UTC; weeks run "
                "Monday to Sunday. For headline numbers without a period, use get_store_overview."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "start_date": _date_param("First day, YYYY-MM-DD."),
                    "end_date": _date_param("Last day (inclusive), YYYY-MM-DD."),
                    "compare_start_date": _date_param("Optional: first day of the period to compare with."),
                    "compare_end_date": _date_param("Optional: last day of the period to compare with."),
                },
                "required": ["start_date", "end_date"],
            },
            run=get_sales,
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
