# test_invoice_emailing.py -- Criterion 8 test evidence: FR-D1 "Email"/"Email All" invoice
# routes (routes/invoices.py send_invoice/send_all_invoices), covering the PDF-attached
# email, the draft->sent transition on success, and Email All looping over every draft.
# Permanent test script -- keep in the repo, do not delete.

import os

from app import app
from database.db import get_db_connection
from email_utils import mail
from models.invoice import Invoice

app.config["TESTING"] = True
client = app.test_client()

# far-future periods, well past every date in the committed seed data, so this test
# never picks up real orders and never collides on a rerun (same convention as
# test_invoice_generation.py). Two distinct periods so the second Email All batch's
# generate_all() call doesn't re-scan (and duplicate-invoice) the first batch's client --
# generate_all() has no per-period uniqueness guard against re-generating an invoice.
PERIOD_START = "2027-02-01"
PERIOD_END = "2027-02-07"
PERIOD_START_2 = "2027-02-15"
PERIOD_END_2 = "2027-02-21"


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


# mirrors test_invoice_generation.py's direct-INSERT approach -- Client.create() enforces
# onboarding rules (product catalogue, etc.) not relevant to invoice emailing
def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@invoice-email-test.local",),
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


def _make_delivered_order(connection, client_id, product_id, delivery_date):
    order_cursor = connection.execute(
        "INSERT INTO orders (client_id, delivery_date, order_status) VALUES (?, ?, 'delivered')",
        (client_id, delivery_date),
    )
    order_id = order_cursor.lastrowid
    connection.execute(
        "INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, 5, 5.00)",
        (order_id, product_id),
    )
    connection.commit()
    return order_id


# invoices.client_id has no ON DELETE CASCADE, so invoices must be deleted before the client
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


connection = get_db_connection()
try:
    owner_row = connection.execute(
        "SELECT user_id FROM users WHERE role = 'owner' AND is_active = 1 LIMIT 1"
    ).fetchone()
    bread_row = connection.execute("SELECT product_id FROM products WHERE product_name = 'Bread'").fetchone()
finally:
    connection.close()

OWNER_ID = owner_row["user_id"]
BREAD_ID = bread_row["product_id"]

invoices = []
client_ids = []

try:
    # 1. FR-D1: "Email" on a single draft invoice emails the PDF and marks it sent
    connection = get_db_connection()
    try:
        client_id, user_id = _make_test_client(connection, "Email Test Cafe", "90000000010")
        _make_delivered_order(connection, client_id, BREAD_ID, PERIOD_START)
    finally:
        connection.close()
    client_ids.append((client_id, user_id))

    invoices = Invoice.generate_all(PERIOD_START, PERIOD_END, OWNER_ID)
    invoice = next(inv for inv in invoices if inv.client_id == client_id)
    assert invoice.invoice_status == "draft", invoice.invoice_status

    seed_session(OWNER_ID, "owner")
    with mail.record_messages() as outbox:
        response = client.post(f"/owner/invoices/{invoice.invoice_id}/send", follow_redirects=True)
    assert response.status_code == 200, response.status_code
    assert b"Invoice sent." in response.data
    print("PASS: emailing a single draft invoice succeeds and redirects with a success flash")

    # TESTING=True (set above) makes Flask-Mail suppress real SMTP sends automatically --
    # record_messages() still captures them via blinker signals, so no network call happens here.
    assert len(outbox) == 1, outbox
    sent_message = outbox[0]
    assert sent_message.recipients == [f"90000000010@invoice-email-test.local"], sent_message.recipients
    assert len(sent_message.attachments) == 1, sent_message.attachments
    assert sent_message.attachments[0].filename == f"{invoice.display_id}.pdf", sent_message.attachments[0].filename
    print("PASS: invoice email has exactly one PDF attachment matching the invoice")

    assert Invoice.load(invoice.invoice_id).invoice_status == "sent"
    print("PASS: invoice status flips from draft to sent only after a successful send")

    # 2. FR-D1: "Email All" sends every remaining draft invoice for the batch
    connection = get_db_connection()
    try:
        client_id_2, user_id_2 = _make_test_client(connection, "Email Test Bakery", "90000000011")
        _make_delivered_order(connection, client_id_2, BREAD_ID, PERIOD_START_2)
        client_id_3, user_id_3 = _make_test_client(connection, "Email Test Deli", "90000000012")
        _make_delivered_order(connection, client_id_3, BREAD_ID, PERIOD_START_2)
    finally:
        connection.close()
    client_ids.append((client_id_2, user_id_2))
    client_ids.append((client_id_3, user_id_3))

    batch_invoices = Invoice.generate_all(PERIOD_START_2, PERIOD_END_2, OWNER_ID)
    invoices += [inv for inv in batch_invoices if inv.client_id in (client_id_2, client_id_3)]
    draft_ids = {inv.client_id: inv.invoice_id for inv in batch_invoices
                 if inv.client_id in (client_id_2, client_id_3)}
    assert len(draft_ids) == 2, draft_ids

    with mail.record_messages() as outbox:
        response = client.post("/owner/invoices/send-all", follow_redirects=True)
    assert response.status_code == 200, response.status_code
    print("PASS: Email All succeeds and redirects")

    # Email All loops over every draft invoice currently in the system, not just this
    # test's two -- assert on the two this test cares about rather than an exact count.
    sent_recipients = {tuple(m.recipients) for m in outbox}
    assert (f"90000000011@invoice-email-test.local",) in sent_recipients, sent_recipients
    assert (f"90000000012@invoice-email-test.local",) in sent_recipients, sent_recipients
    print("PASS: Email All emailed both newly generated draft invoices")

    assert Invoice.load(draft_ids[client_id_2]).invoice_status == "sent"
    assert Invoice.load(draft_ids[client_id_3]).invoice_status == "sent"
    print("PASS: Email All marks every draft invoice it emails as sent")

    print("\nAll checks passed.")
finally:
    for client_id, user_id in client_ids:
        _cleanup_client(client_id, user_id, [inv for inv in invoices if inv.client_id == client_id])
    print(f"cleanup: removed {len(client_ids)} test client(s) and their invoices")
