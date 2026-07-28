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
                    ("moveouts", moveouts), ("tenants", tenants),
                    ("agreements", agreements), ("invoices", invoices),
                    ("cheques", cheques), ("docs", docs),
                    ("approvals", approvals)):
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


# ------------------------------------------------------------------- parties

def tenants():
    """Tenants are ERPNext Customers carrying the tenant flag. Unit count,
    rent and arrears are rolled up from live agreements and invoices rather
    than stored, so they cannot drift."""
    rows = frappe.get_all(
        "Customer",
        filters={"db_is_tenant": 1},
        fields=["name", "customer_name", "customer_type", "db_qid",
                "db_cr_no", "db_mobile", "creation"],
        order_by="customer_name asc")
    if not rows:
        return []

    units, rent = {}, {}
    for ta in frappe.get_all(
            "Tenancy Agreement",
            filters={"status": ["in", ("Active", "Expiring")]},
            fields=["tenant", "monthly_rent"]):
        units[ta.tenant] = units.get(ta.tenant, 0) + 1
        rent[ta.tenant] = rent.get(ta.tenant, 0) + flt(ta.monthly_rent)

    arrears = _arrears_by_tenant()

    out = []
    for c in rows:
        arr = _k(arrears.get(c.name, 0))
        corp = c.customer_type == "Company"
        out.append({
            "id": c.name,
            "n": c.customer_name or c.name,
            "corp": corp,
            "units": units.get(c.name, 0),
            "rent": _k(rent.get(c.name, 0)),
            "arr": arr,
            "st": "In arrears" if arr > 25 else "Late" if arr > 0 else "Current",
            "qid": c.db_cr_no or c.db_qid or "—",
            "since": _fdate(c.creation),
            "phone": c.db_mobile or "—",
        })
    return out


def _arrears_by_tenant():
    out = {}
    for si in frappe.get_all(
            "Sales Invoice",
            filters={"docstatus": 1, "outstanding_amount": [">", 0]},
            fields=["customer", "outstanding_amount"]):
        out[si.customer] = out.get(si.customer, 0) + flt(si.outstanding_amount)
    return out


# ---------------------------------------------------------------- agreements

TA_STATE = {"Draft": "Draft", "Pending Approval": "Pending",
            "Active": "Active", "Expiring": "Expiring",
            "Expired": "Expired", "Terminated": "Terminated"}


def agreements():
    rows = frappe.get_all(
        "Tenancy Agreement",
        filters={"status": ["!=", "Terminated"]},
        fields=["name", "tenant", "unit", "building", "status", "start_date",
                "end_date", "monthly_rent", "security_deposit",
                "payment_mode", "renewal_of"],
        order_by="end_date asc")
    if not rows:
        return []

    tnames = _customer_names([r.tenant for r in rows])
    bnames = _building_names([r.building for r in rows])
    renewed = {r.renewal_of for r in rows if r.renewal_of}

    out = []
    for a in rows:
        end_d = date_diff(a.end_date, today()) if a.end_date else 0
        out.append({
            "id": a.name,
            "t": a.tenant,
            "tn": tnames.get(a.tenant, a.tenant),
            "u": a.unit or "—",
            "b": a.building,
            "bn": bnames.get(a.building, a.building),
            "rent": _k(a.monthly_rent),
            "dep": _k(a.security_deposit),
            "start": _fdate(a.start_date),
            "end": _fdate(a.end_date),
            "endD": end_d,
            "st": TA_STATE.get(a.status, a.status),
            "ren": ("Renewed" if a.name in renewed
                    else "Not started" if end_d < 180 else "—"),
            "freq": a.payment_mode or "Monthly",
        })
    return out


# ------------------------------------------------------------------- finance

def invoices():
    """Sales Invoices raised against tenants. The building and unit come from
    the invoice run line that produced it where there is one; a manually
    raised invoice simply carries no unit."""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": ["<", 2]},
        fields=["name", "customer", "grand_total", "outstanding_amount",
                "due_date", "status", "docstatus"],
        order_by="due_date desc", limit=300)
    if not rows:
        return []

    tnames = _customer_names([r.customer for r in rows])
    link = {}
    for l in frappe.get_all(
            "Invoice Run Line",
            filters={"sales_invoice": ["in", [r.name for r in rows]]},
            fields=["sales_invoice", "tenancy_agreement", "unit"]):
        link[l.sales_invoice] = l
    ta_b = {t.name: t for t in frappe.get_all(
        "Tenancy Agreement",
        fields=["name", "building", "unit"])} if link else {}
    bnames = _building_names([t.building for t in ta_b.values()])

    out = []
    for si in rows:
        paid = flt(si.grand_total) - flt(si.outstanding_amount)
        l = link.get(si.name)
        ta = ta_b.get(l.tenancy_agreement) if l else None
        due_d = date_diff(si.due_date, today()) if si.due_date else 0
        if flt(si.outstanding_amount) <= 0 and si.docstatus == 1:
            st = "Paid"
        elif paid > 0:
            st = "Part paid"
        else:
            st = "Unpaid"
        out.append({
            "id": si.name,
            "t": si.customer,
            "tn": tnames.get(si.customer, si.customer),
            "a": l.tenancy_agreement if l else "—",
            "b": ta.building if ta else "—",
            "bn": bnames.get(ta.building, "—") if ta else "—",
            "amt": _k(si.grand_total),
            "paid": _k(paid),
            "due": _fdate(si.due_date),
            "dueD": due_d,
            "st": "Draft" if si.docstatus == 0 else st,
            "lines": _invoice_lines(si.name),
        })
    return out


def _invoice_lines(invoice):
    return [[i.item_name or i.description or "Rent", _k(i.amount)]
            for i in frappe.get_all(
                "Sales Invoice Item", filters={"parent": invoice},
                fields=["item_name", "description", "amount"])]


CHQ_STATE = {"Received": "On hand", "Deposited": "Deposited",
             "Presented": "Deposited", "Cleared": "Cleared",
             "Returned": "Bounced", "Replaced": "Replaced",
             "Cancelled": "Cancelled"}


def cheques():
    rows = frappe.get_all(
        "Cheque",
        filters={"direction": "Incoming", "status": ["!=", "Cancelled"]},
        fields=["name", "party", "amount", "bank", "cheque_no", "cheque_date",
                "status", "return_reason", "replaced_by", "unit"],
        order_by="cheque_date asc", limit=400)
    if not rows:
        return []
    tnames = _customer_names([r.party for r in rows])
    out = []
    for c in rows:
        mat_d = date_diff(c.cheque_date, today()) if c.cheque_date else 0
        if c.status == "Returned":
            act = ("Replacement received" if c.replaced_by
                   else "Replacement pending")
        else:
            act = ""
        out.append({
            "id": c.name,
            "t": c.party,
            "tn": tnames.get(c.party, c.party or "—"),
            "amt": _k(c.amount),
            "bank": c.bank or "—",
            "no": c.cheque_no or "—",
            "mat": _fdate(c.cheque_date),
            "matD": mat_d,
            "st": CHQ_STATE.get(c.status, c.status),
            "reason": c.return_reason or "",
            "act": act,
        })
    return out


# ----------------------------------------------------------------- documents

DOC_STATE = {"Draft": "Needs review", "Extracting": "Needs review",
             "Needs Review": "Needs review", "Confirmed": "Validated",
             "Rejected": "Flagged", "Superseded": "Pushed to vault"}


def docs():
    rows = frappe.get_all(
        "Document Register",
        filters={"status": ["!=", "Superseded"]},
        fields=["name", "document_type", "source_file", "status",
                "extraction_confidence", "owner", "modified", "document_no",
                "expiry_date", "party", "building"],
        order_by="modified desc", limit=60)
    if not rows:
        return []
    out = []
    for d in rows:
        bits = []
        if d.document_no:
            bits.append(d.document_no)
        if d.party:
            bits.append(str(d.party))
        if d.building:
            bits.append(str(d.building))
        if d.expiry_date:
            bits.append("expiry " + _fdate(d.expiry_date))
        out.append({
            "id": d.name,
            "ty": d.document_type or "Unknown",
            "f": (d.source_file or "").split("/")[-1] or "—",
            "st": DOC_STATE.get(d.status, d.status),
            "conf": round(flt(d.extraction_confidence) * 100)
                    if flt(d.extraction_confidence) <= 1
                    else round(flt(d.extraction_confidence)),
            "by": _short_name(d.owner),
            "when": _fdate(d.modified),
            "ext": " · ".join(bits) or "—",
        })
    return out


# ----------------------------------------------------------------- approvals

def approvals():
    """One queue, several sources. Everything waiting on a human decision
    surfaces here with the reason it is waiting."""
    out = []

    for a in frappe.get_all(
            "Agreement Amendment",
            filters={"status": ["in", ("Pending GM", "Pending MD")]},
            fields=["name", "agreement", "field_changed", "old_value",
                    "new_value", "value_impact", "reason", "requested_by",
                    "requested_on", "status"]):
        out.append({
            "id": a.name,
            "ty": "Amendment",
            "ref": f"{a.agreement} · {_short_name(a.requested_by)}",
            "amt": _k(a.value_impact),
            "age": _age(a.requested_on),
            "res": 1 if a.status == "Pending MD" else 0,
            "st": "Pending",
            "why": a.reason or (f"{a.field_changed}: {a.old_value} → "
                                f"{a.new_value}"),
        })

    ceiling = flt(frappe.db.get_single_value(
        "DBR Settings", "emergency_maintenance_ceiling") or 2000)
    for m in frappe.get_all(
            "Maintenance Request",
            filters={"status": ["in", ("Open", "Assigned", "Scheduled")],
                     "over_ceiling": 1},
            fields=["name", "building", "unit", "cost", "category",
                    "reported_on", "issue"]):
        out.append({
            "id": m.name,
            "ty": "Emergency maint.",
            "ref": f"{m.building} · {m.category or 'Maintenance'}",
            "amt": _k(m.cost),
            "age": _age(m.reported_on),
            "res": 1,
            "st": "Pending",
            "why": (f"Above the QAR {ceiling:,.0f} emergency ceiling — "
                    f"{m.issue or m.category or 'works'} at "
                    f"{m.unit or m.building}."),
        })

    for s in frappe.get_all(
            "Security Deposit",
            filters={"status": "Held", "move_out_case": ["is", "set"]},
            fields=["name", "tenancy_agreement", "amount", "deductions",
                    "move_out_case", "modified"]):
        refund = flt(s.amount) - flt(s.deductions)
        out.append({
            "id": s.name,
            "ty": "Deposit release",
            "ref": f"{s.tenancy_agreement} · {s.move_out_case}",
            "amt": _k(refund),
            "age": _age(s.modified),
            "res": 1,
            "st": "Pending",
            "why": (f"Move-out {s.move_out_case} settled. "
                    f"Deductions raised: QAR {flt(s.deductions):,.0f}."),
        })

    for r in frappe.get_all(
            "Invoice Run",
            filters={"status": "Pending GM"},
            fields=["name", "building", "total_amount", "has_variance",
                    "variance_reason", "generated_on"]):
        out.append({
            "id": r.name,
            "ty": "Invoice run",
            "ref": str(r.building),
            "amt": _k(r.total_amount),
            "age": _age(r.generated_on),
            "res": 0,
            "st": "Pending",
            "why": (r.variance_reason if r.has_variance
                    else "Standard monthly run, no variance against agreements."),
        })

    out.sort(key=lambda x: (-x["res"], -x["age"]))
    return out


def _age(dt):
    if not dt:
        return 0
    try:
        return max(date_diff(today(), getdate(dt)), 0)
    except Exception:
        return 0


def _building_names(ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {b.name: (b.building_name or b.name) for b in frappe.get_all(
        "Building", filters={"name": ["in", ids]},
        fields=["name", "building_name"])}
