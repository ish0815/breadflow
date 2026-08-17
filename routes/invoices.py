# routes/invoices.py -- Module D: batch invoice generation (FR-D1) + records (FR-D2).

import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from email_utils import send_email
from models.client import Client
from models.invoice import Invoice, InvoiceStateError
from routes.auth import login_required

invoices_bp = Blueprint("invoices", __name__)


# FR-D1: emails the client their invoice PDF. Mockup is manual-trigger ("Email"/"Email All"
# buttons), not automatic-on-generate, so this is only ever called from send_invoice/send_all_invoices.
def _notify_client_invoice_sent(invoice):
    recipient = Client.load_by_client_id(invoice.client_id)
    send_email(
        subject=f"BreadFlow invoice {invoice.display_id}",
        recipients=[recipient.email],
        body=f"Your invoice {invoice.display_id} for {invoice.billing_period_start} to "
             f"{invoice.billing_period_end} is attached. Total due: ${invoice.invoice_total:.2f}.",
        attachment_path=invoice.pdf_path,
        attachment_filename=f"{invoice.display_id}.pdf",
    )


# GET renders the period picker + full invoice list; POST runs "Generate All Invoices".
@invoices_bp.route("/owner/invoices", methods=["GET", "POST"])
@login_required("owner")
def owner_invoices():
    if request.method == "POST":
        period_start = request.form.get("period_start", "")
        period_end = request.form.get("period_end", "")
        try:
            datetime.date.fromisoformat(period_start)
            datetime.date.fromisoformat(period_end)
        except ValueError:
            flash("Please select a valid billing period.", "error")
            return redirect(url_for("invoices.owner_invoices"))

        if period_end < period_start:
            flash("Billing period end must be on or after the start date.", "error")
            return redirect(url_for("invoices.owner_invoices"))

        generated = Invoice.generate_all(period_start, period_end, session["user_id"])
        if not generated:
            flash("No approved orders found for that billing period.", "error")
        else:
            flash(f"{len(generated)} invoice(s) generated.", "success")
        return redirect(url_for("invoices.owner_invoices"))

    return render_template("owner_invoices.html", invoices=Invoice.list_all())


@invoices_bp.route("/owner/invoices/<int:invoice_id>/send", methods=["POST"])
@login_required("owner")
def send_invoice(invoice_id):
    invoice = Invoice.load(invoice_id)
    if invoice is None:
        abort(404)

    # email first -- a failed send must not leave the invoice incorrectly marked as sent
    try:
        _notify_client_invoice_sent(invoice)
    except Exception as exc:
        flash(f"Invoice {invoice.display_id} could not be emailed: {exc}", "error")
        return redirect(url_for("invoices.owner_invoices"))

    try:
        Invoice.mark_sent(invoice_id)
    except InvoiceStateError as exc:
        flash(str(exc), "error")
    else:
        flash("Invoice sent.", "success")
    return redirect(url_for("invoices.owner_invoices"))


# Email All: same action, looped over every currently-draft invoice.
@invoices_bp.route("/owner/invoices/send-all", methods=["POST"])
@login_required("owner")
def send_all_invoices():
    sent_count = 0
    failed_count = 0
    for invoice in Invoice.list_all():
        if invoice.invoice_status != "draft":
            continue
        try:
            _notify_client_invoice_sent(invoice)
        except Exception:
            failed_count += 1
            continue
        Invoice.mark_sent(invoice.invoice_id)
        sent_count += 1

    if failed_count:
        flash(f"{sent_count} invoice(s) sent, {failed_count} could not be emailed.", "error")
    else:
        flash(f"{sent_count} invoice(s) sent.", "success")
    return redirect(url_for("invoices.owner_invoices"))


@invoices_bp.route("/owner/invoices/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required("owner")
def mark_invoice_paid(invoice_id):
    try:
        Invoice.mark_paid(invoice_id)
    except InvoiceStateError as exc:
        flash(str(exc), "error")
    else:
        flash("Invoice marked as paid.", "success")
    return redirect(url_for("invoices.owner_invoices"))


@invoices_bp.route("/owner/invoices/<int:invoice_id>/pdf")
@login_required("owner")
def owner_invoice_pdf(invoice_id):
    invoice = Invoice.load(invoice_id)
    if invoice is None or invoice.pdf_path is None:
        abort(404)
    return send_file(invoice.pdf_path, mimetype="application/pdf")


# FR-D2: client sees only their own invoice history.
@invoices_bp.route("/client/invoices")
@login_required("client")
def client_invoices():
    client = Client.load_by_user_id(session["user_id"])
    return render_template("client_invoices.html", client=client,
                            invoices=Invoice.list_for_client(client.client_id))


@invoices_bp.route("/client/invoices/<int:invoice_id>/pdf")
@login_required("client")
def client_invoice_pdf(invoice_id):
    invoice = Invoice.load(invoice_id)
    if invoice is None or invoice.pdf_path is None:
        abort(404)
    if invoice.client_id != session["client_id"]:
        abort(403)  # FR-A3: never let a client fetch another client's invoice
    return send_file(invoice.pdf_path, mimetype="application/pdf")
