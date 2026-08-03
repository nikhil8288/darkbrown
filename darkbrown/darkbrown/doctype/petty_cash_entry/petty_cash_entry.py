import frappe
from frappe.model.document import Document
from frappe.utils import flt


class PettyCashEntry(Document):
    """One movement of the petty cash float.

    The float is a real box of cash with a real balance, which is why this
    records movements rather than expenses. An expense log tells you what was
    spent; it cannot tell you whether the money that is supposed to be there
    still is. Three movements cover it — cash in, cash out, and the correction
    when a physical count disagrees with the book.

    Adjustments carry a mandatory reason. A count that does not agree is a fact
    about the cash and possibly about a person, and silently writing the book
    down to match the box would destroy the only evidence that anything
    happened.

    Top-ups name the account they came from. Given how much anonymous cash
    moves through these statements, an ATM withdrawal that funds the float and
    says so is one less line heading for suspense.
    """

    def validate(self):
        if flt(self.amount) <= 0:
            frappe.throw("An amount is needed, and it is always positive — "
                         "the movement decides which way the cash went.")
        if self.direction != "Expense":
            self.category = None
        if self.direction != "Top-up":
            self.funded_from = None
        if self.direction != "Adjustment":
            self.reason = None
            self.adjustment_effect = None
        elif not self.adjustment_effect:
            # A correction with no direction is not a correction. Defaulting
            # to Increase would quietly paper over a shortfall, so it does not.
            frappe.throw("An adjustment has to say whether the count moved "
                         "the book up or down.")
