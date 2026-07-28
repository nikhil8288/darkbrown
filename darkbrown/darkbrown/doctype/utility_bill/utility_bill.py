import frappe
from frappe import _
from frappe.model.document import Document


class UtilityBill(Document):
	def validate(self):
		self.allocated_total = sum((a.amount or 0) for a in self.allocations)
		self.unallocated = (self.amount or 0) - self.allocated_total
		if self.allocated_total > (self.amount or 0) + 0.005:
			frappe.throw(_("Allocations exceed the bill amount."))
