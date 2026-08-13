# test_delivery_lifecycle.py -- Criterion 8 test evidence: Delivery.create/get_by_id/
# get_by_driver_and_date/mark_delivered + the delivery_status CHECK constraint.
# Permanent test script -- keep in the repo, do not delete.

from database.db import get_db_connection
from models.delivery import Delivery, DeliveryValidationError, DeliveryStateError

connection = get_db_connection()
try:
    order_row = connection.execute("SELECT order_id FROM orders WHERE order_status = 'approved' LIMIT 1").fetchone()
    driver_row = connection.execute("SELECT user_id FROM users WHERE role = 'driver' AND is_active = 1 LIMIT 1").fetchone()
finally:
    connection.close()

order_id = order_row["order_id"]
driver_id = driver_row["user_id"]
print("order_id:", order_id, "driver_id:", driver_id)

# order_id/driver_id are pre-existing seeded rows, never touched by cleanup below --
# this delivery is the only row this script inserts.
d = Delivery.create(order_id, driver_id)
print("created delivery_id:", d.delivery_id, "status:", d.delivery_status)

try:
    fetched = Delivery.get_by_id(d.delivery_id)
    print("get_by_id status:", fetched.delivery_status)

    docket = Delivery.get_by_driver_and_date(driver_id, d.delivery_date)
    print("docket count for driver/date:", len(docket))

    d.mark_delivered("/fake/path.jpg")
    print("after mark_delivered:", d.delivery_status, d.delivered_at)

    try:
        d.mark_delivered("/fake/path2.jpg")
        print("ERROR: should have raised DeliveryStateError")
    except DeliveryStateError:
        print("correctly rejected double mark_delivered")

    # closes in its own finally -- a failed INSERT leaves the connection holding
    # SQLite's write lock, blocking the cleanup connection below.
    try:
        bad_connection = get_db_connection()
        try:
            bad_connection.execute(
                "INSERT INTO deliveries (order_id, driver_id, delivery_date, delivery_status) "
                "VALUES (?, ?, ?, ?)",
                (order_id, driver_id, "2026-01-01", "bogus"),
            )
            bad_connection.commit()
            print("ERROR: should have raised on bad status")
        finally:
            bad_connection.close()
    except Exception as e:
        print("correctly rejected bad status:", type(e).__name__)
finally:
    # cleanup -- removes only the delivery this script created; runs even on failure
    # so a bad run doesn't break the UNIQUE(order_id) constraint next time.
    cleanup_connection = get_db_connection()
    try:
        cleanup_connection.execute("DELETE FROM deliveries WHERE delivery_id = ?", (d.delivery_id,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(f"cleanup: removed test delivery (delivery_id={d.delivery_id})")
