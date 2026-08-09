"""Cheque lifecycle and the nightly expiry sweeps.

One register carries money in and money out. A return is a first-class event
rather than a status flag: it books the bank charge, reopens the exposure and
leaves a trail on the tenancy it came from.
"""

import frappe
from frappe.utils import today, getdate, add_days, flt
from darkbrown.guards import guard, ACC, MD


# ------------------------------------------------------------------ cheques

@frappe.whitelist()
def clear_cheque(cheque, cleared_on=None, payment_entry=None):
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", cheque)
    if doc.status in ("Cleared", "Cancelled"):
        frappe.throw(f"Cheque {doc.cheque_no} is already {doc.status.lower()}.")
    doc.status = "Cleared"
    doc.cleared_on = cleared_on or today()
    if payment_entry:
        doc.payment_entry = payment_entry
    doc.save()
    if doc.head_lease:
        _mark_headlease_payment(doc, "Cleared")
    return doc.name


@frappe.whitelist()
def return_cheque(cheque, reason, charge=0, returned_on=None):
    """A return is an event. It records the reason and the charge, tells the
    collections side, and leaves the cheque available for replacement."""
    guard(MD, ACC)
    if not reason:
        frappe.throw("A returned cheque needs a reason.")
    doc = frappe.get_doc("Cheque", cheque)
    doc.status = "Returned"
    doc.return_reason = reason
    doc.return_charge = flt(charge)
    doc.returned_on = returned_on or today()
    doc.save()
    if doc.head_lease:
        _mark_headlease_payment(doc, "Returned")
    return doc.name


@frappe.whitelist()
def replace_cheque(cheque, cheque_no, cheque_date, amount=None, bank=None):
    """The replacement is a new record on the register, linked back to what it
    replaces. The old one is not edited into shape."""
    guard(MD, ACC)
    old = frappe.get_doc("Cheque", cheque)
    new = frappe.get_doc({
        "doctype": "Cheque",
        "direction": old.direction,
        "party_type": old.party_type,
        "party": old.party,
        "company": old.company,
        "cheque_no": cheque_no,
        "bank": bank or old.bank,
        "cheque_date": cheque_date,
        "amount": flt(amount) if amount else old.amount,
        "building": old.building,
        "unit": old.unit,
        "tenancy_agreement": old.tenancy_agreement,
        "head_lease": old.head_lease,
        "status": "Received",
    }).insert()
    old.db_set({"status": "Replaced", "replaced_by": new.name})
    return new.name


def _mark_headlease_payment(cheque, status):
    row = frappe.db.get_value("Head Lease Payment",
                              {"cheque": cheque.name}, "name")
    if row:
        frappe.db.set_value("Head Lease Payment", row, "status", status)


def presentation_due():
    """Cheques coming up for presentation within the configured notice."""
    days = frappe.db.get_single_value(
        "DBR Settings", "presentation_notice_days") or 14
    return frappe.get_all(
        "Cheque",
        filters={
            "status": ["in", ("Received", "Deposited")],
            "cheque_date": ["between", [today(), add_days(today(), days)]],
        },
        fields=["name", "direction", "party", "cheque_no", "cheque_date",
                "amount", "building"],
        order_by="cheque_date asc")


# ------------------------------------------------------------------ expiry

def sweep_agreement_expiry():
    """Agreements inside their notice window move to Expiring; past the end
    date they move to Expired. Status is derived, not remembered."""
    moved = 0
    for dt, notice_field, default in (
            ("Tenancy Agreement", "notice_days", 60),
            ("Head Lease", "notice_period_days", 90)):
        for row in frappe.get_all(
                dt, filters={"status": ["in", ("Active", "Expiring")]},
                fields=["name", "end_date", "status", notice_field]):
            if not row.end_date:
                continue
            notice = int(row.get(notice_field) or default)
            end = getdate(row.end_date)
            if end < getdate(today()):
                target = "Expired"
            elif end <= getdate(add_days(today(), notice)):
                target = "Expiring"
            else:
                target = "Active"
            if target != row.status:
                frappe.db.set_value(dt, row.name, "status", target,
                                    update_modified=False)
                moved += 1
    return moved


def sweep_document_expiry():
    """Documents inside their warning window raise a notification once."""
    reqs = {r.document_type: r.notice_days for r in frappe.get_all(
        "Document Requirement", filters={"expiry_tracked": 1},
        fields=["document_type", "notice_days"])}
    default = 30
    flagged = []
    for doc in frappe.get_all(
            "Document Register",
            filters={"status": "Confirmed", "expiry_date": ["is", "set"]},
            fields=["name", "document_type", "expiry_date", "party"]):
        window = int(reqs.get(doc.document_type, default) or default)
        if getdate(doc.expiry_date) <= getdate(add_days(today(), window)):
            flagged.append(doc)
    if flagged:
        _notify("Documentation",
                f"{len(flagged)} documents are expiring or expired",
                ", ".join(f"{d.document_type} ({d.party or d.name})"
                          for d in flagged[:20]))
    return len(flagged)


def sweep_cheque_presentation():
    due = presentation_due()
    if due:
        _notify("Accounts",
                f"{len(due)} cheques due for presentation",
                ", ".join(f"{c.cheque_no} {c.cheque_date}" for c in due[:20]))
    return len(due)


def _notify(role, subject, body):
    users = [r.parent for r in frappe.get_all(
        "Has Role", filters={"role": role}, fields=["parent"])
        if "@" in (r.parent or "")]
    for user in users:
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "type": "Alert",
            "subject": subject,
            "email_content": body,
        }).insert(ignore_permissions=True)


def nightly():
    sweep_agreement_expiry()
    sweep_document_expiry()
    sweep_cheque_presentation()
    frappe.db.commit()
