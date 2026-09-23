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

    refund = max(flt(doc.amount) - flt(doc.deductions), 0)
    if doc.refund_journal_entry:
        frappe.throw(_("{0} was already posted in {1}.").format(
            reference, doc.refund_journal_entry))

    company = doc.company
    liability = frappe.db.get_value(
        "Account", {"account_name": "Security Deposits Held",
                    "company": company, "is_group": 0}, "name")
    if not liability:
        frappe.throw(_("Security Deposits Held account is not configured."))

    from darkbrown.api.finance import (
        _cash_account, _paid_to, _settings, _cost_center)
    if doc.receipt_method == "Cash":
        money_account = _cash_account(company)
    else:
        money_account = _paid_to(_settings().default_bank_account, company)
    if refund and not money_account:
        frappe.throw(_("No {0} account is configured for the refund.").format(
            "cash" if doc.receipt_method == "Cash" else "bank"))

    mo = (frappe.get_doc("Move Out Case", doc.move_out_case)
          if doc.move_out_case else None)
    remaining = flt(doc.deductions)
    rent = min(flt(mo.outstanding_rent) if mo else 0, remaining)
    remaining -= rent
    recharge = remaining

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = today()
    je.user_remark = ("Security deposit settlement {0}"
                      + (" for move-out {1}" if mo else "")).format(
                          doc.name, mo.name if mo else "")
    cc = _cost_center(mo.building) if mo and mo.building else None
    je.append("accounts", {"account": liability,
                           "debit_in_account_currency": flt(doc.amount),
                           "cost_center": cc})
    if refund:
        je.append("accounts", {"account": money_account,
                               "credit_in_account_currency": refund,
                               "cost_center": cc})
    if rent:
        from erpnext.accounts.party import get_party_account
        receivable = get_party_account("Customer", doc.tenant, company)
        je.append("accounts", {"account": receivable,
                               "party_type": "Customer", "party": doc.tenant,
                               "credit_in_account_currency": rent,
                               "cost_center": cc})
    if recharge:
        recharge_account = frappe.db.get_value(
            "Account", {"account_name": "Tenant Recharge Income",
                        "company": company, "is_group": 0}, "name")
        if not recharge_account:
            frappe.throw(_("Tenant Recharge Income account is not configured."))
        je.append("accounts", {"account": recharge_account,
                               "credit_in_account_currency": recharge,
                               "cost_center": cc})
    je.flags.ignore_permissions = True
    je.insert()
    je.submit()

    doc.refund_amount = refund
    doc.refunded_on = today()
    doc.refund_journal_entry = je.name
    doc.status = ("Refunded" if refund >= flt(doc.amount)
                  else "Partially Refunded" if refund > 0 else "Forfeited")
    doc.save(ignore_permissions=True)

    if doc.move_out_case:
        mo = frappe.get_doc("Move Out Case", doc.move_out_case)
        if mo.status == "Refund Pending":
            mo.refund_amount = refund
            mo.refund_method = ("Cash" if doc.receipt_method == "Cash"
                                else "Transfer")
            mo.refund_paid_on = today()
            mo.status = "Closed"
            mo.save(ignore_permissions=True)

    return {"reference": doc.name, "status": doc.status,
            "refund": round(refund), "journal_entry": je.name}


@frappe.whitelist()
def reopen_deposit_release(reference, journal_entry, note):
    """Cancel a posted deposit settlement and reopen its full workflow."""
    guard(MD)
    note = (note or "").strip()
    if not note:
        frappe.throw(_("A correction needs an audit reason."))

    doc = frappe.get_doc("Security Deposit", reference)
    if doc.refund_journal_entry != journal_entry:
        frappe.throw(_("{0} is not the refund journal linked to {1}.").format(
            journal_entry, reference))
    if doc.status not in ("Partially Refunded", "Refunded", "Forfeited"):
        frappe.throw(_("{0} is {1}, not a posted release.").format(
            reference, doc.status))

    je = frappe.get_doc("Journal Entry", journal_entry)
    expected = "Security deposit settlement {0}".format(reference)
    if je.docstatus != 1 or expected not in (je.user_remark or ""):
        frappe.throw(_("{0} is not the submitted settlement for {1}.").format(
            journal_entry, reference))

    mo = (frappe.get_doc("Move Out Case", doc.move_out_case)
          if doc.move_out_case else None)
    if not mo or mo.status != "Closed":
        frappe.throw(_("The linked move-out is not in the posted Closed state."))

    je.cancel()

    doc.status = "Held"
    doc.refunded_on = None
    doc.refund_journal_entry = None
    doc.save(ignore_permissions=True)

    mo.status = "Refund Pending"
    mo.refund_paid_on = None
    mo.refund_method = None
    mo.save(ignore_permissions=True)

    if mo.tenancy_agreement:
        frappe.db.set_value("Tenancy Agreement", mo.tenancy_agreement,
                            "status", "Active")
    if mo.unit:
        frappe.db.set_value("Unit", mo.unit, "status", "Occupied")

    doc.add_comment(
        "Comment", "Deposit settlement correction: {0}. Cancelled {1}.".format(
            note, journal_entry))
    return {"reference": doc.name, "status": doc.status,
            "move_out": mo.name, "move_out_status": mo.status,
            "cancelled_journal": journal_entry}


def _invoice_run(reference, decision, note):
    from darkbrown.api.finance import issue_invoice_run
    if decision == "approve":
        return issue_invoice_run(reference)
    doc = frappe.get_doc("Invoice Run", reference)
    doc.status = "Cancelled"
    doc.variance_reason = ((doc.variance_reason or "") + f"\n\nRejected: {note}")
    doc.save(ignore_permissions=True)
    return {"reference": doc.name, "status": doc.status}
