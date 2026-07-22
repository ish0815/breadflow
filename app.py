"""
app.py -- BreadFlow Flask application entry point.

Currently wires up Module 1 (Login) only: the login route, session
configuration FR-A1 depends on, and one stub landing route per role
(Modules 2/3/4 replace these stubs with the real Owner/Client/Driver
portals). Every route below is intentionally minimal -- this file's job
is to demonstrate FR-A1/FR-A3 end-to-end, not to anticipate later modules.
"""

import os
from datetime import timedelta
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

from database.db import init_db
from models.user import (
    AccountDeactivatedError,
    InvalidCredentialsError,
    User,
    ValidationError,
)

app = Flask(__name__)

# SECRET_KEY signs Flask's session cookie (itsdangerous) -- without one,
# anyone could forge a session cookie and set their own user_id/role.
# Read from the environment so a real key never lives in source control;
# the fallback only exists so `flask run` works out of the box locally.
app.config["SECRET_KEY"] = os.environ.get("BREADFLOW_SECRET_KEY", "dev-only-insecure-key")

# FR-A1 data dictionary: sessionToken "Expires after 8 hrs of inactivity".
# PERMANENT_SESSION_LIFETIME caps how long a permanent session cookie is
# valid; Flask's default SESSION_REFRESH_EACH_REQUEST=True re-issues the
# cookie with a fresh expiry on every request, which is what turns this
# into an *inactivity* timeout rather than a fixed 8-hour clock from login.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# Display order for the login form's role tabs, matching the mock-up
# (Owner / Client / Driver, left to right).
ROLE_TABS = ("owner", "client", "driver")
VALID_ROLES = set(ROLE_TABS)

# Where FR-A1's final redirect step sends each role. Keyed by the
# database's role value, never by user-submitted form data -- see login().
DASHBOARD_ENDPOINT = {
    "owner": "owner_dashboard",
    "client": "client_dashboard",
    "driver": "driver_dashboard",
}


@app.route("/")
def index():
    """No dashboard exists to land on anonymously, so root always
    forwards to the login page."""
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    FR-A1: role-based login.

    GET renders the form. POST validates the submission and delegates
    every existence/type/range/format/credential check to
    User.authenticate(), which already implements the full FR-A1
    pseudocode (empty-field, format, invalid-credential, and
    deactivated-account branches).

    The role tab is validated as a required field here (data dictionary:
    "Must be one of: owner | client | driver") so an impossible
    submission is rejected before touching the database -- but it is
    deliberately NOT used to choose the post-login redirect. That
    decision always comes from `account.role`, read back from the
    authenticated database row, matching the FR-A1 pseudocode's
    `session['role'] <- userRecord.role` exactly. Trusting the submitted
    tab instead would let a forged form field claim a role the account
    doesn't actually have.
    """
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for(DASHBOARD_ENDPOINT[session["role"]]))
        return render_template("login.html", roles=ROLE_TABS, active_tab="owner",
                                email="", error=None)

    submitted_tab = request.form.get("role", "")
    email = request.form.get("email", "")
    password = request.form.get("password", "")

    if submitted_tab not in VALID_ROLES:
        return render_template(
            "login.html", roles=ROLE_TABS, active_tab="owner", email=email,
            error="Please select a role.",
        ), 400

    try:
        account = User.authenticate(email, password)
    except (ValidationError, InvalidCredentialsError, AccountDeactivatedError) as exc:
        return render_template(
            "login.html", roles=ROLE_TABS, active_tab=submitted_tab, email=email,
            error=str(exc),
        ), 400

    # NF-06: clear any pre-existing session before writing the new one, so
    # a login can never inherit stale keys from a previous session
    # (session fixation), and so the signed cookie value itself changes on
    # every login -- "regenerated on each login".
    session.clear()
    session.update(account.get_session())
    session.permanent = True  # activates PERMANENT_SESSION_LIFETIME above

    return redirect(url_for(DASHBOARD_ENDPOINT[account.role]))


@app.route("/logout", methods=["POST"])
def logout():
    """Ends the current session immediately, regardless of the 8-hour expiry."""
    session.clear()
    return redirect(url_for("login"))


def login_required(role):
    """
    Decorator factory enforcing FR-A3 role-based access control on a route.

    Redirects to /login unless the session holds a user_id AND its role
    matches the route's required role -- e.g. a client session can never
    reach an @login_required("owner") route, even by guessing the URL.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if session.get("user_id") is None or session.get("role") != role:
                return redirect(url_for("login"))
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


# ---- role dashboards ---------------------------------------------------
# Stub landing pages only: Modules 2 (Owner Dashboard), 3 (Client Order
# Portal), and 4 (Driver docket) define the real content. These exist so
# FR-A1's redirect step has somewhere real to send each role for now.

@app.route("/owner/dashboard")
@login_required("owner")
def owner_dashboard():
    return render_template("dashboard_stub.html", portal_name="Owner")


@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    return render_template("dashboard_stub.html", portal_name="Client")


@app.route("/driver/dashboard")
@login_required("driver")
def driver_dashboard():
    return render_template("dashboard_stub.html", portal_name="Driver")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
