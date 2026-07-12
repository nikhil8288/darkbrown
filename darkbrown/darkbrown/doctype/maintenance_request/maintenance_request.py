import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class MaintenanceRequest(Document):
    def validate(self):
        # cost is always the auto-sum of cost lines
        self.cost = sum((line.amount or 0) for line in (self.cost_lines or []))

        # resolution = documented expense: cannot resolve without cost lines
        if self.status == "Resolved" and not self.cost_lines:
            frappe.throw(
                _("Cannot mark as Resolved without at least one cost line. "
                  "Record what was spent (use amount 0 for no-cost fixes)."),
                title=_("Cost Lines Required"))

        if self.status == "Resolved" and not self.resolved_on:
            self.resolved_on = now_datetime()
