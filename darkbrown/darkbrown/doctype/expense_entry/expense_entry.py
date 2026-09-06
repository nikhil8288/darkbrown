"""One expense, and the journal it writes.

The record exists rather than the screen posting a Journal Entry straight off,
because a journal is a pair of account codes and cannot answer the questions
asked about a cost later: which building, whose bill, where the receipt is,
who keyed it. Those live here and the journal carries the money.

The basis is never typed. It is read off the expense head, which is where the
decision was made once, in `utils.chart_of_accounts`. Someone keying a salary
cannot accidentally pin it to one building, and someone keying a lift repair
cannot accidentally leave it unattributed.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from darkbrown.utils.chart_of_accounts import (BUILDING, COMMON, basis_of,
                                               ensure_overhead_cost_center)


class ExpenseEntry(Document):

    # ------------------------------------------------------------- validation

    def validate(self):
        self.company = self.company or _company()
        self.basis = basis_of(self.expense_head)

        if not self.basis:
            frappe.throw(_(
                "{0} is not one of the expense heads this app knows about, so "
                "there is no way to tell whether it belongs to a building or "
                "to the company. Pick a head from the chart, or add it to "
                "utils.chart_of_accounts first."
            ).format(self.expense_head))

        root = frappe.db.get_value("Account", self.expense_head, "root_type")
        if root != "Expense":
            frappe.throw(_("{0} is not an expense account.")
                         .format(self.expense_head))

        if flt(self.amount) <= 0:
            frappe.throw(_("An expense needs an amount, and it is always "
                           "positive."))

        if self.basis == BUILDING and not self.building:
            frappe.throw(_(
                "{0} is a building cost, so it needs the building it belongs "
                "to.").format(self.expense_head))

        if self.basis == COMMON and self.building:
            # Not an error worth stopping for, but the building would be a lie
            # on the record: the posting does not go there.
            self.building = None

        if self.payment_mode == "Unpaid":
            if not self.supplier:
                frappe.throw(_("An unpaid expense needs the supplier it is "
                               "owed to."))
            self.paid_from = None
        else:
            if not self.paid_from:
                frappe.throw(_("Say which account the money came out of."))
            acc_type = frappe.db.get_value("Account", self.paid_from,
                                           "account_type")
            if acc_type not in ("Bank", "Cash"):
                frappe.throw(_("{0} is not a bank or cash account.")
                             .format(self.paid_from))
            self.supplier = None

        self.cost_center = self._cost_center()

    def _cost_center(self):
        if self.basis == BUILDING:
            cc = frappe.db.get_value("Building", self.building, "cost_center")
            if not cc:
                frappe.throw(_(
                    "{0} has no cost centre, so a cost posted against it would "
                    "not reach its P&L. That is a building setup problem, not "
                    "an expense one.").format(self.building))
            return cc
        cc = ensure_overhead_cost_center(self.company)
        if not cc:
            frappe.throw(_("There is no Overhead cost centre on {0} and one "
                           "could not be created.").format(self.company))
        return cc

    # ---------------------------------------------------------------- posting

    def on_submit(self):
        self.db_set("journal_entry", self._post().name)

    def on_cancel(self):
        if not self.journal_entry:
            return
        je = frappe.get_doc("Journal Entry", self.journal_entry)
        if je.docstatus == 1:
            je.flags.ignore_permissions = True
            je.cancel()

    def _post(self):
        credit_account, party_type, party = self._credit_side()
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": self.company,
            "posting_date": getdate(self.expense_date),
            "user_remark": self._narration(),
            "accounts": [
                {"account": self.expense_head,
                 "debit_in_account_currency": flt(self.amount),
                 "cost_center": self.cost_center},
                {"account": credit_account,
                 "credit_in_account_currency": flt(self.amount),
                 "cost_center": self.cost_center,
                 "party_type": party_type,
                 "party": party},
            ],
        })
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        return je

    def _credit_side(self):
        if self.payment_mode == "Unpaid":
            acc = frappe.db.get_value(
                "Party Account", {"parent": self.supplier,
                                  "company": self.company}, "account")
            if not acc:
                acc = frappe.db.get_value(
                    "Account", {"company": self.company, "is_group": 0,
                                "account_type": "Payable"}, "name")
            if not acc:
                frappe.throw(_("No payable account on {0} to credit.")
                             .format(self.company))
            return acc, "Supplier", self.supplier
        return self.paid_from, None, None

    def _narration(self):
        bits = [self.description or self.expense_head]
        if self.building:
            bits.append(str(self.building))
        if self.reference:
            bits.append("ref " + str(self.reference))
        bits.append(self.name)
        return " \u00b7 ".join(bits)


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or (frappe.get_all("Company", limit=1) or [{}])[0].get("name"))
