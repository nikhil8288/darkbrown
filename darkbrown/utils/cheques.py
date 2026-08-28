"""Cheque lifecycle and the nightly expiry sweeps.

One register carries money in and money out. A return is a first-class event
rather than a status flag: it books the bank charge, reopens the exposure and
leaves a trail on the tenancy it came from.
"""

import frappe
from frappe.utils import today, getdate, add_days, flt
from darkbrown.guards import guard, ACC, MD


# ------------------------------------------------------------------ cheques

# ------------------------------------------------------------------ cheques
#
# clear_cheque / return_cheque / replace_cheque used to be implemented here as
# well as in api.finance. This copy was the quiet danger of the two: it flipped
# the status, returned a name, and booked NO accounting at all, so a clearing
# routed through it succeeded while the ledger never moved. api.finance is the
# single engine; these remain as delegating shims so existing callers keep
# working.

@frappe.whitelist()
def clear_cheque(cheque, cleared_on=None, payment_entry=None):
    from darkbrown.api import finance
    return finance.clear_cheque(cheque, on=cleared_on)["cheque"]


@frappe.whitelist()
def return_cheque(cheque, reason, charge=0, returned_on=None):
    from darkbrown.api import finance
    return finance.return_cheque(cheque, reason=reason, charge=charge,
                                 on=returned_on)["cheque"]


@frappe.whitelist()
def replace_cheque(cheque, cheque_no, cheque_date, amount=None, bank=None):
    from darkbrown.api import finance
    payload = {"cheque_no": cheque_no, "cheque_date": cheque_date}
    if amount:
        payload["amount"] = flt(amount)
    if bank:
        payload["bank"] = bank
    return finance.replace_cheque(cheque, frappe.as_json(payload))["cheque"]


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
    """Documents inside their warning window raise a notification once.

    "Once" was the intent and not the behaviour: there was no guard, so every
    nightly run re-notified every in-window document to every Documentation
    user, for as long as the document stayed unrenewed. Across a portfolio this
    size that is a nightly identical alert, which trains people to ignore the
    channel. A document is now announced once per entry into the window, keyed
    on the document and its expiry date, so a renewal (new expiry date) does
    announce again and a stale one does not.
    """
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
            if _already_announced(doc.name, doc.expiry_date):
                continue
            flagged.append(doc)
    if flagged:
        _notify("Documentation",
                f"{len(flagged)} documents are expiring or expired",
                ", ".join(f"{d.document_type} ({d.party or d.name})"
                          for d in flagged[:20]))
        for d in flagged:
            _mark_announced(d.name, d.expiry_date)
    return len(flagged)


def _announce_key(docname, expiry):
    return "db_docexp:%s:%s" % (docname, expiry)


def _already_announced(docname, expiry):
    return bool(frappe.cache().get_value(_announce_key(docname, expiry)))


def _mark_announced(docname, expiry):
    """Held for a year: long enough that a document inside its window is
    announced once, short enough that the key expires with the document."""
    frappe.cache().set_value(_announce_key(docname, expiry), 1,
                             expires_in_sec=365 * 24 * 3600)


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
