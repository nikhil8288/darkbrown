"""MD Dashboard data endpoints.

One whitelisted method per dashboard tab. Every method re-checks the
Managing Director role server-side (never trust the page alone).

All endpoints currently return {"live": False} so the dashboard keeps
showing its built-in sample data. Wire each one to live DocTypes in
Phase 2, flip "live" to True, and the page JS can start consuming it.

Call from the browser as:
    /api/method/darkbrown.api.md_dashboard.get_overview
"""

import frappe


def _require_md():
    if frappe.session.user == "Guest":
        frappe.throw("Not permitted", frappe.PermissionError)
    if "Managing Director" not in frappe.get_roles(frappe.session.user):
        frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_overview(timeframe: str = "month"):
    """Health cards + alerts + income-vs-collected chart + per-building margin.

    Phase 2 sources:
    - Rental income / collected: Sales Invoice (grand_total, outstanding_amount)
      filtered by posting_date per timeframe, per Cost Center for buildings.
    - Head-lease cost: Purchase Invoice / Payment Entry against Supplier
      group "Landlord", or Landlord Contract schedule.
    - Occupancy / vacant: count of Unit by status.
    - Forward PDC cash: PDC Cheque (direction=incoming, status in
      Pending/Deposited, due date within 30/60/90d).
    - Expiring contracts: Landlord Contract + Tenant Rental Agreement
      with end_date <= 90 days out.
    """
    _require_md()
    return {"live": False, "timeframe": timeframe}


@frappe.whitelist()
def get_portfolio():
    """Buildings (income, head-lease, margin, occupancy, HL expiry) and
    the unit register (status, tenant, rent, days vacant)."""
    _require_md()
    return {"live": False}


@frappe.whitelist()
def get_tenants():
    """Tenant register with agreement status, arrears, bounce history,
    plus expiring agreements, grace/lapsed list, and churn (out + notice)."""
    _require_md()
    return {"live": False}


@frappe.whitelist()
def get_finance(timeframe: str = "month", view: str = "pnl"):
    """P&L (income - head-lease = margin), receivables ageing,
    PDC forward book + cheque lifecycle, landlord payables, liquidity."""
    _require_md()
    return {"live": False, "timeframe": timeframe, "view": view}


@frappe.whitelist()
def get_maintenance():
    """Open/overdue requests, avg resolution, preventive due, by building."""
    _require_md()
    return {"live": False}
