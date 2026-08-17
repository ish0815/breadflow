# routes/driver.py -- Module E: FR-E1/FR-E2 driver portal routes.

import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from email_utils import send_email
from models.client import Client
from models.delivery import Delivery, DeliveryStateError, DeliveryValidationError
from models.order import Order, OrderStateError
from models.owner import Owner
from routes.auth import login_required

driver_bp = Blueprint("driver", __name__)

# FR-E2 data dictionary: proof photo -- JPEG/PNG only, max 10MB.
ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_PHOTO_MIMETYPES = {"image/jpeg", "image/png"}
MAX_PHOTO_BYTES = 10 * 1024 * 1024

# same convention as models/invoice.py's PDF_DIR -- static/ is assets only, never written to at runtime.
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "instance" / "uploads"


# FR-E2: emails all active owner accounts once a delivery is marked complete.
def _notify_owner_delivery(order_id, business_name):
    send_email(
        subject=f"BreadFlow delivery #{order_id} completed",
        recipients=Owner.list_active_emails(),
        body=f"Order #{order_id} for {business_name} has been delivered.",
    )


# FR-E2: emails the client once their delivery is marked complete.
def _notify_client_delivery(order_id, delivered_at, client_email):
    send_email(
        subject=f"BreadFlow order #{order_id} delivered",
        recipients=[client_email],
        body=f"Your order #{order_id} was delivered on {delivered_at}.",
    )


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


# special_instructions is read from the delivery -- a snapshot taken at assignment time.
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


# FR-E2: one route/one submission -- Delivery.mark_delivered() takes the photo path directly.
@driver_bp.route("/driver/delivery/<int:delivery_id>/deliver", methods=["POST"])
@login_required("driver")
def mark_delivered(delivery_id):
    delivery = Delivery.get_by_id(delivery_id)
    if delivery is None:
        abort(404)
    # ownership check before touching the file -- blocks a driver guessing another delivery's ID
    if delivery.driver_id != session["user_id"]:
        abort(403)

    photo = request.files.get("photo")
    error = _validate_photo(photo)
    if error:
        flash(error, "error")
        return redirect(url_for("driver.dashboard"))

    photo_path = _save_photo(delivery_id, photo)

    try:
        delivery.mark_delivered(str(photo_path))
    except (DeliveryValidationError, DeliveryStateError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("driver.dashboard"))

    try:
        Order.mark_delivered(delivery.order_id)
    except OrderStateError as exc:
        # delivery is already recorded -- don't undo it, no cross-table transaction
        # (each model method owns its own connection)
        flash(f"Delivery recorded, but order status could not be updated: {exc}", "error")
        return redirect(url_for("driver.dashboard"))

    try:
        order = Order.get_by_id(delivery.order_id)
        client_record = Client.load_by_client_id(order.client_id)
        _notify_owner_delivery(order.order_id, client_record.business_name)
        _notify_client_delivery(order.order_id, delivery.delivered_at, client_record.email)
    except Exception as exc:
        # delivery + order are already committed above -- a notification failure
        # must not undo or block the successful delivery (same partial-failure
        # philosophy as the Order.mark_delivered() sync above)
        flash(f"Delivery marked as complete, but notifications could not be sent: {exc}", "error")
        return redirect(url_for("driver.dashboard"))

    flash("Delivery marked as complete.", "success")
    return redirect(url_for("driver.dashboard"))


# extension + mimetype only -- no Pillow/python-magic, can't verify actual file content
def _validate_photo(photo):
    if photo is None or not photo.filename:
        return "Please attach a proof-of-delivery photo."

    extension = Path(secure_filename(photo.filename)).suffix.lower()
    if extension not in ALLOWED_PHOTO_EXTENSIONS or photo.mimetype not in ALLOWED_PHOTO_MIMETYPES:
        return "Proof-of-delivery photo must be a JPEG or PNG image."

    photo.stream.seek(0, os.SEEK_END)
    size = photo.stream.tell()
    photo.stream.seek(0)
    if size > MAX_PHOTO_BYTES:
        return "Proof-of-delivery photo must be 10MB or smaller."

    return None


# delivery_id + random suffix so a retried upload never collides with an earlier attempt
def _save_photo(delivery_id, photo):
    extension = Path(secure_filename(photo.filename)).suffix.lower()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{delivery_id}_{uuid4().hex}{extension}"
    photo.save(destination)
    return destination
