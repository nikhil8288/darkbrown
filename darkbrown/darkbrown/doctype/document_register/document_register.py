import frappe
from frappe.model.document import Document
from frappe.utils import date_diff, nowdate

EXPIRY_WINDOW_DAYS = 30


def compute_status(file, expiry_date):
    """Missing (no file) > Expired > Expiring Soon (<=30d) > Valid."""
    if not file:
        return "Missing"
    if expiry_date:
        days = date_diff(expiry_date, nowdate())
        if days < 0:
            return "Expired"
        if days <= EXPIRY_WINDOW_DAYS:
            return "Expiring Soon"
    return "Valid"


class DocumentRegister(Document):
    def validate(self):
        self.status = compute_status(self.file, self.expiry_date)
        if self.link_doctype == "Building" and self.link_name and not self.building:
            self.building = self.link_name
