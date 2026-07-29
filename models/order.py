"""
models/order.py -- Order: a client's order and its FR-B1/FR-B4 lifecycle.
"""

import datetime

from database.db import get_db_connection
from models.order_line import OrderLine

# maps date.weekday() (0-6) to the weekday names stored in clients.delivery_day1/2
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

MAX_SPECIAL_INSTRUCTIONS_LENGTH = 300  # data dictionary: "Max 300 chars"


class OrderValidationError(Exception):
    """Raised when a submitted order fails one of FR-B1's validation rules
    (bad quantity, no products selected, or a delivery date that isn't one
    of the client's two assigned days)."""


class OrderStateError(Exception):
    """Raised when approve()/reject() targets an order that isn't pending
    any more -- e.g. a double-click or a second browser tab acting on an
    order the owner already approved."""


class Order:
    """
    An order placed by a client (FR-B1), pending the owner's approval or
    rejection (FR-B4). Mirrors the `orders` table: no delivery_charge/GST/
    total columns -- see schema.sql for why those are computed, not stored.
    """

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

    @classmethod
    def place(cls, client, delivery_date, raw_quantities, special_instructions=""):
        """
        FR-B1: validate and insert a new order plus its order_lines.

        `raw_quantities` is {product_id: raw_form_string}, exactly as
        submitted -- one entry per product on the client's approved
        catalogue, most of them blank/"0" for products not being ordered
        this time. Parsing and range-checking each one here (rather than
        trusting the route to have already done it) means this method is
        the one place FR-B1's quantity rule is enforced, regardless of
        which route calls it.
        """
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

    @staticmethod
    def _is_valid_delivery_date(delivery_date, assigned_days):
        """FR-B1: the date must be a real future calendar date that falls on
        one of the client's 2 assigned weekdays. FR-B3 deliberately places
        no upper bound on how far ahead it can be."""
        try:
            parsed = datetime.date.fromisoformat(delivery_date)
        except (TypeError, ValueError):
            return False
        if parsed <= datetime.date.today():
            return False
        return WEEKDAYS[parsed.weekday()] in assigned_days

    # ---- reading an order back ---------------------------------------------

    def get_order_lines(self):
        """Returns this order's OrderLine objects, joined with product_name
        for display (e.g. the owner's pending orders list)."""
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

    def calculate_total(self):
        """SUM(quantity x unitPrice) across this order's lines -- the data
        dictionary's totalValue. Deliberately excludes delivery/GST: those
        are only added at the invoicing stage (FR-D1, a later module)."""
        return sum(line.calculate_line_total() for line in self.get_order_lines())

    @classmethod
    def get_pending(cls):
        """FR-B4: the owner's pending-approval queue, oldest delivery date
        first. Returns display-ready dicts (not bare Order objects) since
        every consumer of this list (the pending orders template) needs the
        client's business name and product summary alongside the order --
        exactly what the IPO chart's "DISPLAY orderID, clientName,
        deliveryDate, products, totalValue" describes as one row."""
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
