# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""Security-deposit banking, and back-compat shims for the old PDC engine.

WHAT CHANGED (A-5)

This module used to carry a second, complete implementation of cheque
clearing - mark_cleared / mark_bounced - alongside api.finance. Two engines
posting the same Payment Entry is how a fix lands in the wrong one, and this
one had drifted badly: it was written against a Cheque schema that does not
exist. It read cheque_number, bank_name, cleared_date, bounce_date,
tenant_rental_agreement and landlord_contract; the doctype has cheque_no,
bank, cleared_on, tenancy_agreement and head_lease. mark_cleared raised
AttributeError before it ever inserted a Payment Entry, and mark_bounced set
status "Bounced", which is not one of the seven Select options.

Because _building_for read two fields that do not exist, it always returned
None, so every clearing would have posted to the company default cost centre
rather than the building - even though Cheque carries a building field.

api.finance is now the single engine. mark_cleared and mark_bounced remain as
thin delegating shims so nothing that already calls them breaks, but they hold
no logic of their own.

WHAT STAYED

bank_security_deposit is the one piece of accounting api.finance did not have,
and its treatment is right: a tenant's security cheque that is actually banked
books Dr Bank / Cr Security Deposits Held. It is a refundable liability and it
must NEVER touch income. It is kept here, repaired against the real schema.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from darkbrown.guards import guard, ACC, MD

SECURITY_LIABILITY_NAME = "Security Deposits Held"

#: Drafts first, as elsewhere. Flip once the team trusts the engine.
JE_AUTO_SUBMIT = False


def is_security_cheque(cheque):
    """Kept as a re-export. The definition now lives with the engine that
    enforces it, so the guard and the test cannot drift apart."""
    from darkbrown.api.finance import is_security_cheque as _impl
    return _impl(cheque)


# ------------------------------------------------------------ security deposits

@frappe.whitelist()
def bank_security_deposit(pdc, deposit_date=None):
    """A security cheque was actually banked: Dr Bank / Cr Security Deposits
    Held. Income is never touched."""
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", pdc)
    if not doc.has_permission("write"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if not is_security_cheque(doc.name):
        frappe.throw(_("This action is only for Security Deposit cheques."))
    if doc.status == "Cleared":
        frappe.throw(_("{0} is already cleared.").format(pdc))

    company = (frappe.get_single("DBR Settings").default_company
               or frappe.db.get_value("Company", {}, "name"))
    liability = frappe.db.get_value(
        "Account",
        {"account_name": SECURITY_LIABILITY_NAME, "company": company,
         "is_group": 0},
        "name")
    if not liability:
        frappe.throw(_("Account '{0}' not found in the Chart of Accounts.")
                     .format(SECURITY_LIABILITY_NAME))

    from darkbrown.api.finance import _paid_to, _settings, _cost_center
    bank = _paid_to(doc.bank_account or _settings().default_bank_account,
                    company)
    if not bank:
        frappe.throw(_("No bank account resolved for this deposit."))

    deposit_date = deposit_date or nowdate()
    cc = _cost_center(doc.building) if doc.building else None

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = deposit_date
    je.user_remark = (f"Security cheque {doc.cheque_no} banked. "
                      f"Cheque {doc.name}. Held as refundable liability.")
    je.append("accounts", {"account": bank,
                           "debit_in_account_currency": flt(doc.amount),
                           "cost_center": cc})
    je.append("accounts", {"account": liability,
                           "credit_in_account_currency": flt(doc.amount),
                           "cost_center": cc})
    je.flags.ignore_permissions = True
    je.insert()
    if JE_AUTO_SUBMIT:
        je.submit()

    doc.db_set("status", "Cleared")
    doc.db_set("cleared_on", deposit_date)
    frappe.db.commit()
    return {
        "journal_entry": je.name,
        "msg": (f"Journal Entry {je.name} created "
                f"({'submitted' if JE_AUTO_SUBMIT else 'DRAFT'}): "
                f"Dr Bank / Cr {SECURITY_LIABILITY_NAME}."),
    }


# ------------------------------------------------------------ back-compat shims

@frappe.whitelist()
def mark_cleared(pdc, clearance_date=None, submit=None):
    """Deprecated. Delegates to api.finance.clear_cheque, which is the only
    implementation. Kept so existing callers and client scripts keep working."""
    from darkbrown.api import finance
    res = finance.clear_cheque(pdc, on=clearance_date)
    pe = res.get("payment_entry")
    return {
        "payment_entry": pe,
        "submitted": bool(pe),
        "msg": (f"Cheque {res['cheque']} cleared"
                + (f"; Payment Entry {pe}." if pe else ".")),
    }


@frappe.whitelist()
def mark_bounced(pdc, bounce_date=None, reason=None):
    """Deprecated. Delegates to api.finance.return_cheque.

    Note the status: the register records a bounce as "Returned". "Bounced" is
    not one of the doctype's Select options and never was, which is why the old
    implementation could not save and why the recovery handoff never fired.
    """
    from darkbrown.api import finance
    # return_reason is a Select. "Bounced" is not one of its options either, so
    # a caller that does not supply a reason gets "Other" rather than a
    # ValidationError from deep inside the shim.
    res = finance.return_cheque(
        pdc, reason=reason or "Other", on=bounce_date)
    return {"msg": (f"Cheque {res['cheque']} recorded as Returned"
                    + (f"; collection case {res['case']}."
                       if res.get("case") else "."))}
