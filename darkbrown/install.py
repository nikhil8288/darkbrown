"""Fresh-site setup. Idempotent: safe to re-run, creates nothing twice.

V2 carries no data migration from V1. Everything the app needs to stand up on an
empty site is created here.
"""

import frappe

ROLES = [
    ("Managing Director", "The approving authority. Reserved-category approvals cannot be delegated."),
    ("General Manager", "Operational feasibility and scoped building views."),
    ("Accounts", "Invoicing, receipts, cheques, reconciliation and closing."),
    ("Documentation", "Document intake, OCR review, vault and expiry queue."),
    ("Maintenance", "Maintenance requests and unit readiness."),
]


def after_install():
    create_roles()
    frappe.db.commit()


def create_roles():
    for name, description in ROLES:
        if frappe.db.exists("Role", name):
            continue
        frappe.get_doc({
            "doctype": "Role",
            "role_name": name,
            "desk_access": 1,
            "description": description,
        }).insert(ignore_permissions=True)
