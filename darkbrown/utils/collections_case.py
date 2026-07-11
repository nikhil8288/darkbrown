"""Collection Case automation.

Three moving parts, per the collections spec:

  auto_open_cases        daily   invoice past grace + no open case
                                  -> case auto-opens (Open), Finance to-do
  reopen_broken_promises daily   promised_date passed, still outstanding
                                  -> back to Open, broken_promise flagged
  on_payment_entry_submit hook   payment clears a case's invoices
                                  -> Pending Confirmation (never straight
                                     to Collected; Finance confirms)

Overdue-but-pre-grace = flagged row in the arrears view only. Grace days
come from the building's Active Landlord Contract (grace_period_days).
"""

import frappe
from frappe.utils import getdate, nowdate, flt, cint

OPEN_STATES = ["Open", "Contacted", "Promised", "Pending Confirmation", "Legal"]
FINANCE_ROLE = "Accounts"


def _grace_by_building():
    return {c.building: cint(c.grace_period_days)
            for c in frappe.get_all(
                "Landlord Contract", filters={"status": "Active"},
                fields=["building", "grace_period_days"]) if c.building}


def _finance_users():
    return [u.parent for u in frappe.get_all(
        "Has Role", filters={"role": FINANCE_ROLE, "parenttype": "User"},
        fields=["parent"]) if u.parent not in ("Administrator", "Guest")]


# ------------------------------------------------------------ auto-open

def auto_open_cases():
    """Scheduled daily. One case per tenant-in-arrears, opened when the
    oldest overdue invoice crosses the building's grace period."""
    today = getdate(nowdate())
    grace = _grace_by_building()

    inv = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "outstanding_amount", "due_date"],
    )
    by_cust = {}
    for r in inv:
        by_cust.setdefault(r.customer, []).append(r)

    for tenant, invoices in by_cust.items():
        if frappe.db.exists("Collection Case",
                            {"tenant": tenant, "status": ["in", OPEN_STATES]}):
            continue

        lease = frappe.db.get_value(
            "Tenant Rental Agreement",
            {"tenant": tenant, "status": "Active"},
            ["name", "building", "unit"], as_dict=True) or frappe.db.get_value(
            "Tenant Rental Agreement",
            {"tenant": tenant, "status": "Expired"},
            ["name", "building", "unit"], as_dict=True)

        g = grace.get(lease.building) if lease else None
        if g is None:
            continue  # no grace known -> stays a flagged arrears row

        oldest = min((getdate(i.due_date) for i in invoices if i.due_date),
                     default=None)
        if not oldest or (today - oldest).days <= g:
            continue  # overdue but still within grace

        case = frappe.get_doc({
            "doctype": "Collection Case",
            "tenant": tenant,
            "lease": lease.name if lease else None,
            "building": lease.building if lease else None,
            "unit": lease.unit if lease else None,
            "status": "Open",
            "outstanding_amount": sum(flt(i.outstanding_amount)
                                      for i in invoices),
            "oldest_due_date": oldest,
            "past_grace_on": today,
            "invoices": [{"sales_invoice": i.name,
                          "outstanding_amount": flt(i.outstanding_amount),
                          "due_date": i.due_date} for i in invoices],
        })
        case.insert(ignore_permissions=True)
        _assign_finance(case.name, "Collection case opened — past grace")

    frappe.db.commit()


def _assign_finance(case_name, description):
    users = _finance_users()
    if not users:
        return
    try:
        from frappe.desk.form.assign_to import add
        add({"assign_to": [users[0]], "doctype": "Collection Case",
             "name": case_name, "description": description})
    except Exception:
        frappe.log_error(frappe.get_traceback(),
                         "collections: assign failed %s" % case_name)


# ---------------------------------------------------- broken promises

def reopen_broken_promises():
    """Scheduled daily. Promised date passed and money still outstanding
    -> case reopens flagged 'broken promise'."""
    today = getdate(nowdate())
    for c in frappe.get_all(
            "Collection Case",
            filters={"status": "Promised",
                     "promised_date": ["<", today]},
            fields=["name", "tenant"]):
        still_out = frappe.db.count(
            "Sales Invoice",
            {"docstatus": 1, "customer": c.tenant,
             "outstanding_amount": [">", 0]})
        if not still_out:
            continue
        doc = frappe.get_doc("Collection Case", c.name)
        doc.status = "Open"
        doc.broken_promise = 1
        doc.flags.ignore_permissions = True
        doc.save()
        doc.add_comment("Comment",
                        "Broken promise — promised date passed unpaid. "
                        "Reopened, escalate.")
        _assign_finance(c.name, "Broken promise — escalate")
    frappe.db.commit()


# ------------------------------------------------- payment safeguard

def on_payment_entry_submit(doc, method=None):
    """Payment Entry hook. If it pays down invoices on an open case and the
    tenant's outstanding hits zero, move to Pending Confirmation — Finance
    confirms Collected manually. Partial payment just logs a note."""
    if doc.payment_type != "Receive" or doc.party_type != "Customer":
        return
    case_name = frappe.db.get_value(
        "Collection Case",
        {"tenant": doc.party, "status": ["in",
                                         ["Open", "Contacted", "Promised"]]},
        "name")
    if not case_name:
        return

    remaining = flt(frappe.db.get_value(
        "Sales Invoice",
        {"docstatus": 1, "customer": doc.party,
         "outstanding_amount": [">", 0]},
        "sum(outstanding_amount)") or 0)

    case = frappe.get_doc("Collection Case", case_name)
    if remaining <= 0.005:
        case.status = "Pending Confirmation"
        case.payment_entry = doc.name
        case.flags.ignore_permissions = True
        case.save()
        case.add_comment("Comment",
                         "Payment %s clears all outstanding — pending "
                         "Finance confirmation." % doc.name)
    else:
        case.add_comment("Comment",
                         "Partial payment %s (QAR %.0f). QAR %.0f still "
                         "outstanding." % (doc.name, flt(doc.paid_amount),
                                           remaining))
