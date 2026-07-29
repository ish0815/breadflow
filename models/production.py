"""
models/production.py -- ProductionList: FR-C1/FR-C2 daily production
aggregation, grouped by product only, never by client.
"""

import math

from database.db import get_db_connection
from models.production_line import ProductionLine


class ProductionList:
    """
    The generated production list for one delivery date: header stats
    (how many approved orders/distinct clients it covers, and when it was
    generated) plus one ProductionLine per product.
    """

    def __init__(self, production_list_id, production_date, generated_by, generated_at,
                 approved_order_count, total_client_count, lines):
        self._production_list_id = production_list_id
        self._production_date = production_date
        self._generated_by = generated_by
        self._generated_at = generated_at
        self._approved_order_count = approved_order_count
        self._total_client_count = total_client_count
        self._lines = lines

    @property
    def production_date(self):
        return self._production_date

    @property
    def generated_at(self):
        return self._generated_at

    @property
    def approved_order_count(self):
        return self._approved_order_count

    @property
    def total_client_count(self):
        return self._total_client_count

    @property
    def lines(self):
        return self._lines

    # ---- generation (FR-C1/FR-C2) ------------------------------------------

    @classmethod
    def generate(cls, production_date, owner_id):
        """
        Aggregates every approved order for `production_date` into one row
        per product (GROUP BY/SUM, left to SQLite rather than summed by
        hand in Python -- NF-03 makes the aggregation itself the part that
        most needs to be trustworthy), and logs the generation event.

        Returns None -- not an empty list -- when there are no approved
        orders for this date, matching the pseudocode's own STOP before
        the INSERT INTO production_lists step: idly checking a quiet day
        never writes a meaningless audit row.
        """
        connection = get_db_connection()
        try:
            header = connection.execute(
                """
                SELECT COUNT(*) AS approved_order_count, COUNT(DISTINCT client_id) AS total_client_count
                FROM orders
                WHERE order_status = 'approved' AND delivery_date = ?
                """,
                (production_date,),
            ).fetchone()

            if header["approved_order_count"] == 0:
                return None

            product_rows = connection.execute(
                """
                SELECT products.product_id, products.product_name, SUM(order_lines.quantity) AS total_ordered
                FROM order_lines
                JOIN orders ON orders.order_id = order_lines.order_id
                JOIN products ON products.product_id = order_lines.product_id
                WHERE orders.order_status = 'approved' AND orders.delivery_date = ?
                GROUP BY products.product_id, products.product_name
                ORDER BY products.product_name
                """,
                (production_date,),
            ).fetchall()

            cursor = connection.execute(
                """
                INSERT INTO production_lists (production_date, generated_by, approved_order_count, total_client_count)
                VALUES (?, ?, ?, ?)
                """,
                (production_date, owner_id, header["approved_order_count"], header["total_client_count"]),
            )
            production_list_id = cursor.lastrowid

            lines = []
            for row in product_rows:
                total_ordered = row["total_ordered"]
                buffer_qty = cls._apply_buffer(total_ordered)
                produce_qty = total_ordered + buffer_qty
                connection.execute(
                    """
                    INSERT INTO production_lines
                        (production_list_id, product_id, total_ordered, buffer_qty, produce_qty)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (production_list_id, row["product_id"], total_ordered, buffer_qty, produce_qty),
                )
                lines.append(ProductionLine(row["product_id"], row["product_name"],
                                            total_ordered, buffer_qty, produce_qty))

            connection.commit()

            generated_at = connection.execute(
                "SELECT generated_at FROM production_lists WHERE production_list_id = ?",
                (production_list_id,),
            ).fetchone()["generated_at"]

            return cls(production_list_id, production_date, owner_id, generated_at,
                       header["approved_order_count"], header["total_client_count"], lines)
        finally:
            connection.close()

    @staticmethod
    def _apply_buffer(total_ordered):
        """FR-C2: 10% buffer, rounded UP to a whole unit. Bread Staple's
        existing manual practice always rounds up (Criterion 2 interview) --
        a bakery can't produce half a loaf, and plain rounding would drop
        small totals' buffer to 0 (e.g. 3 x 10% = 0.3), defeating the
        safety margin the buffer exists for."""
        return math.ceil(total_ordered * 0.10)

    # ---- date picker support ------------------------------------------------

    @classmethod
    def get_dates_with_orders(cls):
        """Every distinct delivery date with at least one order, any
        status -- populates the production list's date picker so the
        owner only ever chooses a date that's actually relevant."""
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT DISTINCT delivery_date FROM orders ORDER BY delivery_date ASC"
            ).fetchall()
        finally:
            connection.close()
        return [row["delivery_date"] for row in rows]
