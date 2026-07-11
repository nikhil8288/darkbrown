"""Setup for the monthly rent invoicer.

Creates the idempotency custom fields on Sales/Purchase Invoice and the
two non-stock service Items the invoice lines use. Idempotent.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Sales Invoice": [
            {"fieldname": "custom_rental_agreement", "label": "Rental Agreement",
             "fieldtype": "Link", "options": "Tenant Rental Agreement",
             "insert_after": "customer", "read_only": 1, "search_index": 1},
            {"fieldname": "custom_billing_period", "label": "Billing Period",
             "fieldtype": "Data", "insert_after": "custom_rental_agreement",
             "read_only": 1, "search_index": 1},
        ],
        "Purchase Invoice": [
            {"fieldname": "custom_landlord_contract", "label": "Landlord Contract",
             "fieldtype": "Link", "options": "Landlord Contract",
             "insert_after": "supplier", "read_only": 1, "search_index": 1},
            {"fieldname": "custom_billing_period", "label": "Billing Period",
             "fieldtype": "Data", "insert_after": "custom_landlord_contract",
             "read_only": 1, "search_index": 1},
        ],
    }, ignore_validate=True)

    for code, name in [("Rent", "Rent"), ("Landlord Rent", "Landlord Rent")]:
        if not frappe.db.exists("Item", code):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": code,
                "item_name": name,
                "item_group": frappe.db.get_value(
                    "Item Group", {"is_group": 0}, "name") or "Services",
                "is_stock_item": 0,
                "is_sales_item": 1,
                "is_purchase_item": 1,
            }).insert(ignore_permissions=True)
    frappe.db.commit()
