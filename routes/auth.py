"""
routes/auth.py -- Module 1: login, logout, and the FR-A3 RBAC decorator.

Its own Blueprint rather than routes living directly in app.py, so each
later module (Owner/Client/Driver portals) can add its own routes/<module>.py
registered the same way, instead of app.py growing indefinitely.
"""

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


@auth_bp.route("/login", methods=["GET", "POST"])
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

    # NF-06: fresh session every login, no fixation
    session.clear()
    session.update(account.get_session())
    session.permanent = True  # activates PERMANENT_SESSION_LIFETIME (app.py)

    return redirect(url_for(DASHBOARD_ENDPOINT[account.role]))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Ends the current session immediately, regardless of the 8-hour expiry."""
    session.clear()
    return redirect(url_for("auth.login"))


def login_required(role):
    """
    Decorator factory enforcing FR-A3 role-based access control on a route.

    Two distinct failure cases, so the message actually matches what
    happened: no session at all sends the visitor to /login (they just
    need to sign in), but a session that IS authenticated for a
    *different* role -- e.g. a client session hitting an owner-only
    route by guessing the URL -- aborts with 403 instead, since sending
    them back to a login form they're already logged into would be
    misleading.
    """
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
