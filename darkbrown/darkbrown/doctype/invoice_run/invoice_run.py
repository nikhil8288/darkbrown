import frappe
from frappe import _
from frappe.model.document import Document


class InvoiceRun(Document):
	def validate(self):
		value = lambda row, key: (row.get(key) if hasattr(row, "get") else getattr(row, key))
		self.total_amount = sum((value(l, "invoice_amount") or 0) for l in self.lines)
		self.has_variance = 1 if any(
			abs((value(l, "invoice_amount") or 0) - (value(l, "agreement_amount") or 0)) > 0.005
			for l in self.lines) else 0
		if not self.generated_by:
			self.generated_by = frappe.session.user
			self.generated_on = frappe.utils.now()
		for line in self.lines:
			variance = (value(line, "invoice_amount") or 0) - (value(line, "agreement_amount") or 0)
			if hasattr(line, "get"):
				line["variance"] = variance
			else:
				line.variance = variance
			if abs(variance) > 0.005 and not (value(line, "reason") or "").strip():
				frappe.throw(_("Row {0}: {1} differs from the agreement. "
				                "Type a reason.").format(
					value(line, "idx") or "", value(line, "unit")))
		if self.has_variance and self.status == "Draft":
			self.status = "Pending GM"

	def before_insert(self):
		clash = frappe.db.exists("Invoice Run", {
			"building": self.building, "period_start": self.period_start,
			"status": ["!=", "Cancelled"]})
		if clash:
			frappe.throw(_("{0} has already been generated for this period as {1}.")
			             .format(self.building, clash))
