# routes/orders.py -- Module B: order placement (FR-B1/B2/B3) + owner approval queue (FR-B4).

import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.client import Client
from models.order import Order, OrderStateError, OrderValidationError, WEEKDAYS
from routes.auth import login_required

orders_bp = Blueprint("orders", __name__)

# FR-B3: weeks of future dates to offer -- fixed weekdays only, not a date picker
DELIVERY_DATE_WEEKS_AHEAD = 8


# Future occurrences of `assigned_days`, soonest first.
def _upcoming_delivery_dates(assigned_days):
    today = datetime.date.today()
    dates = []
    for offset in range(1, DELIVERY_DATE_WEEKS_AHEAD * 7 + 1):
        day = today + datetime.timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in assigned_days:
            dates.append(day)
    return dates


# Stub for FR-B4's client notification email -- real SMTP comes later.
def _notify_client_order_status(order_id, status):
    print(f"[stub email] order {order_id} -> client notified: {status}")


# FR-B1/B2/B3: GET renders the order form, POST places it via Order.place().
@orders_bp.route("/client/order", methods=["GET", "POST"])
@login_required("client")
def client_order_form():
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


# FR-B4: simple pending queue. Full filter/search view is Module B, later.
@orders_bp.route("/owner/orders/pending")
@login_required("owner")
def owner_pending_orders():
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
