# routes/auth.py -- Module 1: login, logout, and the FR-A3 RBAC decorator.

from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from models.user import (
    AccountDeactivatedError,
    InvalidCredentialsError,
    User,
    ValidationError,
)

auth_bp = Blueprint("auth", __name__)

# role tab display order, matches the mock-up
ROLE_TABS = ("owner", "client", "driver")
VALID_ROLES = set(ROLE_TABS)

# redirect target per role -- keyed off the DB's role, never submitted form data
DASHBOARD_ENDPOINT = {
    "owner": "owner_dashboard",
    "client": "client_dashboard",
    "driver": "driver_dashboard",
}


# FR-A1: GET renders the form, POST validates via User.authenticate().
# Redirect uses account.role from the DB, never the submitted tab.
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
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

    # NF-06: fresh session every login, no fixation
    session.clear()
    session.update(account.get_session())
    session.permanent = True  # activates PERMANENT_SESSION_LIFETIME (app.py)

    return redirect(url_for(DASHBOARD_ENDPOINT[account.role]))


# Ends the session immediately, regardless of the 8-hour expiry.
@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# FR-A3: no session -> redirect to login; wrong role -> 403.
def login_required(role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if session.get("user_id") is None:
                return redirect(url_for("auth.login"))
            if session.get("role") != role:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
