"""Agreement approval flow: Legal drafts -> GM approves -> MD approves.

Applied to Tenant Rental Agreement and Landlord Contract via a
`workflow_state` field (auto-created by Frappe on Workflow insert; the
existing `status` field is untouched). All existing records are
backfilled to Active so nothing regresses to Draft.

Also creates notification rules N12 (pending GM -> GM bell),
N13 (pending MD -> MD bell), N14 (approved/rejected -> Legal bell).

Idempotent: every create is guarded by an exists() check.
"""

import frappe

DOCTYPES = ["Tenant Rental Agreement", "Landlord Contract"]

STATES = [
    ("Draft", "Danger"),
    ("Pending GM Approval", "Warning"),
    ("Pending MD Approval", "Primary"),
    ("Active", "Success"),
]

ACTIONS = ["Submit for Approval", "Approve", "Reject", "Amend"]


def execute():
    _ensure_states_and_actions()

    for dt in DOCTYPES:
        if not frappe.db.exists("DocType", dt):
            continue
        _create_workflow(dt)
        _backfill_active(dt)
        _create_notifications(dt)

    frappe.db.commit()


def _ensure_states_and_actions():
    for state, style in STATES:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State",
                            "workflow_state_name": state,
                            "style": style}).insert(ignore_permissions=True)
    for action in ACTIONS:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({"doctype": "Workflow Action Master",
                            "workflow_action_name": action}
                           ).insert(ignore_permissions=True)


def _create_workflow(dt):
    wf_name = f"{dt} Approval"
    if frappe.db.exists("Workflow", wf_name):
        return

    frappe.get_doc({
        "doctype": "Workflow",
        "workflow_name": wf_name,
        "document_type": dt,
        "workflow_state_field": "workflow_state",
        "is_active": 1,
        "send_email_alert": 0,
        "states": [
            {"state": "Draft", "doc_status": "0",
             "allow_edit": "Legal and Documentation"},
            {"state": "Pending GM Approval", "doc_status": "0",
             "allow_edit": "General Manager"},
            {"state": "Pending MD Approval", "doc_status": "0",
             "allow_edit": "Managing Director"},
            {"state": "Active", "doc_status": "0",
             "allow_edit": "System Manager"},
        ],
        "transitions": [
            {"state": "Draft", "action": "Submit for Approval",
             "next_state": "Pending GM Approval",
             "allowed": "Legal and Documentation"},
            {"state": "Pending GM Approval", "action": "Approve",
             "next_state": "Pending MD Approval",
             "allowed": "General Manager"},
            {"state": "Pending GM Approval", "action": "Reject",
             "next_state": "Draft", "allowed": "General Manager"},
            {"state": "Pending MD Approval", "action": "Approve",
             "next_state": "Active", "allowed": "Managing Director"},
            {"state": "Pending MD Approval", "action": "Reject",
             "next_state": "Draft", "allowed": "Managing Director"},
            {"state": "Active", "action": "Amend",
             "next_state": "Draft", "allowed": "Legal and Documentation"},
        ],
    }).insert(ignore_permissions=True)


def _backfill_active(dt):
    """Existing agreements are live -> Active, never Draft."""
    if not frappe.db.has_column(dt, "workflow_state"):
        return
    frappe.db.sql(
        """update `tab{0}` set workflow_state = 'Active'
           where ifnull(workflow_state, '') in ('', 'Draft')""".format(dt))


def _create_notifications(dt):
    rules = [
        # (suffix, state condition, role, subject)
        ("N12", "Pending GM Approval", "General Manager",
         "{{ doc.name }} awaits your (GM) approval"),
        ("N13", "Pending MD Approval", "Managing Director",
         "{{ doc.name }} awaits your (MD) approval"),
        ("N14", None, "Legal and Documentation",
         "{{ doc.name }}: {{ doc.workflow_state }}"),
    ]
    for suffix, state, role, subject in rules:
        name = f"{suffix} - {dt} Approval"
        if frappe.db.exists("Notification", name):
            continue
        if state:
            condition = f'doc.workflow_state == "{state}"'
        else:  # N14: approved (Active) or rejected (back to Draft)
            condition = 'doc.workflow_state in ("Active", "Draft")'
        doc = frappe.get_doc({
            "doctype": "Notification",
            "__newname": name,
            "subject": subject,
            "document_type": dt,
            "event": "Value Change",
            "value_changed": "workflow_state",
            "condition": condition,
            "channel": "System Notification",
            "message": subject,
            "enabled": 1,
            "recipients": [{"receiver_by_role": role}],
        })
        doc.insert(ignore_permissions=True)
