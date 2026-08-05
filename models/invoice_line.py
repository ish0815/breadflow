# models/invoice_line.py -- InvoiceLine: one (product, unit_price) aggregate on an invoice.


# One invoice_lines row: product, quantity, and price aggregated across a billing period.
class InvoiceLine:

    def __init__(self, invoice_line_id, invoice_id, product_id, quantity, unit_price,
                 gst_applicable, product_name=None):
        self._invoice_line_id = invoice_line_id
        self._invoice_id = invoice_id
        self._product_id = product_id
        self._quantity = quantity
        self._unit_price = unit_price
        # snapshot of products.gst_applicable at generation time -- see schema.sql
        self._gst_applicable = bool(gst_applicable)
        # only set when joined with products, for display purposes
        self._product_name = product_name

    @property
    def invoice_line_id(self):
        return self._invoice_line_id

    @property
    def invoice_id(self):
        return self._invoice_id

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
    def gst_applicable(self):
        return self._gst_applicable

    @property
    def product_name(self):
        return self._product_name

    # quantity x unitPrice.
    def calculate_line_total(self):
        return self._quantity * self._unit_price
