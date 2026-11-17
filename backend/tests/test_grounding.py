"""The grounding check: numbers in a reply that no tool result contains."""

import json

from app.services.grounding import unsupported_numbers

# The real tool results and reply behind a made-up answer ("compare all the values" for Sep vs Oct).
SEP = {
    "from": "2026-09-01",
    "to": "2026-09-30",
    "days": 30,
    "orders_placed": 43,
    "revenue_before_refunds_usd": 5800.13,
}
OCT = {
    "from": "2026-10-01",
    "to": "2026-10-31",
    "days": 31,
    "orders_placed": 40,
    "revenue_before_refunds_usd": 6836.16,
}
CHANGE = {
    "orders_placed": -3,
    "orders_placed_pct": -7.0,
    "revenue_before_refunds_usd": 1036.03,
    "revenue_before_refunds_usd_pct": 17.9,
}
RESULTS = [json.dumps({"period": OCT, "comparison": SEP, "change": CHANGE})]

REPLY = """**Full month-by-month comparison (September 2026 vs October 2026)**

| Metric | September 2026 | October 2026 | Change (Oct vs Sep) |
|--------|----------------|--------------|---------------------|
| **Orders placed** | 43 | 40 | **-3** (-7 %) |
| **Revenue (before refunds)** | $5,800.13 | $6,836.16 | **+ $1,036.03** (+ 18 %) |
| **Average order value** | $134.88 | $170.90 | **+ $36.02** (+ 27 %) |
| **Open tickets** | 5 (Sept) | 3 (Oct) | -2 (-40 %) |
| **Tickets resolved** | 12 | 9 | -3 (-25 %) |
"""


def test_made_up_and_worked_out_numbers_are_flagged():
    flagged = unsupported_numbers(REPLY, RESULTS)
    # Real figures (and "18" for the tool's 17.9) pass; the average order value the model
    # worked out and the ticket counts it invented are flagged.
    assert flagged == ["134.88", "170.90", "36.02", "27", "5", "2", "12", "9", "25"]


def test_dates_list_numbers_and_rounding_are_not_flagged():
    reply = "1. Sales from 2026-11-09 to 2026-11-15 (Nov 9 – 15): 1,204 orders, up 17.9% (about 18%)."
    sources = [json.dumps({"from": "2026-11-09", "to": "2026-11-15", "orders": 1204, "pct": 17.94})]
    assert unsupported_numbers(reply, sources) == []


def test_numbers_from_the_question_or_earlier_messages_count():
    reply = "Order ORD-00000042 is shipped."
    assert unsupported_numbers(reply, ['{"role": "user", "content": "where is order 42?"}']) == []
    assert unsupported_numbers(reply, []) == ["00000042"]
