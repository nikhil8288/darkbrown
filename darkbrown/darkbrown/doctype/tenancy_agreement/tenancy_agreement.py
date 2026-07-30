import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class TenancyAgreement(Document):
	def validate(self):
		if self.end_date and self.start_date and \
				getdate(self.end_date) <= getdate(self.start_date):
			frappe.throw(_("End date must fall after the start date."))
		self._set_activation_route()

	def _set_activation_route(self):
		"""D78 / D79. Both present means the tenancy stands on its own; the GM and
		MD are told, not asked. Either missing means it is created but routes, and
		the approval item has to say what is missing."""
		missing = []
		if not (self.qid_number or "").strip():
			missing.append(_("QID number"))
		if not self.signed_pack:
			missing.append(_("signed agreement pack"))
		self.missing_items = ", ".join(missing)
		if self.status in ("Expired", "Terminated"):
			return
		if missing:
			self.activation_route = "Routed for Approval"
			if self.status == "Draft":
				self.status = "Pending Approval"
		else:
			self.activation_route = "Self Approved"
			if self.status in ("Draft", "Pending Approval"):
				self.status = "Active"

	def on_update(self):
		frappe.db.set_value("Unit", self.unit, "status",
		                    "Occupied" if self.status == "Active" else "Vacant",
		                    update_modified=False)
