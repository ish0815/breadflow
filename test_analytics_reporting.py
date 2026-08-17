# test_analytics_reporting.py -- Criterion 8 test evidence: Module F sales analytics
# (routes/analytics.py, models/analytics.py Analytics class) -- period summary, monthly
# revenue, top clients, product units, and YoY all only count delivered orders in range;
# and the FR-F3 dashboard reminder (models/client.py Client.get_overdue_clients()).
# Permanent test script -- keep in the repo, do not delete.

from datetime import date, timedelta

from app import app
from database.db import get_db_connection
from models.analytics import Analytics, fy_bounds, fy_start_year

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)

# unique marker so this test's clients/orders never get mistaken for real dev data
SEARCH_MARKER = "ZZZ Analytics Test"

CURRENT_FY = fy_start_year()
CUR_START, CUR_END = fy_bounds(CURRENT_FY)
PREV_START, PREV_END = fy_bounds(CURRENT_FY - 1)


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@analytics-test.local",),
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


def _make_order(connection, client_id, status, delivery_date_iso, product_id, quantity, unit_price):
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

        # -- baselines, captured before any test data exists, so assertions below use
        # deltas and are immune to whatever real orders already sit in the dev DB --
        baseline_current = Analytics.get_period_summary(CUR_START, CUR_END)
        baseline_previous = Analytics.get_period_summary(PREV_START, PREV_END)
        baseline_monthly = Analytics.get_monthly_revenue(CURRENT_FY)["revenue"]
        baseline_product_units = {
            row["product_id"]: row["units_sold"] for row in Analytics.get_product_units(CUR_START, CUR_END)
        }
        baseline_yoy = {row["label"]: row for row in Analytics.get_yoy_comparison(CURRENT_FY)}

        gamma_id, gamma_user_id = _make_test_client(connection, f"{SEARCH_MARKER} Gamma", "92000000001")
        user_ids.append(gamma_user_id)

        cur_start_date = date.fromisoformat(CUR_START)
        order1_date = (cur_start_date + timedelta(days=10)).isoformat()   # July -> monthly index 0
        order2_date = (cur_start_date + timedelta(days=40)).isoformat()   # August -> monthly index 1
        prev_order_date = (date.fromisoformat(PREV_START) + timedelta(days=10)).isoformat()

        # delivered: counts everywhere. pending/rejected: must NOT count anywhere below.
        _make_order(connection, gamma_id, "delivered", order1_date, product_id, 2, 5000.00)   # $10,000.00
        _make_order(connection, gamma_id, "delivered", order2_date, product_id, 3, 3000.00)   # $9,000.00
        _make_order(connection, gamma_id, "pending", order1_date, product_id, 1, 9999.00)
        _make_order(connection, gamma_id, "rejected", order2_date, product_id, 1, 9999.00)
        _make_order(connection, gamma_id, "delivered", prev_order_date, product_id, 1, 5000.00)  # $5,000.00

        # 1. period summary: only the 2 delivered current-FY orders count ($19,000, 2 orders)
        after_current = Analytics.get_period_summary(CUR_START, CUR_END)
        assert after_current["total_revenue"] - baseline_current["total_revenue"] == 19000.00
        assert after_current["order_count"] - baseline_current["order_count"] == 2
        assert after_current["active_clients"] - baseline_current["active_clients"] == 1
        print("PASS: period summary counts only delivered orders in range, excludes pending/rejected")

        after_previous = Analytics.get_period_summary(PREV_START, PREV_END)
        assert after_previous["total_revenue"] - baseline_previous["total_revenue"] == 5000.00
        assert after_previous["order_count"] - baseline_previous["order_count"] == 1
        print("PASS: previous FY's delivered order is counted separately from the current FY")

        # 2. monthly revenue: $10,000 lands in July (index 0), $9,000 in August (index 1);
        # the $9,999 pending/rejected orders on those same dates must not leak in
        after_monthly = Analytics.get_monthly_revenue(CURRENT_FY)["revenue"]
        assert after_monthly[0] - baseline_monthly[0] == 10000.00
        assert after_monthly[1] - baseline_monthly[1] == 9000.00
        print("PASS: monthly revenue buckets delivered orders into the right month, excludes non-delivered")

        # 3. product units: 2 + 3 = 5 delivered units; the pending/rejected orders'
        # units for the same product must not be counted
        after_product_units = {row["product_id"]: row["units_sold"] for row in Analytics.get_product_units(CUR_START, CUR_END)}
        delta_units = after_product_units.get(product_id, 0) - baseline_product_units.get(product_id, 0)
        assert delta_units == 5, delta_units
        print("PASS: product units sold counts only delivered order lines")

        # 4. top clients: this client's own row, scoped by client_id, isn't affected by
        # any other client's revenue in the dev DB
        top_clients = Analytics.get_top_clients(CUR_START, CUR_END, limit=1000)
        gamma_row = next(row for row in top_clients if row["client_id"] == gamma_id)
        assert gamma_row["revenue"] == 19000.00, gamma_row["revenue"]
        print("PASS: top clients ranks this client with its correct delivered-order revenue")

        # 5. year-on-year: current vs previous FY deltas match what was seeded in each
        after_yoy = {row["label"]: row for row in Analytics.get_yoy_comparison(CURRENT_FY)}
        assert after_yoy["Total revenue"]["current"] - baseline_yoy["Total revenue"]["current"] == 19000.00
        assert after_yoy["Total revenue"]["previous"] - baseline_yoy["Total revenue"]["previous"] == 5000.00
        assert after_yoy["Total orders"]["current"] - baseline_yoy["Total orders"]["current"] == 2
        assert after_yoy["Total orders"]["previous"] - baseline_yoy["Total orders"]["previous"] == 1
        print("PASS: YoY comparison reflects both FYs' seeded delivered orders")

        # 6. route-level smoke test + CSV export contains this client (its $19,000
        # revenue guarantees a top-5 rank for a dev-sized dataset)
        seed_session(OWNER_ID, "owner")
        response = client.get(f"/owner/analytics?period=yearly&fy={CURRENT_FY}")
        assert response.status_code == 200, response.status_code
        print("PASS: /owner/analytics renders for the selected FY")

        response = client.get(f"/owner/analytics/export?period=yearly&fy={CURRENT_FY}")
        assert response.status_code == 200, response.status_code
        assert response.mimetype == "text/csv", response.mimetype
        assert f"{SEARCH_MARKER} Gamma".encode() in response.data, response.data
        print("PASS: CSV export includes this client in its Top Clients section")

        # 7. FR-F3: a client overdue against its own history shows on the dashboard;
        # one that ordered recently does not
        overdue_id, overdue_user_id = _make_test_client(connection, f"{SEARCH_MARKER} Overdue", "92000000002")
        uptodate_id, uptodate_user_id = _make_test_client(connection, f"{SEARCH_MARKER} UpToDate", "92000000003")
        user_ids.append(overdue_user_id)
        user_ids.append(uptodate_user_id)

        overdue_date = (date.today() - timedelta(days=30)).isoformat()
        uptodate_date = (date.today() - timedelta(days=2)).isoformat()
        _make_order(connection, overdue_id, "delivered", overdue_date, product_id, 1, 10.00)
        _make_order(connection, uptodate_id, "delivered", uptodate_date, product_id, 1, 10.00)

        response = client.get("/owner/dashboard")
        assert response.status_code == 200, response.status_code
        assert f"{SEARCH_MARKER} Overdue".encode() in response.data, response.data
        assert f"{SEARCH_MARKER} UpToDate".encode() not in response.data, response.data
        print("PASS: dashboard flags the overdue client and not the up-to-date one")

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
