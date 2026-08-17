# app.py -- Flask entry point: registers blueprints, session config, role dashboards.

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from database.db import init_db
from email_utils import mail
from models.analytics import Analytics, fy_start_year, resolve_period_bounds
from models.client import Client
from models.order import Order
from routes.analytics import analytics_bp
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
app.register_blueprint(analytics_bp)

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


# Sidebar pending-orders badge (Module F) -- only computed for the owner portal,
# so client/driver pages don't pay for an extra query on every request.
@app.context_processor
def inject_owner_nav_data():
    if session.get("role") == "owner":
        return {"owner_pending_count": Order.count_pending()}
    return {}


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
# owner dashboard is real (Module F: FR-F3 reminder list); client's is still a
# stub -- Module 3 replaces it with the real client portal

@app.route("/owner/dashboard")
@login_required("owner")
def owner_dashboard():
    week_start, week_end = resolve_period_bounds("weekly", fy_start_year())
    return render_template(
        "owner_dashboard.html",
        overdue_clients=Client.get_overdue_clients(),
        pending_count=Order.count_pending(),
        approved_today_count=Order.count_approved_today(),
        deliveries_today_count=Order.count_deliveries_today(),
        week_revenue=Analytics.get_period_summary(week_start, week_end)["total_revenue"],
    )


@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    return render_template("dashboard_stub.html", portal_name="Client", extra_links=[
        (url_for("orders.client_order_form"), "Place an order"),
        (url_for("orders.client_order_history"), "Order history"),
        (url_for("invoices.client_invoices"), "View invoices"),
    ])


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
