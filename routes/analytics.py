# routes/analytics.py -- Module F: sales reports/charts (FR-F1) + CSV export.

import csv
import io

from flask import Blueprint, Response, render_template, request

from models.analytics import Analytics, fy_label, resolve_period_bounds
from routes.auth import login_required

analytics_bp = Blueprint("analytics", __name__)

PERIODS = ("weekly", "monthly", "yearly")


# Shared period/fy query-param resolution for both routes below -- fy always falls
# back to the newest available FY if missing or not one the DB actually has data for.
def _resolve_query_params():
    period = request.args.get("period", "weekly")
    if period not in PERIODS:
        period = "weekly"

    available_fys = Analytics.get_available_fy_start_years()
    selected_fy = request.args.get("fy", type=int)
    if selected_fy not in available_fys:
        selected_fy = available_fys[0]

    return period, selected_fy, available_fys


@analytics_bp.route("/owner/analytics")
@login_required("owner")
def dashboard():
    period, selected_fy, available_fys = _resolve_query_params()
    start, end = resolve_period_bounds(period, selected_fy)

    summary = Analytics.get_period_summary(start, end)
    monthly = Analytics.get_monthly_revenue(selected_fy)
    top_clients = Analytics.get_top_clients(start, end)
    product_units = Analytics.get_product_units(start, end)
    yoy = Analytics.get_yoy_comparison(selected_fy)

    chart_payload = {
        "monthly_labels": monthly["labels"],
        "monthly_revenue": monthly["revenue"],
        "top_client_names": [row["business_name"] for row in top_clients],
        "top_client_revenue": [row["revenue"] for row in top_clients],
        "product_names": [row["product_name"] for row in product_units],
        "product_units": [row["units_sold"] for row in product_units],
    }

    return render_template(
        "analytics_dashboard.html",
        period=period, selected_fy=selected_fy, available_fys=available_fys, fy_label=fy_label,
        summary=summary, yoy=yoy, chart_payload=chart_payload,
    )


# Derived on-demand summary, not a stored business record like invoices -- built
# entirely in memory, no disk write, nothing to re-fetch later.
@analytics_bp.route("/owner/analytics/export")
@login_required("owner")
def export_csv():
    period, selected_fy, available_fys = _resolve_query_params()
    start, end = resolve_period_bounds(period, selected_fy)

    yoy = Analytics.get_yoy_comparison(selected_fy)
    top_clients = Analytics.get_top_clients(start, end)
    product_units = Analytics.get_product_units(start, end)

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["Year-on-Year", fy_label(selected_fy), fy_label(selected_fy - 1), "% Change"])
    for row in yoy:
        current = f"{row['current']:.2f}" if row["is_currency"] else row["current"]
        previous = f"{row['previous']:.2f}" if row["is_currency"] else row["previous"]
        pct = "N/A" if row["pct_change"] is None else f"{row['pct_change']:.1f}%"
        writer.writerow([row["label"], current, previous, pct])
    writer.writerow([])

    writer.writerow(["Top Clients", "Revenue"])
    for row in top_clients:
        writer.writerow([row["business_name"], f"{row['revenue']:.2f}"])
    writer.writerow([])

    writer.writerow(["Sales by Product", "Units Sold"])
    for row in product_units:
        writer.writerow([row["product_name"], row["units_sold"]])

    filename = f"analytics_{fy_label(selected_fy).replace(' ', '_')}.csv"
    return Response(
        buffer.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
