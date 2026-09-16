import frappe
from frappe import _
from frappe.model.document import Document


class HeadLease(Document):
	def validate(self):
		self._validate_links()
		if self.end_date and self.start_date and self.end_date <= self.start_date:
			frappe.throw(_("End date must fall after the start date."))
		for field in ("annual_rent", "security_deposit", "rent_free_days", "notice_period_days", "units_covered"):
			if (getattr(self, field, 0) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(field.replace("_", " ").title()))
		if self.status in ("Active", "Expiring"):
			self._validate_no_overlap()
		self._validate_transition()
		# Rounded to the field precision here so that the stored figure and
		# any sum(round(annual_rent/12, 2)) elsewhere agree. Left at full
		# precision, the record and the dashboard reported different rent.
		self.monthly_rent = frappe.utils.flt((self.annual_rent or 0) / 12.0, 2)
		self._check_schedule()

	def _validate_links(self):
		if not self.building or not frappe.db.exists("Building", self.building):
			frappe.throw(_("Head Lease must link to a valid Building."))
		building = frappe.db.get_value("Building", self.building, ["landlord", "company", "cost_center"], as_dict=True)
		if self.landlord != building.landlord:
			frappe.throw(_("Head Lease landlord must match the Building landlord."))
		if frappe.get_meta("Supplier").has_field("db_is_landlord") and not frappe.db.get_value("Supplier", self.landlord, "db_is_landlord"):
			frappe.throw(_("Head Lease Supplier is not classified as a DarkBrown landlord."))
		if self.company != building.company:
			frappe.throw(_("Head Lease company must match the Building company."))
		if not building.cost_center or not frappe.db.exists("Cost Center", building.cost_center):
			frappe.throw(_("Building must have a valid Cost Center before a Head Lease is created."))
		self.cost_center = building.cost_center

	def _validate_transition(self):
		before = self.get_doc_before_save()
		if not before:
			if self.status != "Draft":
				frappe.throw(_("A new Head Lease must start as Draft."))
			return
		allowed = {
			"Draft": {"Draft", "Active", "Terminated"},
			"Active": {"Active", "Expiring", "Expired", "Terminated"},
			"Expiring": {"Expiring", "Active", "Expired", "Terminated"},
			"Expired": {"Expired"}, "Terminated": {"Terminated"},
		}
		if self.status not in allowed.get(before.status, set()):
			frappe.throw(_("Invalid Head Lease status transition from {0} to {1}.").format(before.status, self.status))
		if self.status == "Active" and before.status != "Active":
			roles = set(frappe.get_roles(frappe.session.user))
			if not ({"Managing Director", "General Manager", "System Manager"} & roles) and frappe.session.user != "Administrator":
				frappe.throw(_("Only an approval role may activate a Head Lease."), frappe.PermissionError)
			if not self.signed_document:
				frappe.throw(_("Activation requires the signed Head Lease document."))

	def _validate_no_overlap(self):
		if not self.start_date or not self.end_date:
			return
		for row in frappe.get_all("Head Lease", filters={
				"building": self.building, "status": ["in", ("Active", "Expiring")],
				"name": ["!=", self.get("name")]}, fields=["name", "start_date", "end_date"]):
			if row.start_date <= self.end_date and row.end_date >= self.start_date:
				frappe.throw(_("Head Lease overlaps active obligation {0}.").format(row.name))

	def on_trash(self):
		if self.status not in ("Draft", "Expired", "Terminated"):
			frappe.throw(_("An active Head Lease cannot be deleted; terminate it instead."))

	def _check_schedule(self):
		if not self.payments:
			return
		total = sum((p.amount or 0) for p in self.payments)
		term_years = 1
		if self.start_date and self.end_date:
			days = frappe.utils.date_diff(self.end_date, self.start_date) + 1
			term_years = max(days / 365.0, 0.5)
		expected = (self.annual_rent or 0) * term_years
		if expected and abs(total - expected) > max(expected * 0.01, 1):
			frappe.msgprint(
				_("Scheduled payments total {0} against an expected {1} for the term.")
				.format(frappe.utils.fmt_money(total, currency="QAR"),
				        frappe.utils.fmt_money(expected, currency="QAR")),
				indicator="orange", alert=True)
