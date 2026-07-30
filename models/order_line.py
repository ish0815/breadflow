# models/order_line.py -- OrderLine: one product/quantity within a placed order.


# One order_lines row: product, quantity, and price locked in at order time.
class OrderLine:

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

    # quantity x unitPrice.
    def calculate_line_total(self):
        return self._quantity * self._unit_price

    # True if a positive integer >= 1. Expects an already-parsed int.
    @staticmethod
    def validate_quantity(quantity):
        return isinstance(quantity, int) and quantity >= 1
