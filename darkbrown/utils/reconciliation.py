"""Reconciliation hooks on Payment Entry.

Roughly three quarters of inflows arrive anonymous — ATM cash deposits and
cheque clearings that carry no payer identity on the statement. Matching on
payer name therefore cannot be the architecture. Identity comes from the
collection slip captured at the point of receipt and carried through the
deposit batch, so a payment is tied back to a tenant through the slip rather
than through anything the bank tells us.
"""

import frappe
from frappe.utils import flt


def on_payment_submit(doc, method=None):
    _settle_cheque(doc)
    _refresh_cases(doc)


def on_payment_cancel(doc, method=None):
    """Unwinding a payment unwinds the clearing, and no further.

    This used to force the cheque to "Deposited" whatever it had been, so a
    cheque that was Received or Presented moved backwards into a state it had
    never occupied. A cheque is only ever pushed back to Presented if it was
    actually presented, otherwise to Deposited if it was deposited, otherwise
    to Received.
    """
    row = frappe.db.get_value("Cheque", {"payment_entry": doc.name},
                              ["name", "presented_on", "deposit_batch"],
                              as_dict=True)
    if not row:
        return
    prior = ("Presented" if row.presented_on
             else "Deposited" if row.deposit_batch
             else "Received")
    frappe.db.set_value("Cheque", row.name, {"status": prior,
                                             "payment_entry": None,
                                             "cleared_on": None})


def _settle_cheque(doc):
    """A payment carrying a cheque reference clears that cheque on the
    register, so the register and the ledger cannot drift apart."""
    ref = (doc.get("reference_no") or "").strip()
    if not ref:
        return
    party = doc.get("party")
    amount = flt(doc.get("paid_amount"))

    # Number and party alone are not an identity. A party can hold the same
    # cheque number in two books, and matching without the amount let a small
    # payment clear a large cheque - exactly the register/ledger drift this
    # module exists to prevent. Match on the amount too, and refuse when more
    # than one candidate fits rather than taking whichever row came back first.
    hits = frappe.get_all(
        "Cheque",
        filters={"cheque_no": ref, "party": party,
                 "status": ["!=", "Cleared"]},
        fields=["name", "amount"])
    fits = [h for h in hits if abs(flt(h.amount) - amount) <= 0.01]
    if len(fits) != 1:
        if hits:
            frappe.log_error(
                message=(f"Payment Entry {doc.name}: reference {ref} for "
                         f"{party} matched {len(hits)} cheque(s), "
                         f"{len(fits)} at the payment amount "
                         f"{amount:,.2f}. Cleared none - clear it by hand."),
                title="darkbrown: ambiguous cheque reference")
        return

    frappe.db.set_value("Cheque", fits[0].name, {
        "status": "Cleared",
        "cleared_on": doc.get("reference_date") or doc.posting_date,
        "payment_entry": doc.name,
    })


def _refresh_cases(doc):
    """Money arriving against a tenant with a live case updates the exposure
    and closes the case where nothing is left outstanding."""
    if doc.get("party_type") != "Customer" or not doc.get("party"):
        return
    from darkbrown.utils.collections_case import LIVE_STATES

    cases = frappe.get_all("Collection Case",
                           filters={"tenant": doc.party,
                                    "status": ["in", LIVE_STATES]},
                           pluck="name")
    for name in cases:
        case = frappe.get_doc("Collection Case", name)
        outstanding = 0
        for row in case.invoices:
            left = flt(frappe.db.get_value(
                "Sales Invoice", row.sales_invoice, "outstanding_amount"))
            outstanding += left
            row.db_set("outstanding", left)
        case.outstanding_amount = outstanding
        if outstanding <= 0.005:
            case.status = "Resolved"
            case.resolution = "Paid in Full"
            case.resolved_on = frappe.utils.today()
        elif case.status in ("Broken Promise", "Promised"):
            case.status = "Contacted"
        case.append("actions", {
            "action_on": frappe.utils.now(),
            "method": "In Person",
            "outcome": "Paid",
            "notes": f"Payment {doc.name} received, "
                     f"{frappe.utils.fmt_money(doc.paid_amount, currency='QAR')}.",
        })
        case.save(ignore_permissions=True)
