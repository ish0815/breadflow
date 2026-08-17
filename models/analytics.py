# models/analytics.py -- FR-F1 sales analytics queries. FR-F2 (historical order archive)
# needs no new code: grep confirms no DELETE FROM orders outside test_*.py cleanup scripts,
# so these plain date-range queries can already reach any past period.

import datetime

from database.db import get_db_connection

FY_START_MONTH = 7  # Australian financial year: 1 July - 30 June


# The FY a given date falls in, as its starting calendar year (e.g. 12 Aug 2025 -> 2025).
def fy_start_year(for_date=None):
    for_date = for_date or datetime.date.today()
    return for_date.year if for_date.month >= FY_START_MONTH else for_date.year - 1


# (start, end) ISO date strings for the FY starting 1 July of start_year.
def fy_bounds(start_year):
    return f"{start_year}-07-01", f"{start_year + 1}-06-30"


def fy_label(start_year):
    return f"FY {start_year}-{str(start_year + 1)[-2:]}"


# Weekly/monthly are always relative to today (week-to-date / month-to-date), independent
# of the FY dropdown; yearly uses the selected FY's full bounds.
def resolve_period_bounds(period, fy_start_year_val, today=None):
    today = today or datetime.date.today()
    if period == "weekly":
        start = today - datetime.timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    if period == "monthly":
        return today.replace(day=1).isoformat(), today.isoformat()
    return fy_bounds(fy_start_year_val)


# FY revenue/orders/active-clients/avg-order-value for the owner Analytics page.
class Analytics:

    @staticmethod
    def get_period_summary(start, end):
        connection = get_db_connection()
        try:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(order_lines.quantity * order_lines.unit_price), 0) AS total_revenue,
                       COUNT(DISTINCT orders.order_id) AS order_count,
                       COUNT(DISTINCT orders.client_id) AS active_clients
                FROM orders
                JOIN order_lines ON order_lines.order_id = orders.order_id
                WHERE orders.order_status = 'delivered' AND orders.delivery_date BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchone()
        finally:
            connection.close()

        order_count = row["order_count"]
        return {
            "total_revenue": row["total_revenue"],
            "order_count": order_count,
            "active_clients": row["active_clients"],
            "avg_order_value": (row["total_revenue"] / order_count) if order_count else 0,
        }

    # 12-point Jul->Jun revenue trend for the selected FY; months with no delivered
    # orders are reindexed to 0 rather than silently missing a chart point.
    @staticmethod
    def get_monthly_revenue(fy_start_year_val):
        start, end = fy_bounds(fy_start_year_val)
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT STRFTIME('%Y-%m', orders.delivery_date) AS month,
                       SUM(order_lines.quantity * order_lines.unit_price) AS revenue
                FROM orders
                JOIN order_lines ON order_lines.order_id = orders.order_id
                WHERE orders.order_status = 'delivered' AND orders.delivery_date BETWEEN ? AND ?
                GROUP BY month
                """,
                (start, end),
            ).fetchall()
        finally:
            connection.close()
        revenue_by_month = {row["month"]: row["revenue"] for row in rows}

        labels = []
        revenue = []
        year, month = fy_start_year_val, FY_START_MONTH
        for _ in range(12):
            key = f"{year:04d}-{month:02d}"
            labels.append(datetime.date(year, month, 1).strftime("%b %Y"))
            revenue.append(revenue_by_month.get(key, 0))
            month += 1
            if month > 12:
                month = 1
                year += 1
        return {"labels": labels, "revenue": revenue}

    @staticmethod
    def get_top_clients(start, end, limit=5):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT clients.client_id, clients.business_name,
                       SUM(order_lines.quantity * order_lines.unit_price) AS revenue
                FROM order_lines
                JOIN orders ON orders.order_id = order_lines.order_id
                JOIN clients ON clients.client_id = orders.client_id
                WHERE orders.order_status = 'delivered' AND orders.delivery_date BETWEEN ? AND ?
                GROUP BY clients.client_id, clients.business_name
                ORDER BY revenue DESC
                LIMIT ?
                """,
                (start, end, limit),
            ).fetchall()
        finally:
            connection.close()
        return [{"client_id": r["client_id"], "business_name": r["business_name"], "revenue": r["revenue"]}
                for r in rows]

    # No LIMIT -- the product catalogue is small, unlike the top-5-clients ranking.
    @staticmethod
    def get_product_units(start, end):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT products.product_id, products.product_name,
                       SUM(order_lines.quantity) AS units_sold
                FROM order_lines
                JOIN orders ON orders.order_id = order_lines.order_id
                JOIN products ON products.product_id = order_lines.product_id
                WHERE orders.order_status = 'delivered' AND orders.delivery_date BETWEEN ? AND ?
                GROUP BY products.product_id, products.product_name
                ORDER BY units_sold DESC
                """,
                (start, end),
            ).fetchall()
        finally:
            connection.close()
        return [{"product_id": r["product_id"], "product_name": r["product_name"], "units_sold": r["units_sold"]}
                for r in rows]

    # Current FY vs previous FY, 4 rows with a % change each ("N/A" if the previous
    # value was 0, avoiding a divide-by-zero).
    @staticmethod
    def get_yoy_comparison(fy_start_year_val):
        current = Analytics.get_period_summary(*fy_bounds(fy_start_year_val))
        previous = Analytics.get_period_summary(*fy_bounds(fy_start_year_val - 1))

        metrics = (
            ("total_revenue", "Total revenue", True),
            ("order_count", "Total orders", False),
            ("avg_order_value", "Avg order value", True),
            ("active_clients", "Active clients", False),
        )
        rows = []
        for key, label, is_currency in metrics:
            current_value = current[key]
            previous_value = previous[key]
            pct_change = ((current_value - previous_value) / previous_value * 100) if previous_value else None
            rows.append({
                "label": label, "is_currency": is_currency,
                "current": current_value, "previous": previous_value, "pct_change": pct_change,
            })
        return rows

    # Populates the FY dropdown from actual data -- current FY first, back to the
    # earliest FY with a delivered order. Falls back to just the current FY if the
    # DB has no delivered orders yet, so the dropdown never comes back empty.
    @staticmethod
    def get_available_fy_start_years():
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT MIN(delivery_date) AS min_date FROM orders WHERE order_status = 'delivered'"
            ).fetchone()
        finally:
            connection.close()

        current = fy_start_year()
        if row["min_date"] is None:
            return [current]
        earliest = fy_start_year(datetime.date.fromisoformat(row["min_date"]))
        return list(range(current, earliest - 1, -1))
