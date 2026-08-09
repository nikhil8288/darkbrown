"""Create the role-gated Collection Case workflow.

Finance (Accounts) drives Open -> Contacted -> Promised and confirms
Pending Confirmation -> Collected. Only the General Manager can move a
case to Legal. Idempotent: skips if the workflow already exists.
"""

import frappe

WF_NAME = "Collection Case Flow"


def execute():
    if frappe.db.exists("Workflow", WF_NAME):
        return

    for state, style in [("Open", "Danger"), ("Contacted", "Warning"),
                         ("Promised", "Primary"),
                         ("Pending Confirmation", "Info"),
                         ("Collected", "Success"), ("Legal", "Inverse")]:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State",
                            "workflow_state_name": state,
                            "style": style}).insert(ignore_permissions=True)

    for action in ["Contact", "Record Promise", "Confirm Collected",
                   "Escalate to Legal", "Reopen"]:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({"doctype": "Workflow Action Master",
                            "workflow_action_name": action}
                           ).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "Workflow",
        "workflow_name": WF_NAME,
        "document_type": "Collection Case",
        "workflow_state_field": "status",
        "is_active": 1,
        "send_email_alert": 0,
        "states": [
            {"state": "Open", "doc_status": "0", "allow_edit": "Accounts"},
            {"state": "Contacted", "doc_status": "0", "allow_edit": "Accounts"},
            {"state": "Promised", "doc_status": "0", "allow_edit": "Accounts"},
            {"state": "Pending Confirmation", "doc_status": "0",
             "allow_edit": "Accounts"},
            {"state": "Collected", "doc_status": "0",
             "allow_edit": "System Manager"},
            {"state": "Legal", "doc_status": "0",
             "allow_edit": "Documentation"},
        ],
        "transitions": [
            {"state": "Open", "action": "Contact",
             "next_state": "Contacted", "allowed": "Accounts"},
            {"state": "Contacted", "action": "Record Promise",
             "next_state": "Promised", "allowed": "Accounts"},
            {"state": "Pending Confirmation", "action": "Confirm Collected",
             "next_state": "Collected", "allowed": "Accounts"},
            {"state": "Promised", "action": "Escalate to Legal",
             "next_state": "Legal", "allowed": "General Manager"},
            {"state": "Contacted", "action": "Escalate to Legal",
             "next_state": "Legal", "allowed": "General Manager"},
            {"state": "Promised", "action": "Reopen",
             "next_state": "Open", "allowed": "Accounts"},
        ],
    }).insert(ignore_permissions=True)
    frappe.db.commit()
