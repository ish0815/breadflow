# models/production.py -- ProductionList: FR-C1/FR-C2 daily production totals, by product only.

import math

from database.db import get_db_connection
from models.production_line import ProductionLine


# Generated production list for one date: header stats + one ProductionLine per product.
class ProductionList:

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

    # FR-C1/C2: GROUP BY/SUM approved orders into per-product lines, logs the event.
    # Returns None (no audit row) if there are no approved orders for this date.
    @classmethod
    def generate(cls, production_date, owner_id):
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

    # FR-C2: 10% buffer, rounded up -- plain rounding could drop small totals to 0.
    @staticmethod
    def _apply_buffer(total_ordered):
        return math.ceil(total_ordered * 0.10)

    # ---- date picker support ------------------------------------------------

    # Distinct delivery dates with any order -- populates the date picker.
    @classmethod
    def get_dates_with_orders(cls):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT DISTINCT delivery_date FROM orders ORDER BY delivery_date ASC"
            ).fetchall()
        finally:
            connection.close()
        return [row["delivery_date"] for row in rows]
