import frappe
from frappe import _
from frappe.model.document import Document


class SecurityDeposit(Document):
	def validate(self):
		self.refund_amount = max((self.amount or 0) - (self.deductions or 0), 0)
		if (self.deductions or 0) > 0 and not (self.deduction_reason or "").strip():
			frappe.throw(_("A deduction needs a reason."))
