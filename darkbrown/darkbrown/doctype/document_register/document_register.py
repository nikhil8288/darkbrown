import frappe
from frappe import _
from frappe.model.document import Document


class DocumentRegister(Document):
	def validate(self):
		if self.expiry_date:
			self.days_to_expiry = frappe.utils.date_diff(
				self.expiry_date, frappe.utils.today())
		if self.status == "Confirmed" and not self.reviewed_by:
			self.reviewed_by = frappe.session.user
			self.reviewed_on = frappe.utils.now()
		if self.status == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw(_("Say why the document was rejected."))
