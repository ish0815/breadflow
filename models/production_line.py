# models/production_line.py -- ProductionLine: one product's total in a production list (FR-C1/C2).


# One product's total_ordered, buffer, and produce_qty. No client info.
class ProductionLine:

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
