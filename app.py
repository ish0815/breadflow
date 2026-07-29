"""
app.py -- BreadFlow Flask application entry point.

Currently wires up Module 1 (Login) only: registers the auth Blueprint
(routes/auth.py), the session configuration FR-A1 depends on, and one
stub landing route per role (Modules 2/3/4 replace these stubs with the
real Owner/Client/Driver portals).
"""

import os
from datetime import timedelta

from flask import Flask, redirect, render_template, url_for

from database.db import init_db
from routes.auth import auth_bp, login_required
from routes.orders import orders_bp
from routes.production import production_bp

app = Flask(__name__)
app.register_blueprint(auth_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(production_bp)

# signs the session cookie so it can't be forged; env var in prod, dev fallback locally
app.config["SECRET_KEY"] = os.environ.get("BREADFLOW_SECRET_KEY", "dev-only-insecure-key")

# FR-A1: 8hr inactivity timeout (Flask refreshes expiry each request)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)


@app.route("/")
def index():
    """No dashboard exists to land on anonymously, so root always
    forwards to the login page."""
    return redirect(url_for("auth.login"))


@app.errorhandler(403)
def forbidden(_exc):
    """FR-A3: an authenticated session with the wrong role for this route
    (routes/auth.py's login_required) lands here instead of being bounced
    back to a login form it's already signed into."""
    return render_template("403.html"), 403


# ---- role dashboards ---------------------------------------------------
# stubs only -- Modules 2/3/4 replace these with the real portals

@app.route("/owner/dashboard")
@login_required("owner")
def owner_dashboard():
    return render_template("dashboard_stub.html", portal_name="Owner", extra_links=[
        (url_for("orders.owner_pending_orders"), "View pending orders"),
        (url_for("production.production_list_view"), "View production list"),
    ])


@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    return render_template("dashboard_stub.html", portal_name="Client", extra_links=[
        (url_for("orders.client_order_form"), "Place an order"),
    ])


@app.route("/driver/dashboard")
@login_required("driver")
def driver_dashboard():
    return render_template("dashboard_stub.html", portal_name="Driver")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
