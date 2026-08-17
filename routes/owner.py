# routes/owner.py -- Module A: owner client management (FR-A2, FR-B2).

from flask import Blueprint, flash, redirect, render_template, request, url_for

from database.db import get_db_connection
from email_utils import send_email
from models.client import Client, ClientValidationError, ZONES
from models.order import WEEKDAYS
from routes.auth import login_required

owner_bp = Blueprint("owner", __name__)


# FR-A2: emails a newly created client their login credentials.
def _notify_client_welcome(client, temp_password):
    send_email(
        subject="Welcome to BreadFlow",
        recipients=[client.email],
        body=f"Hi {client.business_name}, your BreadFlow account has been created.\n\n"
             f"Login email: {client.email}\nTemporary password: {temp_password}\n\n"
             f"Please log in and keep these details safe.",
    )


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


# Module 12: edit form only exposes Agreed Price per row (not pack size) -- pack_size
# carries over from the client's current catalogue entry, or the product's base pack size.
def _parse_catalogue_edit(form, products, current_pack_sizes):
    selections = []
    for product in products:
        product_id = product["product_id"]
        if not form.get(f"product_{product_id}"):
            continue
        try:
            agreed_price = float(form.get(f"price_{product_id}", ""))
        except ValueError:
            raise ClientValidationError(f"{product['product_name']}: agreed price required")
        if agreed_price <= 0:
            raise ClientValidationError(f"{product['product_name']}: agreed price required")
        pack_size = current_pack_sizes.get(product_id, product["pack_size"])
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

    temp_password = request.form.get("temp_password", "")
    try:
        product_selections = _parse_product_selections(request.form, products)
        client = Client.create(
            business_name=request.form.get("business_name", ""),
            abn=request.form.get("abn", ""),
            email=request.form.get("email", ""),
            temp_password=temp_password,
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

    try:
        _notify_client_welcome(client, temp_password)
    except Exception as exc:
        flash(f"{client.business_name} added, but the welcome email could not be sent -- "
              f"share the login details with them manually: {exc}", "error")
        return redirect(url_for("owner.client_list"))

    flash(f"{client.business_name} added.", "success")
    return redirect(url_for("owner.client_list"))


# Module 12: revisit an existing client's product catalogue -- toggle products on/off
# and edit their agreed price. Per-client only; never touches products.base_price.
@owner_bp.route("/owner/clients/<int:client_id>/products", methods=["GET", "POST"])
@login_required("owner")
def edit_client_products(client_id):
    client = Client.load_by_client_id(client_id)
    products = _all_products()

    if request.method == "GET":
        # same form_data shape owner_client_form.html expects, built from this client's
        # current catalogue instead of a resubmitted form
        current_prices = {row["product_id"]: row["agreed_price"] for row in client.get_approved_products()}
        form_data = {}
        for product in products:
            if product["product_id"] in current_prices:
                form_data[f"product_{product['product_id']}"] = "on"
                form_data[f"price_{product['product_id']}"] = current_prices[product["product_id"]]
        return render_template(
            "owner_client_products.html", client=client, products=products,
            form_data=form_data, error=None,
        )

    current_pack_sizes = {row["product_id"]: row["pack_size"] for row in client.get_approved_products()}
    try:
        selections = _parse_catalogue_edit(request.form, products, current_pack_sizes)
        client.update_product_catalogue(selections)
    except ClientValidationError as exc:
        return render_template(
            "owner_client_products.html", client=client, products=products,
            form_data=request.form, error=str(exc),
        ), 400

    flash("Catalogue updated successfully.", "success")
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
