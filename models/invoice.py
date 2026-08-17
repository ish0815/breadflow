# models/invoice.py -- Invoice: FR-D1 batch generation + FR-D2 records, per client per period.

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from database.db import get_db_connection
from models.invoice_line import InvoiceLine

GST_RATE = 0.10  # FR-D1: 10% GST on the taxable bucket only

# same convention as db.py's DATABASE_PATH -- absolute, so PDF writes don't
# depend on the process's working directory
PDF_DIR = Path(__file__).resolve().parent.parent / "instance" / "invoices"

BREAD_STAPLE_NAME = "Bread Staple Bakery"
BREAD_STAPLE_LOCATION = "Williamstown North, VIC"


# send()/mark_paid() called on an invoice not in the required prior state.
class InvoiceStateError(Exception):
    pass


# One client's invoice for a billing period: header totals + InvoiceLine snapshot rows.
class Invoice:

    def __init__(self, invoice_id, client_id, billing_period_start, billing_period_end,
                 gst_free_subtotal, taxable_subtotal, delivery_charge_total,
                 approved_order_count, gst_amount, invoice_total, invoice_status,
                 pdf_path, generated_by, generated_at, sent_at=None,
                 business_name=None, abn=None, lines=None):
        self._invoice_id = invoice_id
        self._client_id = client_id
        self._billing_period_start = billing_period_start
        self._billing_period_end = billing_period_end
        self._gst_free_subtotal = gst_free_subtotal
        self._taxable_subtotal = taxable_subtotal
        self._delivery_charge_total = delivery_charge_total
        self._approved_order_count = approved_order_count
        self._gst_amount = gst_amount
        self._invoice_total = invoice_total
        self._invoice_status = invoice_status
        self._pdf_path = pdf_path
        self._generated_by = generated_by
        self._generated_at = generated_at
        self._sent_at = sent_at
        # only set when joined with clients, for display purposes
        self._business_name = business_name
        self._abn = abn
        self._lines = lines or []

    # ---- read-only accessors ----------------------------------------------

    @property
    def invoice_id(self):
        return self._invoice_id

    @property
    def client_id(self):
        return self._client_id

    # FR-D1: 
    # separate stored ID, consistent with every other table in this schema
    @property
    def display_id(self):
        return f"INV-{self._invoice_id:04d}"

    @property
    def billing_period_start(self):
        return self._billing_period_start

    @property
    def billing_period_end(self):
        return self._billing_period_end

    @property
    def gst_free_subtotal(self):
        return self._gst_free_subtotal

    @property
    def taxable_subtotal(self):
        return self._taxable_subtotal

    @property
    def delivery_charge_total(self):
        return self._delivery_charge_total

    @property
    def approved_order_count(self):
        return self._approved_order_count

    @property
    def gst_amount(self):
        return self._gst_amount

    @property
    def invoice_total(self):
        return self._invoice_total

    @property
    def invoice_status(self):
        return self._invoice_status

    @property
    def pdf_path(self):
        return self._pdf_path

    @property
    def generated_at(self):
        return self._generated_at

    @property
    def sent_at(self):
        return self._sent_at

    @property
    def business_name(self):
        return self._business_name

    @property
    def abn(self):
        return self._abn

    @property
    def lines(self):
        return self._lines

    # ---- generation (FR-D1) -------------------------------------------------

    # Batch "Generate All Invoices": one Invoice per client with >=1 approved order
    # in [period_start, period_end]. Clients with none never appear in the query
    # below, so they're skipped.
    @classmethod
    def generate_all(cls, period_start, period_end, owner_id):
        connection = get_db_connection()
        try:
            # FR-D1 requires approved AND delivered orders; 'delivered' implies
            # 'approved' was already passed (FR-B4 gates that transition)
            client_rows = connection.execute(
                """
                SELECT DISTINCT client_id FROM orders
                WHERE order_status = 'delivered' AND delivery_date BETWEEN ? AND ?
                ORDER BY client_id
                """,
                (period_start, period_end),
            ).fetchall()

            invoices = [
                cls._generate_for_client(connection, row["client_id"], period_start, period_end, owner_id)
                for row in client_rows
            ]
            return invoices
        finally:
            connection.close()

    # One client's invoice: aggregate lines, bucket GST, insert header+lines, write PDF.
    # Reuses the caller's connection (avoids opening one per client in the batch), but
    # commits per client
    @classmethod
    def _generate_for_client(cls, connection, client_id, period_start, period_end, owner_id):
        client_row = connection.execute(
            "SELECT business_name, abn, delivery_charge FROM clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()

        # FR-D1 requires approved AND delivered orders; 'delivered' implies 'approved'
        # was already passed (FR-B4 gates that transition), so this counts both.
        # Kept as approved_order_count to match the invoices table column, but it
        # now counts delivered orders, satisfying the approved+delivered requirement.
        approved_order_count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM orders
            WHERE client_id = ? AND order_status = 'delivered'
              AND delivery_date BETWEEN ? AND ?
            """,
            (client_id, period_start, period_end),
        ).fetchone()["count"]

        # grouped by (product, unit_price), not just product -- a mid-period agreed_price
        # change must produce two distinct lines, not one silently-blended wrong total
        # FR-D1 requires approved AND delivered orders; 'delivered' implies 'approved'
        # was already passed (FR-B4 gates that transition).
        line_rows = connection.execute(
            """
            SELECT order_lines.product_id, order_lines.unit_price, products.product_name,
                   products.gst_applicable, SUM(order_lines.quantity) AS quantity
            FROM order_lines
            JOIN orders ON orders.order_id = order_lines.order_id
            JOIN products ON products.product_id = order_lines.product_id
            WHERE orders.client_id = ? AND orders.order_status = 'delivered'
              AND orders.delivery_date BETWEEN ? AND ?
            GROUP BY order_lines.product_id, order_lines.unit_price
            ORDER BY products.product_name
            """,
            (client_id, period_start, period_end),
        ).fetchall()

        # -- GST bucketing: flag-driven per line, not a hardcoded "products are free" rule --
        gst_free_subtotal = 0.0
        taxable_subtotal = 0.0
        for row in line_rows:
            line_total = row["quantity"] * row["unit_price"]
            if row["gst_applicable"]:
                taxable_subtotal += line_total
            else:
                gst_free_subtotal += line_total

        # flat per-order fee x number of approved orders in the period -- delivery is
        # always taxable, so it joins the taxable bucket, never the GST-free one
        delivery_charge = client_row["delivery_charge"]
        delivery_charge_total = delivery_charge * approved_order_count
        taxable_subtotal += delivery_charge_total

        gst_amount = round(taxable_subtotal * GST_RATE, 2)
        invoice_total = gst_free_subtotal + taxable_subtotal + gst_amount

        cursor = connection.execute(
            """
            INSERT INTO invoices (client_id, billing_period_start, billing_period_end,
                gst_free_subtotal, taxable_subtotal, delivery_charge_total,
                approved_order_count, gst_amount, invoice_total, generated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (client_id, period_start, period_end, gst_free_subtotal, taxable_subtotal,
             delivery_charge_total, approved_order_count, gst_amount, invoice_total, owner_id),
        )
        invoice_id = cursor.lastrowid

        for row in line_rows:
            connection.execute(
                """
                INSERT INTO invoice_lines (invoice_id, product_id, quantity, unit_price, gst_applicable)
                VALUES (?, ?, ?, ?, ?)
                """,
                (invoice_id, row["product_id"], row["quantity"], row["unit_price"], row["gst_applicable"]),
            )

        connection.commit()

        header_row = connection.execute(
            "SELECT invoice_status, generated_at FROM invoices WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        lines = cls._get_lines(connection, invoice_id)

        invoice = cls(
            invoice_id, client_id, period_start, period_end, gst_free_subtotal,
            taxable_subtotal, delivery_charge_total, approved_order_count, gst_amount,
            invoice_total, header_row["invoice_status"], None, owner_id,
            header_row["generated_at"], business_name=client_row["business_name"],
            abn=client_row["abn"], lines=lines,
        )

        # passed through directly rather than back-computed from delivery_charge_total /
        # approved_order_count
        pdf_path = invoice.export_to_pdf(delivery_charge)
        connection.execute("UPDATE invoices SET pdf_path = ? WHERE invoice_id = ?",
                            (str(pdf_path), invoice_id))
        connection.commit()
        invoice._pdf_path = str(pdf_path)
        return invoice

    # This invoice's InvoiceLine rows, joined with product_name for display.
    @staticmethod
    def _get_lines(connection, invoice_id):
        rows = connection.execute(
            """
            SELECT invoice_lines.*, products.product_name
            FROM invoice_lines
            JOIN products ON products.product_id = invoice_lines.product_id
            WHERE invoice_lines.invoice_id = ?
            ORDER BY products.product_name
            """,
            (invoice_id,),
        ).fetchall()
        return [
            InvoiceLine(row["invoice_line_id"], row["invoice_id"], row["product_id"],
                        row["quantity"], row["unit_price"], row["gst_applicable"],
                        product_name=row["product_name"])
            for row in rows
        ]

    # ---- PDF (FR-D1) ----------------------------------------------------------

    # Renders this invoice via ReportLab, saves to instance/invoices/INV-0007.pdf,
    # returns the path. delivery_unit_charge is the client's flat per-order fee,
    # shown as the delivery line's unit price.
    def export_to_pdf(self, delivery_unit_charge):
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = PDF_DIR / f"{self.display_id}.pdf"

        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)

        story = [
            Paragraph(BREAD_STAPLE_NAME, styles["Title"]),
            Paragraph(BREAD_STAPLE_LOCATION, styles["Normal"]),
            Spacer(1, 12),
            Paragraph(f"Tax Invoice {self.display_id}", styles["Heading2"]),
            Paragraph(f"Bill to: {self._business_name} (ABN {self._abn})", styles["Normal"]),
            Paragraph(f"Billing period: {self._billing_period_start} to {self._billing_period_end}",
                      styles["Normal"]),
            Spacer(1, 12),
        ]

        line_table_data = [["Product", "Qty", "Unit Price", "Subtotal"]]
        for line in self._lines:
            line_table_data.append([
                line.product_name, str(line.quantity),
                f"${line.unit_price:.2f}", f"${line.calculate_line_total():.2f}",
            ])
        line_table_data.append([
            "Delivery", str(self._approved_order_count),
            f"${delivery_unit_charge:.2f}", f"${self._delivery_charge_total:.2f}",
        ])
        story.append(Table(line_table_data, style=TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])))
        story.append(Spacer(1, 16))

        story.append(Table([
            ["GST-free subtotal", f"${self._gst_free_subtotal:.2f}"],
            ["Taxable subtotal", f"${self._taxable_subtotal:.2f}"],
            ["GST (10%)", f"${self._gst_amount:.2f}"],
            ["Total", f"${self._invoice_total:.2f}"],
        ], colWidths=[300, 100]))

        doc.build(story)
        return pdf_path

    # ---- lifecycle (FR-D1) -----------------------------------------------------

    @classmethod
    def mark_sent(cls, invoice_id):
        cls._set_status(invoice_id, "sent", "draft", "sent_at")

    @classmethod
    def mark_paid(cls, invoice_id):
        cls._set_status(invoice_id, "paid", "sent", None)

    @staticmethod
    def _set_status(invoice_id, new_status, required_status, timestamp_column):
        connection = get_db_connection()
        try:
            set_clause = "invoice_status = ?"
            if timestamp_column:
                set_clause += f", {timestamp_column} = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')"
            # only matches if still in the required prior state -- blocks a double send/pay
            cursor = connection.execute(
                f"UPDATE invoices SET {set_clause} WHERE invoice_id = ? AND invoice_status = ?",
                (new_status, invoice_id, required_status),
            )
            connection.commit()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            raise InvoiceStateError("This invoice is not in the expected state for that action")

    # ---- records (FR-D2) --------------------------------------------------------

    # Owner's full invoice history, every client, newest first.
    @classmethod
    def list_all(cls):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT invoices.*, clients.business_name, clients.abn
                FROM invoices
                JOIN clients ON clients.client_id = invoices.client_id
                ORDER BY invoices.generated_at DESC
                """
            ).fetchall()
        finally:
            connection.close()
        return [cls._build_from_row(row) for row in rows]

    # FR-D2: a client's own invoice history only.
    @classmethod
    def list_for_client(cls, client_id):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT invoices.*, clients.business_name, clients.abn
                FROM invoices
                JOIN clients ON clients.client_id = invoices.client_id
                WHERE invoices.client_id = ?
                ORDER BY invoices.generated_at DESC
                """,
                (client_id,),
            ).fetchall()
        finally:
            connection.close()
        return [cls._build_from_row(row) for row in rows]

    # Single invoice + its lines, for the PDF-download routes. None if it doesn't exist.
    @classmethod
    def load(cls, invoice_id):
        connection = get_db_connection()
        try:
            row = connection.execute(
                """
                SELECT invoices.*, clients.business_name, clients.abn
                FROM invoices
                JOIN clients ON clients.client_id = invoices.client_id
                WHERE invoices.invoice_id = ?
                """,
                (invoice_id,),
            ).fetchone()
            if row is None:
                return None
            lines = cls._get_lines(connection, invoice_id)
        finally:
            connection.close()
        return cls._build_from_row(row, lines=lines)

    @staticmethod
    def _build_from_row(row, lines=None):
        return Invoice(
            row["invoice_id"], row["client_id"], row["billing_period_start"],
            row["billing_period_end"], row["gst_free_subtotal"], row["taxable_subtotal"],
            row["delivery_charge_total"], row["approved_order_count"], row["gst_amount"],
            row["invoice_total"], row["invoice_status"], row["pdf_path"],
            row["generated_by"], row["generated_at"], sent_at=row["sent_at"],
            business_name=row["business_name"], abn=row["abn"], lines=lines or [],
        )
