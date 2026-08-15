# test_driver_routing.py -- Criterion 8 test evidence: FR-A3 role routing for the
# driver portal (login redirect, /driver/dashboard 403 for wrong roles), plus
# FR-E1 docket rendering (assigned deliveries vs. empty-day message) and FR-E2
# mark-as-delivered (photo validation, ownership check).
# Permanent test script -- keep in the repo, do not delete.

import contextlib
import io
from datetime import date

from app import app
from database.db import get_db_connection
from models.delivery import Delivery

app.config["TESTING"] = True
client = app.test_client()

# real account IDs from the committed DB (see users table)
OWNER_ID, CLIENT_ID, DRIVER_ID = 1, 3, 13


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


# no Pillow available -- just needs bytes/filename the route's extension+mimetype check will accept
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 200


# Order.place() only allows future dates, so an approved order for today is inserted directly
# connection closes in finally -- a failed statement must not leave a lock-holding connection open
def _make_approved_order_and_delivery(driver_id):
    connection = get_db_connection()
    try:
        client_row = connection.execute("SELECT client_id FROM clients LIMIT 1").fetchone()
        product_row = connection.execute("SELECT product_id FROM products LIMIT 1").fetchone()
        order_cursor = connection.execute(
            "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, 'approved')",
            (client_row["client_id"], date.today().isoformat()),
        )
        order_id = order_cursor.lastrowid
        connection.execute(
            "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, 1, 1.0)",
            (order_id, product_row["product_id"]),
        )
        connection.commit()
    finally:
        connection.close()
    return order_id, Delivery.create(order_id, driver_id)


# order_ids this script inserts -- deleted in finally below; order_lines/deliveries
# cascade with them (ON DELETE CASCADE, FK pragma on in db.py)
created_order_ids = []
second_driver_id = None  # set in test 9 if that block runs

try:
    # 1. driver session -> GET /login (the "already logged in" branch) should redirect
    #    to /driver/dashboard via DASHBOARD_ENDPOINT["driver"] = "driver.dashboard"
    seed_session(DRIVER_ID, "driver")
    response = client.get("/login")
    assert response.status_code == 302, f"expected 302, got {response.status_code}"
    assert response.headers["Location"] == "/driver/dashboard", response.headers["Location"]
    print("PASS: driver session redirects /login -> /driver/dashboard")

    followed = client.get("/driver/dashboard")
    assert followed.status_code == 200, followed.status_code
    assert b"Today's deliveries" in followed.data
    print("PASS: /driver/dashboard renders (200)")

    # 2. owner/client sessions must be blocked from /driver/dashboard with 403
    seed_session(OWNER_ID, "owner")
    response = client.get("/driver/dashboard")
    assert response.status_code == 403, f"owner expected 403, got {response.status_code}"
    print("PASS: owner session gets 403 on /driver/dashboard")

    seed_session(CLIENT_ID, "client")
    response = client.get("/driver/dashboard")
    assert response.status_code == 403, f"client expected 403, got {response.status_code}"
    print("PASS: client session gets 403 on /driver/dashboard")

    # 3. owner/client dashboards still work unchanged
    seed_session(OWNER_ID, "owner")
    response = client.get("/owner/dashboard")
    assert response.status_code == 200, response.status_code
    print("PASS: /owner/dashboard still 200")

    seed_session(CLIENT_ID, "client")
    response = client.get("/client/dashboard")
    assert response.status_code == 200, response.status_code
    print("PASS: /client/dashboard still 200")

    # 4. FR-E1: a delivery assigned today shows client/product/instructions on the docket
    TODAY = date.today().isoformat()
    SPECIAL_INSTRUCTIONS = "Leave with the cafe next door if no one answers"

    connection = get_db_connection()
    try:
        client_row = connection.execute("SELECT client_id, business_name FROM clients LIMIT 1").fetchone()
        product_row = connection.execute("SELECT product_id, product_name FROM products LIMIT 1").fetchone()

        order_cursor = connection.execute(
            "INSERT INTO orders (client_id, delivery_date, order_status, special_instructions) "
            "VALUES (?, ?, 'approved', ?)",
            (client_row["client_id"], TODAY, SPECIAL_INSTRUCTIONS),
        )
        order_id = order_cursor.lastrowid
        created_order_ids.append(order_id)
        connection.execute(
            "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, product_row["product_id"], 7, 4.50),
        )
        connection.commit()
    finally:
        connection.close()

    Delivery.create(order_id, DRIVER_ID)

    seed_session(DRIVER_ID, "driver")
    response = client.get("/driver/dashboard")
    assert response.status_code == 200, response.status_code
    assert client_row["business_name"].encode() in response.data
    assert product_row["product_name"].encode() in response.data
    assert SPECIAL_INSTRUCTIONS.encode() in response.data
    print("PASS: /driver/dashboard shows client, product, and special instructions for an assigned delivery")

    # 5. FR-E1: a date with no deliveries assigned shows the empty-docket message
    response = client.get("/driver/dashboard?date=2099-01-01")
    assert response.status_code == 200, response.status_code
    assert b"No deliveries scheduled" in response.data
    print("PASS: /driver/dashboard shows 'No deliveries scheduled' for a date with no assignments")

    # 6. FR-E2: valid photo upload updates both the delivery/order, and notifies owner + client
    order_id, delivery = _make_approved_order_and_delivery(DRIVER_ID)
    created_order_ids.append(order_id)
    seed_session(DRIVER_ID, "driver")
    captured_output = io.StringIO()
    with contextlib.redirect_stdout(captured_output):
        response = client.post(
            f"/driver/delivery/{delivery.delivery_id}/deliver",
            data={"photo": (io.BytesIO(FAKE_JPEG_BYTES), "proof.jpg")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert response.status_code == 200, response.status_code
    assert b"Delivery marked as complete." in response.data
    assert Delivery.get_by_id(delivery.delivery_id).delivery_status == "delivered"
    connection = get_db_connection()
    try:
        order_status = connection.execute(
            "SELECT order_status FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()["order_status"]
    finally:
        connection.close()
    assert order_status == "delivered", order_status
    print("PASS: valid photo upload marks delivery and order as delivered")

    stub_output = captured_output.getvalue()
    assert f"order {order_id}" in stub_output and "owner notified" in stub_output, stub_output
    assert f"order {order_id}" in stub_output and "client notified: delivered on" in stub_output, stub_output
    print("PASS: mark-as-delivered prints owner and client delivery notification stubs")

    # 7. FR-E2: wrong file type is rejected, delivery stays pending
    order_id2, delivery2 = _make_approved_order_and_delivery(DRIVER_ID)
    created_order_ids.append(order_id2)
    response = client.post(
        f"/driver/delivery/{delivery2.delivery_id}/deliver",
        data={"photo": (io.BytesIO(b"not an image"), "proof.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200, response.status_code
    assert b"must be a JPEG or PNG" in response.data
    assert Delivery.get_by_id(delivery2.delivery_id).delivery_status == "pending"
    print("PASS: wrong file type rejected, delivery stays pending")

    # 8. FR-E2: oversized file is rejected, delivery stays pending
    order_id3, delivery3 = _make_approved_order_and_delivery(DRIVER_ID)
    created_order_ids.append(order_id3)
    oversized = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post(
        f"/driver/delivery/{delivery3.delivery_id}/deliver",
        data={"photo": (io.BytesIO(oversized), "proof.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200, response.status_code
    assert b"10MB or smaller" in response.data
    assert Delivery.get_by_id(delivery3.delivery_id).delivery_status == "pending"
    print("PASS: oversized photo rejected, delivery stays pending")

    # 9. FR-E2: a driver gets 403 marking another driver's delivery as delivered
    # closes in finally -- this INSERT can legitimately fail (duplicate email on a rerun)
    connection = get_db_connection()
    try:
        second_driver_cursor = connection.execute(
            "INSERT INTO users (email, password_hash, role) VALUES ('driver2-test@breadflow.local', 'x', 'driver')"
        )
        second_driver_id = second_driver_cursor.lastrowid
        connection.commit()
    finally:
        connection.close()

    order_id4, delivery4 = _make_approved_order_and_delivery(second_driver_id)
    created_order_ids.append(order_id4)
    seed_session(DRIVER_ID, "driver")  # logged in as the original test driver, not second_driver_id
    response = client.post(
        f"/driver/delivery/{delivery4.delivery_id}/deliver",
        data={"photo": (io.BytesIO(FAKE_JPEG_BYTES), "proof.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    assert Delivery.get_by_id(delivery4.delivery_id).delivery_status == "pending"
    print("PASS: driver gets 403 marking another driver's delivery, delivery stays pending")

    print("\nAll checks passed.")
finally:
    # cleanup -- deletes only rows this script created; OWNER_ID/CLIENT_ID/DRIVER_ID and
    # real clients/products are pre-existing, never touched. Runs even on failure.
    cleanup_connection = get_db_connection()
    try:
        for order_id_to_remove in created_order_ids:
            cleanup_connection.execute("DELETE FROM orders WHERE order_id = ?", (order_id_to_remove,))
        if second_driver_id is not None:
            cleanup_connection.execute("DELETE FROM users WHERE user_id = ?", (second_driver_id,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(
        f"cleanup: removed {len(created_order_ids)} test order(s) "
        f"(order_lines/deliveries cascade with them)"
        + (", and 1 test driver user" if second_driver_id is not None else "")
    )
