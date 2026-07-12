"""Show full numbers (no K/M shortening) on every DBR Number Card,
matching the MD dashboard's full-number formatting."""

import frappe


def execute():
    if not frappe.db.exists("DocType", "Number Card"):
        return
    frappe.db.sql("""update `tabNumber Card`
                     set show_full_number = 1 where is_public = 1""")
    frappe.db.commit()
