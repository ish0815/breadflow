# test_invoice_generation.py -- Criterion 8 test evidence: FR-D1 Invoice.generate_all()/
# _generate_for_client(), covering the approved-vs-delivered order_status filter fix,
# a manual total/GST/line-item calculation, and a basic happy-path PDF+row check.
# Permanent test script -- keep in the repo, do not delete.

import os

from database.db import get_db_connection
from models.invoice import Invoice

GST_RATE = 0.10  # matches models/invoice.py -- 10% on the taxable bucket only

# far-future period, well past every date in the committed seed data (max 2026-08-11
# as of writing), so these tests never pick up real orders and never collide on a rerun
PERIOD_START = "2027-01-04"
PERIOD_END = "2027-01-10"


# Inserts a client (+ its backing user row) directly, mirroring test_driver_routing.py's
# direct-INSERT approach -- Client.register() enforces onboarding rules not relevant here.
def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@invoice-test.local",),
    )
    user_id = user_cursor.lastrowid
    client_cursor = connection.execute(
        """
        INSERT INTO clients (user_id, business_name, abn, delivery_zone,
            delivery_day1, delivery_day2, delivery_charge)
        VALUES (?, ?, ?, 'Western', 'Monday', 'Thursday', 15.0)
        """,
        (user_id, business_name, abn),
    )
    client_id = client_cursor.lastrowid
    connection.commit()
    return client_id, user_id


# lines: list of (product_id, quantity, unit_price) -- unit_price passed explicitly
# rather than looked up, since real orders lock it in from client_products.agreed_price
def _make_order(connection, client_id, order_status, lines):
    order_cursor = connection.execute(
        "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, ?)",
        (client_id, PERIOD_START, order_status),
    )
    order_id = order_cursor.lastrowid
    for product_id, quantity, unit_price in lines:
        connection.execute(
            "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, product_id, quantity, unit_price),
        )
    connection.commit()
    return order_id


# invoices.client_id has no ON DELETE CASCADE (unlike orders/order_lines, which cascade
# off clients), so invoices must be deleted before the client or the FK pragma blocks it
def _cleanup_client(client_id, user_id, invoices):
    for invoice in invoices:
        if invoice.pdf_path and os.path.exists(invoice.pdf_path):
            os.remove(invoice.pdf_path)
    connection = get_db_connection()
    try:
        connection.execute("DELETE FROM invoices WHERE client_id = ?", (client_id,))
        connection.execute("DELETE FROM clients WHERE client_id = ?", (client_id,))
        connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        connection.commit()
    finally:
        connection.close()


def test_invoice_excludes_undelivered_orders(owner_id, bread_id, kulcha_id):
    connection = get_db_connection()
    try:
        client_id, user_id = _make_test_client(connection, "Test Loaf Cafe", "90000000001")
        # approved but not yet delivered -- must NOT appear on the invoice
        _make_order(connection, client_id, "approved", [(bread_id, 20, 5.00)])
        # approved and delivered -- the only order that should appear
        _make_order(connection, client_id, "delivered", [(kulcha_id, 15, 3.80)])
    finally:
        connection.close()

    invoices = []
    try:
        invoices = Invoice.generate_all(PERIOD_START, PERIOD_END, owner_id)
        invoice = next(inv for inv in invoices if inv.client_id == client_id)

        assert invoice.approved_order_count == 1, invoice.approved_order_count
        assert len(invoice.lines) == 1, len(invoice.lines)
        line = invoice.lines[0]
        assert line.product_name == "Kulcha", line.product_name
        assert line.quantity == 15, line.quantity
        assert line.unit_price == 3.80, line.unit_price
        print("PASS: invoice excludes the approved-only order, includes only the delivered one")
    finally:
        _cleanup_client(client_id, user_id, invoices)


def test_invoice_includes_delivered_orders(owner_id, bread_id, kulcha_id):
    connection = get_db_connection()
    try:
        client_id, user_id = _make_test_client(connection, "Test Bakery Co", "90000000002")
        # one delivered order, two product lines -- exercises both grouping and totals
        _make_order(connection, client_id, "delivered", [
            (bread_id, 10, 5.00),
            (kulcha_id, 8, 3.80),
        ])
    finally:
        connection.close()

    # manual calculation matching models/invoice.py's bucketing (both products are
    # GST-free per products.gst_applicable; delivery is always taxable)
    expected_gst_free_subtotal = 10 * 5.00 + 8 * 3.80  # 80.40
    expected_delivery_charge_total = 15.0 * 1  # one delivered order, client's flat fee
    expected_taxable_subtotal = expected_delivery_charge_total  # 15.00
    expected_gst_amount = round(expected_taxable_subtotal * GST_RATE, 2)  # 1.50
    expected_invoice_total = expected_gst_free_subtotal + expected_taxable_subtotal + expected_gst_amount

    invoices = []
    try:
        invoices = Invoice.generate_all(PERIOD_START, PERIOD_END, owner_id)
        invoice = next(inv for inv in invoices if inv.client_id == client_id)

        assert invoice.gst_free_subtotal == expected_gst_free_subtotal, invoice.gst_free_subtotal
        assert invoice.taxable_subtotal == expected_taxable_subtotal, invoice.taxable_subtotal
        assert invoice.delivery_charge_total == expected_delivery_charge_total, invoice.delivery_charge_total
        assert invoice.gst_amount == expected_gst_amount, invoice.gst_amount
        assert invoice.invoice_total == expected_invoice_total, invoice.invoice_total

        lines_by_product = {line.product_name: line for line in invoice.lines}
        assert set(lines_by_product) == {"Bread", "Kulcha"}, lines_by_product.keys()
        assert lines_by_product["Bread"].quantity == 10
        assert lines_by_product["Bread"].unit_price == 5.00
        assert lines_by_product["Kulcha"].quantity == 8
        assert lines_by_product["Kulcha"].unit_price == 3.80
        print("PASS: invoice totals, GST, and line items match the manual calculation")
    finally:
        _cleanup_client(client_id, user_id, invoices)


def test_invoice_generation_basic(owner_id, bread_id):
    connection = get_db_connection()
    try:
        client_id, user_id = _make_test_client(connection, "Test Corner Store", "90000000003")
        _make_order(connection, client_id, "delivered", [(bread_id, 12, 5.00)])
    finally:
        connection.close()

    invoices = []
    try:
        invoices = Invoice.generate_all(PERIOD_START, PERIOD_END, owner_id)
        invoice = next(inv for inv in invoices if inv.client_id == client_id)

        assert invoice.pdf_path, "expected a pdf_path to be set"
        assert os.path.exists(invoice.pdf_path), invoice.pdf_path
        print("PASS: invoice PDF file created on disk")

        check_connection = get_db_connection()
        try:
            row = check_connection.execute(
                "SELECT invoice_id FROM invoices WHERE invoice_id = ?", (invoice.invoice_id,)
            ).fetchone()
        finally:
            check_connection.close()
        assert row is not None, "expected an invoices table row for the generated invoice"
        print("PASS: invoices table row exists for the generated invoice")
    finally:
        _cleanup_client(client_id, user_id, invoices)


connection = get_db_connection()
try:
    owner_row = connection.execute(
        "SELECT user_id FROM users WHERE role = 'owner' AND is_active = 1 LIMIT 1"
    ).fetchone()
    bread_row = connection.execute("SELECT product_id FROM products WHERE product_name = 'Bread'").fetchone()
    kulcha_row = connection.execute("SELECT product_id FROM products WHERE product_name = 'Kulcha'").fetchone()
finally:
    connection.close()

owner_id = owner_row["user_id"]
bread_id = bread_row["product_id"]
kulcha_id = kulcha_row["product_id"]

test_invoice_excludes_undelivered_orders(owner_id, bread_id, kulcha_id)
test_invoice_includes_delivered_orders(owner_id, bread_id, kulcha_id)
test_invoice_generation_basic(owner_id, bread_id)

print("\nAll checks passed.")
