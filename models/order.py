# models/order.py -- Order: a client's order and its FR-B1/FR-B4 lifecycle.

import datetime

from database.db import get_db_connection
from models.order_line import OrderLine

# maps date.weekday() (0-6) to the weekday names stored in clients.delivery_day1/2
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

MAX_SPECIAL_INSTRUCTIONS_LENGTH = 300  # data dictionary: "Max 300 chars"


# FR-B1 validation failure: bad quantity, no products, or wrong delivery day.
class OrderValidationError(Exception):
    pass


# approve()/reject() called on an order that's no longer pending.
class OrderStateError(Exception):
    pass


# A client's order (FR-B1), pending owner approval (FR-B4).
class Order:

    def __init__(self, order_id, client_id, delivery_date, order_status,
                 special_instructions, order_created_at, approved_by=None, approved_at=None):
        self._order_id = order_id
        self._client_id = client_id
        self._delivery_date = delivery_date
        self._order_status = order_status
        self._special_instructions = special_instructions
        self._order_created_at = order_created_at
        self._approved_by = approved_by
        self._approved_at = approved_at

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

    # ---- approval / rejection (FR-B4) --------------------------------------

    @classmethod
    def approve(cls, order_id, owner_id):
        cls._set_status(order_id, "approved", owner_id)

    @classmethod
    def reject(cls, order_id, owner_id):
        cls._set_status(order_id, "rejected", owner_id)

    @staticmethod
    def _set_status(order_id, status, owner_id):
        connection = get_db_connection()
        try:
            # only matches if still pending -- blocks a double approve/reject
            cursor = connection.execute(
                """
                UPDATE orders SET order_status = ?, approved_by = ?,
                                  approved_at = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')
                WHERE order_id = ? AND order_status = 'pending'
                """,
                (status, owner_id, order_id),
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
                     row["approved_by"], row["approved_at"])
