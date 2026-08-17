# models/order.py -- Order: a client's order and its FR-B1/FR-B4 lifecycle.

import datetime

from database.db import get_db_connection
from models.order_line import OrderLine

# maps date.weekday() (0-6) to the weekday names stored in clients.delivery_day1/2
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

MAX_SPECIAL_INSTRUCTIONS_LENGTH = 300  # data dictionary: "Max 300 chars"
MAX_REJECTION_REASON_LENGTH = 300  # matches special_instructions' cap convention


# FR-B1 validation failure: bad quantity, no products, or wrong delivery day.
class OrderValidationError(Exception):
    pass


# approve()/reject()/mark_delivered() called on an order in the wrong state.
class OrderStateError(Exception):
    pass


# A client's order (FR-B1), pending owner approval (FR-B4).
class Order:

    def __init__(self, order_id, client_id, delivery_date, order_status,
                 special_instructions, order_created_at, approved_by=None, approved_at=None,
                 rejection_reason=None):
        self._order_id = order_id
        self._client_id = client_id
        self._delivery_date = delivery_date
        self._order_status = order_status
        self._special_instructions = special_instructions
        self._order_created_at = order_created_at
        self._approved_by = approved_by
        self._approved_at = approved_at
        self._rejection_reason = rejection_reason

    @property
    def order_id(self):
        return self._order_id

    @property
    def client_id(self):
        return self._client_id

    @property
    def delivery_date(self):
        return self._delivery_date

    @property
    def order_status(self):
        return self._order_status

    @property
    def special_instructions(self):
        return self._special_instructions

    @property
    def order_created_at(self):
        return self._order_created_at

    @property
    def approved_by(self):
        return self._approved_by

    @property
    def approved_at(self):
        return self._approved_at

    @property
    def rejection_reason(self):
        return self._rejection_reason

    # ---- placing an order (FR-B1) -----------------------------------------

    # FR-B1: validates and inserts a new order + its lines. raw_quantities: {product_id: form_string}.
    @classmethod
    def place(cls, client, delivery_date, raw_quantities, special_instructions=""):
        special_instructions = (special_instructions or "").strip()
        if len(special_instructions) > MAX_SPECIAL_INSTRUCTIONS_LENGTH:
            raise OrderValidationError(
                f"Special instructions must be {MAX_SPECIAL_INSTRUCTIONS_LENGTH} characters or fewer"
            )

        approved_products = {row["product_id"]: row for row in client.get_approved_products()}

        line_items = []  # (product_id, quantity, unit_price)
        for product_id, raw_quantity in raw_quantities.items():
            if product_id not in approved_products:
                # tampered form -- fields only ever render for approved products
                raise OrderValidationError("One or more products in your order are invalid")

            raw_quantity = (raw_quantity or "").strip()
            if not raw_quantity or raw_quantity == "0":
                continue  # not ordering this product this time

            if not raw_quantity.isdigit():
                raise OrderValidationError("Please enter a valid quantity")

            quantity = int(raw_quantity)
            if not OrderLine.validate_quantity(quantity):
                raise OrderValidationError("Please enter a valid quantity")

            product = approved_products[product_id]
            line_items.append((product_id, quantity, product["agreed_price"]))

        if not line_items:
            raise OrderValidationError("Please add at least one product to your order")

        if not cls._is_valid_delivery_date(delivery_date, client.delivery_days):
            raise OrderValidationError("Please select one of your assigned delivery days")

        connection = get_db_connection()
        try:
            cursor = connection.execute(
                """
                INSERT INTO orders (client_id, delivery_date, order_status, special_instructions)
                VALUES (?, ?, 'pending', ?)
                """,
                (client.client_id, delivery_date, special_instructions or None),
            )
            order_id = cursor.lastrowid

            for product_id, quantity, unit_price in line_items:
                connection.execute(
                    "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                    (order_id, product_id, quantity, unit_price),
                )

            connection.commit()
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            return cls._build_from_row(row)
        finally:
            connection.close()

    # FR-B1/B3: must be a future date on one of the client's 2 assigned weekdays, no upper bound.
    @staticmethod
    def _is_valid_delivery_date(delivery_date, assigned_days):
        try:
            parsed = datetime.date.fromisoformat(delivery_date)
        except (TypeError, ValueError):
            return False
        if parsed <= datetime.date.today():
            return False
        return WEEKDAYS[parsed.weekday()] in assigned_days

    # ---- reading an order back ---------------------------------------------

    # This order's OrderLine objects, joined with product_name for display.
    def get_order_lines(self):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT order_lines.*, products.product_name
                FROM order_lines
                JOIN products ON products.product_id = order_lines.product_id
                WHERE order_lines.order_id = ?
                """,
                (self._order_id,),
            ).fetchall()
        finally:
            connection.close()

        return [
            OrderLine(row["order_line_id"], row["order_id"], row["product_id"],
                      row["quantity"], row["unit_price"], product_name=row["product_name"])
            for row in rows
        ]

    # SUM(qty x unitPrice) across lines -- excludes delivery/GST (added at invoicing, FR-D1).
    def calculate_total(self):
        return sum(line.calculate_line_total() for line in self.get_order_lines())

    # FR-B4: pending orders queue, oldest delivery date first, as display-ready dicts.
    @classmethod
    def get_pending(cls):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT orders.*, clients.business_name
                FROM orders
                JOIN clients ON clients.client_id = orders.client_id
                WHERE orders.order_status = 'pending'
                ORDER BY orders.delivery_date ASC
                """
            ).fetchall()
        finally:
            connection.close()

        pending = []
        for row in rows:
            order = cls._build_from_row(row)
            lines = order.get_order_lines()
            pending.append({
                "order_id": order.order_id,
                "business_name": row["business_name"],
                "delivery_date": order.delivery_date,
                "special_instructions": order.special_instructions,
                "product_summary": ", ".join(f"{line.product_name} x{line.quantity}" for line in lines),
                "total_value": order.calculate_total(),
            })
        return pending

    # Sidebar badge (Module F): cheap count, no row data needed.
    @classmethod
    def count_pending(cls):
        connection = get_db_connection()
        try:
            return connection.execute(
                "SELECT COUNT(*) AS count FROM orders WHERE order_status = 'pending'"
            ).fetchone()["count"]
        finally:
            connection.close()

    # Owner dashboard stat card: actioned today and not rejected -- approved_at is
    # set on both approve() and reject() (see _set_status), so the status filter is
    # what actually excludes rejections here. approved_at is stored via SQLite's UTC
    # 'now' (same as everywhere else in this schema); 'localtime' converts both sides
    # to the owner's actual calendar day, so a morning approval in Melbourne doesn't
    # get counted as "yesterday" for most of the business day.
    @classmethod
    def count_approved_today(cls):
        connection = get_db_connection()
        try:
            return connection.execute(
                """
                SELECT COUNT(*) AS count FROM orders
                WHERE order_status IN ('approved', 'delivered')
                  AND STRFTIME('%Y-%m-%d', approved_at, 'localtime') = STRFTIME('%Y-%m-%d', 'now', 'localtime')
                """
            ).fetchone()["count"]
        finally:
            connection.close()

    # Owner dashboard stat card: confirmed orders due out today. Reads delivery_date
    # on orders, not the deliveries table -- nothing in the app currently creates a
    # deliveries row outside test scripts, so that table isn't a reliable dashboard signal.
    @classmethod
    def count_deliveries_today(cls):
        connection = get_db_connection()
        try:
            return connection.execute(
                """
                SELECT COUNT(*) AS count FROM orders
                WHERE order_status IN ('approved', 'delivered') AND delivery_date = DATE('now', 'localtime')
                """
            ).fetchone()["count"]
        finally:
            connection.close()

    # Module 6: fixed whitelist of sort columns -- never build ORDER BY from raw input.
    _SORT_COLUMNS = {
        "newest": "orders.order_id DESC",
        "delivery_date": "orders.delivery_date ASC",
        "client_name": "clients.business_name ASC",
        "total": "(SELECT COALESCE(SUM(order_lines.quantity * order_lines.unit_price), 0) "
                 "FROM order_lines WHERE order_lines.order_id = orders.order_id) DESC",
    }

    # Module 6: full searchable/filterable/paginated order list for the owner.
    # Returns (orders, total_count) as display-ready dicts, same shape as get_pending().
    @classmethod
    def list_all(cls, search=None, status=None, sort="newest", date_start=None, date_end=None,
                 page=1, per_page=24):
        conditions = []
        params = []
        if status and status != "All":
            conditions.append("orders.order_status = ?")
            params.append(status.lower())
        if search:
            conditions.append("(clients.business_name LIKE ? OR CAST(orders.order_id AS TEXT) = ?)")
            params.append(f"%{search}%")
            params.append(search)
        if date_start:
            conditions.append("orders.delivery_date >= ?")
            params.append(date_start)
        if date_end:
            conditions.append("orders.delivery_date <= ?")
            params.append(date_end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_by = cls._SORT_COLUMNS.get(sort, cls._SORT_COLUMNS["newest"])

        connection = get_db_connection()
        try:
            total_count = connection.execute(
                f"""
                SELECT COUNT(*) AS count FROM orders
                JOIN clients ON clients.client_id = orders.client_id
                {where_clause}
                """,
                params,
            ).fetchone()["count"]

            rows = connection.execute(
                f"""
                SELECT orders.*, clients.business_name, clients.delivery_zone
                FROM orders
                JOIN clients ON clients.client_id = orders.client_id
                {where_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
        finally:
            connection.close()

        orders = []
        for row in rows:
            order = cls._build_from_row(row)
            lines = order.get_order_lines()
            orders.append({
                "order_id": order.order_id,
                "business_name": row["business_name"],
                "delivery_zone": row["delivery_zone"],
                "delivery_date": order.delivery_date,
                "product_summary": ", ".join(f"{line.product_name} x{line.quantity}" for line in lines),
                "total_value": order.calculate_total(),
                "order_status": order.order_status,
            })
        return orders, total_count

    # Module 10: a client's own order history, always scoped by client_id (FR-A3 --
    # caller must derive client_id from session, never trust a request-supplied value).
    # Newest first, per the data dictionary -- no sort option, unlike list_all().
    @classmethod
    def list_for_client(cls, client_id, status=None, month=None, search=None, page=1, per_page=24):
        conditions = ["orders.client_id = ?"]
        params = [client_id]
        if status and status != "All":
            conditions.append("orders.order_status = ?")
            params.append(status.lower())
        if month:
            conditions.append("STRFTIME('%Y-%m', orders.delivery_date) = ?")
            params.append(month)
        if search:
            conditions.append(
                "(CAST(orders.order_id AS TEXT) = ? OR orders.order_id IN "
                "(SELECT order_lines.order_id FROM order_lines "
                "JOIN products ON products.product_id = order_lines.product_id "
                "WHERE products.product_name LIKE ?))"
            )
            params.append(search)
            params.append(f"%{search}%")

        where_clause = "WHERE " + " AND ".join(conditions)

        connection = get_db_connection()
        try:
            total_count = connection.execute(
                f"SELECT COUNT(*) AS count FROM orders {where_clause}", params
            ).fetchone()["count"]

            rows = connection.execute(
                f"""
                SELECT * FROM orders {where_clause}
                ORDER BY orders.order_id DESC
                LIMIT ? OFFSET ?
                """,
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
        finally:
            connection.close()

        orders = []
        for row in rows:
            order = cls._build_from_row(row)
            lines = order.get_order_lines()
            orders.append({
                "order_id": order.order_id,
                "delivery_date": order.delivery_date,
                "product_summary": ", ".join(f"{line.product_name} x{line.quantity}" for line in lines),
                "total_value": order.calculate_total(),
                "order_status": order.order_status,
            })
        return orders, total_count

    # Module 10: summary cards -- total orders, pending count, this-month/lifetime spend.
    # Spend excludes 'rejected' orders (never fulfilled) but includes pending/approved/
    # delivered -- this is the client's own "what I've ordered" view, not a billing figure.
    @classmethod
    def get_client_summary(cls, client_id):
        connection = get_db_connection()
        try:
            row = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT orders.order_id) AS total_order_count,
                    COUNT(DISTINCT CASE WHEN orders.order_status = 'pending'
                                         THEN orders.order_id END) AS pending_count,
                    COALESCE(SUM(CASE WHEN orders.order_status != 'rejected'
                                       AND STRFTIME('%Y-%m', orders.delivery_date) = STRFTIME('%Y-%m', 'now')
                                       THEN order_lines.quantity * order_lines.unit_price END), 0) AS this_month_spend,
                    COALESCE(SUM(CASE WHEN orders.order_status != 'rejected'
                                       THEN order_lines.quantity * order_lines.unit_price END), 0) AS lifetime_spend
                FROM orders
                LEFT JOIN order_lines ON order_lines.order_id = orders.order_id
                WHERE orders.client_id = ?
                """,
                (client_id,),
            ).fetchone()
        finally:
            connection.close()

        return {
            "total_order_count": row["total_order_count"],
            "pending_count": row["pending_count"],
            "this_month_spend": row["this_month_spend"],
            "lifetime_spend": row["lifetime_spend"],
        }

    # FR-E1: single-order lookup, used to pull client/product details onto a driver's docket.
    @classmethod
    def get_by_id(cls, order_id):
        connection = get_db_connection()
        try:
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        finally:
            connection.close()
        return cls._build_from_row(row) if row else None

    # ---- approval / rejection (FR-B4) --------------------------------------

    @classmethod
    def approve(cls, order_id, owner_id):
        cls._set_status(order_id, "approved", owner_id)

    # FR-B4: reason is optional, but capped to match special_instructions' length convention.
    @classmethod
    def reject(cls, order_id, owner_id, reason=None):
        reason = (reason or "").strip() or None
        if reason and len(reason) > MAX_REJECTION_REASON_LENGTH:
            raise OrderValidationError(
                f"Rejection reason must be {MAX_REJECTION_REASON_LENGTH} characters or fewer"
            )
        cls._set_status(order_id, "rejected", owner_id, reason=reason)

    # ---- delivery completion (FR-E2) ---------------------------------------

    # Driver-triggered sync, called after Delivery.mark_delivered() in the route.
    # Distinct from _set_status: no owner_id/approved_at (not an owner action), and
    # the guard is 'approved' not 'pending' -- only an approved order can have an
    # active delivery in the first place (see Delivery.create).
    @classmethod
    def mark_delivered(cls, order_id):
        connection = get_db_connection()
        try:
            cursor = connection.execute(
                "UPDATE orders SET order_status = 'delivered' WHERE order_id = ? AND order_status = 'approved'",
                (order_id,),
            )
            connection.commit()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            raise OrderStateError("This order is not in a state that can be marked delivered")

    @staticmethod
    def _set_status(order_id, status, owner_id, reason=None):
        connection = get_db_connection()
        try:
            # only matches if still pending -- blocks a double approve/reject
            cursor = connection.execute(
                """
                UPDATE orders SET order_status = ?, approved_by = ?,
                                  approved_at = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now'),
                                  rejection_reason = ?
                WHERE order_id = ? AND order_status = 'pending'
                """,
                (status, owner_id, reason, order_id),
            )
            connection.commit()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            raise OrderStateError("This order has already been actioned")

    @staticmethod
    def _build_from_row(row):
        return Order(row["order_id"], row["client_id"], row["delivery_date"], row["order_status"],
                     row["special_instructions"], row["order_created_at"],
                     row["approved_by"], row["approved_at"], row["rejection_reason"])
