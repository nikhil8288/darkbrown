import frappe
from frappe import _
from frappe.model.document import Document


class InvoiceRun(Document):
	def validate(self):
		self.total_amount = sum((l.invoice_amount or 0) for l in self.lines)
		self.has_variance = 1 if any(
			abs((l.invoice_amount or 0) - (l.agreement_amount or 0)) > 0.005
			for l in self.lines) else 0
		if not self.generated_by:
			self.generated_by = frappe.session.user
			self.generated_on = frappe.utils.now()
		for line in self.lines:
			line.variance = (line.invoice_amount or 0) - (line.agreement_amount or 0)
			if abs(line.variance) > 0.005 and not (line.reason or "").strip():
				frappe.throw(_("Row {0}: {1} differs from the agreement. "
				                "Type a reason.").format(line.idx, line.unit))
		if self.has_variance and self.status == "Draft":
			self.status = "Pending GM"

	def before_insert(self):
		clash = frappe.db.exists("Invoice Run", {
			"building": self.building, "period_start": self.period_start,
			"status": ["!=", "Cancelled"]})
		if clash:
			frappe.throw(_("{0} has already been generated for this period as {1}.")
			             .format(self.building, clash))
