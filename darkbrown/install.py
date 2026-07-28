"""Fresh-site setup. Idempotent: safe to re-run, creates nothing twice.

V2 carries no data migration from V1. Everything the app needs to stand up on
an empty site is created here.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = [
    ("Managing Director",
     "The approving authority. Reserved-category approvals cannot be delegated."),
    ("General Manager", "Operational feasibility and scoped building views."),
    ("Accounts", "Invoicing, receipts, cheques, reconciliation and closing."),
    ("Documentation", "Document intake, OCR review, vault and expiry queue."),
    ("Maintenance", "Maintenance requests and unit readiness."),
]

# Landlords and tenants are ERPNext parties with identity layered on, not
# standalone DocTypes. That keeps one ledger and one party master.
CUSTOM_FIELDS = {
    "Supplier": [
        {"fieldname": "db_landlord_section", "fieldtype": "Section Break",
         "label": "Landlord Details", "insert_after": "supplier_group",
         "collapsible": 1},
        {"fieldname": "db_is_landlord", "fieldtype": "Check",
         "label": "Is Landlord", "insert_after": "db_landlord_section"},
        {"fieldname": "db_qid_number", "fieldtype": "Data",
         "label": "QID / CR No", "insert_after": "db_is_landlord",
         "depends_on": "db_is_landlord"},
        {"fieldname": "db_nationality", "fieldtype": "Data",
         "label": "Nationality", "insert_after": "db_qid_number",
         "depends_on": "db_is_landlord"},
        {"fieldname": "db_col_landlord", "fieldtype": "Column Break",
         "insert_after": "db_nationality"},
        {"fieldname": "db_bank_iban", "fieldtype": "Data", "label": "IBAN",
         "insert_after": "db_col_landlord", "depends_on": "db_is_landlord"},
        {"fieldname": "db_bank_name", "fieldtype": "Data", "label": "Bank",
         "insert_after": "db_bank_iban", "depends_on": "db_is_landlord"},
        {"fieldname": "db_docs_section", "fieldtype": "Section Break",
         "label": "Documents", "insert_after": "db_bank_name",
         "collapsible": 1},
        {"fieldname": "db_documents", "fieldtype": "Table",
         "label": "Documents", "options": "Party Document",
         "insert_after": "db_docs_section"},
    ],
    "Customer": [
        {"fieldname": "db_tenant_section", "fieldtype": "Section Break",
         "label": "Tenant Details", "insert_after": "customer_group",
         "collapsible": 1},
        {"fieldname": "db_is_tenant", "fieldtype": "Check", "label": "Is Tenant",
         "insert_after": "db_tenant_section"},
        {"fieldname": "db_qid_number", "fieldtype": "Data", "label": "QID No",
         "insert_after": "db_is_tenant", "depends_on": "db_is_tenant"},
        {"fieldname": "db_qid_expiry", "fieldtype": "Date",
         "label": "QID Expiry", "insert_after": "db_qid_number",
         "depends_on": "db_is_tenant"},
        {"fieldname": "db_col_tenant", "fieldtype": "Column Break",
         "insert_after": "db_qid_expiry"},
        {"fieldname": "db_nationality", "fieldtype": "Data",
         "label": "Nationality", "insert_after": "db_col_tenant",
         "depends_on": "db_is_tenant"},
        {"fieldname": "db_mobile_no", "fieldtype": "Data", "label": "Mobile",
         "insert_after": "db_nationality", "depends_on": "db_is_tenant"},
        {"fieldname": "db_employer", "fieldtype": "Data", "label": "Employer",
         "insert_after": "db_mobile_no", "depends_on": "db_is_tenant"},
        {"fieldname": "db_docs_section", "fieldtype": "Section Break",
         "label": "Documents", "insert_after": "db_employer",
         "collapsible": 1},
        {"fieldname": "db_documents", "fieldtype": "Table",
         "label": "Documents", "options": "Party Document",
         "insert_after": "db_docs_section"},
    ],
}

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
    install_custom_fields()
    seed_settings()
    seed_document_requirements()
    frappe.db.commit()


def after_migrate():
    """Re-runs on every migrate so a new field or requirement lands without a
    patch. Everything below is a no-op when it already exists."""
    install_custom_fields()
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


def install_custom_fields():
    for fields in CUSTOM_FIELDS.values():
        for f in fields:
            f.setdefault("module", "Darkbrown")
    create_custom_fields(CUSTOM_FIELDS, update=True)


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
