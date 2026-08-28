import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

#: A tenant is in the flat under either of these. Same set as api.agreements,
#: api.command, api.finance and api.attention.
LIVE_TENANCY = ("Active", "Expiring")


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
		self._sync_unit_occupancy()

	def _sync_unit_occupancy(self):
		"""A unit is Occupied while ANY live tenancy covers it.

		This read only the agreement being saved:

		    "Occupied" if self.status == "Active" else "Vacant"

		which is wrong three ways, and all three bite during a bulk import.

		"Expiring" is a live tenancy everywhere else in this app - the tenant
		is in the flat and the rent is still invoiced - but it fell to the else
		branch, so saving an agreement inside its notice window marked an
		occupied unit Vacant.

		Saving a historical Expired agreement for a unit that has a CURRENT
		tenancy did the same. Importing a tenancy book with any history in it
		would therefore have emptied the portfolio one row at a time.

		And it overwrote Not Ready and Under Maintenance, which are the
		operations team's to set and have nothing to do with tenancy.
		"""
		if not self.unit:
			return
		current = frappe.db.get_value("Unit", self.unit, "status")
		if current in ("Not Ready", "Under Maintenance"):
			return
		occupied = (self.status in LIVE_TENANCY) or bool(frappe.db.exists(
			"Tenancy Agreement",
			{"unit": self.unit, "status": ["in", LIVE_TENANCY],
			 "name": ["!=", self.name]}))
		if occupied:
			want = "Occupied"
		elif current == "Reserved":
			return          # somebody is holding it; not ours to release
		else:
			want = "Vacant"
		if current != want:
			frappe.db.set_value("Unit", self.unit, "status", want,
			                    update_modified=False)
