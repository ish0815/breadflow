# routes/owner.py -- Module A: owner client management (FR-A2, FR-B2).

from flask import Blueprint, flash, redirect, render_template, request, url_for

from database.db import get_db_connection
from models.client import Client, ClientValidationError, ZONES
from models.order import WEEKDAYS
from routes.auth import login_required

owner_bp = Blueprint("owner", __name__)


# Plain inline query, same convention as Client.get_approved_products() and the
# order routes -- there's no Product model class, products is always read directly.
def _all_products():
    connection = get_db_connection()
    try:
        return connection.execute(
            "SELECT product_id, product_name, category, base_price, pack_size "
            "FROM products ORDER BY category, product_name"
        ).fetchall()
    finally:
        connection.close()


# Reads the checked product_<id> checkboxes plus their paired price_<id>/pack_<id>
# inputs into the list of dicts Client.create() expects. Unchecked rows are skipped.
def _parse_product_selections(form, products):
    selections = []
    for product in products:
        product_id = product["product_id"]
        if not form.get(f"product_{product_id}"):
            continue
        try:
            agreed_price = float(form.get(f"price_{product_id}", ""))
            pack_size = int(form.get(f"pack_{product_id}", ""))
        except ValueError:
            raise ClientValidationError("Enter a valid price and pack size for every selected product")
        selections.append({"product_id": product_id, "agreed_price": agreed_price, "pack_size": pack_size})
    return selections


# Module A: owner sees every client, business name / zone / active status.
@owner_bp.route("/owner/clients")
@login_required("owner")
def client_list():
    return render_template("owner_clients.html", clients=Client.list_all())


# Module A: add a new client + their initial product catalogue in one step.
@owner_bp.route("/owner/clients/new", methods=["GET", "POST"])
@login_required("owner")
def add_client():
    products = _all_products()

    if request.method == "GET":
        return render_template(
            "owner_client_form.html", zones=ZONES, weekdays=WEEKDAYS,
            products=products, form_data={}, error=None,
        )

    try:
        product_selections = _parse_product_selections(request.form, products)
        client = Client.create(
            business_name=request.form.get("business_name", ""),
            abn=request.form.get("abn", ""),
            email=request.form.get("email", ""),
            temp_password=request.form.get("temp_password", ""),
            delivery_zone=request.form.get("delivery_zone", ""),
            delivery_day1=request.form.get("delivery_day1", ""),
            delivery_day2=request.form.get("delivery_day2", ""),
            delivery_charge=request.form.get("delivery_charge", ""),
            internal_notes=request.form.get("internal_notes", ""),
            product_selections=product_selections,
        )
    except ClientValidationError as exc:
        return render_template(
            "owner_client_form.html", zones=ZONES, weekdays=WEEKDAYS,
            products=products, form_data=request.form, error=str(exc),
        ), 400

    flash(f"{client.business_name} added.", "success")
    return redirect(url_for("owner.client_list"))


# Module A: blocks login without deleting the account (User.authenticate() already
# checks is_active -- this just flips it).
@owner_bp.route("/owner/clients/<int:client_id>/deactivate", methods=["POST"])
@login_required("owner")
def deactivate_client(client_id):
    client = Client.load_by_client_id(client_id)
    client.deactivate()
    flash(f"{client.business_name} deactivated.", "success")
    return redirect(url_for("owner.client_list"))


@owner_bp.route("/owner/clients/<int:client_id>/reactivate", methods=["POST"])
@login_required("owner")
def reactivate_client(client_id):
    client = Client.load_by_client_id(client_id)
    client.reactivate()
    flash(f"{client.business_name} reactivated.", "success")
    return redirect(url_for("owner.client_list"))
