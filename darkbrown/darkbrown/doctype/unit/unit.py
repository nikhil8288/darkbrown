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
        self.guard_building_change()
        self.guard_occupancy()

    def guard_duplicate(self):
        existing = frappe.db.exists(
            "Unit", {"building": self.building, "unit_no": self.unit_no, "name": ["!=", self.name]}
        )
        if existing:
            frappe.throw(
                _("Unit {0} already exists in {1}.").format(self.unit_no, self.building)
            )

    def guard_building_change(self):
        if not self.building or not frappe.db.exists("Building", self.building):
            frappe.throw(_("Unit must link to a valid Building."))
        before = self.get_doc_before_save()
        if before and before.building != self.building:
            if frappe.db.exists("Tenancy Agreement", {"unit": self.name}):
                frappe.throw(_("A Unit with agreement history cannot be moved to another Building."))

    def guard_occupancy(self):
        live = frappe.db.exists("Tenancy Agreement", {
            "unit": self.get("name"), "status": ["in", ("Active", "Expiring")]}) if self.get("name") else None
        if self.status == "Occupied" and not live and not getattr(self.flags, "occupancy_sync", False):
            frappe.throw(_("Occupied status is derived from an active tenancy."))
        if live and self.status in ("Vacant", "Not Ready"):
            frappe.throw(_("A Unit with a live tenancy cannot be marked vacant or not ready."))

    def on_update(self):
        refresh_unit_count(self.building)

    def after_insert(self):
        refresh_unit_count(self.building)

    def on_trash(self):
        if frappe.db.exists("Tenancy Agreement", {"unit": self.name}):
            frappe.throw(_("A Unit with agreement history cannot be deleted."))

    def after_delete(self):
        refresh_unit_count(self.building)
