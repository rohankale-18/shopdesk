from datetime import date

from app.db import SessionLocal
from app.services.seed import SeedCounts, seed_database


def find_customer(client, email):
    r = client.get("/api/customers", params={"q": email})
    assert r.status_code == 200
    return r.json()["items"][0]


# ---------- meta ----------


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "X-Request-ID" in r.headers


def test_openapi_has_clean_operation_ids(client):
    ops = {
        op["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for op in path.values()
    }
    assert {"list_orders", "create_refund", "get_ticket", "add_ticket_message"} <= ops


# ---------- seeding ----------


def test_seed_is_deterministic(client):
    def snapshot():
        orders = client.get("/api/orders", params={"page_size": 100, "sort": "id"}).json()
        return [(o["number"], o["total_cents"], o["status"], o["placed_at"]) for o in orders["items"]]

    first = snapshot()
    with SessionLocal() as db:
        seed_database(
            db, seed=1, counts=SeedCounts(15, 12, 40, 10), anchor_date=date(2026, 6, 1)
        )
    assert snapshot() == first


def test_seed_endpoint(client):
    r = client.post("/api/admin/seed?anchor_date=2026-06-01", json={"seed": 7, "customers": 5,
                    "products": 5, "orders": 10, "tickets": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["customers"] == 9  # 5 random + 4 scenario customers
    assert len(body["scenarios"]) == 5


def test_seed_without_reset_on_non_empty_db_is_rejected(client):
    r = client.post("/api/admin/seed", json={"reset": False})
    assert r.status_code == 409


# ---------- customers ----------


def test_customer_search_and_detail(client):
    priya = find_customer(client, "priya.sharma")
    r = client.get(f"/api/customers/{priya['id']}")
    assert r.status_code == 200
    d = r.json()
    assert d["order_count"] >= 1
    assert d["open_ticket_count"] >= 1


def test_customer_create_and_duplicate_email(client):
    payload = {"name": "Test User", "email": "Test.User@Example.com"}
    r = client.post("/api/customers", json=payload)
    assert r.status_code == 201
    assert r.json()["email"] == "test.user@example.com"
    r = client.post("/api/customers", json=payload)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_validation_error_shape(client):
    r = client.post("/api/customers", json={"name": "", "email": "not-an-email"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert {f["field"] for f in err["details"]["fields"]} == {"name", "email"}


def test_not_found_shape(client):
    r = client.get("/api/customers/999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert "hint" in r.json()["error"]["details"]


def test_bad_sort_field(client):
    r = client.get("/api/customers", params={"sort": "password"})
    assert r.status_code == 400
    assert "allowed" in r.json()["error"]["details"]


# ---------- products ----------


def test_product_filters(client):
    r = client.get("/api/products", params={"in_stock": False, "page_size": 100})
    assert all(p["stock"] == 0 for p in r.json()["items"])
    assert any(p["sku"] == "SCN-0003" for p in r.json()["items"])


def test_archive_product(client):
    pid = client.get("/api/products", params={"q": "SCN-0002"}).json()["items"][0]["id"]
    r = client.delete(f"/api/products/{pid}")
    assert r.status_code == 200 and r.json()["is_active"] is False


# ---------- orders ----------


def _new_order(client, qty=1, sku="SCN-0004"):
    cust = find_customer(client, "marcus.lee")
    product = client.get("/api/products", params={"q": sku}).json()["items"][0]
    r = client.post(
        "/api/orders",
        json={
            "customer_id": cust["id"],
            "items": [{"product_id": product["id"], "quantity": qty}],
            "shipping_address": "221B Baker Street, London",
        },
    )
    return r, product


def test_create_order_decrements_stock(client):
    r, product = _new_order(client, qty=3)
    assert r.status_code == 201
    order = r.json()
    assert order["status"] == "pending"
    assert order["total_cents"] == product["price_cents"] * 3
    after = client.get(f"/api/products/{product['id']}").json()
    assert after["stock"] == product["stock"] - 3


def test_create_order_insufficient_stock(client):
    r, _ = _new_order(client, sku="SCN-0003")  # stock 0
    assert r.status_code == 422
    assert r.json()["error"]["details"]["items"][0]["problem"] == "insufficient_stock"


def test_order_lifecycle(client):
    order = _new_order(client)[0].json()
    oid = order["id"]
    for target in ["paid", "shipped", "delivered"]:
        r = client.post(f"/api/orders/{oid}/status", json={"status": target})
        assert r.status_code == 200, r.json()
    final = r.json()
    assert final["tracking_number"] and final["delivered_at"]

    r = client.post(f"/api/orders/{oid}/status", json={"status": "paid"})
    assert r.status_code == 422
    assert r.json()["error"]["details"]["allowed_targets"] == []


def test_cancel_restocks(client):
    r, product = _new_order(client, qty=2)
    oid = r.json()["id"]
    r = client.post(f"/api/orders/{oid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.get(f"/api/products/{product['id']}").json()["stock"] == product["stock"]


def test_cannot_cancel_delivered_order(client):
    o = client.get("/api/orders/by-number/ORD-00000001").json()
    r = client.post(f"/api/orders/{o['id']}/cancel")
    assert r.status_code == 422


def test_partial_refund_limit_scenario(client):
    o = client.get("/api/orders/by-number/ORD-00000003").json()
    assert o["refundable_cents"] == 19999
    r = client.post(
        f"/api/orders/{o['id']}/refunds", json={"amount_cents": 24998, "reason": "other"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"]["refundable_cents"] == 19999

    r = client.post(
        f"/api/orders/{o['id']}/refunds", json={"amount_cents": 19999, "reason": "other"}
    )
    assert r.status_code == 201
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "refunded"


def test_order_filters(client):
    r = client.get("/api/orders", params=[("status", "paid"), ("status", "shipped")])
    assert r.status_code == 200
    assert {o["status"] for o in r.json()["items"]} <= {"paid", "shipped"}


# ---------- tickets ----------


def test_ticket_flow(client):
    james = find_customer(client, "james.okafor")
    r = client.post(
        "/api/tickets",
        json={"customer_id": james["id"], "subject": "Hello there", "message": "Need help"},
    )
    assert r.status_code == 201
    tid = r.json()["id"]

    r = client.patch(f"/api/tickets/{tid}", json={"status": "pending", "assignee": "asha"})
    assert r.json()["status"] == "pending"

    r = client.post(f"/api/tickets/{tid}/messages", json={"author": "customer", "body": "Any update?"})
    assert r.status_code == 201
    t = client.get(f"/api/tickets/{tid}").json()
    assert t["status"] == "open"  # customer reply re-opens
    assert len(t["messages"]) == 2


def test_ticket_order_must_belong_to_customer(client):
    james = find_customer(client, "james.okafor")
    priya_order = client.get("/api/orders/by-number/ORD-00000001").json()
    r = client.post(
        "/api/tickets",
        json={"customer_id": james["id"], "order_id": priya_order["id"],
              "subject": "Wrong", "message": "x"},
    )
    assert r.status_code == 422


def test_closed_ticket_rejects_messages(client):
    tid = client.get("/api/tickets", params={"page_size": 1}).json()["items"][0]["id"]
    client.patch(f"/api/tickets/{tid}", json={"status": "closed"})
    r = client.post(f"/api/tickets/{tid}/messages", json={"body": "hello"})
    assert r.status_code == 422


# ---------- stats ----------


def test_stats_overview(client):
    r = client.get("/api/stats/overview")
    assert r.status_code == 200
    s = r.json()
    assert s["orders"] == 44
    assert len(s["revenue_last_30_days"]) == 30
    assert sum(s["orders_by_status"].values()) == s["orders"]


def test_seed_meets_large_product_count(client):
    # More products than there are unique word combinations in the catalog.
    r = client.post(
        "/api/admin/seed",
        json={"seed": 3, "customers": 5, "products": 2500, "orders": 5, "tickets": 1},
    )
    assert r.status_code == 200
    assert r.json()["products"] == 2504  # 2500 requested + 4 scenario products
    assert client.get("/api/products", params={"page_size": 1}).json()["total"] == 2504
