import frappe
from frappe.model.document import Document


class MDAlertDismissal(Document):
    def before_insert(self):
        self.dismissed_by = self.dismissed_by or frappe.session.user
        self.dismissed_on = self.dismissed_on or frappe.utils.now_datetime()
