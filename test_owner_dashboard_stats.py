# test_owner_dashboard_stats.py -- Criterion 8 test evidence: owner dashboard stat cards
# (app.py owner_dashboard(), models/order.py Order.count_approved_today()/
# count_deliveries_today(), models/analytics.py Analytics.get_period_summary() reused
# for the week-revenue card). Uses before/after deltas throughout since the dev DB
# already has real order history (e.g. Test Cafe), so absolute counts would be fragile.
# Permanent test script -- keep in the repo, do not delete.

from datetime import date, timedelta

from app import app
from database.db import get_db_connection
from models.analytics import Analytics, fy_start_year, resolve_period_bounds
from models.order import Order

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)
SEARCH_MARKER = "ZZZ Dashboard Stats Test"

TODAY = date.today().isoformat()
TODAY_TIMESTAMP = f"{TODAY}T09:00:00"


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@dashboard-stats-test.local",),
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


# approved_at_iso lets a test order simulate having been actioned "today" without
# going through the real approve()/reject() routes (and their email side effects).
def _make_order(connection, client_id, status, delivery_date_iso, product_id, quantity, unit_price,
                 approved_at_iso=None):
    if approved_at_iso:
        order_cursor = connection.execute(
            "INSERT INTO orders (client_id, delivery_date, order_status, approved_by, approved_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (client_id, delivery_date_iso, status, OWNER_ID, approved_at_iso),
        )
    else:
        order_cursor = connection.execute(
            "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, ?)",
            (client_id, delivery_date_iso, status),
        )
    order_id = order_cursor.lastrowid
    connection.execute(
        "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
        (order_id, product_id, quantity, unit_price),
    )
    connection.commit()
    return order_id


user_ids = []

try:
    connection = get_db_connection()
    try:
        product_row = connection.execute("SELECT product_id FROM products LIMIT 1").fetchone()
        product_id = product_row["product_id"]

        # -- baselines, captured before any test data exists --
        pending_before = Order.count_pending()
        approved_today_before = Order.count_approved_today()
        deliveries_today_before = Order.count_deliveries_today()
        week_start, week_end = resolve_period_bounds("weekly", fy_start_year())
        week_revenue_before = Analytics.get_period_summary(week_start, week_end)["total_revenue"]

        test_client_id, test_user_id = _make_test_client(connection, f"{SEARCH_MARKER} Delta", "93000000001")
        user_ids.append(test_user_id)

        future_date = (date.today() + timedelta(days=10)).isoformat()

        # pending -> pending_count delta +1
        _make_order(connection, test_client_id, "pending", future_date, product_id, 1, 10.00)

        # approved, actioned today, delivery date irrelevant (not today) ->
        # approved_today delta +1, deliveries_today untouched
        _make_order(connection, test_client_id, "approved", future_date, product_id, 1, 10.00,
                    approved_at_iso=TODAY_TIMESTAMP)

        # approved, due today, actioned at some point in the past (not today) ->
        # deliveries_today delta +1, approved_today untouched
        _make_order(connection, test_client_id, "approved", TODAY, product_id, 1, 10.00)

        # rejected, due today, actioned today -- negative control: approved_at is set on
        # rejections too (see Order._set_status), so this must NOT move either stat
        _make_order(connection, test_client_id, "rejected", TODAY, product_id, 1, 999.00,
                    approved_at_iso=TODAY_TIMESTAMP)

        # delivered, due today -- week_revenue delta +$200.00, and also counts toward
        # deliveries_today (delivered counts as "due today" alongside approved)
        _make_order(connection, test_client_id, "delivered", TODAY, product_id, 2, 100.00)

        pending_after = Order.count_pending()
        approved_today_after = Order.count_approved_today()
        deliveries_today_after = Order.count_deliveries_today()
        week_revenue_after = Analytics.get_period_summary(week_start, week_end)["total_revenue"]

        assert pending_after - pending_before == 1, (pending_before, pending_after)
        print("PASS: pending orders count includes the new pending order")

        assert approved_today_after - approved_today_before == 1, (approved_today_before, approved_today_after)
        print("PASS: approved-today count includes only the order actioned today, excludes the rejected one")

        assert deliveries_today_after - deliveries_today_before == 2, (deliveries_today_before, deliveries_today_after)
        print("PASS: deliveries-today count includes the approved + delivered orders due today, excludes the rejected one")

        assert week_revenue_after - week_revenue_before == 200.00, (week_revenue_before, week_revenue_after)
        print("PASS: this week's revenue includes only the delivered order")

        # route-level: the exact after-seeding values render on the actual page
        seed_session(OWNER_ID, "owner")
        response = client.get("/owner/dashboard")
        assert response.status_code == 200, response.status_code
        html = response.data.decode()

        assert f'<div class="summary-card-value">{pending_after}</div>' in html, html
        assert f'<div class="summary-card-value">{approved_today_after}</div>' in html, html
        assert f'<div class="summary-card-value">{deliveries_today_after}</div>' in html, html
        assert f'<div class="summary-card-value">${week_revenue_after:.2f}</div>' in html, html
        print("PASS: /owner/dashboard renders all four stat card values correctly")

        print("\nAll checks passed.")
    finally:
        connection.close()
finally:
    cleanup_connection = get_db_connection()
    try:
        for user_id in user_ids:
            cleanup_connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(f"cleanup: removed {len(user_ids)} test client(s) (orders cascade with them)")
