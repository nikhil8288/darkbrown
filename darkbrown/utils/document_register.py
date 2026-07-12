"""Daily refresh of Document Register statuses (Expiring Soon / Expired
roll forward as dates pass, without anyone opening the record)."""

import frappe

from darkbrown.darkbrown.doctype.document_register.document_register import (
    compute_status,
)


def refresh_statuses():
    if not frappe.db.exists("DocType", "Document Register"):
        return
    rows = frappe.get_all("Document Register",
                          fields=["name", "file", "expiry_date", "status"])
    for r in rows:
        new = compute_status(r.file, r.expiry_date)
        if new != r.status:
            frappe.db.set_value("Document Register", r.name, "status", new,
                                update_modified=False)
    frappe.db.commit()
