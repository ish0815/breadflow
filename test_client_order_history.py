# test_client_order_history.py -- Criterion 8 test evidence: Module 10 client order
# history page (routes/orders.py client_order_history, models/order.py
# Order.list_for_client()/get_client_summary()) -- FR-A3 session scoping and the 4
# summary-card figures.
# Permanent test script -- keep in the repo, do not delete.

from datetime import date, timedelta

from app import app
from database.db import get_db_connection
from models.order import Order

app.config["TESTING"] = True
client = app.test_client()

TODAY = date.today().isoformat()
NEXT_MONTH = (date.today() + timedelta(days=60)).isoformat()  # always a different month than TODAY
THIS_MONTH = date.today().strftime("%Y-%m")


def seed_session(user_id, role, client_id):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role
        sess["client_id"] = client_id


def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@order-history-test.local",),
    )
    user_id = user_cursor.lastrowid
    client_cursor = connection.execute(
        """
        INSERT INTO clients (user_id, business_name, abn, delivery_zone,
            delivery_day1, delivery_day2, delivery_charge)
        VALUES (?, ?, ?, 'Western', 'Monday', 'Thursday', 15.0)
        """,
        (user_id, business_name, abn),
    )
    client_id = client_cursor.lastrowid
    connection.commit()
    return client_id, user_id


def _make_order(connection, client_id, status, delivery_date, product_id, quantity, unit_price):
    order_cursor = connection.execute(
        "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, ?)",
        (client_id, delivery_date, status),
    )
    order_id = order_cursor.lastrowid
    connection.execute(
        "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
        (order_id, product_id, quantity, unit_price),
    )
    connection.commit()
    return order_id


client_ids = []
order_ids = {}

try:
    connection = get_db_connection()
    try:
        product_row = connection.execute("SELECT product_id FROM products LIMIT 1").fetchone()
        product_id = product_row["product_id"]

        client_a_id, user_a_id = _make_test_client(connection, "History Test Client A", "92000000001")
        client_b_id, user_b_id = _make_test_client(connection, "History Test Client B", "92000000002")
        client_ids.append((client_a_id, user_a_id))
        client_ids.append((client_b_id, user_b_id))

        order_ids["A1_pending"] = _make_order(connection, client_a_id, "pending", TODAY, product_id, 2, 5.00)
        order_ids["A2_approved"] = _make_order(connection, client_a_id, "approved", TODAY, product_id, 1, 20.00)
        order_ids["A3_rejected"] = _make_order(connection, client_a_id, "rejected", TODAY, product_id, 5, 100.00)
        order_ids["A4_delivered_other_month"] = _make_order(
            connection, client_a_id, "delivered", NEXT_MONTH, product_id, 3, 10.00
        )
        order_ids["B1_pending"] = _make_order(connection, client_b_id, "pending", TODAY, product_id, 1, 50.00)
    finally:
        connection.close()

    # 1. FR-A3: client A's history never includes client B's order, and vice versa
    seed_session(user_a_id, "client", client_a_id)
    response = client.get("/client/orders?per_page=100")
    assert response.status_code == 200, response.status_code
    for key in ("A1_pending", "A2_approved", "A3_rejected", "A4_delivered_other_month"):
        assert f"#{order_ids[key]}".encode() in response.data, f"missing {key}"
    assert f"#{order_ids['B1_pending']}".encode() not in response.data
    print("PASS: client A's order history includes only client A's own orders")

    seed_session(user_b_id, "client", client_b_id)
    response = client.get("/client/orders?per_page=100")
    assert f"#{order_ids['B1_pending']}".encode() in response.data
    for key in ("A1_pending", "A2_approved", "A3_rejected", "A4_delivered_other_month"):
        assert f"#{order_ids[key]}".encode() not in response.data
    print("PASS: client B's order history never includes client A's orders")

    # 2. summary cards: total=4, pending=1, this month spend=30.00 (A1+A2, A3 rejected
    # excluded, A4 in a different month excluded), lifetime spend=60.00 (A1+A2+A4)
    summary = Order.get_client_summary(client_a_id)
    assert summary["total_order_count"] == 4, summary
    assert summary["pending_count"] == 1, summary
    assert summary["this_month_spend"] == 30.00, summary
    assert summary["lifetime_spend"] == 60.00, summary
    print("PASS: summary cards match a hand-computed expectation")

    seed_session(user_a_id, "client", client_a_id)
    response = client.get("/client/orders")
    assert b"$30.00" in response.data, response.data
    assert b"$60.00" in response.data, response.data
    print("PASS: summary card figures render on the page")

    # 3. status filter
    response = client.get("/client/orders?status=Rejected&per_page=100")
    assert f"#{order_ids['A3_rejected']}".encode() in response.data
    assert f"#{order_ids['A1_pending']}".encode() not in response.data
    print("PASS: status filter shows only rejected orders")

    # 4. month filter -- this month excludes the order placed 2 months out
    response = client.get(f"/client/orders?month={THIS_MONTH}&per_page=100")
    assert f"#{order_ids['A1_pending']}".encode() in response.data
    assert f"#{order_ids['A4_delivered_other_month']}".encode() not in response.data
    print("PASS: month filter excludes orders outside the selected month")

    print("\nAll checks passed.")
finally:
    cleanup_connection = get_db_connection()
    try:
        for client_id, user_id in client_ids:
            cleanup_connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(f"cleanup: removed {len(client_ids)} test client(s) (orders cascade with them)")
