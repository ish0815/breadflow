# routes/orders.py -- Module B: order placement (FR-B1/B2/B3) + owner approval queue (FR-B4)
# + Module 6/10: owner order management and client order history.

import datetime
from math import ceil

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from email_utils import send_email
from models.client import Client
from models.delivery import Delivery, DeliveryValidationError
from models.driver import Driver
from models.order import Order, OrderStateError, OrderValidationError, WEEKDAYS
from routes.auth import login_required

orders_bp = Blueprint("orders", __name__)

# FR-B3: weeks of future dates to offer -- fixed weekdays only, not a date picker
DELIVERY_DATE_WEEKS_AHEAD = 8

# Module 6/10: data dictionary confirms 24/48/100 as the only page-size choices
PAGE_SIZES = (24, 48, 100)
DEFAULT_PAGE_SIZE = 24


# Shared by owner_orders/client_order_history: clamps page/per_page from query args.
def _parse_pagination_args(args):
    try:
        page = int(args.get("page", 1))
    except ValueError:
        page = 1
    try:
        per_page = int(args.get("per_page", DEFAULT_PAGE_SIZE))
    except ValueError:
        per_page = DEFAULT_PAGE_SIZE
    if per_page not in PAGE_SIZES:
        per_page = DEFAULT_PAGE_SIZE
    if page < 1:
        page = 1
    return page, per_page


# Future occurrences of `assigned_days`, soonest first.
def _upcoming_delivery_dates(assigned_days):
    today = datetime.date.today()
    dates = []
    for offset in range(1, DELIVERY_DATE_WEEKS_AHEAD * 7 + 1):
        day = today + datetime.timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in assigned_days:
            dates.append(day)
    return dates


# FR-B1: emails the client a confirmation once their order is placed.
def _notify_client_order_confirmation(order):
    client = Client.load_by_client_id(order.client_id)
    send_email(
        subject=f"BreadFlow order #{order.order_id} received",
        recipients=[client.email],
        body=f"We've received your order #{order.order_id} for {order.delivery_date}. "
             f"It's awaiting approval.",
    )


# FR-E1: auto-assigns the order to Bread Staple's one active driver so it
# shows up on their docket -- order status is already committed, so a
# failure here must not block approval (same philosophy as the email step below).
def _assign_default_driver(order_id):
    driver_id = Driver.get_default()
    if driver_id is None:
        raise DeliveryValidationError("No active driver account exists to assign")
    Delivery.create(order_id, driver_id)


# FR-B4: emails the client once an owner has approved/rejected their order.
def _notify_client_order_status(order_id, status):
    order = Order.get_by_id(order_id)
    client = Client.load_by_client_id(order.client_id)
    body = f"Your order #{order_id} for {order.delivery_date} has been {status}."
    if status == "rejected" and order.rejection_reason:
        body += f" Reason: {order.rejection_reason}"
    send_email(subject=f"BreadFlow order #{order_id} {status}", recipients=[client.email], body=body)


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
        order = Order.place(client, delivery_date, raw_quantities, special_instructions)
    except OrderValidationError as exc:
        return render_template(
            "order_form.html", client=client, products=approved_products,
            delivery_dates=delivery_dates, error=str(exc), submitted=request.form,
        ), 400

    try:
        _notify_client_order_confirmation(order)
    except Exception as exc:
        # order is already committed -- a failed confirmation email must not block placement
        flash(f"Your order has been placed, but the confirmation email could not be sent: {exc}", "error")
        return redirect(url_for("orders.client_order_form"))

    flash("Your order has been placed and is awaiting approval.", "success")
    return redirect(url_for("orders.client_order_form"))


# FR-B4: simple pending queue -- quick approve/reject. Module 6 below is the full list.
@orders_bp.route("/owner/orders/pending")
@login_required("owner")
def owner_pending_orders():
    return render_template("owner_orders_pending.html", orders=Order.get_pending())


# Module 6: full searchable/filterable/sortable/paginated order list.
@orders_bp.route("/owner/orders")
@login_required("owner")
def owner_orders():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "All")
    sort = request.args.get("sort", "newest")
    date_start = request.args.get("date_start", "").strip()
    date_end = request.args.get("date_end", "").strip()
    page, per_page = _parse_pagination_args(request.args)

    orders, total_count = Order.list_all(
        search=search or None, status=status, sort=sort,
        date_start=date_start or None, date_end=date_end or None,
        page=page, per_page=per_page,
    )

    return render_template(
        "owner_orders.html", orders=orders, search=search, status=status, sort=sort,
        date_start=date_start, date_end=date_end, page=page, per_page=per_page,
        page_sizes=PAGE_SIZES, total_count=total_count,
        total_pages=max(1, ceil(total_count / per_page)),
    )


# Module 6: read-only order detail, reached via the orders list's "View" action.
@orders_bp.route("/owner/orders/<int:order_id>")
@login_required("owner")
def owner_order_detail(order_id):
    order = Order.get_by_id(order_id)
    if order is None:
        abort(404)
    client = Client.load_by_client_id(order.client_id)
    return render_template(
        "owner_order_detail.html", order=order, client=client,
        lines=order.get_order_lines(), total_value=order.calculate_total(),
    )


# Module 10: client's own order history -- client_id always comes from the session
# (FR-A3), never from the request, so a client can only ever see their own orders.
@orders_bp.route("/client/orders")
@login_required("client")
def client_order_history():
    client = Client.load_by_user_id(session["user_id"])
    status = request.args.get("status", "All")
    month = request.args.get("month", "").strip()
    search = request.args.get("search", "").strip()
    page, per_page = _parse_pagination_args(request.args)

    orders, total_count = Order.list_for_client(
        client.client_id, status=status, month=month or None, search=search or None,
        page=page, per_page=per_page,
    )
    summary = Order.get_client_summary(client.client_id)

    return render_template(
        "client_order_history.html", client=client, orders=orders, summary=summary,
        status=status, month=month, search=search, page=page, per_page=per_page,
        page_sizes=PAGE_SIZES, total_count=total_count,
        total_pages=max(1, ceil(total_count / per_page)),
    )


@orders_bp.route("/owner/orders/<int:order_id>/approve", methods=["POST"])
@login_required("owner")
def approve_order(order_id):
    try:
        Order.approve(order_id, session["user_id"])
    except OrderStateError as exc:
        flash(str(exc), "error")
    else:
        try:
            _assign_default_driver(order_id)
        except DeliveryValidationError as exc:
            # order status is already committed -- a failed assignment must not block approval
            flash(f"Order #{order_id} approved, but no driver could be assigned: {exc}", "error")
            return redirect(url_for("orders.owner_pending_orders"))
        try:
            _notify_client_order_status(order_id, "approved")
        except Exception as exc:
            # order status is already committed -- a failed email must not block approval
            flash(f"Order #{order_id} approved, but the client could not be emailed: {exc}", "error")
            return redirect(url_for("orders.owner_pending_orders"))
        flash(f"Order #{order_id} approved.", "success")

    return redirect(url_for("orders.owner_pending_orders"))


@orders_bp.route("/owner/orders/<int:order_id>/reject", methods=["POST"])
@login_required("owner")
def reject_order(order_id):
    try:
        Order.reject(order_id, session["user_id"], request.form.get("reason", ""))
    except (OrderStateError, OrderValidationError) as exc:
        flash(str(exc), "error")
    else:
        try:
            _notify_client_order_status(order_id, "rejected")
        except Exception as exc:
            # order status is already committed -- a failed email must not block rejection
            flash(f"Order #{order_id} rejected, but the client could not be emailed: {exc}", "error")
            return redirect(url_for("orders.owner_pending_orders"))
        flash(f"Order #{order_id} rejected.", "success")

    return redirect(url_for("orders.owner_pending_orders"))
