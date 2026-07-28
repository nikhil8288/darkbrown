import frappe
from frappe import _
from frappe.model.document import Document


class CollectionCase(Document):
	def validate(self):
		if not self.opened_on:
			self.opened_on = frappe.utils.today()
		if self.trigger == "Manual" and not (self.manual_reason or "").strip():
			frappe.throw(_("A case opened by hand needs a reason."))
		if self.oldest_due_date:
			self.days_past_due = frappe.utils.date_diff(
				frappe.utils.today(), self.oldest_due_date)
		if (self.promised_date and self.status == "Promised"
				and frappe.utils.getdate(self.promised_date) < frappe.utils.getdate()):
			self.broken_promise = 1
			self.status = "Broken Promise"
		self._check_legal_threshold()

	def _check_legal_threshold(self):
		months = frappe.db.get_single_value(
			"DBR Settings", "legal_escalation_months") or 2
		rent = frappe.db.get_value("Tenancy Agreement", self.tenancy_agreement,
		                           "monthly_rent") or 0
		if rent and (self.outstanding_amount or 0) >= rent * months:
			if self.status in ("Open", "Contacted", "Promised", "Broken Promise"):
				frappe.msgprint(
					_("Outstanding has reached {0} months of rent. This case is due "
					  "for legal escalation.").format(months),
					indicator="red", alert=True)
