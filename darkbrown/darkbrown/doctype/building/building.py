import frappe
from frappe import _
from frappe.model.document import Document
from darkbrown.guards import guard, GM, MD


class Building(Document):
    def validate(self):
        self.set_company()
        self.validate_master_links()
        self.validate_unique_name()
        self.validate_exit()

    def validate_master_links(self):
        if not self.company or not frappe.db.exists("Company", self.company):
            frappe.throw(_("Building must link to a valid Company."))
        if frappe.db.get_value("Company", self.company, "default_currency") != "QAR":
            frappe.throw(_("Launch Buildings must belong to a QAR company."))
        if not self.landlord or not frappe.db.exists("Supplier", self.landlord):
            frappe.throw(_("Building must link to a valid landlord Supplier."))
        if frappe.get_meta("Supplier").has_field("db_is_landlord") and not \
                frappe.db.get_value("Supplier", self.landlord, "db_is_landlord"):
            frappe.throw(_("The selected Supplier is not classified as a DarkBrown landlord."))

    def validate_unique_name(self):
        label = (self.building_name or "").strip()
        self.building_name = label
        if not label:
            frappe.throw(_("Building name is required."))
        for row in frappe.get_all("Building", fields=["name", "building_name"]):
            if row.name != self.get("name") and (row.building_name or "").strip().casefold() == label.casefold():
                frappe.throw(_("A building with this name already exists."))

    def before_save(self):
        before = self.get_doc_before_save()
        if before and before.company != self.company:
            linked = (frappe.db.exists("Unit", {"building": self.name}) or
                      frappe.db.exists("Head Lease", {"building": self.name}) or
                      frappe.db.exists("Tenancy Agreement", {"building": self.name}))
            if linked:
                frappe.throw(_("Company cannot be changed after units or agreements exist."))

    def on_trash(self):
        for doctype in ("Unit", "Head Lease", "Tenancy Agreement"):
            if frappe.db.exists(doctype, {"building": self.name}):
                frappe.throw(_("A linked {0} prevents deleting this Building.").format(doctype))

    def set_company(self):
        if not self.company:
            self.company = frappe.defaults.get_user_default("Company")

    def validate_exit(self):
        if self.status == "Exited" and not self.exit_date:
            frappe.throw(_("An exited building must carry an exit date."))
        if self.exit_date and self.handover_date and self.exit_date < self.handover_date:
            frappe.throw(_("Exit date cannot fall before the handover date."))

    def refresh_unit_count(self):
        """Recount units from the register. Called by the Unit controller, never typed."""
        count = frappe.db.count("Unit", {"building": self.name})
        if count != (self.total_units or 0):
            frappe.db.set_value("Building", self.name, "total_units", count, update_modified=False)


def refresh_unit_count(building: str):
    if not building:
        return
    count = frappe.db.count("Unit", {"building": building})
    frappe.db.set_value("Building", building, "total_units", count, update_modified=False)


@frappe.whitelist()
def bulk_create_units(building: str, unit_numbers: str, unit_type: str = None,
                      floor: str = None, status: str = "Not Ready"):
    """Create Unit records from a newline- or comma-separated list of physical unit numbers.

    Unit numbers are never generated. Whatever is pasted here is what is on the door.
    Duplicates against the existing register are skipped and reported rather than merged.
    """
    guard(MD, GM)
    frappe.has_permission("Unit", "create", throw=True)

    raw = (unit_numbers or "").replace(",", "\n").split("\n")
    numbers, seen = [], set()
    for token in raw:
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            numbers.append(token)

    if not numbers:
        frappe.throw(_("No unit numbers were supplied."))

    created, skipped = [], []
    for number in numbers:
        if frappe.db.exists("Unit", {"building": building, "unit_no": number}):
            skipped.append(number)
            continue
        doc = frappe.get_doc({
            "doctype": "Unit",
            "building": building,
            "unit_no": number,
            "floor": floor,
            "unit_type": unit_type,
            "status": status,
        })
        doc.insert()
        created.append(doc.name)

    refresh_unit_count(building)
    return {"created": created, "skipped": skipped}
