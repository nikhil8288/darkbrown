"""One queue, one decision endpoint.

The approvals screen shows four different kinds of thing waiting on a human.
Rather than teach the front end which endpoint each kind needs, it sends the
decision here and this module dispatches it. The screen stays simple and the
routing rules live in one readable place.

Reserved decisions cannot be delegated. Where a category is reserved for the
Managing Director, no amount of role stacking gets around it — the check is
here, on the server, not in the interface that happens to be showing.
"""

import frappe
from frappe import _
from darkbrown.guards import guard, GM, MD
from frappe.utils import flt, today

RESERVED = {"Deposit release", "Emergency maint."}

#: The record each queue category actually lives on. The queue shows a
#: category and an id; the decision has to be written against the doctype that
#: holds it, and so does the note.
KIND_DOCTYPE = {
    "Amendment": "Agreement Amendment",
    "Tenancy activation": "Tenancy Agreement",
    "Emergency maint.": "Maintenance Request",
    "Deposit release": "Security Deposit",
    "Invoice run": "Invoice Run",
}


def _is_md():
    return bool({"Managing Director", "System Manager"} & set(frappe.get_roles()))


def _is_gm():
    return bool({"General Manager", "Managing Director", "System Manager"}
                & set(frappe.get_roles()))


@frappe.whitelist()
def decide(kind, reference, decision, note=None):
    """Approve or reject whatever is waiting.

    `kind` is the category the queue displayed; `reference` is the record it
    came from. Both are checked against the record itself rather than trusted,
    so a forged category cannot route a decision to a softer check.

    The per-category checks below are the real rule. This first line only makes
    sure someone with no standing at all is refused before the endpoint starts
    telling them what the queue contains.
    """
    guard(MD, GM)
    if decision not in ("approve", "reject"):
        frappe.throw(_("A decision is either an approval or a rejection."))
    if decision == "reject" and not note:
        frappe.throw(_("A rejection needs a reason."))

    handler = {
        "Amendment": _amendment,
        "Tenancy activation": _tenancy,
        "Emergency maint.": _maintenance,
        "Deposit release": _deposit,
        "Invoice run": _invoice_run,
    }.get(kind)

    if not handler:
        frappe.throw(_("{0} is not something this queue can decide.").format(kind))

    if kind in RESERVED and not _is_md():
        frappe.throw(
            _("{0} is reserved for the Managing Director.").format(kind),
            frappe.PermissionError)
    if kind not in RESERVED and not _is_gm():
        frappe.throw(
            _("Approvals are for the General Manager or above."),
            frappe.PermissionError)

    result = handler(reference, decision, note)

    # The form calls this note "permanent in the audit trail" and makes it
    # mandatory. It was not permanent: only three of the five handlers kept it,
    # and only on rejection - an approved amendment, deposit release or invoice
    # run discarded the reason entirely. Recording it here rather than in each
    # handler means every category keeps it, and keeps it the same way.
    from darkbrown.api import notes
    if note:
        notes.record(
            KIND_DOCTYPE[kind], reference,
            "{0}: {1}".format(
                "Approved" if decision == "approve" else "Rejected", note))

    if isinstance(result, dict):
        result.setdefault("doctype", KIND_DOCTYPE[kind])
        result.setdefault("kind", kind)
    return result


def _amendment(reference, decision, note):
    from darkbrown.api.agreements import decide_amendment
    return decide_amendment(reference, decision, note)


def _tenancy(reference, decision, note):
    """Approving stands in for the paperwork that was missing.

    Approval runs the same activation the self-approved route runs, so a
    tenancy that arrived here ends up in exactly the state one that never
    needed an approver would. Rejection leaves it Draft rather than deleting
    it — the tenant and the terms were real, only the pack was not.
    """
    from darkbrown.api.agreements import activate
    doc = frappe.get_doc("Tenancy Agreement", reference)
    if doc.status != "Pending Approval":
        frappe.throw(_("{0} is already {1}.").format(reference, doc.status))

    if decision == "reject":
        doc.status = "Draft"
        doc.notes = (doc.notes or "") + f"\n\nApproval refused: {note}"
        doc.save(ignore_permissions=True)
        return {"reference": doc.name, "status": doc.status}

    return activate(reference, note)


def _maintenance(reference, decision, note):
    doc = frappe.get_doc("Maintenance Request", reference)
    if not doc.over_ceiling:
        frappe.throw(_("{0} is not above the ceiling.").format(reference))
    if decision == "approve":
        doc.status = "Assigned" if doc.status == "Open" else doc.status
        doc.over_ceiling = 0
        doc.resolution_notes = ((doc.resolution_notes or "")
                                + f"\n\nCeiling approved by "
                                  f"{frappe.session.user}"
                                + (f": {note}" if note else ""))
    else:
        doc.status = "Cancelled"
        doc.resolution_notes = ((doc.resolution_notes or "")
                                + f"\n\nRejected: {note}")
    doc.save(ignore_permissions=True)
    return {"reference": doc.name, "status": doc.status}


def _deposit(reference, decision, note):
    """Releasing a deposit pays real money out, which is why it is reserved."""
    doc = frappe.get_doc("Security Deposit", reference)
    if doc.status != "Held":
        frappe.throw(_("{0} is already {1}.").format(reference, doc.status))

    if decision == "reject":
        doc.deduction_reason = ((doc.deduction_reason or "")
                                + f"\n\nRelease refused: {note}")
        doc.save(ignore_permissions=True)
        return {"reference": doc.name, "status": doc.status}

    refund = flt(doc.amount) - flt(doc.deductions)
    doc.refund_amount = refund
    doc.refunded_on = today()
    doc.status = ("Refunded" if refund >= flt(doc.amount)
                  else "Partially Refunded" if refund > 0 else "Forfeited")
    doc.save(ignore_permissions=True)

    if doc.move_out_case:
        mo = frappe.get_doc("Move Out Case", doc.move_out_case)
        if mo.status == "Refund Pending":
            mo.status = "Closed"
            mo.save(ignore_permissions=True)

    return {"reference": doc.name, "status": doc.status,
            "refund": round(refund)}


def _invoice_run(reference, decision, note):
    from darkbrown.api.finance import issue_invoice_run
    if decision == "approve":
        return issue_invoice_run(reference)
    doc = frappe.get_doc("Invoice Run", reference)
    doc.status = "Cancelled"
    doc.variance_reason = ((doc.variance_reason or "") + f"\n\nRejected: {note}")
    doc.save(ignore_permissions=True)
    return {"reference": doc.name, "status": doc.status}
