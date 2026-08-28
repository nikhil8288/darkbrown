import frappe
from frappe import _
from frappe.model.document import Document


class HeadLease(Document):
	def validate(self):
		if self.end_date and self.start_date and self.end_date <= self.start_date:
			frappe.throw(_("End date must fall after the start date."))
		# Rounded to the field precision here so that the stored figure and
		# any sum(round(annual_rent/12, 2)) elsewhere agree. Left at full
		# precision, the record and the dashboard reported different rent.
		self.monthly_rent = frappe.utils.flt((self.annual_rent or 0) / 12.0, 2)
		self._check_schedule()

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
