# test_driver_routing.py -- Criterion 8 test evidence: FR-A3 role routing for the
# driver portal (login redirect, /driver/dashboard 403 for wrong roles), plus
# FR-E1 docket rendering (assigned deliveries vs. empty-day message).
# Permanent test script -- keep in the repo, do not delete.

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

# 4. FR-E1: a delivery assigned to the driver for today shows client/product/
#    instructions details. Order.place() only allows future dates, so this
#    order is inserted directly (same approach test_delivery_lifecycle.py
#    uses for its bogus-status case) rather than going through the form flow.
TODAY = date.today().isoformat()
SPECIAL_INSTRUCTIONS = "Leave with the cafe next door if no one answers"

connection = get_db_connection()
client_row = connection.execute("SELECT client_id, business_name FROM clients LIMIT 1").fetchone()
product_row = connection.execute("SELECT product_id, product_name FROM products LIMIT 1").fetchone()

order_cursor = connection.execute(
    "INSERT INTO orders (client_id, delivery_date, order_status, special_instructions) VALUES (?, ?, 'approved', ?)",
    (client_row["client_id"], TODAY, SPECIAL_INSTRUCTIONS),
)
order_id = order_cursor.lastrowid
connection.execute(
    "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
    (order_id, product_row["product_id"], 7, 4.50),
)
connection.commit()
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

print("\nAll checks passed.")
