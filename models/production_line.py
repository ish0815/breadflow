"""
models/production_line.py -- ProductionLine: one product's aggregated
total within a generated production list (FR-C1/FR-C2).
"""


class ProductionLine:
    """One row of a generated production list: a product, its aggregated
    approved-order total, the 10% buffer, and the final quantity to
    produce. Deliberately carries no client information -- see
    schema.sql's production_lines comment."""

    def __init__(self, product_id, product_name, total_ordered, buffer_qty, produce_qty):
        self._product_id = product_id
        self._product_name = product_name
        self._total_ordered = total_ordered
        self._buffer_qty = buffer_qty
        self._produce_qty = produce_qty

    @property
    def product_id(self):
        return self._product_id

    @property
    def product_name(self):
        return self._product_name

    @property
    def total_ordered(self):
        return self._total_ordered

    @property
    def buffer_qty(self):
        return self._buffer_qty

    @property
    def produce_qty(self):
        return self._produce_qty
