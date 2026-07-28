import frappe
from frappe import _
from frappe.model.document import Document


class MaintenanceRequest(Document):
	def validate(self):
		self.cost = sum((l.amount or 0) for l in self.cost_lines)
		if not self.reported_on:
			self.reported_on = frappe.utils.now()
			self.reported_by = frappe.session.user
		ceiling = frappe.db.get_single_value(
			"DBR Settings", "emergency_maintenance_ceiling") or 0
		self.over_ceiling = 1 if (ceiling and self.priority == "Emergency"
		                          and (self.cost or 0) > ceiling) else 0
		if self.over_ceiling:
			frappe.msgprint(
				_("This emergency job is over the {0} ceiling and needs approval.")
				.format(frappe.utils.fmt_money(ceiling, currency="QAR")),
				indicator="red", alert=True)
		if self.rechargeable and not self.recharge_status:
			self.recharge_status = "Pending"
