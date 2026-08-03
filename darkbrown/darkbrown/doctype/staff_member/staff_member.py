import frappe
from frappe.model.document import Document
from frappe.utils import flt


class StaffMember(Document):
    """A person on DarkBrown's own payroll, held for one reason in this
    version: the money. Staff cost is a real monthly operating expense and
    until now it was nowhere in the system, so every cost base, every bridge
    and every week of the cash runway read better than the business actually
    was.

    Pay is stored as basic plus allowances rather than one figure. Nothing in
    this version needs the split — the deeper version does. End-of-service
    gratuity is computed on basic alone, and the WPS file wants the components
    separately, so recording a single number now would mean going back to
    every record later (D75).

    Not here, deliberately: leave, attendance, documents and their expiry,
    payroll runs, the WPS file, gratuity accrual. Those are the deeper version.
    """

    def validate(self):
        self.monthly_cost = flt(self.basic_salary) + flt(self.allowances)
        if self.status == "Active":
            self.left_on = None
        if self.left_on and self.joined_on and self.left_on < self.joined_on:
            frappe.throw("The leaving date cannot be before the joining date.")
