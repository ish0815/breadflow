# routes/driver.py -- Module 5: FR-E1/FR-E2 driver portal routes.

from flask import Blueprint, render_template

from routes.auth import login_required

driver_bp = Blueprint("driver", __name__)


# FR-E1: driver's daily docket. Shell only -- real query/docket logic is Commit 3.
@driver_bp.route("/driver/dashboard")
@login_required("driver")
def dashboard():
    return render_template("driver_dashboard.html")
