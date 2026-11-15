"""The assistant's tools, called directly (no model involved)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Order, OrderStatus
from app.services import tools

PERIOD = ("2026-05-01", "2026-05-31")  # inside the seeded data (anchor date 2026-06-01)


def run(name: str, **arguments) -> dict:
    return tools.run(name, json.dumps(arguments))


def expected_sales(start: date, end: date) -> tuple[int, float]:
    """Orders and revenue for a period, counted the slow, obvious way."""
    with SessionLocal() as db:
        orders = [
            o
            for o in db.scalars(select(Order))
            if start <= o.placed_at.astimezone(UTC).date() <= end and o.status != OrderStatus.cancelled
        ]
    return len(orders), round(sum(o.total_cents for o in orders) / 100, 2)


def test_get_sales_totals_match_the_orders(client):
    result = run("get_sales", start_date=PERIOD[0], end_date=PERIOD[1])
    period = result["period"]
    orders, revenue = expected_sales(date(2026, 5, 1), date(2026, 5, 31))
    assert orders > 0  # the period really has data
    assert period == {
        "from": "2026-05-01",
        "to": "2026-05-31",
        "days": 31,
        "orders_placed": orders,
        "revenue_before_refunds_usd": revenue,
    }
    assert "comparison" not in result


def test_get_sales_compares_two_periods(client):
    result = run(
        "get_sales",
        start_date="2026-05-16",
        end_date="2026-05-31",
        compare_start_date="2026-05-01",
        compare_end_date="2026-05-15",
    )
    now, before = result["period"], result["comparison"]
    assert result["change"]["orders_placed"] == now["orders_placed"] - before["orders_placed"]
    diff = now["revenue_before_refunds_usd"] - before["revenue_before_refunds_usd"]
    assert result["change"]["revenue_before_refunds_usd"] == round(diff, 2)


def test_compare_handles_a_zero_previous_value():
    change = tools.compare({"orders": 5, "usd": 10.5}, {"orders": 0, "usd": 7.0}, ["orders", "usd"])
    assert change == {"orders": 5, "orders_pct": None, "usd": 3.5, "usd_pct": 50.0}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start_date": "2026-02-30", "end_date": "2026-03-01"}, "start_date must be a real date"),
        ({"start_date": "last week", "end_date": "2026-03-01"}, "start_date must be a real date"),
        ({"start_date": "2026-05-10", "end_date": "2026-05-01"}, "is before start_date"),
        ({"start_date": "2999-01-01", "end_date": "2999-01-02"}, "is in the future"),
        (
            {"start_date": "2026-05-01", "end_date": "2026-05-02", "compare_start_date": "2026-04-01"},
            "give both",
        ),
        ({"end_date": "2026-05-02"}, "Invalid arguments for get_sales"),
        ({"start_date": "2026-05-01", "end_date": "2026-05-02", "region": "EU"}, "Invalid arguments"),
    ],
)
def test_bad_arguments_go_back_to_the_model_as_an_error(client, arguments, message):
    result = run("get_sales", **arguments)
    assert list(result) == ["error"]
    assert message in result["error"]


def test_days_after_today_are_cut_off(client):
    today = datetime.now(UTC).date()
    start, end = today - timedelta(days=2), today + timedelta(days=5)
    period = run("get_sales", start_date=start.isoformat(), end_date=end.isoformat())["period"]
    assert (period["to"], period["days"]) == (today.isoformat(), 3)


def test_labels_show_the_arguments():
    args = {"start_date": "2026-11-03", "end_date": "2026-11-09"}
    assert tools.label("get_sales", json.dumps(args)) == "Looked up sales, 2026-11-03 to 2026-11-09"
    args |= {"compare_start_date": "2026-10-27", "compare_end_date": "2026-11-02"}
    assert tools.label("get_sales", json.dumps(args)).endswith("vs 2026-10-27 to 2026-11-02")
    assert tools.label("get_sales", "not json") == "Used get_sales"  # never breaks the chat
    assert tools.label("get_store_overview") == "Looked up store overview"
