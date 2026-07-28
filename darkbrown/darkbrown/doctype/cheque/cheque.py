import frappe
from frappe import _
from frappe.model.document import Document


class Cheque(Document):
	def validate(self):
		if (self.amount or 0) <= 0:
			frappe.throw(_("A cheque needs an amount."))
		dup = frappe.db.exists("Cheque", {
			"cheque_no": self.cheque_no, "party": self.party,
			"name": ["!=", self.name or ""]})
		if dup:
			frappe.msgprint(
				_("Cheque {0} is already on the register for this party as {1}.")
				.format(self.cheque_no, dup), indicator="orange", alert=True)

	def on_update(self):
		"""A return is an event, not a status flag: it opens a collection case
		on the tenancy it belonged to."""
		if self.has_value_changed("status") and self.status == "Returned":
			if self.direction == "Incoming" and self.tenancy_agreement:
				from darkbrown.utils.collections_case import open_case
				open_case(self.tenancy_agreement, trigger="Returned Cheque",
				          reference=self.name)
