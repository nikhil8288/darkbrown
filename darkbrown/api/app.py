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

def _k(v):
    """Money crosses to the shell in whole riyals. No scaling anywhere."""
    return round(flt(v))


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
            # No revenue means the percentage is undefined, not zero.
            # Zero made a building losing its whole head-lease cost
            # read as break-even.
            "mp": round(margin / rev * 100, 1) if rev else None,
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


def _health():
    from darkbrown.api.command import health
    return health()


def _kpi():
    from darkbrown.api.command import kpis
    return kpis()


def _panels():
    from darkbrown.api.command import panels
    return panels()


def seed():
    """Everything the front end needs at boot, in one round trip.

    A module that returns nothing is left out, and the front end decides what
    to do about it. What it must not do is quietly fall back to demo values,
    because an exception in one function then reads as four confident tiles
    about a portfolio that does not exist. Anything that raised is named in
    `_failed` so the screen can say the server broke rather than invent.
    """
    data = {}
    failed = []
    for key, fn in (("buildings", buildings), ("units", units),
                    ("cases", cases), ("jobs", jobs),
                    ("moveouts", moveouts), ("tenants", tenants),
                    ("agreements", agreements), ("invoices", invoices),
                    ("cheques", cheques), ("docs", docs),
                    ("approvals", approvals), ("wall", wall),
                    ("landlords", landlords),
                    ("health", _health), ("kpi", _kpi),
                    ("panels", _panels),
                    ("bankAccounts", bank_accounts)):
        try:
            rows = fn()
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"darkbrown seed: {key}")
            failed.append(key)
            rows = []
        if rows:
            data[key] = rows
    if failed:
        data["_failed"] = failed
    return data


@frappe.whitelist()
def refresh():
    """Called by the front end after a write, so the screen reflects what was
    actually saved rather than what the browser thinks it saved."""
    return {"seed": seed(), "role": role_code(),
            "user": frappe.db.get_value("User", frappe.session.user,
                                        "full_name")}


def bank_accounts():
    rows = frappe.get_all("Bank Account", filters={"is_company_account": 1},
                          fields=["name", "account_name", "bank"])
    return [{"name": r.name,
             "label": f"{r.bank} — {r.account_name}" if r.bank
             else r.account_name} for r in rows]


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
            "st": "In arrears" if arr > 25000 else "Late" if arr > 0 else "Current",
            "qid": c.db_cr_no or c.db_qid or "—",
            "since": _fdate(c.creation),
            "phone": c.db_mobile or "—",
        })
    return out


def landlords():
    """Landlords are parties in their own right, not a text field on a
    building. What comes back here is what the head lease, the payment run and
    the document vault all hang off, so it is read from the Supplier record
    rather than derived from the building list."""
    rows = frappe.get_all(
        "Supplier",
        filters={"db_is_landlord": 1},
        fields=["name", "supplier_name", "supplier_type", "creation",
                "db_landlord_qid", "db_nationality", "db_iban", "db_bank_name",
                "db_mobile", "email_id"])
    if not rows:
        return []

    by_landlord = {}
    for b in frappe.get_all("Building", fields=["name", "landlord"]):
        if b.landlord:
            by_landlord.setdefault(b.landlord, []).append(b.name)

    docs = {}
    for d in frappe.get_all(
            "Document Register",
            filters={"party_type": "Supplier",
                     "status": ["!=", "Superseded"]},
            fields=["party", "document_type", "source_file", "status"]):
        docs.setdefault(d.party, []).append({
            "t": d.document_type or "Unknown",
            "f": (d.source_file or "").split("/")[-1] or "\u2014",
            "st": DOC_STATE.get(d.status, d.status)})

    out = []
    for s in rows:
        out.append({
            "id": s.name,
            "n": s.supplier_name or s.name,
            "type": "Company" if s.supplier_type == "Company" else "Individual",
            "idno": s.db_landlord_qid or "—",
            "phone": s.db_mobile or "—",
            "email": s.email_id or "—",
            "bank": " · ".join(x for x in (s.db_bank_name, s.db_iban) if x) or "—",
            "rep": "—",
            "buildings": by_landlord.get(s.name, []),
            "since": _fdate(s.creation),
            "docs": docs.get(s.name, []),
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
                "payment_mode", "payment_frequency", "renewal_of",
                "activation_route", "missing_items", "signed_pack",
                "qid_number", "approved_by", "approved_on"],
        order_by="end_date asc")
    if not rows:
        return []

    tnames = _customer_names([r.tenant for r in rows])
    bnames = _building_names([r.building for r in rows])
    renewed = {r.renewal_of for r in rows if r.renewal_of}
    linked = _agreement_docs(rows)

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
            # Mode is how rent arrives; frequency is how often it falls due.
            # They were one key, which is why a cash tenancy read as a cash
            # billing cycle.
            "freq": a.payment_frequency or "Monthly",
            "mode": a.payment_mode or "Cheque",
            "route": a.activation_route or "",
            "missing": a.missing_items or "",
            "apby": _short_name(a.approved_by) if a.approved_by else "",
            "apon": _fdate(a.approved_on) if a.approved_on else "",
            "docs": linked.get(a.name, []),
        })
    return out


def _agreement_docs(rows):
    """The documents actually on file against each tenancy.

    Nothing is assumed present. A tenancy with no register entries comes back
    with an empty list, and the screen says so rather than showing a tidy row
    of ticks for paperwork that was never uploaded.
    """
    units = {r.unit for r in rows if r.unit}
    tenants = {r.tenant for r in rows if r.tenant}
    by_unit, by_party = {}, {}
    if units or tenants:
        filters = {"status": ["!=", "Superseded"]}
        for d in frappe.get_all(
                "Document Register", filters=filters,
                fields=["name", "document_type", "source_file", "status",
                        "unit", "party", "expiry_date"]):
            item = {
                "id": d.name,
                "t": d.document_type or "Unknown",
                "f": (d.source_file or "").split("/")[-1] or "\u2014",
                "st": DOC_STATE.get(d.status, d.status),
                "exp": _fdate(d.expiry_date) if d.expiry_date else "",
            }
            if d.unit:
                by_unit.setdefault(d.unit, []).append(item)
            if d.party:
                by_party.setdefault(d.party, []).append(item)

    out = {}
    for r in rows:
        seen, items = set(), []
        for item in by_unit.get(r.unit, []) + by_party.get(r.tenant, []):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)
        out[r.name] = items
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
        order_by="modified desc", limit=200)
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
            # what the vault needs to file it against something
            "link": (str(d.party) if d.party
                     else str(d.building) if d.building else "—"),
            "ent": ("Tenant" if d.party else "Building" if d.building
                    else "Unfiled"),
            "filed": str(d.modified)[:10] if d.modified else "",
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

    for t in frappe.get_all(
            "Tenancy Agreement",
            filters={"status": "Pending Approval"},
            fields=["name", "tenant", "unit", "building", "monthly_rent",
                    "missing_items", "creation", "owner"]):
        out.append({
            "id": t.name,
            "ty": "Tenancy activation",
            "ref": f"{t.unit or t.building} · {_short_name(t.owner)}",
            "amt": _k(t.monthly_rent),
            "age": _age(t.creation),
            "res": 0,
            "st": "Pending",
            "why": (f"Routed rather than self-approved. Missing: "
                    f"{t.missing_items}." if t.missing_items
                    else "Routed for approval; nothing was recorded as missing."),
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


# ---------------------------------------------------------------------- wall

"""The four numbers an MD looks at before anything else.

Each one carries its own verdict. The band is decided here, on the server,
against thresholds an owner can change in settings — the front end only
renders the colour it was handed. That matters because a threshold buried in
a browser script is a threshold nobody can audit or tune.

Every tile also carries what it means and, when it is not green, what to do
about it. A number without a next step is a number that gets ignored.
"""

BAND_ORDER = {"red": 0, "amber": 1, "green": 2}


def _band(value, green_at, red_below, higher_is_better=True):
    if value is None:
        return "grey"
    if higher_is_better:
        if value < red_below:
            return "red"
        return "green" if value >= green_at else "amber"
    if value > red_below:
        return "red"
    return "green" if value <= green_at else "amber"


def wall():
    s = frappe.get_single("DBR Settings")
    tiles = [_cover(s), _spread(s), _collection(s), _losers(s)]
    return [t for t in tiles if t]


def _cover(s):
    """Can the landlords be paid?

    Cheques already in hand are near-certain money. Invoiced-but-unpaid rent
    is not, so it is discounted by the collection rate actually achieved
    rather than taken at face value.
    """
    days = int(s.wall_cover_days or 60)
    horizon = add_days(today(), days)

    # Owed splits into the backlog and the window. Both are real obligations
    # and both stay in the ratio, but a single figure labelled "next 60 days"
    # that silently carries every unpaid month of history reads as two months
    # of rent when it is not — the split has to be on the tile.
    overdue = sum(flt(p.amount) for p in frappe.get_all(
        "Head Lease Payment",
        filters={"status": ["!=", "Paid"], "due_date": ["<", today()]},
        fields=["amount"]))
    due_window = sum(flt(p.amount) for p in frappe.get_all(
        "Head Lease Payment",
        filters={"status": ["!=", "Paid"],
                 "due_date": ["between", [today(), horizon]]},
        fields=["amount"]))
    owed = overdue + due_window

    # A post-dated cheque is bankable until it goes stale — six months in
    # Qatar. Anything older sitting at Received/Deposited is a data problem,
    # not money, so it does not count toward cover.
    in_hand = sum(flt(c.amount) for c in frappe.get_all(
        "Cheque",
        filters={"direction": "Incoming",
                 "status": ["in", ("Received", "Deposited", "Presented")],
                 "cheque_date": ["between",
                                 [add_days(today(), -180), horizon]]},
        fields=["amount"]))

    billed_open = sum(flt(i.outstanding_amount) for i in frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0],
                 "due_date": ["<=", horizon]},
        fields=["outstanding_amount"]))

    # No billing history means no achieved rate to discount by. Inventing
    # one (the old fallback was a flat 90%) puts a made-up number inside the
    # one tile that can end the business; unpaid invoices simply do not
    # count toward cover until there is a real rate.
    rate = _collection_rate()
    if rate is None:
        expected = in_hand
    else:
        expected = in_hand + billed_open * (rate / 100.0)

    if not owed:
        return {"id": "cover", "label": "Obligation cover",
                "value": "—", "band": "grey",
                "sub": f"No landlord rent falls due in the next {days} days.",
                "means": ("Landlord rent you owe in the next "
                          f"{days} days, against the money you can reasonably "
                          "expect to have by then."),
                "why": ("Your rent to landlords is fixed and contractual — it "
                        "is owed whether the building is full or empty. This "
                        "is the one number that can end the business."),
                "act": "", "go": "#/cheques"}

    ratio = expected / owed
    band = _band(ratio, flt(s.wall_cover_green or 1.2),
                 flt(s.wall_cover_red or 1.0))
    act = {
        "red": (f"You are short by about {_kfmt(owed - expected)}. Chase the "
                "largest arrears now and check whether any landlord payment "
                "can be rescheduled."),
        "amber": ("You will cover it, but with nothing spare. A couple of "
                  "bounced cheques would put you short."),
        "green": "",
    }.get(band, "")

    owed_txt = (f"{_kfmt(owed)} owed ({_kfmt(overdue)} overdue + "
                f"{_kfmt(due_window)} next {days}d)"
                if overdue else f"{_kfmt(owed)} owed · {days} days")
    disc_txt = ("unpaid invoices excluded — no collection history to "
                "discount them by" if rate is None else
                "unpaid invoices discounted at your actual collection "
                f"rate of {rate:.1f}%")
    return {
        "id": "cover", "label": "Obligation cover",
        "value": f"{ratio:.2f}×", "band": band,
        "sub": f"{_kfmt(expected)} expected · {owed_txt}",
        "means": ("All unpaid landlord rent — anything overdue plus what "
                  f"falls due in the next {days} days — set against cheques "
                  f"in hand, with {disc_txt}."),
        "why": ("Rent to your landlords is fixed and contractual — owed "
                "whether a building is full or empty. Your bank balance "
                "cannot answer this because the accounts sweep to near zero "
                "daily. This is the one number that can end the business."),
        "act": act, "go": "#/cheques",
    }


def _spread(s):
    """Is the business making money this month?

    Billed revenue and head-lease cost have to cover the same buildings. A
    building whose invoice run is still sitting in the approvals queue
    contributes nothing to billing while contributing its whole cost, and the
    tile then reports a loss that is really an unmade decision. Those
    buildings come out of both sides and are named instead.
    """
    from darkbrown.api.command import unbilled_buildings

    start = getdate(today()).replace(day=1)
    pending = unbilled_buildings(start)

    billed = sum(flt(i.grand_total) for i in frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "posting_date": [">=", start]},
        fields=["grand_total"]))
    cost = sum(flt(h.monthly_rent) for h in frappe.get_all(
        "Head Lease",
        filters={"status": ["in", ("Active", "Expiring")]},
        fields=["building", "monthly_rent"])
        if h.building not in pending)

    if pending:
        names = _building_names(list(pending.keys()))
        held = sum(pending.values())
        held_txt = (", ".join(names.get(b, b) for b in pending)
                    + f" \u00b7 {_kfmt(held)} raised but not issued")
    else:
        held_txt = ""

    if not billed:
        return {"id": "spread", "label": "Portfolio spread",
                "value": "—", "band": "grey",
                "sub": (f"Nothing issued this month yet \u00b7 {held_txt}"
                        if held_txt else "Nothing billed this month yet."),
                "means": ("What you charge tenants, less what you pay "
                          "landlords."),
                "why": ("This is your entire profit model in one number. You "
                        "do not own property — you rent it and re-rent it, "
                        "and the gap is the business."),
                "act": "", "go": "#/reports"}

    spread = billed - cost
    margin = spread / billed * 100
    band = _band(margin, flt(s.wall_margin_green or 20),
                 flt(s.wall_margin_red or 12))
    act = {
        "red": ("The portfolio is not covering its own cost base. Look at the "
                "loss-making buildings first, then at head leases up for "
                "renewal."),
        "amber": ("Margin is thinner than it should be. Worth checking "
                  "whether it is one building or the whole book."),
        "green": "",
    }.get(band, "")
    if held_txt:
        # Naming a loss-making building is the wrong instruction when the
        # real one is to issue an invoice run someone already raised.
        act = ("Issue the outstanding invoice run before reading this "
               f"month: {held_txt}. Its cost is excluded here until you do.")

    return {
        "id": "spread", "label": "Portfolio spread · gross",
        "value": f"{margin:.1f}%", "band": band,
        "sub": (f"{_kfmt(spread)} on {_kfmt(billed)} billed this month"
                + (f" \u00b7 excludes {held_txt}" if held_txt else "")),
        "means": ("What you charged tenants this month, less head-lease rent "
                  "for the same month, as a percentage of what you charged. "
                  "Gross: before maintenance and utilities — the P&L "
                  "waterfall carries the spread after recorded costs."),
        "why": ("You never buy property — you head-lease it and sub-let it, "
                "so this gap is the entire business. It compresses slowly and "
                "quietly, usually through renewals at higher rent, and is "
                "easy to miss until a year has gone."),
        "act": act, "go": "#/reports",
    }


def _collection(s):
    """Is billed money actually arriving?"""
    rate = _collection_rate()
    if rate is None:
        return {"id": "collection", "label": "Collection rate",
                "value": "—", "band": "grey",
                "sub": "Nothing billed in the last 90 days.",
                "means": "What you billed against what actually arrived.",
                "why": ("Spread is theoretical until the money lands."),
                "act": "", "go": "#/arrears"}

    band = _band(rate, flt(s.wall_collection_green or 95),
                 flt(s.wall_collection_red or 85))
    arrears = sum(_arrears_by_tenant().values())
    act = {
        "red": (f"{_kfmt(arrears)} is outstanding. Collection has broken down "
                "rather than slipped — work the arrears list by size."),
        "amber": (f"{_kfmt(arrears)} outstanding. Worth a pass through the "
                  "oldest cases before it hardens."),
        "green": "",
    }.get(band, "")

    return {
        "id": "collection", "label": "Collection rate · rolling 90d",
        # One decimal, deliberately: the runway footnote quotes the same
        # rate at one decimal, and 91.6% shown here as 92% reads as a
        # second, disagreeing number on the same screen.
        "value": f"{rate:.1f}%", "band": band,
        "sub": f"{_kfmt(arrears)} outstanding · rolling 90 days",
        "means": ("Of everything invoiced in the last 90 days, the share that "
                  "has actually been received."),
        "why": ("A healthy spread on paper means nothing if the money does "
                "not arrive. Most of your rent comes in by cheque, and a "
                "cheque is a promise until it clears. This is the number that "
                "separates a profitable business from a failing one with good "
                "invoices."),
        "act": act, "go": "#/arrears",
    }


def _losers(s):
    """Which buildings are eating the profit the others make?"""
    hl = {}
    # Active *and* Expiring. Filtering to Active alone dropped any building
    # whose head lease was close to renewal, which is exactly the building
    # this tile exists to surface. It also disagreed with the portfolio
    # table, which has always counted both.
    for h in frappe.get_all("Head Lease",
                            filters={"status": ["in", ("Active", "Expiring")]},
                            fields=["building", "monthly_rent"]):
        hl[h.building] = hl.get(h.building, 0) + flt(h.monthly_rent)
    if not hl:
        return None

    rent_by_b, _ = _tenancy_rollup()
    bnames = _building_names(list(hl.keys()))

    negative, worst, total_loss, total_spread = [], None, 0, 0
    for b, cost in hl.items():
        spread = flt(rent_by_b.get(b, 0)) - cost
        total_spread += spread
        if spread < 0:
            total_loss += -spread
            negative.append((bnames.get(b, b), spread))
            if worst is None or spread < worst[1]:
                worst = (bnames.get(b, b), spread)

    count = len(negative)
    share = (total_loss / total_spread * 100) if total_spread > 0 else 0
    red_at = int(s.wall_loss_red or 3)
    amber_at = int(s.wall_loss_amber or 1)
    share_red = flt(s.wall_loss_share_red or 5)

    if count >= red_at or (count and share >= share_red):
        band = "red"
    elif count >= amber_at:
        band = "amber"
    else:
        band = "green"

    if count:
        sub = (f"{worst[0]} worst at {_kfmt(worst[1])}/month · "
               f"{_kfmt(total_loss)} total")
    else:
        sub = f"All {len(hl)} buildings above water"

    act = {
        "red": (f"{_kfmt(total_loss)} a month is being lost. Start with "
                f"{worst[0]}: either occupancy comes up, the head-lease rent "
                "comes down at renewal, or you exit."),
        "amber": (f"{worst[0]} is running at a loss. Check its occupancy and "
                  "when its head lease is next up."),
        "green": "",
    }.get(band, "")

    return {
        "id": "losers", "label": "Buildings losing money",
        "value": str(count), "band": band, "sub": sub,
        "means": ("Buildings where the rent you collect from tenants is less "
                  "than the rent you pay the landlord."),
        "why": ("The portfolio average hides the loser. A building at low "
                "occupancy still owes its landlord in full, so it quietly "
                "eats the profit the good buildings make. A negative building "
                "does not recover on its own — something has to change."),
        "act": act, "go": "#/portfolio",
    }


def _collection_rate():
    start = add_days(today(), -90)
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "posting_date": [">=", start]},
        fields=["grand_total", "outstanding_amount"])
    billed = sum(flt(r.grand_total) for r in rows)
    if not billed:
        return None
    outstanding = sum(flt(r.outstanding_amount) for r in rows)
    return (billed - outstanding) / billed * 100


def _kfmt(v):
    """Full number with thousands separators. No K or M abbreviation."""
    return "QAR {:,.0f}".format(flt(v))
