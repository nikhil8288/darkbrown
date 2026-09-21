"""Give invoice agreement links their current, user-facing names."""

import frappe


FIELDS = (
    ("Sales Invoice", "custom_rental_agreement",
     "Tenancy Agreement", "Tenancy Agreement"),
    ("Purchase Invoice", "custom_landlord_contract",
     "Head Lease", "Head Lease"),
)


def execute():
    for dt, fieldname, label, options in FIELDS:
        name = frappe.db.get_value(
            "Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
        if not name:
            continue
        frappe.db.set_value("Custom Field", name, {
            "label": label,
            "options": options,
        }, update_modified=False)
        frappe.clear_cache(doctype=dt)

