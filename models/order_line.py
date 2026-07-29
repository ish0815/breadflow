"""
models/order_line.py -- OrderLine: one product/quantity within a placed order.

Kept as its own class (rather than plain tuples) because the data
dictionary gives it its own validation rule (validateQuantity) and derived
value (calculateLineTotal) -- both belong on the line, not on the parent
Order.
"""


class OrderLine:
    """One row of order_lines: a product, the quantity ordered, and the
    price locked in at order time (unaffected by later catalogue changes)."""

    def __init__(self, order_line_id, order_id, product_id, quantity, unit_price, product_name=None):
        self._order_line_id = order_line_id
        self._order_id = order_id
        self._product_id = product_id
        self._quantity = quantity
        self._unit_price = unit_price
        # only set when joined with products, for display purposes
        self._product_name = product_name

    @property
    def order_line_id(self):
        return self._order_line_id

    @property
    def order_id(self):
        return self._order_id

    @property
    def product_id(self):
        return self._product_id

    @property
    def quantity(self):
        return self._quantity

    @property
    def unit_price(self):
        return self._unit_price

    @property
    def product_name(self):
        return self._product_name

    def calculate_line_total(self):
        """quantity x unitPrice, per the data dictionary."""
        return self._quantity * self._unit_price

    @staticmethod
    def validate_quantity(quantity):
        """True if quantity is a positive integer >= 1, per the data dictionary.
        Expects an already-parsed int -- string parsing happens in Order.place(),
        which knows what a malformed form field should display as an error."""
        return isinstance(quantity, int) and quantity >= 1
