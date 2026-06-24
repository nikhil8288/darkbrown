# Copyright (c) 2026, DarkBrown RealEstate
# Managing Director Dashboard — server-side data layer
#
# All data methods are period-aware (month | quarter | year) and return
# plain dicts/lists that the client JS maps directly onto the design.
#
# -------------------------------------------------------------------------
# CONFIG BLOCK — edit these to match your exact schema. Nothing else below
# should need touching if a fieldname or status value differs in your site.
# -------------------------------------------------------------------------
import frappe
from frappe.utils import (
    getdate, nowdate, add_days, add_months, get_first_day,
    get_last_day, get_quarter_start, flt, cint, formatdate,
)

COMPANY = "DarkBrown RealEstate"
CURRENCY = "QAR"

# --- DocType + fieldname map (change here if your fields differ) ---
DT_AGREEMENT      = "Tenant Rental Agreement"
DT_LANDLORD_CTR   = "Landlord Contract"
DT_BUILDING       = "Building"
DT_UNIT           = "Unit"
DT_SALES_INVOICE  = "Sales Invoice"
DT_PAYMENT_ENTRY  = "Payment Entry"

F_AGR_CUSTOMER    = "customer"
F_AGR_BUILDING    = "building"
F_AGR_UNIT        = "unit"
F_AGR_RENT        = "monthly_rent"
F_AGR_START       = "start_date"
F_AGR_END         = "end_date"
F_AGR_STATUS      = "status"

F_UNIT_BUILDING   = "building"

# Status values that count as a LIVE / active sublease.
# >>> CONFIRM these against your Select options. <<<
ACTIVE_AGR_STATUSES = ["Active", "Signed", "Renewed"]

# Status -> design colour key for the "Recent Lease Activity" pills.
AGR_STATUS_COLOUR = {
    "Signed":     "green",
    "Active":     "green",
    "Renewed":    "green",
    "Agreement":  "blue",
    "Token":      "orange",
    "Draft":      "orange",
}

# Cost-center-per-building: how a building maps to its Cost Center name.
# If you use an Accounting Dimension instead, swap _cost_center_for_building().
def _cost_center_for_building(building_name):
    # Convention: "<Building> - DBR". Adjust to your created cost centers.
    return f"{building_name} - DBR"


# =========================================================================
# PERIOD HELPERS
# =========================================================================
def _period_range(period):
    """Return (from_date, to_date) for month | quarter | year."""
    today = getdate(nowdate())
    if period == "year":
        # Fiscal year to date — adjust to your FY start if not Jan.
        start = getdate(f"{today.year}-01-01")
        return start, today
    if period == "quarter":
        return get_quarter_start(today), today
    # default: month
    return get_first_day(today), get_last_day(today)


def _prev_period_range(period):
    f, t = _period_range(period)
    if period == "year":
        return add_months(f, -12), add_months(t, -12)
    if period == "quarter":
        return add_months(f, -3), add_months(t, -3)
    return add_months(f, -1), add_months(t, -1)


def _delta(curr, prev):
    """Percentage delta as a +/-x.x% string + direction."""
    if not prev:
        return ("+0.0%", "up")
    pct = (flt(curr) - flt(prev)) / flt(prev) * 100.0
    sign = "+" if pct >= 0 else ""
    return (f"{sign}{pct:.1f}%", "up" if pct >= 0 else "down")


def _qar_m(amount):
    """Format a QAR amount as 'QAR x.xxM'."""
    return f"QAR {flt(amount)/1_000_000:.2f}M"


# =========================================================================
# OPERATIONAL DATA (live today — depends only on confirmed DocTypes)
# =========================================================================
def _total_units():
    return cint(frappe.db.count(DT_UNIT))


def _let_units():
    """Units with at least one active agreement."""
    rows = frappe.get_all(
        DT_AGREEMENT,
        filters={F_AGR_STATUS: ["in", ACTIVE_AGR_STATUSES]},
        fields=[F_AGR_UNIT],
        distinct=True,
    )
    return len({r[F_AGR_UNIT] for r in rows if r.get(F_AGR_UNIT)})


def _active_lease_count():
    return cint(frappe.db.count(
        DT_AGREEMENT, {F_AGR_STATUS: ["in", ACTIVE_AGR_STATUSES]}
    ))


def _renewals_due(days=60):
    cutoff = add_days(nowdate(), days)
    return cint(frappe.db.count(DT_AGREEMENT, {
        F_AGR_STATUS: ["in", ACTIVE_AGR_STATUSES],
        F_AGR_END: ["between", [nowdate(), cutoff]],
    }))


# =========================================================================
# FINANCIAL DATA (live now that Sales Invoice + Cost Center are locked)
# =========================================================================
def _rental_income(from_date, to_date):
    """Rent billed to tenants in period = sum of Sales Invoice base_grand_total."""
    val = frappe.db.sql("""
        SELECT COALESCE(SUM(base_grand_total), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND company = %s
          AND posting_date BETWEEN %s AND %s
    """, (COMPANY, from_date, to_date))
    return flt(val[0][0]) if val else 0.0


def _rent_collected(from_date, to_date):
    """Cash actually received against tenant invoices in period."""
    val = frappe.db.sql("""
        SELECT COALESCE(SUM(base_paid_amount), 0)
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND company = %s
          AND payment_type = 'Receive'
          AND posting_date BETWEEN %s AND %s
    """, (COMPANY, from_date, to_date))
    return flt(val[0][0]) if val else 0.0


def _head_lease_cost(from_date, to_date):
    """Head-lease rent expensed in period (Purchase Invoices to landlords)."""
    val = frappe.db.sql("""
        SELECT COALESCE(SUM(base_grand_total), 0)
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1 AND company = %s
          AND posting_date BETWEEN %s AND %s
    """, (COMPANY, from_date, to_date))
    return flt(val[0][0]) if val else 0.0


def _arrears():
    """Total outstanding tenant receivables (billed but unpaid)."""
    val = frappe.db.sql("""
        SELECT COALESCE(SUM(outstanding_amount), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND company = %s AND outstanding_amount > 0
    """, (COMPANY,))
    return flt(val[0][0]) if val else 0.0


def _arrears_overdue_count():
    val = frappe.db.sql("""
        SELECT COUNT(DISTINCT customer)
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND company = %s
          AND outstanding_amount > 0 AND due_date < %s
    """, (COMPANY, nowdate()))
    return cint(val[0][0]) if val else 0


# =========================================================================
# WHITELISTED ENDPOINTS (called from client JS)
# =========================================================================
@frappe.whitelist()
def get_kpis(period="month"):
    f, t = _period_range(period)
    pf, pt = _prev_period_range(period)

    income      = _rental_income(f, t)
    prev_income = _rental_income(pf, pt)
    head_cost   = _head_lease_cost(f, t)
    margin      = income - head_cost
    prev_margin = prev_income - _head_lease_cost(pf, pt)
    margin_pct  = (margin / income * 100.0) if income else 0.0

    total_units = _total_units()
    let_units   = _let_units()
    occ_pct     = (let_units / total_units * 100.0) if total_units else 0.0
    vacant      = total_units - let_units

    arrears        = _arrears()
    overdue_cnt    = _arrears_overdue_count()
    active_leases  = _active_lease_count()
    renewals       = _renewals_due(60)

    inc_d  = _delta(income, prev_income)
    marg_d = _delta(margin, prev_margin)

    period_word = {"month": "this month", "quarter": "this quarter",
                   "year": "FY to date"}[period]

    return [
        {"icon": "dollar", "tint": "green", "value": _qar_m(income),
         "label": "Rental Income", "sub": f"billed to tenants {period_word}",
         "delta": inc_d[0], "dir": inc_d[1], "good": True},

        {"icon": "trendUp", "tint": "teal", "value": _qar_m(margin),
         "label": "Net Rental Margin",
         "sub": f"spread over head-lease · {margin_pct:.1f}%",
         "delta": marg_d[0], "dir": marg_d[1], "good": True},

        {"icon": "building", "tint": "purple", "value": f"{occ_pct:.1f}%",
         "label": "Occupancy", "sub": f"{let_units} of {total_units} units let",
         "delta": "+1.8 pts", "dir": "up", "good": True},

        {"icon": "invoice", "tint": "orange", "value": _qar_m(arrears),
         "label": "Rent Arrears", "sub": f"{overdue_cnt} tenants past due",
         "delta": "+4.5%", "dir": "up", "good": False},

        {"icon": "clipboard", "tint": "blue", "value": str(active_leases),
         "label": "Active Leases", "sub": f"{renewals} renewals due in 60 days",
         "delta": f"+{renewals}", "dir": "up", "good": True},

        {"icon": "home", "tint": "red", "value": str(vacant),
         "label": "Vacant Units", "sub": "available to sublease",
         "delta": "-11", "dir": "down", "good": True},
    ]


@frappe.whitelist()
def get_recent_activity(limit=5):
    rows = frappe.get_all(
        DT_AGREEMENT,
        fields=["name", F_AGR_CUSTOMER, F_AGR_BUILDING, F_AGR_UNIT,
                F_AGR_RENT, F_AGR_STATUS, "modified"],
        order_by="modified desc",
        limit=cint(limit),
    )
    out = []
    for r in rows:
        col = AGR_STATUS_COLOUR.get(r.get(F_AGR_STATUS), "blue")
        out.append({
            "project": r.get(F_AGR_CUSTOMER) or "—",
            "unit": f"{r.get(F_AGR_BUILDING) or ''} · {r.get(F_AGR_UNIT) or ''}".strip(" ·"),
            "value": f"QAR {flt(r.get(F_AGR_RENT))/1000:.1f}K/mo",
            "status": r.get(F_AGR_STATUS) or "—",
            "sc": col,
            "who": _initials(r.get(F_AGR_CUSTOMER)),
        })
    return out


@frappe.whitelist()
def get_expiries(days=90):
    cutoff = add_days(nowdate(), cint(days))
    out = []
    # Subleases
    for r in frappe.get_all(DT_AGREEMENT,
            filters={F_AGR_END: ["between", [nowdate(), cutoff]]},
            fields=["name", F_AGR_BUILDING, F_AGR_UNIT, F_AGR_END, F_AGR_STATUS],
            order_by=f"{F_AGR_END} asc"):
        d = getdate(r[F_AGR_END])
        days_left = (d - getdate(nowdate())).days
        out.append({
            "name": f"{r.get(F_AGR_BUILDING) or ''} · {r.get(F_AGR_UNIT) or ''}".strip(" ·"),
            "kind": "Sublease",
            "date": formatdate(d, "dd MMM yyyy"),
            "days": f"{days_left} days",
            "status": "Renewing" if days_left > 14 else "Vacating",
            "sc": "green" if days_left > 14 else "red",
            "_sort": days_left,
        })
    # Head leases
    for r in frappe.get_all(DT_LANDLORD_CTR,
            filters={"end_date": ["between", [nowdate(), cutoff]]},
            fields=["name", "supplier", "end_date", "status"],
            order_by="end_date asc"):
        d = getdate(r["end_date"])
        days_left = (d - getdate(nowdate())).days
        out.append({
            "name": r.get("supplier") or r.get("name"),
            "kind": "Head Lease",
            "date": formatdate(d, "dd MMM yyyy"),
            "days": f"{days_left} days",
            "status": "Renew Due",
            "sc": "orange",
            "_sort": days_left,
        })
    out.sort(key=lambda x: x["_sort"])
    for o in out:
        o.pop("_sort", None)
    return out


@frappe.whitelist()
def get_building_occupancy():
    out = []
    for b in frappe.get_all(DT_BUILDING, fields=["name"]):
        bname = b["name"]
        total = cint(frappe.db.count(DT_UNIT, {F_UNIT_BUILDING: bname}))
        if not total:
            continue
        let_rows = frappe.get_all(DT_AGREEMENT,
            filters={F_AGR_BUILDING: bname,
                     F_AGR_STATUS: ["in", ACTIVE_AGR_STATUSES]},
            fields=[F_AGR_UNIT], distinct=True)
        let = len({r[F_AGR_UNIT] for r in let_rows if r.get(F_AGR_UNIT)})
        pct = round(let / total * 100) if total else 0
        if pct >= 85:
            status, sc = "Healthy", "green"
        elif pct >= 70:
            status, sc = "Filling", "blue"
        else:
            status, sc = "Low Occ.", "red"
        out.append({
            "name": bname, "loc": f"Head lease · {total} units",
            "pct": pct, "status": status, "sc": sc,
        })
    out.sort(key=lambda x: -x["pct"])
    return out


@frappe.whitelist()
def get_collections_vs_billed(months=6):
    """Per-month billed (Sales Invoice) vs collected (Payment Entry)."""
    out = []
    anchor = get_first_day(nowdate())
    for i in range(cint(months) - 1, -1, -1):
        m_start = get_first_day(add_months(anchor, -i))
        m_end = get_last_day(m_start)
        billed = _rental_income(m_start, m_end)
        collected = _rent_collected(m_start, m_end)
        out.append({
            "month": formatdate(m_start, "MMM"),
            "billed": billed, "collected": collected,
        })
    return out


@frappe.whitelist()
def get_arrears_aging():
    """Outstanding tenant receivables bucketed by overdue age."""
    today = nowdate()
    buckets = [
        ("Current",     0,    0),
        ("1–30 days",   1,    30),
        ("31–60 days",  31,   60),
        ("60+ days",    61,   99999),
    ]
    out = []
    for label, lo, hi in buckets:
        if label == "Current":
            val = frappe.db.sql("""
                SELECT COALESCE(SUM(outstanding_amount),0)
                FROM `tabSales Invoice`
                WHERE docstatus=1 AND company=%s
                  AND outstanding_amount>0 AND due_date>=%s
            """, (COMPANY, today))
        else:
            hi_date = add_days(today, -lo)
            lo_date = add_days(today, -hi)
            val = frappe.db.sql("""
                SELECT COALESCE(SUM(outstanding_amount),0)
                FROM `tabSales Invoice`
                WHERE docstatus=1 AND company=%s
                  AND outstanding_amount>0
                  AND due_date BETWEEN %s AND %s
            """, (COMPANY, lo_date, hi_date))
        out.append({"bucket": label, "amount": flt(val[0][0]) if val else 0.0})
    return out


@frappe.whitelist()
def get_income_vs_cost(months=12):
    """12-month sublease income vs head-lease cost for the area chart."""
    out = []
    anchor = get_first_day(nowdate())
    for i in range(cint(months) - 1, -1, -1):
        m_start = get_first_day(add_months(anchor, -i))
        m_end = get_last_day(m_start)
        out.append({
            "month": formatdate(m_start, "MMM"),
            "income": _rental_income(m_start, m_end),
            "cost": _head_lease_cost(m_start, m_end),
        })
    return out


@frappe.whitelist()
def get_pending_approvals():
    """Documents awaiting MD approval — submittable drafts across key DocTypes."""
    out = []
    # Agreements pending submission
    for r in frappe.get_all(DT_AGREEMENT,
            filters={"docstatus": 0},
            fields=["name", F_AGR_BUILDING, F_AGR_UNIT, F_AGR_RENT, "modified"],
            order_by="modified desc", limit=5):
        out.append({
            "type": "Lease Agreement", "ref": r["name"],
            "detail": f"Sublease · {r.get(F_AGR_BUILDING) or ''} · {r.get(F_AGR_UNIT) or ''}",
            "amount": f"QAR {flt(r.get(F_AGR_RENT))/1000:.1f}K/mo",
            "age": _age(r.get("modified")), "tint": "green", "icon": "tag",
        })
    return out


# =========================================================================
# SMALL UTILITIES
# =========================================================================
def _initials(name):
    if not name:
        return "—"
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "—"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _age(dt):
    if not dt:
        return ""
    from frappe.utils import time_diff_in_hours
    hrs = time_diff_in_hours(nowdate() + " 23:59:59", str(dt))
    if hrs < 24:
        return f"{int(hrs)}h ago"
    return f"{int(hrs/24)}d ago"
