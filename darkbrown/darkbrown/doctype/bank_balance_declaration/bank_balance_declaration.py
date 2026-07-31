import frappe
from frappe.model.document import Document


class BankBalanceDeclaration(Document):
    """A cash position someone actually counted and stood behind. The bank
    balance itself is unusable here — the accounts sweep to near zero daily —
    so the runway opens from the latest declaration per account instead, and
    the screen says how old it is."""

    def before_insert(self):
        self.declared_by = frappe.session.user
        self.declared_on = self.declared_on or frappe.utils.now_datetime()
