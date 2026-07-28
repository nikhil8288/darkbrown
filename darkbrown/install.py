"""Fresh-site setup. Idempotent: safe to re-run, creates nothing twice.

V2 carries no data migration from V1. Everything the app needs to stand up on
an empty site is created here.
"""

import frappe

ROLES = [
    ("Managing Director",
     "The approving authority. Reserved-category approvals cannot be delegated."),
    ("General Manager", "Operational feasibility and scoped building views."),
    ("Accounts", "Invoicing, receipts, cheques, reconciliation and closing."),
    ("Documentation", "Document intake, OCR review, vault and expiry queue."),
    ("Maintenance", "Maintenance requests and unit readiness."),
]

DOCUMENT_REQUIREMENTS = [
    ("Tenant", "QID", 1, 1, 30),
    ("Tenant", "Passport", 0, 1, 60),
    ("Tenant", "Signed Tenancy Agreement", 1, 0, 0),
    ("Landlord", "QID / CR", 1, 1, 30),
    ("Landlord", "Title Deed", 0, 0, 0),
    ("Landlord", "Signed Head Lease", 1, 0, 0),
    ("Landlord", "IBAN Certificate", 1, 0, 0),
    ("Building", "Civil Defence Certificate", 1, 1, 45),
    ("Building", "Kahramaa Account", 1, 0, 0),
    ("Unit", "Handover Checklist", 0, 0, 0),
]

SETTINGS_DEFAULTS = {
    "invoice_generation_day": 1,
    "presentation_notice_days": 14,
    "default_tenancy_notice_days": 60,
    "default_headlease_notice_days": 90,
    "grace_days": 7,
    "legal_escalation_months": 2,
    "emergency_maintenance_ceiling": 2000,
    "weekly_closing_day": "Thursday",
    "reserve_months": 3,
}


def after_install():
    create_roles()
    reconcile_custom_fields()
    seed_settings()
    seed_document_requirements()
    frappe.db.commit()


def after_migrate():
    """Re-runs on every migrate so a new field or requirement lands without a
    patch. Everything below is a no-op when it already exists."""
    reconcile_custom_fields()
    seed_document_requirements()
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


def reconcile_custom_fields():
    """The party fields are defined once, in darkbrown/custom/*.json, and applied
    by migrate before this hook runs. An earlier build also declared them in
    Python with different names and types, which left duplicates on any site
    that ran it. Anything this app owns on Customer or Supplier that the JSON
    no longer declares is removed here."""
    import json
    import os

    base = os.path.join(os.path.dirname(__file__), "darkbrown", "custom")
    for dt, fname in (("Customer", "customer.json"), ("Supplier", "supplier.json")):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            continue
        keep = {f["fieldname"] for f in json.load(open(path)).get("custom_fields", [])}
        stale = frappe.get_all(
            "Custom Field",
            filters={"dt": dt, "module": "Darkbrown", "fieldname": ["not in", list(keep) or [""]]},
            pluck="name",
        )
        for name in stale:
            frappe.delete_doc("Custom Field", name,
                              ignore_permissions=True, force=True)
        if stale:
            frappe.clear_cache(doctype=dt)


def seed_settings():
    doc = frappe.get_single("DBR Settings")
    for key, value in SETTINGS_DEFAULTS.items():
        if not doc.get(key):
            doc.set(key, value)
    company = (frappe.defaults.get_user_default("Company")
               or frappe.db.get_value("Company", {}, "name"))
    if company and not doc.default_company:
        doc.default_company = company
    doc.flags.ignore_mandatory = True
    doc.save(ignore_permissions=True)


def seed_document_requirements():
    for applies_to, dtype, mandatory, tracked, notice in DOCUMENT_REQUIREMENTS:
        name = f"{applies_to}-{dtype}"
        if frappe.db.exists("Document Requirement", name):
            continue
        frappe.get_doc({
            "doctype": "Document Requirement",
            "applies_to": applies_to,
            "document_type": dtype,
            "mandatory": mandatory,
            "expiry_tracked": tracked,
            "notice_days": notice,
        }).insert(ignore_permissions=True)
