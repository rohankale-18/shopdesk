"""The assistant's tools, called directly (no model involved)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Order, OrderStatus, Refund, Ticket
from app.services import tools

PERIOD = ("2026-05-01", "2026-05-31")  # inside the seeded data (anchor date 2026-06-01)


def run(name: str, **arguments) -> dict:
    return tools.run(name, json.dumps(arguments))


def expected_sales(start: date, end: date) -> dict:
    """A period's sales figures, counted the slow, obvious way."""
    within = lambda when: start <= when.astimezone(UTC).date() <= end  # noqa: E731
    with SessionLocal() as db:
        placed = [o for o in db.scalars(select(Order)) if within(o.placed_at)]
        refunds = [r for r in db.scalars(select(Refund)) if within(r.created_at)]
    kept = [o for o in placed if o.status != OrderStatus.cancelled]
    revenue = sum(o.total_cents for o in kept)
    return {
        "orders_placed": len(kept),
        "revenue_before_refunds_usd": round(revenue / 100, 2),
        "average_order_value_usd": round(revenue / len(kept) / 100, 2),
        "cancelled_orders": len(placed) - len(kept),
        "refunds_issued": len(refunds),
        "refunded_usd": round(sum(r.amount_cents for r in refunds) / 100, 2),
    }


def test_get_sales_totals_match_the_orders(client):
    result = run("get_sales", start_date=PERIOD[0], end_date=PERIOD[1])
    expected = expected_sales(date(2026, 5, 1), date(2026, 5, 31))
    assert expected["orders_placed"] > 0 and expected["refunds_issued"] > 0  # the period has data
    assert result["period"] == {"from": "2026-05-01", "to": "2026-05-31", "days": 31, **expected}
    assert "comparison" not in result


def test_a_period_without_orders_has_no_average(client):
    period = run("get_sales", start_date="2020-01-01", end_date="2020-01-31")["period"]
    assert (period["orders_placed"], period["average_order_value_usd"]) == (0, None)
    compared = run(
        "get_sales",
        start_date="2020-01-01",
        end_date="2020-01-31",
        compare_start_date=PERIOD[0],
        compare_end_date=PERIOD[1],
    )
    assert compared["change"]["average_order_value_usd"] is None  # nothing to compare with


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
    assert set(result["change"]) == {f for name in tools.SALES_FIELDS for f in (name, f"{name}_pct")}
    assert result["change_means"].startswith("2026-05-16 to 2026-05-31 compared with 2026-05-01")


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


# ---------- get_order ----------


def test_get_order_returns_the_late_delivery_scenario(client):
    order = run("get_order", order_number="ORD-00000002")
    today = datetime.now(UTC).date()
    shipped = date(2026, 5, 20)  # 12 days before the seed's anchor date
    assert order["number"] == "ORD-00000002"
    assert order["status"] == "shipped"
    assert order["customer"]["name"] == "Marcus Lee"
    assert order["shipped"] == {"on": shipped.isoformat(), "days_ago": (today - shipped).days}
    assert order["delivered"] is None
    assert order["items"] == [
        {"product": "Halo Desk Lamp", "quantity": 1, "unit_price_usd": 49.99, "line_total_usd": 49.99}
    ]
    assert [t["subject"] for t in order["tickets"]] == ["Still waiting for my lamp"]


def test_get_order_shows_what_is_still_refundable(client):
    order = run("get_order", order_number="ORD-00000003")  # lamp already refunded
    assert (order["total_usd"], order["refunded_usd"], order["still_refundable_usd"]) == (
        249.98,
        49.99,
        199.99,
    )
    assert order["refunds"][0]["reason"] == "wrong_item"


@pytest.mark.parametrize("given", ["ORD-00000002", "ord-00000002", "ORD-2", "#2", "2", " ORD 2 "])
def test_order_number_formats_are_normalized(given):
    assert tools.normalize_order_number(given) == "ORD-00000002"


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ("ORD-99999999", "There is no order ORD-99999999"),
        ("order two", "should look like ORD-00001234"),
        ("ORD-123456789", "should look like ORD-00001234"),  # too many digits
        ("", "should look like ORD-00001234"),
    ],
)
def test_get_order_problems_go_back_to_the_model(client, given, message):
    result = run("get_order", order_number=given)
    assert list(result) == ["error"]
    assert message in result["error"]


def test_get_order_label():
    assert tools.label("get_order", '{"order_number": "ORD-00000002"}') == "Looked up order ORD-00000002"


# ---------- find_customer, list_customer_orders ----------


def test_find_customer_by_name_or_email(client):
    by_name = run("find_customer", query="Priya Sharma")
    by_email = run("find_customer", query="PRIYA.SHARMA@example")  # partial, any case
    assert by_name["total_matches"] == 1 and "next_step" not in by_name
    assert by_name["matches"] == by_email["matches"]
    (priya,) = by_name["matches"]
    assert (priya["email"], priya["location"], priya["tier"]) == (
        "priya.sharma@example.com",
        "Pune, India",
        "gold",
    )
    assert priya["orders"] >= 1


def test_several_matches_ask_the_user_to_choose(client):
    result = run("find_customer", query=".com")  # every email matches
    assert result["total_matches"] > tools.CUSTOMER_MATCHES == len(result["matches"])
    assert "Ask the user which one" in result["next_step"]
    assert f"first {tools.CUSTOMER_MATCHES} of {result['total_matches']}" in result["next_step"]


def test_no_match_is_a_result_not_an_error(client):
    result = run("find_customer", query="Zebediah Q")
    assert (result["total_matches"], result["matches"]) == (0, [])
    assert "another spelling" in result["next_step"]
    assert "error" in run("find_customer", query=" a ")  # too short to search


def test_list_customer_orders_newest_first_with_tickets(client):
    marcus = run("find_customer", query="marcus.lee")["matches"][0]
    result = run("list_customer_orders", customer_id=marcus["id"])
    assert result["customer"] == {"id": marcus["id"], "name": "Marcus Lee"}
    assert result["total_orders"] == marcus["orders"] == len(result["orders"])
    placed = [o["placed"]["on"] for o in result["orders"]]
    assert placed == sorted(placed, reverse=True)
    late = next(o for o in result["orders"] if o["number"] == "ORD-00000002")
    assert late["tickets"][0]["subject"] == "Still waiting for my lamp"


def test_list_customer_orders_is_capped(client, monkeypatch):
    with SessionLocal() as db:  # the customer with the most orders
        busiest = db.execute(
            select(Order.customer_id, func.count()).group_by(Order.customer_id).order_by(func.count().desc())
        ).first()
    monkeypatch.setattr(tools, "ORDERS_SHOWN", 1)
    result = run("list_customer_orders", customer_id=busiest[0])
    assert len(result["orders"]) == 1 and result["total_orders"] == busiest[1]
    assert result["showing"] == "newest 1"


@pytest.mark.parametrize("customer_id", [999999, "abc", None])
def test_unknown_customer_id_goes_back_as_an_error(client, customer_id):
    result = run("list_customer_orders", customer_id=customer_id)
    assert "find_customer first" in result["error"]


def test_get_order_flags_a_late_delivery(client):
    assert run("get_order", order_number="2")["delivery_late"] is True  # shipped 12 days ago
    assert run("get_order", order_number="3")["delivery_late"] is False  # delivered


# ---------- get_ticket, list_tickets ----------


def test_get_ticket_has_the_thread_and_the_order(client):
    ticket = run("get_ticket", ticket_id=2)
    assert (ticket["subject"], ticket["status"], ticket["waiting_on"]) == (
        "Still waiting for my lamp",
        "open",
        "support",  # the customer wrote last
    )
    assert ticket["customer"]["email"] == "marcus.lee@example.com"
    assert ticket["order"]["number"] == "ORD-00000002"
    assert ticket["order"]["delivery_late"] is True
    assert [m["from"] for m in ticket["messages"]] == ["customer"]
    assert "tracking hasn't moved" in ticket["messages"][0]["text"]


def test_a_ticket_without_an_order(client):
    ticket = run("get_ticket", ticket_id=5)  # the yoga mat question
    assert ticket["order"] is None


@pytest.mark.parametrize("ticket_id", [999999, "abc", None])
def test_unknown_ticket_goes_back_as_an_error(client, ticket_id):
    assert "There is no ticket" in run("get_ticket", ticket_id=ticket_id)["error"]


def test_list_tickets_defaults_to_open_tickets_most_urgent_first(client):
    result = run("list_tickets")
    with SessionLocal() as db:
        open_now = db.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.status.in_(["open", "pending"]))
        )
    assert result["total_matches"] == open_now == sum(result["by_priority"].values())
    assert {t["status"] for t in result["tickets"]} <= {"open", "pending"}
    ranks = [tools.PRIORITY_RANK[t["priority"]] for t in result["tickets"]]
    assert ranks == sorted(ranks)
    assert list(result["by_priority"]) == ["urgent", "high", "medium", "low"]


def test_list_tickets_filters(client):
    high = run("list_tickets", priority=["high"])
    assert high["tickets"] and {t["priority"] for t in high["tickets"]} == {"high"}
    assert high["by_priority"]["medium"] == 0
    closed = run("list_tickets", status=["resolved", "closed"])
    assert all(t["waiting_on"] is None for t in closed["tickets"])  # nothing left to do
    james = run("find_customer", query="james.okafor")["matches"][0]
    theirs = run("list_tickets", customer_id=james["id"])
    assert {t["subject"] for t in theirs["tickets"]} >= {
        "Please cancel my order",
        "When is the yoga mat back?",
    }


def test_list_tickets_is_capped(client):
    result = run("list_tickets", limit=2)
    assert len(result["tickets"]) == 2 < result["total_matches"]
    assert result["showing"] == "the 2 most urgent, oldest first"
    assert len(run("list_tickets", limit=500)["tickets"]) <= tools.TICKETS_SHOWN


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"status": ["opened"]}, "status can only be open, pending, resolved, closed"),
        ({"priority": "critical"}, "priority can only be"),
        ({"limit": "lots"}, "limit must be a number"),
    ],
)
def test_bad_ticket_filters_go_back_to_the_model(client, arguments, message):
    assert message in run("list_tickets", **arguments)["error"]


def test_ticket_labels():
    assert tools.label("get_ticket", '{"ticket_id": 12}') == "Looked up ticket #12"
    assert tools.label("list_tickets") == "Looked up tickets (open, pending)"
    args = {"status": ["open"], "priority": ["urgent", "high"]}
    assert tools.label("list_tickets", json.dumps(args)) == "Looked up tickets (open; urgent, high)"
