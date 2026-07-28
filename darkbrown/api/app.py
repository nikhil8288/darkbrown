"""The bridge between Frappe and the prototype.

The prototype is the application. It builds its screens from a handful of
in-memory arrays — BUILDINGS, UNITS, CASES, JOBS, MOVEOUT and the rest — and
every screen is written against those shapes. So rather than rewrite the
front end to speak Frappe, this module speaks the front end's language: it
reads real records and hands back exactly the shapes the prototype already
knows how to render.

Money is carried in thousands of QAR, because that is what the prototype's
formatters expect. One place converts, here.
"""

import frappe
from frappe.utils import flt, getdate, today, date_diff, add_days

K = 1000.0


def _k(v):
    return round(flt(v) / K, 1)


def _fdate(d):
    """The prototype renders dates as '24 Jul 26'."""
    if not d:
        return "—"
    return getdate(d).strftime("%d %b %y")


# ------------------------------------------------------------------ portfolio

def buildings():
    rows = frappe.get_all(
        "Building",
        fields=["name", "building_name", "status", "landlord", "area_name",
                "floors", "total_units"],
        order_by="building_name asc")
    if not rows:
        return []

    units_by_b = {}
    for u in frappe.get_all("Unit", fields=["name", "building", "status"]):
        units_by_b.setdefault(u.building, []).append(u)

    rent_by_b, arrears_by_b = _tenancy_rollup()
    hl_by_b = _headlease_rollup()

    out = []
    for b in rows:
        us = units_by_b.get(b.name, [])
        total = len(us) or (b.total_units or 0)
        occupied = len([u for u in us if u.status == "Occupied"])
        vacant = [u for u in us if u.status in ("Vacant", "Not Ready",
                                                "Reserved")]
        rev = _k(rent_by_b.get(b.name, 0))
        hl = hl_by_b.get(b.name, {})
        cost = _k(hl.get("monthly", 0))
        margin = round(rev - cost, 1)
        out.append({
            "id": b.name,
            "n": b.building_name or b.name,
            "units": total,
            "rev": rev,
            "cost": cost,
            "m": margin,
            "mp": round(margin / rev * 100, 1) if rev else 0,
            "arr": _k(arrears_by_b.get(b.name, 0)),
            "vd": len(vacant),
            "om": 0,
            "ex": 0,
            "occ": round(occupied / total * 100) if total else 0,
            "d": 0,
            "ll": hl.get("landlord") or b.landlord or "—",
            "hlEnd": _fdate(hl.get("end_date")),
            "hlRent": cost,
            "area": b.area_name or "—",
            "floors": b.floors or 0,
        })
    return out


def _tenancy_rollup():
    rent, arrears = {}, {}
    tas = frappe.get_all(
        "Tenancy Agreement",
        filters={"status": ["in", ("Active", "Expiring")]},
        fields=["name", "building", "tenant", "monthly_rent"])
    for ta in tas:
        rent[ta.building] = rent.get(ta.building, 0) + flt(ta.monthly_rent)

    by_customer = {}
    for row in frappe.get_all(
            "Sales Invoice",
            filters={"docstatus": 1, "outstanding_amount": [">", 0]},
            fields=["customer", "outstanding_amount"]):
        by_customer[row.customer] = (by_customer.get(row.customer, 0)
                                     + flt(row.outstanding_amount))
    for ta in tas:
        if ta.tenant in by_customer:
            arrears[ta.building] = (arrears.get(ta.building, 0)
                                    + by_customer[ta.tenant])
    return rent, arrears


def _headlease_rollup():
    out = {}
    for hl in frappe.get_all(
            "Head Lease",
            filters={"status": ["in", ("Active", "Expiring")]},
            fields=["building", "landlord", "monthly_rent", "end_date"]):
        out[hl.building] = {
            "monthly": flt(hl.monthly_rent),
            "landlord": hl.landlord,
            "end_date": hl.end_date,
        }
    return out


UNIT_STATE = {
    "Occupied": "Occupied",
    "Vacant": "Void",
    "Not Ready": "Make-ready",
    "Reserved": "Reserved",
    "Under Maintenance": "Make-ready",
}


def units():
    rows = frappe.get_all(
        "Unit",
        fields=["name", "building", "unit_no", "unit_type", "floor",
                "area_sqm", "status", "modified"],
        order_by="building asc, unit_no asc")
    if not rows:
        return []

    bnames = {b.name: b.building_name for b in frappe.get_all(
        "Building", fields=["name", "building_name"])}
    rent_by_unit = {ta.unit: flt(ta.monthly_rent) for ta in frappe.get_all(
        "Tenancy Agreement",
        filters={"status": ["in", ("Active", "Expiring")]},
        fields=["unit", "monthly_rent"])}

    out = []
    for u in rows:
        vacant = u.status in ("Vacant", "Not Ready", "Reserved")
        rent = _k(rent_by_unit.get(u.name, 0))
        out.append({
            "id": u.name,
            "b": u.building,
            "bn": bnames.get(u.building, u.building),
            "type": u.unit_type or "—",
            "floor": u.floor or "—",
            "sqm": round(flt(u.area_sqm)) or 0,
            "rent": rent,
            "llRent": round(rent * 0.78, 1),
            "st": UNIT_STATE.get(u.status, u.status or "Void"),
            "vd": date_diff(today(), u.modified) if vacant else 0,
        })
    return out


# ----------------------------------------------------------------- operations

CASE_STAGE = {
    "Open": "Reminder sent",
    "Contacted": "Reminder sent",
    "Promised": "Promise to pay",
    "Broken Promise": "Promise broken",
    "Escalated": "Escalated",
    "Legal": "Legal notice",
}


def cases():
    rows = frappe.get_all(
        "Collection Case",
        filters={"status": ["in", list(CASE_STAGE)]},
        fields=["name", "tenant", "status", "outstanding_amount", "opened_on",
                "promised_date", "owner", "days_past_due"],
        order_by="outstanding_amount desc")
    if not rows:
        return []
    tnames = _customer_names([r.tenant for r in rows])
    out = []
    for c in rows:
        out.append({
            "id": c.name,
            "t": c.tenant,
            "tn": tnames.get(c.tenant, c.tenant),
            "amt": _k(c.outstanding_amount),
            "stage": CASE_STAGE.get(c.status, c.status),
            "age": (date_diff(today(), c.opened_on) if c.opened_on else 0),
            "owner": _short_name(c.owner),
            "promise": _fdate(c.promised_date) if c.promised_date else "—",
        })
    return out


JOB_STATE = {
    "Open": "Open",
    "Assigned": "Assigned",
    "Scheduled": "Assigned",
    "In Progress": "In progress",
    "Resolved": "Completed",
    "Cancelled": "Completed",
}
JOB_PRIORITY = {"Emergency": "Emergency", "High": "Planned",
                "Medium": "Planned", "Low": "Routine"}


def jobs():
    rows = frappe.get_all(
        "Maintenance Request",
        filters={"status": ["!=", "Cancelled"]},
        fields=["name", "building", "unit", "category", "priority", "cost",
                "status", "rechargeable", "reported_on", "assigned_to",
                "over_ceiling"],
        order_by="reported_on desc")
    if not rows:
        return []
    bnames = {b.name: b.building_name for b in frappe.get_all(
        "Building", fields=["name", "building_name"])}
    out = []
    for j in rows:
        out.append({
            "id": j.name,
            "b": j.building,
            "bn": bnames.get(j.building, j.building),
            "u": j.unit or "—",
            "cat": j.category or "Other",
            "pr": JOB_PRIORITY.get(j.priority, "Routine"),
            "cost": _k(j.cost),
            "st": JOB_STATE.get(j.status, j.status),
            "rch": bool(j.rechargeable),
            "age": (date_diff(today(), j.reported_on) if j.reported_on else 0),
            "owner": _short_name(j.assigned_to) or "Maint. team",
            "ceil": bool(j.over_ceiling),
        })
    return out


MO_STEP = {
    "Notice Received": 0,
    "Inspection Pending": 1,
    "Inspection Done": 2,
    "Settlement Pending": 3,
    "Refund Pending": 4,
    "Closed": 4,
}


def moveouts():
    rows = frappe.get_all(
        "Move Out Case",
        filters={"status": ["!=", "Cancelled"]},
        fields=["name", "tenant", "unit", "status", "deposit_held",
                "notice_received_on", "planned_move_out", "outstanding_rent",
                "utilities_due", "damages_charged"],
        order_by="planned_move_out asc")
    if not rows:
        return []
    tnames = _customer_names([r.tenant for r in rows])
    out = []
    for m in rows:
        ded = []
        if flt(m.outstanding_rent):
            ded.append(["Outstanding rent", _k(m.outstanding_rent)])
        if flt(m.utilities_due):
            ded.append(["Utilities", _k(m.utilities_due)])
        if flt(m.damages_charged):
            ded.append(["Damages", _k(m.damages_charged)])
        out.append({
            "id": m.name,
            "t": m.tenant,
            "tn": tnames.get(m.tenant, m.tenant),
            "u": m.unit,
            "dep": _k(m.deposit_held),
            "step": MO_STEP.get(m.status, 0),
            "notice": _fdate(m.notice_received_on),
            "out": _fdate(m.planned_move_out),
            "ded": ded,
        })
    return out


# ---------------------------------------------------------------- helpers

def _customer_names(ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {c.name: c.customer_name for c in frappe.get_all(
        "Customer", filters={"name": ["in", ids]},
        fields=["name", "customer_name"])}


def _short_name(user):
    if not user or user == "Administrator":
        return "MD"
    full = frappe.db.get_value("User", user, "full_name") or user
    parts = full.split()
    if len(parts) < 2:
        return full
    return f"{parts[0]} {parts[-1][0]}."


ROLE_CODE = [
    ("Managing Director", "MD"),
    ("General Manager", "GM"),
    ("Accounts", "ACC"),
    ("Documentation", "DOC"),
    ("Maintenance", "MNT"),
]


def role_code(user=None):
    """The prototype masks screens by a single role code. Frappe users can
    hold several roles; the most privileged one wins."""
    roles = set(frappe.get_roles(user or frappe.session.user))
    if "System Manager" in roles and "Managing Director" not in roles:
        return "MD"
    for name, code in ROLE_CODE:
        if name in roles:
            return code
    return "ACC"


def seed():
    """Everything the front end needs at boot, in one round trip.

    A module that returns nothing is left out entirely, and the prototype
    falls back to its own seeded values for that module. That is deliberate:
    Finance, Documents, Planning and Owners are not wired yet, and a screen
    showing its demo data is far better than a screen showing zero.
    """
    data = {}
    for key, fn in (("buildings", buildings), ("units", units),
                    ("cases", cases), ("jobs", jobs),
                    ("moveouts", moveouts)):
        try:
            rows = fn()
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"darkbrown seed: {key}")
            rows = []
        if rows:
            data[key] = rows
    return data


@frappe.whitelist()
def refresh():
    """Called by the front end after a write, so the screen reflects what was
    actually saved rather than what the browser thinks it saved."""
    return {"seed": seed(), "role": role_code(),
            "user": frappe.db.get_value("User", frappe.session.user,
                                        "full_name")}
