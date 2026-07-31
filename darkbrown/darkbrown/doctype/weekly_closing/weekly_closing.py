import frappe
from frappe.model.document import Document


class WeeklyClosing(Document):
    def validate(self):
        if self.status == "Closed" and not self.closed_on:
            self.closed_on = frappe.utils.now_datetime()
