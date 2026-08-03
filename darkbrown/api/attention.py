"""The attention feed behind My Work's flagged panel and the MD alert strip.

Six rules, spec numbering preserved:

    1   Arrears past the grace period      get_arrears()
    2   Landlord cheque maturing <= 15d    get_landlord_pdc()
    6   Vacant units and what they bleed   get_vacant()
    9   Head-lease expiring within 90d     get_headlease_expiring()
    10  Tenancy expiring within 30d        get_tenant_expiring()
    13  Maintenance open past 48h          get_maintenance_aging()

These rules were written against V1 and were never called. When they were
finally wired into the boot payload they could not run: every one of them
queried `Tenant Rental Agreement`, `Landlord Contract` or `PDC Cheque`, none
of which exist in V2, and get_vacant() filtered `Unit.occupancy_status`
against a doctype whose field is `status`. seed() caught the exception and
carried on, so the panel read as "nothing is flagged" on a portfolio that had
plenty flagged — the worst of the three possible outcomes. They are rewritten
here against the V2 schema: Tenancy Agreement, Head Lease, Cheque, Unit.

Read-only by design. Every function returns a stable shape when there is
nothing to report, so an empty portfolio and a broken query never look alike.
Role is re-checked on the server on every call.
"""

import frappe
from frappe.utils import getdate, nowdate, now_datetime, flt, cint

_ALLOWED = {"Managing Director", "General Manager", "System Manager",
            "Administrator"}

MAINT_AGE_HOURS = 48
HEADLEASE_WINDOW = 90
TENANT_WINDOW = 30
PDC_WINDOW_DAYS = 15

_OPEN_MAINT = ["Open", "Assigned", "Scheduled", "In Progress"]
_LIVE_LEASE = ["Active", "Expiring"]

_BUCKETS = [(30, "0-30", "amber"), (60, "31-60", "orange"),
            (90, "61-90", "red"), (10 ** 6, "90+", "dark")]


# ------------------------------------------------------------- helpers

def _guard():
    if not (set(frappe.get_roles(frappe.session.user)) & _ALLOWED):
        frappe.throw("Not permitted", frappe.PermissionError)


def _has(doctype):
    return bool(frappe.db.exists("DocType", doctype))


def _days_until(d):
    return None if not d else (getdate(d) - getdate(nowdate())).days


def _fmt(d):
    return frappe.utils.formatdate(d, "d MMM yy") if d else "—"


def _bucket(days):
    for limit, label, band in _BUCKETS:
        if days <= limit:
            return label, band
    return "90+", "dark"


def _grace_days():
    """One portfolio-wide grace period, held on DBR Settings. V1 carried it
    per landlord contract; V2 does not, and inventing a per-building number
    here would put a figure on screen that no record supports."""
    try:
        return cint(frappe.db.get_single_value("DBR Settings", "grace_days"))
    except Exception:
        return 0


def _customer_names(names=None):
    f = {"name": ["in", list(names)]} if names else {}
    return {c.name: (c.customer_name or c.name)
            for c in frappe.get_all("Customer", filters=f,
                                    fields=["name", "customer_name"])}


def _supplier_names(names=None):
    f = {"name": ["in", list(names)]} if names else {}
    return {s.name: (s.supplier_name or s.name)
            for s in frappe.get_all("Supplier", filters=f,
                                    fields=["name", "supplier_name"])}


def _unit_label(u):
    return u.unit_no or u.name


def _head_leases():
    """Live head-leases, one per building where there is more than one."""
    return frappe.get_all(
        "Head Lease",
        filters={"status": ["in", _LIVE_LEASE]},
        fields=["name", "building", "landlord", "monthly_rent", "annual_rent",
                "end_date", "units_covered"],
        order_by="end_date asc")


def _lease_by_building():
    out = {}
    for h in _head_leases():
        out.setdefault(h.building, h)
    return out


# ------------------------------------------------------------ 1. arrears

@frappe.whitelist()
def get_arrears():
    """Outstanding invoices past their due date plus the grace period,
    worst first, with the tenancy that produced them."""
    _guard()
    today = getdate(nowdate())
    grace = _grace_days()

    inv = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "outstanding_amount", "due_date",
                "grand_total"])
    overdue = [r for r in inv
               if r.due_date and (today - getdate(r.due_date)).days > grace]
    if not overdue:
        return {"live": True, "rows": [], "total": 0.0, "count": 0}

    by_cust = {}
    for r in overdue:
        by_cust.setdefault(r.customer, []).append(r)

    leases = frappe.get_all(
        "Tenancy Agreement",
        filters={"tenant": ["in", list(by_cust)],
                 "status": ["in", _LIVE_LEASE]},
        fields=["name", "tenant", "unit", "building", "monthly_rent"])
    lease_by_tenant = {}
    for a in leases:
        lease_by_tenant.setdefault(a.tenant, a)

    cases = {}
    if _has("Collection Case"):
        for c in frappe.get_all("Collection Case",
                                filters={"status": ["!=", "Closed"]},
                                fields=["name", "tenant", "status", "days_past_due"]):
            cases.setdefault(c.tenant, c)

    names = _customer_names(by_cust)
    rows, total = [], 0.0
    for cust, items in by_cust.items():
        owed = sum(flt(i.outstanding_amount) for i in items)
        total += owed
        oldest = min(getdate(i.due_date) for i in items)
        days = (today - oldest).days
        label, band = _bucket(days)
        lease = lease_by_tenant.get(cust)
        case = cases.get(cust)
        rows.append({
            "tenant": names.get(cust, cust),
            "tenant_id": cust,
            "unit": lease.unit if lease else "—",
            "building": lease.building if lease else "—",
            "monthly_rent": flt(lease.monthly_rent) if lease else 0.0,
            "outstanding": round(owed, 0),
            "invoices": len(items),
            "days_overdue": days,
            "bucket": label,
            "band": band,
            "case": case.name if case else None,
            "case_status": case.status if case else None,
        })
    rows.sort(key=lambda r: -r["outstanding"])
    return {"live": True, "rows": rows, "total": round(total, 0),
            "count": len(rows)}


# ----------------------------------------------------- 2. landlord cheques

@frappe.whitelist()
def get_landlord_pdc():
    """Outgoing cheques maturing inside the window. These are the payments
    that must be funded, so they are the ones worth a red line."""
    _guard()
    if not _has("Cheque"):
        return {"live": True, "configured": False, "rows": []}

    rows = []
    cheques = frappe.get_all(
        "Cheque",
        filters={"direction": "Outgoing",
                 "status": ["in", ["Received", "Deposited", "Presented"]]},
        fields=["name", "cheque_no", "bank", "cheque_date", "amount",
                "party", "building", "head_lease"])
    suppliers = _supplier_names({c.party for c in cheques if c.party})
    for c in cheques:
        d = _days_until(c.cheque_date)
        if d is None or d > PDC_WINDOW_DAYS:
            continue
        rows.append({
            "cheque": c.name,
            "cheque_no": c.cheque_no or c.name,
            "bank": c.bank or "",
            "amount": flt(c.amount),
            "landlord": suppliers.get(c.party, c.party or "—"),
            "building": c.building or "",
            "maturity": _fmt(c.cheque_date),
            "days_remaining": d,
        })
    rows.sort(key=lambda r: r["days_remaining"])
    return {"live": True, "configured": True, "rows": rows,
            "count": len(rows)}


# ------------------------------------------------------------- dismissals

@frappe.whitelist()
def resolve_alert(alert_id):
    """Shared, persisted dismissal — gone for everyone, not per user."""
    _guard()
    if not frappe.db.exists("MD Alert Dismissal", alert_id):
        frappe.get_doc({
            "doctype": "MD Alert Dismissal",
            "alert_id": alert_id,
            "dismissed_by": frappe.session.user,
            "dismissed_on": now_datetime(),
        }).insert(ignore_permissions=False)
    return {"ok": True}


def _dismissed():
    if not _has("MD Alert Dismissal"):
        return set()
    return {d.name for d in frappe.get_all("MD Alert Dismissal")}


# ------------------------------------------------------- 6. vacant units

@frappe.whitelist()
def get_vacant():
    """Vacant units and the share of head-lease rent each one is bleeding."""
    _guard()
    today = getdate(nowdate())
    units = frappe.get_all(
        "Unit", filters={"status": "Vacant"},
        fields=["name", "unit_no", "building", "unit_type", "furnishing",
                "asking_rent"])
    if not units:
        return {"live": True, "rows": [], "count": 0, "bleed_total": 0.0}

    leases = _lease_by_building()
    unit_count = {}
    for u in frappe.get_all("Unit", fields=["building"]):
        unit_count[u.building] = unit_count.get(u.building, 0) + 1

    prior = frappe.get_all(
        "Tenancy Agreement",
        filters={"unit": ["in", [u.name for u in units]],
                 "status": ["in", ["Expired", "Terminated"]]},
        fields=["unit", "tenant", "end_date"],
        order_by="end_date desc")
    last = {}
    for p in prior:
        last.setdefault(p.unit, p)      # first hit is the most recent
    cust = _customer_names({p.tenant for p in prior if p.tenant})

    rows, bleed_total = [], 0.0
    for u in units:
        hl = leases.get(u.building)
        n = unit_count.get(u.building, 0) or 1
        bleed = flt(hl.monthly_rent) / n if hl else 0.0
        bleed_total += bleed
        lp = last.get(u.name)
        rows.append({
            "building": u.building,
            "unit": _unit_label(u),
            "unit_id": u.name,
            "unit_type": u.unit_type or "",
            "furnishing": u.furnishing or "",
            "bleed": round(bleed, 0),
            "asking_rent": flt(u.asking_rent) or None,
            "last_tenant": cust.get(lp.tenant, lp.tenant) if lp else "—",
            "days_vacant": (today - getdate(lp.end_date)).days
            if lp and lp.end_date else None,
        })
    rows.sort(key=lambda r: (r["days_vacant"] is None,
                             -(r["days_vacant"] or 0)))
    return {"live": True, "rows": rows, "count": len(rows),
            "bleed_total": round(bleed_total, 0)}


# -------------------------------------------------- 9. head-lease expiring

@frappe.whitelist()
def get_headlease_expiring():
    _guard()
    rows = []
    landlords = _supplier_names()
    for h in _head_leases():
        d = _days_until(h.end_date)
        if d is None or d > HEADLEASE_WINDOW:
            continue
        rows.append({
            "head_lease": h.name,
            "building": h.building,
            "landlord": landlords.get(h.landlord, h.landlord or "—"),
            "monthly_cost": flt(h.monthly_rent),
            "annual_cost": flt(h.annual_rent),
            "units": cint(h.units_covered),
            "end_date": _fmt(h.end_date),
            "days_remaining": d,
            "overdue": d < 0,
        })
    rows.sort(key=lambda r: r["days_remaining"])
    return {"live": True, "rows": rows, "count": len(rows)}


# ----------------------------------------------------- 10. tenancy expiring

@frappe.whitelist()
def get_tenant_expiring():
    _guard()
    agreements = frappe.get_all(
        "Tenancy Agreement",
        filters={"status": ["in", _LIVE_LEASE]},
        fields=["name", "tenant", "unit", "building", "monthly_rent",
                "end_date", "notice_days", "auto_renew"],
        order_by="end_date asc")
    names = _customer_names({a.tenant for a in agreements if a.tenant})
    rows = []
    for a in agreements:
        d = _days_until(a.end_date)
        if d is None or d > TENANT_WINDOW:
            continue
        rows.append({
            "agreement": a.name,
            "tenant": names.get(a.tenant, a.tenant or "—"),
            "unit": a.unit or "—",
            "building": a.building or "—",
            "monthly_rent": flt(a.monthly_rent),
            "end_date": _fmt(a.end_date),
            "days_remaining": d,
            "notice_days": cint(a.notice_days),
            "auto_renew": bool(a.auto_renew),
            "notice_passed": cint(a.notice_days) > 0 and d < cint(a.notice_days),
        })
    return {"live": True, "rows": rows, "count": len(rows)}


# --------------------------------------------------- 13. maintenance aging

@frappe.whitelist()
def get_maintenance_aging():
    _guard()
    if not _has("Maintenance Request"):
        return {"live": True, "rows": [], "count": 0}
    now = now_datetime()
    rows = []
    for m in frappe.get_all(
            "Maintenance Request",
            filters={"status": ["in", _OPEN_MAINT]},
            fields=["name", "building", "unit", "category", "status",
                    "priority", "issue", "reported_on", "creation",
                    "assigned_to"]):
        raised = m.reported_on or m.creation
        if not raised:
            continue
        hours = (now - frappe.utils.get_datetime(raised)).total_seconds() / 3600.0
        if hours < MAINT_AGE_HOURS:
            continue
        rows.append({
            "job": m.name,
            "building": m.building or "—",
            "unit": m.unit or "—",
            "category": m.category or "",
            "status": m.status,
            "priority": m.priority or "",
            "issue": m.issue or "",
            "hours_open": int(hours),
            "assigned": m.assigned_to or "—",
        })
    rows.sort(key=lambda r: -r["hours_open"])
    return {"live": True, "rows": rows, "count": len(rows)}


# ------------------------------------------------------------ the strip

@frappe.whitelist()
def get_attention():
    """The six alerts, each pointing at the screen that can act on it.
    Entry shape is [id, severity, icon, message, drill_route, drill_label]."""
    _guard()
    gone = _dismissed()
    out = []

    ar = get_arrears()
    if ar["count"]:
        out.append(["arrears", "high", "invoice",
                    "Arrears — QAR %s across %d tenants"
                    % ("{:,.0f}".format(ar["total"]), ar["count"]),
                    "tenants/arrears", "Open arrears"])

    pdc = get_landlord_pdc()
    if pdc.get("configured"):
        for r in pdc["rows"]:
            aid = "pdc_%s" % r["cheque"]
            if aid in gone:
                continue
            out.append([aid, "high", "dollar",
                        "Landlord cheque %s — QAR %s to %s in %d days"
                        % (r["cheque_no"], "{:,.0f}".format(r["amount"]),
                           r["landlord"], r["days_remaining"]),
                        "finance/pdc", "Cheque detail"])

    vc = get_vacant()
    if vc["count"]:
        out.append(["vac", "warn", "home",
                    "%d vacant unit%s · QAR %s/mo head-lease bleed"
                    % (vc["count"], "" if vc["count"] == 1 else "s",
                       "{:,.0f}".format(vc["bleed_total"])),
                    "portfolio/units/Vacant", "Vacant units"])

    hl = get_headlease_expiring()
    if hl["count"]:
        out.append(["hl", "warn", "building",
                    "%d head-lease%s expiring within %d days"
                    % (hl["count"], "" if hl["count"] == 1 else "s",
                       HEADLEASE_WINDOW),
                    "portfolio/headleases", "Review head-leases"])

    te = get_tenant_expiring()
    if te["count"]:
        out.append(["exp", "warn", "calendar",
                    "%d tenancy agreement%s expire within %d days"
                    % (te["count"], "" if te["count"] == 1 else "s",
                       TENANT_WINDOW),
                    "tenants/expiring", "Review renewals"])

    mn = get_maintenance_aging()
    if mn["count"]:
        out.append(["mnt", "warn", "wrench",
                    "%d maintenance request%s open past %dh"
                    % (mn["count"], "" if mn["count"] == 1 else "s",
                       MAINT_AGE_HOURS),
                    "maintenance/aging", "Aged tickets"])

    return {"live": True,
            "alerts": [a for a in out if a[0] not in gone][:6]}
