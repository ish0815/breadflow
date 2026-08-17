# test_order_rejection_reason.py -- Criterion 8 test evidence: FR-B4 rejection reason
# (routes/orders.py reject_order, models/order.py Order.reject()), covering both a
# reason being stored + emailed, and rejecting with no reason at all.
# Permanent test script -- keep in the repo, do not delete.

from datetime import date, timedelta

from app import app
from database.db import get_db_connection
from email_utils import mail

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


# Order.place() only allows future dates on the client's assigned weekdays, so a pending
# order is inserted directly, matching test_driver_routing.py's approach.
def _make_pending_order(connection, client_id, product_id):
    order_cursor = connection.execute(
        "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, 'pending')",
        (client_id, (date.today() + timedelta(days=7)).isoformat()),
    )
    order_id = order_cursor.lastrowid
    connection.execute(
        "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, 2, 5.00)",
        (order_id, product_id),
    )
    connection.commit()
    return order_id


created_order_ids = []

try:
    connection = get_db_connection()
    try:
        client_row = connection.execute("SELECT client_id FROM clients LIMIT 1").fetchone()
        product_row = connection.execute("SELECT product_id FROM products LIMIT 1").fetchone()
    finally:
        connection.close()

    seed_session(OWNER_ID, "owner")

    # 1. FR-B4: rejecting with a reason stores it and includes it in the notification email
    connection = get_db_connection()
    try:
        order_id = _make_pending_order(connection, client_row["client_id"], product_row["product_id"])
    finally:
        connection.close()
    created_order_ids.append(order_id)

    with mail.record_messages() as outbox:
        response = client.post(
            f"/owner/orders/{order_id}/reject", data={"reason": "Out of ingredients"}, follow_redirects=True
        )
    assert response.status_code == 200, response.status_code
    assert f"Order #{order_id} rejected.".encode() in response.data
    print("PASS: rejecting a pending order with a reason succeeds")

    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT order_status, rejection_reason FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row["order_status"] == "rejected", row["order_status"]
    assert row["rejection_reason"] == "Out of ingredients", row["rejection_reason"]
    print("PASS: rejection_reason is stored on the order")

    # TESTING=True (set above) makes Flask-Mail suppress real SMTP sends automatically --
    # record_messages() still captures them via blinker signals, so no network call happens here.
    assert len(outbox) == 1, outbox
    assert "Reason: Out of ingredients" in outbox[0].body, outbox[0].body
    print("PASS: rejection notification email includes the reason")

    # 2. FR-B4: rejecting with no reason leaves rejection_reason NULL, no "Reason:" in the email
    connection = get_db_connection()
    try:
        order_id_2 = _make_pending_order(connection, client_row["client_id"], product_row["product_id"])
    finally:
        connection.close()
    created_order_ids.append(order_id_2)

    with mail.record_messages() as outbox:
        response = client.post(f"/owner/orders/{order_id_2}/reject", data={}, follow_redirects=True)
    assert response.status_code == 200, response.status_code

    connection = get_db_connection()
    try:
        row_2 = connection.execute(
            "SELECT order_status, rejection_reason FROM orders WHERE order_id = ?", (order_id_2,)
        ).fetchone()
    finally:
        connection.close()
    assert row_2["order_status"] == "rejected", row_2["order_status"]
    assert row_2["rejection_reason"] is None, row_2["rejection_reason"]
    assert "Reason:" not in outbox[0].body, outbox[0].body
    print("PASS: rejecting without a reason stores NULL and omits 'Reason:' from the email")

    print("\nAll checks passed.")
finally:
    cleanup_connection = get_db_connection()
    try:
        for order_id_to_remove in created_order_ids:
            cleanup_connection.execute("DELETE FROM orders WHERE order_id = ?", (order_id_to_remove,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(f"cleanup: removed {len(created_order_ids)} test order(s)")
