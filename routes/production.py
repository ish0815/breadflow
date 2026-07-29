"""
routes/production.py -- Module C: daily production list generation and
display (FR-C1, FR-C2). On-screen only for now -- PDF export via
ReportLab is a follow-up once this aggregation is verified correct.
"""

import datetime

from flask import Blueprint, render_template, request, session

from models.production import ProductionList
from routes.auth import login_required

production_bp = Blueprint("production", __name__)


@production_bp.route("/owner/production")
@login_required("owner")
def production_list_view():
    """FR-C1: defaults to today; the date dropdown is restricted to dates
    that actually have orders (plus today itself), not a free calendar --
    any other date is guaranteed to show nothing."""
    requested_date = request.args.get("date", "")
    try:
        production_date = datetime.date.fromisoformat(requested_date).isoformat()
    except ValueError:
        production_date = datetime.date.today().isoformat()

    available_dates = ProductionList.get_dates_with_orders()
    if production_date not in available_dates:
        available_dates = sorted(available_dates + [production_date])

    return render_template(
        "production_list.html",
        production_date=production_date,
        available_dates=available_dates,
        production_list=ProductionList.generate(production_date, session["user_id"]),
    )
