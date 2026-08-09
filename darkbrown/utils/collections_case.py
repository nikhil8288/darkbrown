"""Collection cases open on four system triggers, plus one manual route.

    Past Due            an invoice passes the configured grace period
    Returned Cheque     an incoming cheque comes back
    Broken Promise      a promised date passes without payment
    Two Months Arrears  exposure reaches the legal escalation threshold

A tenancy carries at most one live case. A second trigger on a tenancy that
already has one updates the existing case rather than opening a duplicate,
because two cases against one tenant means two people chasing the same money.
"""

import frappe
from frappe.utils import today, getdate, date_diff, flt
from darkbrown.guards import guard, ACC, GM, MD

LIVE_STATES = ("Open", "Contacted", "Promised", "Broken Promise",
               "Escalated", "Legal")


def _settings():
    return {
        "grace_days": frappe.db.get_single_value("DBR Settings", "grace_days") or 7,
        "legal_months": frappe.db.get_single_value(
            "DBR Settings", "legal_escalation_months") or 2,
    }


def live_case(tenancy):
    return frappe.db.get_value(
        "Collection Case",
        {"tenancy_agreement": tenancy, "status": ["in", LIVE_STATES]},
        "name")


def open_case(tenancy, trigger, reference=None, outstanding=None,
              oldest_due=None):
    """Open a case, or refresh the one already running against this tenancy."""
    if not tenancy:
        return None

    existing = live_case(tenancy)
    if existing:
        doc = frappe.get_doc("Collection Case", existing)
        if outstanding is not None:
            doc.outstanding_amount = flt(outstanding)
        if oldest_due:
            doc.oldest_due_date = oldest_due
        if trigger == "Returned Cheque":
            doc.append("actions", {
                "action_on": frappe.utils.now(),
                "method": "Letter",
                "outcome": "Disputed",
                "notes": f"Cheque {reference} returned.",
                "by_user": frappe.session.user,
            })
        doc.save(ignore_permissions=True)
        return doc.name

    ta = frappe.db.get_value("Tenancy Agreement", tenancy,
                             ["tenant", "unit", "building"], as_dict=True)
    if not ta:
        return None

    doc = frappe.get_doc({
        "doctype": "Collection Case",
        "tenancy_agreement": tenancy,
        "tenant": ta.tenant,
        "trigger": trigger,
        "status": "Open",
        "opened_on": today(),
        "reference": reference,
        "outstanding_amount": flt(outstanding),
        "oldest_due_date": oldest_due,
    }).insert(ignore_permissions=True)
    return doc.name


# ------------------------------------------------------------------ triggers

def sweep_past_due():
    """Trigger 1 and 4. Runs nightly."""
    s = _settings()
    rows = frappe.db.sql("""
        select si.customer, si.name as invoice, si.due_date,
               si.outstanding_amount, si.grand_total
        from `tabSales Invoice` si
        where si.docstatus = 1
          and si.outstanding_amount > 0
          and si.due_date < %(cut)s
    """, {"cut": frappe.utils.add_days(today(), -s["grace_days"])}, as_dict=True)

    by_tenant = {}
    for r in rows:
        by_tenant.setdefault(r.customer, []).append(r)

    opened = 0
    for customer, invs in by_tenant.items():
        tenancy = frappe.db.get_value(
            "Tenancy Agreement",
            {"tenant": customer, "status": ["in", ("Active", "Expiring")]},
            "name")
        if not tenancy:
            continue
        outstanding = sum(flt(i.outstanding_amount) for i in invs)
        oldest = min(getdate(i.due_date) for i in invs)
        rent = flt(frappe.db.get_value("Tenancy Agreement", tenancy,
                                       "monthly_rent"))
        trigger = ("Two Months Arrears"
                   if rent and outstanding >= rent * s["legal_months"]
                   else "Past Due")
        name = open_case(tenancy, trigger, outstanding=outstanding,
                         oldest_due=oldest)
        if name:
            _sync_invoices(name, invs)
            opened += 1
    return opened


def _sync_invoices(case, invoices):
    doc = frappe.get_doc("Collection Case", case)
    held = {r.sales_invoice for r in doc.invoices}
    changed = False
    for inv in invoices:
        if inv.invoice in held:
            continue
        doc.append("invoices", {
            "sales_invoice": inv.invoice,
            "due_date": inv.due_date,
            "amount": flt(inv.grand_total),
            "outstanding": flt(inv.outstanding_amount),
        })
        changed = True
    if changed:
        doc.save(ignore_permissions=True)


def sweep_broken_promises():
    """Trigger 3. A promise that passes its date without payment is broken."""
    cases = frappe.get_all(
        "Collection Case",
        filters={"status": "Promised", "promised_date": ["<", today()]},
        pluck="name")
    for name in cases:
        doc = frappe.get_doc("Collection Case", name)
        doc.broken_promise = 1
        doc.status = "Broken Promise"
        doc.append("actions", {
            "action_on": frappe.utils.now(),
            "method": "Call",
            "outcome": "Refused",
            "notes": "Promised date passed with no payment received.",
        })
        doc.save(ignore_permissions=True)
    return len(cases)


def close_settled_cases():
    """A case whose invoices are all settled closes itself."""
    closed = 0
    for name in frappe.get_all("Collection Case",
                               filters={"status": ["in", LIVE_STATES]},
                               pluck="name"):
        doc = frappe.get_doc("Collection Case", name)
        if not doc.invoices:
            continue
        outstanding = 0
        for row in doc.invoices:
            outstanding += flt(frappe.db.get_value(
                "Sales Invoice", row.sales_invoice, "outstanding_amount"))
        if outstanding <= 0.005:
            doc.status = "Resolved"
            doc.resolution = "Paid in Full"
            doc.resolved_on = today()
            doc.outstanding_amount = 0
            doc.save(ignore_permissions=True)
            closed += 1
    return closed


def nightly():
    sweep_past_due()
    sweep_broken_promises()
    close_settled_cases()
    frappe.db.commit()


@frappe.whitelist()
def open_manual(tenancy_agreement, reason):
    """The fifth route. A person may open a case by hand, with a reason."""
    guard(MD, GM, ACC)
    if not (reason or "").strip():
        frappe.throw("A case opened by hand needs a reason.")
    if live_case(tenancy_agreement):
        frappe.throw("This tenancy already has a live case.")
    ta = frappe.db.get_value("Tenancy Agreement", tenancy_agreement,
                             ["tenant"], as_dict=True)
    doc = frappe.get_doc({
        "doctype": "Collection Case",
        "tenancy_agreement": tenancy_agreement,
        "tenant": ta.tenant,
        "trigger": "Manual",
        "manual_reason": reason,
        "status": "Open",
        "opened_on": today(),
    }).insert()
    return doc.name
