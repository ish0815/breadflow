# app.py -- Flask entry point: registers blueprints, session config, dashboard stubs.

import os
from datetime import timedelta

from flask import Flask, redirect, render_template, url_for

from database.db import init_db
from routes.auth import auth_bp, login_required
from routes.orders import orders_bp
from routes.owner import owner_bp
from routes.production import production_bp

app = Flask(__name__)
app.register_blueprint(auth_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(owner_bp)
app.register_blueprint(production_bp)

# signs the session cookie so it can't be forged; env var in prod, dev fallback locally
app.config["SECRET_KEY"] = os.environ.get("BREADFLOW_SECRET_KEY", "dev-only-insecure-key")

# FR-A1: 8hr inactivity timeout (Flask refreshes expiry each request)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)


# No anonymous dashboard -- always redirect to login.
@app.route("/")
def index():
    return redirect(url_for("auth.login"))


# FR-A3: wrong-role access lands here, not back at login.
@app.errorhandler(403)
def forbidden(_exc):
    return render_template("403.html"), 403


# ---- role dashboards ---------------------------------------------------
# stubs only -- Modules 2/3/4 replace these with the real portals

@app.route("/owner/dashboard")
@login_required("owner")
def owner_dashboard():
    return render_template("dashboard_stub.html", portal_name="Owner", extra_links=[
        (url_for("orders.owner_pending_orders"), "View pending orders"),
        (url_for("production.production_list_view"), "View production list"),
        (url_for("owner.client_list"), "Manage clients"),
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
