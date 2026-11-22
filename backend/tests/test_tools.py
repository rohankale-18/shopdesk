"""The assistant's tools, called directly (no model involved)."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Order, OrderStatus, Product, Refund, Ticket
from app.services import tools
from app.services.chat import SYSTEM_PROMPT
from app.services.stats import LOW_STOCK

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


# ---------- search_products ----------


def test_search_products_by_name_or_sku(client):
    by_name = run("search_products", query="yoga mat")
    by_sku = run("search_products", query="scn-0003")
    assert by_name["products"][0] == by_sku["products"][0]
    mat = by_sku["products"][0]
    assert (mat["name"], mat["stock"], mat["stock_status"]) == ("Grip Pro Yoga Mat", 0, "out_of_stock")
    assert "restock dates" in by_sku["not_recorded"]  # the gap is stated, not left for the model to fill


def test_running_low_means_1_to_5_left_and_for_sale(client):
    low = run("search_products", stock="low")
    with SessionLocal() as db:
        expected = db.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.stock.between(1, LOW_STOCK), Product.is_active.is_(True))
        )
    assert low["total_matches"] == expected
    assert all(p["stock_status"] == "low" for p in low["products"])
    stocks = [p["stock"] for p in low["products"]]
    assert stocks == sorted(stocks)  # fewest left first
    sold_out = run("search_products", stock="out_of_stock")
    assert "Grip Pro Yoga Mat" in [p["name"] for p in sold_out["products"]]


def test_overview_and_search_agree_on_low_stock(client):
    overview = run("get_store_overview")["low_stock_products"]
    assert {p["stock_status"] for p in overview} <= {"low", "out_of_stock"}
    assert all(p["stock"] <= LOW_STOCK for p in overview)
    assert f"1 to {LOW_STOCK} left" in SYSTEM_PROMPT  # the prompt's definition matches the code


def test_products_not_for_sale_are_marked(client):
    with SessionLocal() as db:
        lamp = db.scalar(select(Product).where(Product.sku == "SCN-0002"))
        lamp.is_active = False
        db.commit()
    (lamp,) = run("search_products", query="Halo Desk Lamp")["products"]
    assert lamp["stock_status"] == "not_for_sale"


def test_search_products_by_category_and_no_match(client):
    sports = run("search_products", category="sports")
    assert sports["products"] and {p["category"] for p in sports["products"]} == {"sports"}
    nothing = run("search_products", query="hovercraft")
    assert nothing["total_matches"] == 0 and "Don't repeat the search" in nothing["next_step"]


def test_available_includes_low_stock(client):
    """Alternatives to suggest: anything that can be bought now, even with only a few left."""
    available = run("search_products", stock="available", category="sports")
    assert all(p["stock"] > 0 and p["stock_status"] in ("low", "in_stock") for p in available["products"])
    low = run("search_products", stock="low", category="sports")
    in_stock = run("search_products", stock="in_stock", category="sports")
    assert available["total_matches"] == low["total_matches"] + in_stock["total_matches"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"stock": "sold out"}, "stock can only be available, out_of_stock, low, in_stock"),
        ({"category": "toys"}, "category can only be"),
        ({"query": "x"}, "at least 2 characters"),
    ],
)
def test_bad_product_filters_go_back_to_the_model(client, arguments, message):
    assert message in run("search_products", **arguments)["error"]


def test_product_labels():
    assert tools.label("search_products", '{"query": "mat"}') == "Searched products for “mat”"
    assert tools.label("search_products", '{"stock": "out_of_stock"}') == "Looked up products (out of stock)"
    assert tools.label("search_products") == "Looked up products"


# ---------- sales_over_time, top_products (data for charts) ----------


def test_sales_over_time_adds_up_to_get_sales(client):
    for interval in ("day", "week", "month"):
        result = run("sales_over_time", start_date=PERIOD[0], end_date=PERIOD[1], interval=interval)
        sales = run("get_sales", start_date=PERIOD[0], end_date=PERIOD[1])["period"]
        assert result["totals"] == {
            "orders": sales["orders_placed"],
            "revenue_usd": sales["revenue_before_refunds_usd"],
        }
        assert sum(r["orders"] for r in result["rows"]) == sales["orders_placed"]
        assert sum(r["days"] for r in result["rows"]) == 31  # every day counted once


def test_sales_over_time_periods(client):
    days = run("sales_over_time", start_date="2026-05-01", end_date="2026-05-31")["rows"]
    assert [r["period"] for r in days[:2]] == ["2026-05-01", "2026-05-02"] and len(days) == 31  # zeros kept
    weeks = run("sales_over_time", start_date="2026-05-01", end_date="2026-05-31", interval="week")["rows"]
    assert weeks[0] == {**weeks[0], "period": "2026-04-27", "days": 3}  # Monday; Fri-Sun in range
    months = run("sales_over_time", start_date="2026-04-15", end_date="2026-05-31", interval="month")["rows"]
    assert [(r["period"], r["days"]) for r in months] == [("2026-04", 16), ("2026-05", 31)]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start_date": "2026-01-01", "end_date": "2026-05-31"}, "Use a longer interval"),
        ({"start_date": "2026-05-01", "end_date": "2026-05-31", "interval": "hour"}, "interval can only be"),
    ],
)
def test_bad_sales_over_time_arguments(client, arguments, message):
    assert message in run("sales_over_time", **arguments)["error"]


def test_top_products_match_the_order_items(client):
    by_units = run("top_products", start_date=PERIOD[0], end_date=PERIOD[1], limit=10)
    within = lambda when: date(2026, 5, 1) <= when.astimezone(UTC).date() <= date(2026, 5, 31)  # noqa: E731
    units: dict[str, int] = {}
    with SessionLocal() as db:
        for o in db.scalars(select(Order)):
            if within(o.placed_at) and o.status != OrderStatus.cancelled:
                for i in o.items:
                    units[i.product_name] = units.get(i.product_name, 0) + i.quantity
    assert by_units["products_sold"] == len(units)
    top = by_units["rows"][0]
    assert top["rank"] == 1 and top["units_sold"] == max(units.values()) == units[top["product"]]
    ranked = [r["units_sold"] for r in by_units["rows"]]
    assert ranked == sorted(ranked, reverse=True)
    by_revenue = run("top_products", start_date=PERIOD[0], end_date=PERIOD[1], by="revenue", limit=3)
    revenue = [r["revenue_usd"] for r in by_revenue["rows"]]
    assert len(revenue) == 3 and revenue == sorted(revenue, reverse=True)


def test_data_tools_give_rows_a_chart_can_point_at(client):
    result = run("top_products", start_date=PERIOD[0], end_date=PERIOD[1])
    ref = result["data_ref"]
    assert ref.isalpha() and len(ref) == 6  # no digits for the grounding check to pick up
    assert tools.chart_data(result) == {"ref": ref, "rows": result["rows"]}
    assert tools.chart_data(run("get_store_overview")) is None


def test_data_tool_labels():
    args = {"start_date": "2026-05-01", "end_date": "2026-05-31", "interval": "week"}
    assert (
        tools.label("sales_over_time", json.dumps(args))
        == "Looked up sales per week, 2026-05-01 to 2026-05-31"
    )
    assert tools.label("top_products", json.dumps(args)) == "Looked up top products, 2026-05-01 to 2026-05-31"


def test_top_products_totals_are_worked_out_in_code(client):
    result = run("top_products", start_date=PERIOD[0], end_date=PERIOD[1], limit=3)
    shown, everything = result["totals"]["shown"], result["totals"]["all_products"]
    assert shown["units_sold"] == sum(r["units_sold"] for r in result["rows"])
    sales = run("get_sales", start_date=PERIOD[0], end_date=PERIOD[1])["period"]
    assert everything["revenue_usd"] == sales["revenue_before_refunds_usd"]  # every item of every order
