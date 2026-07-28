import frappe
from frappe import _
from frappe.model.document import Document


class DepositBatch(Document):
	def validate(self):
		self.total_amount = sum((l.amount or 0) for l in self.lines)
		if not self.prepared_by:
			self.prepared_by = frappe.session.user
		if (self.deposited_by and self.deposited_by == self.prepared_by
				and not (self.override_reason or "").strip()):
			frappe.throw(_("The same user prepared and deposited this batch. "
			                "Give a reason or hand it to a second person."))

	def on_update(self):
		for line in self.lines:
			if line.cheque:
				frappe.db.set_value("Cheque", line.cheque, {
					"deposit_batch": self.name,
					"status": "Deposited" if self.status == "Deposited" else "Received",
				}, update_modified=False)
