"""Notification rules N1-N11, system bell only (no email).

N5 (grace period) is NOT here - no stored grace-end date field, so it
runs as a daily job in darkbrown.utils.handoffs.grace_period_alerts.
N6 was folded into N3. N12-N14 live in create_approval_workflow.

Idempotent: each rule guarded by exists() on its name.
"""

import frappe

RULES = [
    # (name, document_type, event, config, roles, subject)
    ("N1 - Landlord PDC maturing 15d", "PDC Cheque", "Days Before",
     {"date_changed": "cheque_date", "days_in_advance": 15,
      "condition": 'doc.direction == "Outgoing"'},
     ["Accounts"],
     "Landlord cheque {{ doc.cheque_number or doc.name }} matures in 15 days"),

    ("N2a - Tenant agreement expiring 90d", "Tenant Rental Agreement",
     "Days Before",
     {"date_changed": "end_date", "days_in_advance": 90,
      "condition": 'doc.status == "Active"'},
     ["General Manager"],
     "{{ doc.name }} expires in 90 days"),

    ("N2b - Tenant agreement expiring 60d", "Tenant Rental Agreement",
     "Days Before",
     {"date_changed": "end_date", "days_in_advance": 60,
      "condition": 'doc.status == "Active"'},
     ["General Manager"],
     "{{ doc.name }} expires in 60 days"),

    ("N2c - Tenant agreement expiring 30d", "Tenant Rental Agreement",
     "Days Before",
     {"date_changed": "end_date", "days_in_advance": 30,
      "condition": 'doc.status == "Active"'},
     ["General Manager"],
     "{{ doc.name }} expires in 30 days"),

    ("N3 - Head-lease expiring 90d", "Landlord Contract", "Days Before",
     {"date_changed": "contract_end_date", "days_in_advance": 90,
      "condition": 'doc.status == "Active"'},
     ["General Manager", "Managing Director"],
     "Head-lease {{ doc.name }} ({{ doc.building }}) expires in 90 days"),

    ("N4 - Register document expiring 30d", "Document Register",
     "Days Before",
     {"date_changed": "expiry_date", "days_in_advance": 30},
     ["Legal and Documentation"],
     "Document expiring in 30 days: {{ doc.title }}"),

    ("N7 - Invoice overdue", "Sales Invoice", "Days After",
     {"date_changed": "due_date", "days_in_advance": 1,
      "condition": "doc.docstatus == 1 and doc.outstanding_amount > 0"},
     ["Accounts"],
     "Invoice {{ doc.name }} ({{ doc.customer }}) is overdue - "
     "QAR {{ doc.outstanding_amount }}"),

    ("N8 - PDC bounced", "PDC Cheque", "Value Change",
     {"value_changed": "status", "condition": 'doc.status == "Bounced"'},
     ["Accounts", "General Manager"],
     "Cheque {{ doc.cheque_number or doc.name }} ({{ doc.party }}) BOUNCED"),

    ("N9 - New maintenance request", "Maintenance Request", "New",
     {},
     ["Maintenance"],
     "New maintenance request: {{ doc.issue or doc.name }} "
     "({{ doc.building }})"),

    ("N10 - Maintenance aged 48h", "Maintenance Request", "Days After",
     {"date_changed": "reported_on", "days_in_advance": 2,
      "condition": 'doc.status in ("Open", "In Progress")'},
     ["Maintenance", "General Manager"],
     "Maintenance request {{ doc.name }} open for 48h+ "
     "({{ doc.building }})"),

    ("N11 - Unit went vacant", "Tenant Rental Agreement", "Value Change",
     {"value_changed": "status",
      "condition": 'doc.status in ("Expired", "Terminated", "Cancelled")'},
     ["General Manager"],
     "{{ doc.name }} ended ({{ doc.building }} / {{ doc.unit }}) - "
     "unit vacant"),
]


def execute():
    for name, dt, event, cfg, roles, subject in RULES:
        if frappe.db.exists("Notification", name):
            continue
        if not frappe.db.exists("DocType", dt):
            continue
        doc = {
            "doctype": "Notification",
            "__newname": name,
            "document_type": dt,
            "event": event,
            "channel": "System Notification",
            "subject": subject,
            "message": subject,
            "enabled": 1,
            "recipients": [{"receiver_by_role": r} for r in roles],
        }
        doc.update(cfg)
        frappe.get_doc(doc).insert(ignore_permissions=True)

    frappe.db.commit()
