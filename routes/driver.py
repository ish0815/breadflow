# routes/driver.py -- Module E: FR-E1/FR-E2 driver portal routes.

from datetime import date

from flask import Blueprint, render_template, request, session

from models.client import Client
from models.delivery import Delivery
from models.order import Order
from routes.auth import login_required

driver_bp = Blueprint("driver", __name__)


# FR-E1: driver's daily docket for a chosen date (today by default).
@driver_bp.route("/driver/dashboard")
@login_required("driver")
def dashboard():
    driver_id = session["user_id"]  # drivers have no separate driver_id in session
    docket_date = _resolve_date(request.args.get("date"))

    deliveries = Delivery.get_by_driver_and_date(driver_id, docket_date)
    docket = [_build_docket_entry(delivery) for delivery in deliveries]

    return render_template("driver_dashboard.html", docket=docket, docket_date=docket_date)


# Falls back to today on a missing or malformed ?date= param.
def _resolve_date(raw_date):
    if raw_date:
        try:
            return date.fromisoformat(raw_date).isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


# Assembles one display-ready docket card: client + product details for a Delivery.
# special_instructions is read from the delivery (its snapshot at assignment time),
# not the order, since that's the read-only copy the driver screen is meant to show.
def _build_docket_entry(delivery):
    order = Order.get_by_id(delivery.order_id)
    client = Client.load_by_client_id(order.client_id)
    lines = order.get_order_lines()

    return {
        "delivery_id": delivery.delivery_id,
        "delivery_status": delivery.delivery_status,
        "business_name": client.business_name,
        "delivery_zone": client.delivery_zone,
        "special_instructions": delivery.special_instructions,
        "order_lines": [{"product_name": line.product_name, "quantity": line.quantity} for line in lines],
    }
