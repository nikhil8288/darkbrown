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
				values = {"deposit_batch": self.name}
				# Reconciliation is saved after its cheques are cleared. The old
				# two-way expression treated every status except Deposited as
				# Received, so saving a Reconciled batch silently rolled a cleared
				# cheque back to the start while leaving its Payment Entry in place.
				if self.status == "Draft":
					values["status"] = "Received"
				elif self.status == "Deposited":
					values["status"] = "Deposited"
				elif self.status == "Cancelled":
					values = {"deposit_batch": None, "status": "Received"}
				# Reconciled deliberately changes no cheque status: the explicit
				# posting action owns the transition to Cleared.
				frappe.db.set_value("Cheque", line.cheque, values,
				                    update_modified=False)
