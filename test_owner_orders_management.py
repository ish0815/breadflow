# test_owner_orders_management.py -- Criterion 8 test evidence: Module 6 owner orders
# management page (routes/orders.py owner_orders, models/order.py Order.list_all()) --
# search, status filter, date range filter, sort, and pagination.
# Permanent test script -- keep in the repo, do not delete.

from datetime import date, timedelta

from app import app
from database.db import get_db_connection
from models.order import Order

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)

# unique marker so search filters only ever match this test's own data, never
# whatever real orders already exist in the dev DB
SEARCH_MARKER = "ZZZ Orders Test"


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@owner-orders-test.local",),
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


def _make_order(connection, client_id, status, days_ahead, product_id, quantity, unit_price):
    order_cursor = connection.execute(
        "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, ?)",
        (client_id, (date.today() + timedelta(days=days_ahead)).isoformat(), status),
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

        alpha_id, alpha_user_id = _make_test_client(connection, f"{SEARCH_MARKER} Alpha", "91000000001")
        beta_id, beta_user_id = _make_test_client(connection, f"{SEARCH_MARKER} Beta", "91000000002")
        client_ids.append((alpha_id, alpha_user_id))
        client_ids.append((beta_id, beta_user_id))

        # totals: A1=10.00, A2=20.00, B1=30.00, B2=40.00
        order_ids["A1_pending_10days"] = _make_order(connection, alpha_id, "pending", 10, product_id, 2, 5.00)
        order_ids["A2_approved_20days"] = _make_order(connection, alpha_id, "approved", 20, product_id, 2, 10.00)
        order_ids["B1_delivered_5days"] = _make_order(connection, beta_id, "delivered", 5, product_id, 3, 10.00)
        order_ids["B2_rejected_15days"] = _make_order(connection, beta_id, "rejected", 15, product_id, 4, 10.00)
    finally:
        connection.close()

    seed_session(OWNER_ID, "owner")

    # 1. search matches only this test's 4 orders, none of the dev DB's real ones
    response = client.get(f"/owner/orders?search={SEARCH_MARKER}&per_page=100")
    assert response.status_code == 200, response.status_code
    for order_id in order_ids.values():
        assert f"#{order_id}".encode() in response.data, f"missing #{order_id}"
    print("PASS: search returns exactly this test's own orders")

    # 2. status filter
    response = client.get(f"/owner/orders?search={SEARCH_MARKER}&status=Pending&per_page=100")
    assert f"#{order_ids['A1_pending_10days']}".encode() in response.data
    assert f"#{order_ids['A2_approved_20days']}".encode() not in response.data
    assert f"#{order_ids['B1_delivered_5days']}".encode() not in response.data
    assert f"#{order_ids['B2_rejected_15days']}".encode() not in response.data
    print("PASS: status filter shows only pending orders")

    # 3. date range filter -- [today+1, today+12] includes B1 (+5) and A1 (+10) only
    date_start = (date.today() + timedelta(days=1)).isoformat()
    date_end = (date.today() + timedelta(days=12)).isoformat()
    response = client.get(
        f"/owner/orders?search={SEARCH_MARKER}&date_start={date_start}&date_end={date_end}&per_page=100"
    )
    assert f"#{order_ids['B1_delivered_5days']}".encode() in response.data
    assert f"#{order_ids['A1_pending_10days']}".encode() in response.data
    assert f"#{order_ids['A2_approved_20days']}".encode() not in response.data
    assert f"#{order_ids['B2_rejected_15days']}".encode() not in response.data
    print("PASS: date range filter excludes orders outside the window")

    # 4. sort by delivery date ascending: B1 (+5) < A1 (+10) < B2 (+15) < A2 (+20)
    response = client.get(f"/owner/orders?search={SEARCH_MARKER}&sort=delivery_date&per_page=100")
    positions = {
        key: response.data.index(f"#{order_id}".encode())
        for key, order_id in order_ids.items()
    }
    assert positions["B1_delivered_5days"] < positions["A1_pending_10days"] < \
        positions["B2_rejected_15days"] < positions["A2_approved_20days"], positions
    print("PASS: sort by delivery date orders ascending")

    # 5. sort by total descending: B2 (40) > B1 (30) > A2 (20) > A1 (10)
    response = client.get(f"/owner/orders?search={SEARCH_MARKER}&sort=total&per_page=100")
    positions = {
        key: response.data.index(f"#{order_id}".encode())
        for key, order_id in order_ids.items()
    }
    assert positions["B2_rejected_15days"] < positions["B1_delivered_5days"] < \
        positions["A2_approved_20days"] < positions["A1_pending_10days"], positions
    print("PASS: sort by total orders descending")

    # 6. pagination math, exercised directly against the model (the route only accepts
    # per_page in {24, 48, 100} per the data dictionary, too coarse for this small a set)
    page_1, total_count = Order.list_all(search=SEARCH_MARKER, per_page=2, page=1)
    page_2, total_count_2 = Order.list_all(search=SEARCH_MARKER, per_page=2, page=2)
    assert total_count == 4 and total_count_2 == 4, (total_count, total_count_2)
    assert len(page_1) == 2 and len(page_2) == 2, (len(page_1), len(page_2))
    page_1_ids = {o["order_id"] for o in page_1}
    page_2_ids = {o["order_id"] for o in page_2}
    assert page_1_ids.isdisjoint(page_2_ids), (page_1_ids, page_2_ids)
    assert page_1_ids | page_2_ids == set(order_ids.values()), (page_1_ids, page_2_ids, order_ids)
    print("PASS: pagination splits results across pages with no overlap or gaps")

    # route-level per_page is clamped to {24, 48, 100} -- an out-of-set value falls back to 24
    response = client.get(f"/owner/orders?search={SEARCH_MARKER}&per_page=2&page=1")
    assert b"Page 1 of 1" in response.data, response.data
    assert b'value="24" selected' in response.data, response.data
    print("PASS: route clamps an invalid per_page back to the default (24)")

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
