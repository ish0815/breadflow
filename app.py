# app.py -- Flask entry point: registers blueprints, session config, dashboard stubs.

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from database.db import init_db
from email_utils import mail
from routes.auth import auth_bp, login_required
from routes.driver import driver_bp
from routes.invoices import invoices_bp
from routes.orders import orders_bp
from routes.owner import owner_bp
from routes.production import production_bp

# loads .env (gitignored) so MAIL_USERNAME/PASSWORD/DEFAULT_SENDER below are set locally
load_dotenv()

app = Flask(__name__)
app.register_blueprint(auth_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(owner_bp)
app.register_blueprint(production_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(driver_bp)

# signs the session cookie so it can't be forged; env var in prod, dev fallback locally
app.config["SECRET_KEY"] = os.environ.get("BREADFLOW_SECRET_KEY", "dev-only-insecure-key")

# FR-A1: 8hr inactivity timeout (Flask refreshes expiry each request)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# FR-E2 safety net: coarse cap above the 10MB photo rule the route enforces
# itself -- stops an oversized request body being buffered into memory at all.
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

# FR-B1/FR-B4/FR-E2: Gmail SMTP for order/delivery notifications
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")
mail.init_app(app)


# No anonymous dashboard -- always redirect to login.
@app.route("/")
def index():
    return redirect(url_for("auth.login"))


# FR-A3: wrong-role access lands here, not back at login.
@app.errorhandler(403)
def forbidden(_exc):
    return render_template("403.html"), 403


# FR-E2: request body over MAX_CONTENT_LENGTH -- clean flash instead of a raw 413 page.
@app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(_exc):
    flash("Upload was too large.", "error")
    return redirect(url_for("driver.dashboard"))


# ---- role dashboards ---------------------------------------------------
# stubs only -- Modules 2/3/4 replace these with the real portals

@app.route("/owner/dashboard")
@login_required("owner")
def owner_dashboard():
    return render_template("dashboard_stub.html", portal_name="Owner", extra_links=[
        (url_for("orders.owner_pending_orders"), "View pending orders"),
        (url_for("production.production_list_view"), "View production list"),
        (url_for("owner.client_list"), "Manage clients"),
        (url_for("invoices.owner_invoices"), "Manage invoices"),
    ])


@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    return render_template("dashboard_stub.html", portal_name="Client", extra_links=[
        (url_for("orders.client_order_form"), "Place an order"),
        (url_for("invoices.client_invoices"), "View invoices"),
    ])


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
