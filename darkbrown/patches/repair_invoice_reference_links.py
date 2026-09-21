"""Repair invoice links left on the pre-rename agreement DocTypes.

``setup_rent_invoicing`` may already be recorded as executed on an older site,
so changing that patch cannot repair installed Custom Field rows. This new
idempotent schema patch updates the persisted options without touching any
invoice or ledger data.
"""

import frappe


FIELDS = (
    ("Sales Invoice", "custom_rental_agreement", "Rental Agreement",
     "Tenancy Agreement"),
    ("Purchase Invoice", "custom_landlord_contract", "Head Lease",
     "Head Lease"),
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

