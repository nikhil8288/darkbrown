import frappe
from frappe import _
from frappe.model.document import Document


class AgreementAmendment(Document):
	def validate(self):
		if not (self.reason or "").strip():
			frappe.throw(_("An amendment needs a reason."))
		if not self.requested_by:
			self.requested_by = frappe.session.user
			self.requested_on = frappe.utils.now()
		self._route()

	def _route(self):
		"""The GM approves by default. Above the configured threshold it is the
		MD instead."""
		if self.status not in ("Draft", "Pending GM", "Pending MD"):
			return
		threshold = frappe.db.get_single_value(
			"DBR Settings", "amendment_md_threshold") or 0
		if threshold and abs(self.value_impact or 0) >= threshold:
			self.status = "Pending MD"
		else:
			self.status = "Pending GM"
