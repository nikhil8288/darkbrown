import frappe
from frappe import _
from frappe.model.document import Document


class MoveOutCase(Document):
	def validate(self):
		self._notice_check()
		self._settle()

	def _notice_check(self):
		if self.notice_received_on and self.planned_move_out:
			given = frappe.utils.date_diff(self.planned_move_out,
			                               self.notice_received_on)
			self.short_notice = 1 if given < (self.notice_days or 0) else 0

	def _settle(self):
		if self.security_deposit:
			self.deposit_held = frappe.db.get_value(
				"Security Deposit", self.security_deposit, "amount") or 0
		deductions = ((self.outstanding_rent or 0) + (self.utilities_due or 0)
		              + (self.damages_charged or 0))
		self.refund_amount = (self.deposit_held or 0) - deductions

	def on_update(self):
		if self.status == "Closed":
			frappe.db.set_value("Tenancy Agreement", self.tenancy_agreement,
			                    "status", "Terminated", update_modified=False)
			frappe.db.set_value("Unit", self.unit, "status", "Not Ready",
			                    update_modified=False)
