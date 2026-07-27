import frappe
from frappe import _
from frappe.model.document import Document

from darkbrown.darkbrown.doctype.building.building import refresh_unit_count


class Unit(Document):
    def validate(self):
        self.unit_no = (self.unit_no or "").strip()
        if not self.unit_no:
            frappe.throw(_("Unit number is required and must match the number on the apartment."))
        self.guard_duplicate()

    def guard_duplicate(self):
        existing = frappe.db.exists(
            "Unit", {"building": self.building, "unit_no": self.unit_no, "name": ["!=", self.name]}
        )
        if existing:
            frappe.throw(
                _("Unit {0} already exists in {1}.").format(self.unit_no, self.building)
            )

    def on_update(self):
        refresh_unit_count(self.building)

    def after_insert(self):
        refresh_unit_count(self.building)

    def on_trash(self):
        if self.status == "Occupied":
            frappe.throw(_("An occupied unit cannot be deleted. Close the tenancy first."))

    def after_delete(self):
        refresh_unit_count(self.building)
