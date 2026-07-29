"""
routes/orders.py -- Module B: client order placement (FR-B1/B2/B3) and the
owner's pending-order approval queue (FR-B4).
"""

import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.client import Client
from models.order import Order, OrderStateError, OrderValidationError, WEEKDAYS
from routes.auth import login_required

orders_bp = Blueprint("orders", __name__)

# FR-B3: weeks of future dates to offer -- fixed weekdays only, not a date picker
DELIVERY_DATE_WEEKS_AHEAD = 8


def _upcoming_delivery_dates(assigned_days):
    """Every future occurrence of `assigned_days` over the next
    DELIVERY_DATE_WEEKS_AHEAD weeks, soonest first."""
    today = datetime.date.today()
    dates = []
    for offset in range(1, DELIVERY_DATE_WEEKS_AHEAD * 7 + 1):
        day = today + datetime.timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in assigned_days:
            dates.append(day)
    return dates


def _notify_client_order_status(order_id, status):
    """Stub for FR-B4's client notification email. Flask-Mail/SMTP wiring
    is a later task -- this only marks where that call goes."""
    print(f"[stub email] order {order_id} -> client notified: {status}")


@orders_bp.route("/client/order", methods=["GET", "POST"])
@login_required("client")
def client_order_form():
    """FR-B1/B2/B3: the client's order form. GET renders it; POST validates
    and places the order via Order.place(), which owns every FR-B1 rule
    (approved products, positive-integer quantities, assigned delivery day)."""
    client = Client.load_by_user_id(session["user_id"])
    approved_products = client.get_approved_products()
    delivery_dates = _upcoming_delivery_dates(client.delivery_days)

    if request.method == "GET":
        return render_template(
            "order_form.html", client=client, products=approved_products,
            delivery_dates=delivery_dates, error=None, submitted={},
        )

    raw_quantities = {
        product["product_id"]: request.form.get(f"quantity_{product['product_id']}", "")
        for product in approved_products
    }
    delivery_date = request.form.get("delivery_date", "")
    special_instructions = request.form.get("special_instructions", "")

    try:
        Order.place(client, delivery_date, raw_quantities, special_instructions)
    except OrderValidationError as exc:
        return render_template(
            "order_form.html", client=client, products=approved_products,
            delivery_dates=delivery_dates, error=str(exc), submitted=request.form,
        ), 400

    flash("Your order has been placed and is awaiting approval.", "success")
    return redirect(url_for("orders.client_order_form"))


@orders_bp.route("/owner/orders/pending")
@login_required("owner")
def owner_pending_orders():
    """FR-B4: the owner's simple pending-approval queue. The fuller
    filter/search/paginated all-orders view (Module 6) is a separate,
    later screen -- this one only ever shows orders awaiting a decision."""
    return render_template("owner_orders_pending.html", orders=Order.get_pending())


@orders_bp.route("/owner/orders/<int:order_id>/approve", methods=["POST"])
@login_required("owner")
def approve_order(order_id):
    try:
        Order.approve(order_id, session["user_id"])
    except OrderStateError as exc:
        flash(str(exc), "error")
    else:
        _notify_client_order_status(order_id, "approved")
        flash(f"Order #{order_id} approved.", "success")

    return redirect(url_for("orders.owner_pending_orders"))


@orders_bp.route("/owner/orders/<int:order_id>/reject", methods=["POST"])
@login_required("owner")
def reject_order(order_id):
    try:
        Order.reject(order_id, session["user_id"])
    except OrderStateError as exc:
        flash(str(exc), "error")
    else:
        _notify_client_order_status(order_id, "rejected")
        flash(f"Order #{order_id} rejected.", "success")

    return redirect(url_for("orders.owner_pending_orders"))
