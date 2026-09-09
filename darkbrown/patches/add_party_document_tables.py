# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Adds a "Documents" tab with a Party Document child table to
Customer (Tenant) and Supplier (Landlord).

Runs under [post_model_sync] so the Party Document DocType already
exists when the custom fields are created. Idempotent: safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	custom_fields = {
		"Customer": [
			{
				"fieldname": "dbr_documents_tab",
				"fieldtype": "Tab Break",
				"label": "Documents",
				"insert_after": "portal_users",
			},
			{
				"fieldname": "dbr_party_documents",
				"fieldtype": "Table",
				"label": "Party Documents",
				"options": "Party Document",
				"insert_after": "dbr_documents_tab",
			},
		],
		"Supplier": [
			{
				"fieldname": "dbr_documents_tab",
				"fieldtype": "Tab Break",
				"label": "Documents",
				"insert_after": "portal_users",
			},
			{
				"fieldname": "dbr_party_documents",
				"fieldtype": "Table",
				"label": "Party Documents",
				"options": "Party Document",
				"insert_after": "dbr_documents_tab",
			},
		],
	}

	create_custom_fields(custom_fields, ignore_validate=True)
	frappe.db.commit()
