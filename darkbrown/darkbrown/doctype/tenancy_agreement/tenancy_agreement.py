import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

#: A tenant is in the flat under either of these. Same set as api.agreements,
#: api.command, api.finance and api.attention.
LIVE_TENANCY = ("Active", "Expiring")
BLOCKING_TENANCY = ("Pending Approval", "Active", "Expiring")


class TenancyAgreement(Document):
	def validate(self):
		self._validate_links_and_values()
		if self.end_date and self.start_date and \
				getdate(self.end_date) <= getdate(self.start_date):
			frappe.throw(_("End date must fall after the start date."))
		self._validate_transition()
		self._set_activation_route()
		self._validate_no_overlap()

	def _validate_links_and_values(self):
		if not self.unit or not frappe.db.exists("Unit", self.unit):
			frappe.throw(_("Tenancy Agreement must link to a valid Unit."))
		building = frappe.db.get_value("Unit", self.unit, "building")
		if self.building and self.building != building:
			frappe.throw(_("Agreement Building must match the selected Unit."))
		self.building = building
		if not self.tenant or not frappe.db.exists("Customer", self.tenant):
			frappe.throw(_("Tenancy Agreement must link to a valid tenant Customer."))
		if frappe.get_meta("Customer").has_field("db_is_tenant") and not frappe.db.get_value("Customer", self.tenant, "db_is_tenant"):
			frappe.throw(_("The selected Customer is not classified as a DarkBrown tenant."))
		company = frappe.db.get_value("Building", building, "company")
		if self.company and self.company != company:
			frappe.throw(_("Agreement Company must match the Building company."))
		self.company = company
		if frappe.db.get_value("Company", company, "default_currency") != "QAR":
			frappe.throw(_("Launch tenancy agreements support QAR only."))
		for field in ("monthly_rent", "security_deposit", "notice_days", "cheques_held"):
			if (getattr(self, field, 0) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(field.replace("_", " ").title()))
		if self.payment_mode not in ("Cheque", "Cash", "Transfer"):
			frappe.throw(_("Unsupported payment mode."))
		if self.payment_frequency not in ("Monthly", "Quarterly", "Half Yearly", "Annual"):
			frappe.throw(_("Unsupported payment frequency."))

	def _validate_transition(self):
		before = self.get_doc_before_save()
		if not before:
			if self.status not in ("Draft", "Pending Approval"):
				frappe.throw(_("New agreements must start as Draft or Pending Approval."))
			return
		allowed = {
			"Draft": {"Draft", "Pending Approval", "Terminated"},
			"Pending Approval": {"Pending Approval", "Active", "Terminated"},
			"Active": {"Active", "Expiring", "Expired", "Terminated"},
			"Expiring": {"Expiring", "Active", "Expired", "Terminated"},
			"Expired": {"Expired"}, "Terminated": {"Terminated"},
		}
		if self.status not in allowed.get(before.status, set()):
			frappe.throw(_("Invalid agreement status transition from {0} to {1}.").format(before.status, self.status))
		if self.status == "Active" and before.status != "Active":
			roles = set(frappe.get_roles(frappe.session.user))
			if not ({"Managing Director", "General Manager", "System Manager"} & roles) and frappe.session.user != "Administrator":
				frappe.throw(_("Only an approval role may activate an agreement."), frappe.PermissionError)
			if not self.signed_pack or not (self.qid_number or "").strip():
				frappe.throw(_("Activation requires the signed agreement pack and tenant identity reference."))

	def _validate_no_overlap(self):
		if self.status not in BLOCKING_TENANCY or not self.start_date or not self.end_date:
			return
		for row in frappe.get_all("Tenancy Agreement", filters={
				"unit": self.unit, "status": ["in", BLOCKING_TENANCY],
				"name": ["!=", self.get("name")]}, fields=["name", "start_date", "end_date"]):
			if getdate(row.start_date) <= getdate(self.end_date) and getdate(row.end_date) >= getdate(self.start_date):
				frappe.throw(_("Unit already has overlapping active agreement {0}.").format(row.name))

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
		if missing and self.status == "Draft":
			self.activation_route = "Routed for Approval"
			self.status = "Pending Approval"
		elif not missing and self.status in ("Draft", "Pending Approval"):
			self.activation_route = "Routed for Approval"

	def on_update(self):
		self._sync_unit_occupancy()

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Only a Draft agreement can be deleted; preserve agreement history."))

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
