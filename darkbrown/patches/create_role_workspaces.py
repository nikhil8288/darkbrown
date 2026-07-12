"""Create the four role Workspaces (Finance, GM, Legal, Maintenance)
plus every Number Card and Dashboard Chart they reference.

All server-side documents - no Workspace editor needed. Each workspace:
My To-Dos quick list on top, number-card rows, shortcuts, report links.
Visibility: owning role + Managing Director (workspace roles table).

Idempotent: every create guarded by exists().
"""

import json

import frappe

M = "darkbrown.api.number_cards."


# ------------------------------------------------------- number cards

def _dt_card(label, dt, filters, function="Count", based_on=None):
    return {"label": label, "type": "Document Type", "document_type": dt,
            "function": function,
            "aggregate_function_based_on": based_on,
            "filters_json": json.dumps(filters)}


def _custom_card(label, method):
    return {"label": label, "type": "Custom", "method": method,
            "filters_json": "[]"}


CARDS = [
    # --- custom (computed) ---
    _custom_card("Vacant Units", M + "vacant_units"),
    _custom_card("Occupancy %", M + "occupancy_pct"),
    _custom_card("Arrears (QAR)", M + "arrears_total"),
    _custom_card("Maintenance Aged 48h+", M + "maintenance_aged_48h"),
    _custom_card("Expiring 30d", M + "tra_expiring_30"),
    _custom_card("Expiring 60d", M + "tra_expiring_60"),
    _custom_card("Expiring 90d", M + "tra_expiring_90"),
    _custom_card("Head-Leases Expiring 90d", M + "headlease_expiring_90"),
    _custom_card("Pending GM Approval", M + "pending_gm_approvals"),
    _custom_card("Pending MD Approval", M + "pending_md_approvals"),

    # --- document type ---
    _dt_card("Total Units", "Unit", []),
    _dt_card("Active Tenants", "Tenant Rental Agreement",
             [["Tenant Rental Agreement", "status", "=", "Active"]]),
    _dt_card("New Agreements This Month", "Tenant Rental Agreement",
             [["Tenant Rental Agreement", "creation", "Timespan",
               "this month"]]),
    _dt_card("Ending This Month", "Tenant Rental Agreement",
             [["Tenant Rental Agreement", "end_date", "Timespan",
               "this month"]]),
    _dt_card("Outstanding Receivables (QAR)", "Sales Invoice",
             [["Sales Invoice", "docstatus", "=", 1],
              ["Sales Invoice", "outstanding_amount", ">", 0]],
             function="Sum", based_on="outstanding_amount"),
    _dt_card("Overdue Invoices", "Sales Invoice",
             [["Sales Invoice", "status", "=", "Overdue"]]),
    _dt_card("Open Collection Cases", "Collection Case",
             [["Collection Case", "status", "!=", "Collected"]]),
    _dt_card("Landlord Payable (QAR)", "Purchase Invoice",
             [["Purchase Invoice", "docstatus", "=", 1],
              ["Purchase Invoice", "outstanding_amount", ">", 0]],
             function="Sum", based_on="outstanding_amount"),
    _dt_card("Landlord Invoices Due This Week", "Purchase Invoice",
             [["Purchase Invoice", "docstatus", "=", 1],
              ["Purchase Invoice", "outstanding_amount", ">", 0],
              ["Purchase Invoice", "due_date", "Timespan", "next week"]]),
    _dt_card("PDC Incoming This Week", "PDC Cheque",
             [["PDC Cheque", "direction", "=", "Incoming"],
              ["PDC Cheque", "cheque_date", "Timespan", "next week"]]),
    _dt_card("PDC Outgoing This Week", "PDC Cheque",
             [["PDC Cheque", "direction", "=", "Outgoing"],
              ["PDC Cheque", "cheque_date", "Timespan", "next week"]]),
    _dt_card("Docs Expiring Soon", "Document Register",
             [["Document Register", "status", "=", "Expiring Soon"]]),
    _dt_card("Docs Expired", "Document Register",
             [["Document Register", "status", "=", "Expired"]]),
    _dt_card("Docs Missing", "Document Register",
             [["Document Register", "status", "=", "Missing"]]),
    _dt_card("Draft Tenant Agreements", "Tenant Rental Agreement",
             [["Tenant Rental Agreement", "workflow_state", "=", "Draft"]]),
    _dt_card("Draft Landlord Contracts", "Landlord Contract",
             [["Landlord Contract", "workflow_state", "=", "Draft"]]),
    _dt_card("Open Requests", "Maintenance Request",
             [["Maintenance Request", "status", "=", "Open"]]),
    _dt_card("In Progress", "Maintenance Request",
             [["Maintenance Request", "status", "=", "In Progress"]]),
    _dt_card("Resolved This Month", "Maintenance Request",
             [["Maintenance Request", "status", "=", "Resolved"],
              ["Maintenance Request", "resolved_on", "Timespan",
               "this month"]]),
    _dt_card("Maintenance Spend This Month (QAR)", "Maintenance Request",
             [["Maintenance Request", "status", "=", "Resolved"],
              ["Maintenance Request", "resolved_on", "Timespan",
               "this month"]],
             function="Sum", based_on="cost"),
]

CHARTS = [
    {"chart_name": "Occupied Units by Building",
     "document_type": "Tenant Rental Agreement",
     "group_by_based_on": "building", "chart_type": "Group By",
     "group_by_type": "Count", "type": "Bar",
     "filters_json": json.dumps(
         [["Tenant Rental Agreement", "status", "=", "Active"]])},
    {"chart_name": "Documents by Status",
     "document_type": "Document Register",
     "group_by_based_on": "status", "chart_type": "Group By",
     "group_by_type": "Count", "type": "Donut",
     "filters_json": "[]"},
    {"chart_name": "Open Maintenance by Building",
     "document_type": "Maintenance Request",
     "group_by_based_on": "building", "chart_type": "Group By",
     "group_by_type": "Count", "type": "Bar",
     "filters_json": json.dumps(
         [["Maintenance Request", "status", "in",
           ["Open", "In Progress"]]])},
]


# --------------------------------------------------- workspace helpers

def _id():
    return frappe.generate_hash(length=10)


def _header(text):
    return {"id": _id(), "type": "header",
            "data": {"text": f'<span class="h4"><b>{text}</b></span>',
                     "col": 12}}


def _ncard(name, col=3):
    return {"id": _id(), "type": "number_card",
            "data": {"number_card_name": name, "col": col}}


def _shortcut(name, col=3):
    return {"id": _id(), "type": "shortcut",
            "data": {"shortcut_name": name, "col": col}}


def _card(name, col=4):
    return {"id": _id(), "type": "card",
            "data": {"card_name": name, "col": col}}


def _chart(name, col=12):
    return {"id": _id(), "type": "chart",
            "data": {"chart_name": name, "col": col}}


def _qlist(name, col=4):
    return {"id": _id(), "type": "quick_list",
            "data": {"quick_list_name": name, "col": col}}


def _spacer():
    return {"id": _id(), "type": "spacer", "data": {"col": 12}}


REPORT_LINKS = ["General Ledger", "Accounts Receivable",
                "Accounts Payable", "Profit and Loss Statement"]

WORKSPACES = {
    "DBR Finance": {
        "icon": "bank", "roles": ["Accounts", "Managing Director"],
        "sequence_id": 30.0,
        "ncards": {
            "Money In": ["Outstanding Receivables (QAR)",
                         "Overdue Invoices", "Arrears (QAR)",
                         "Open Collection Cases"],
            "Money Out - Landlords": ["Landlord Payable (QAR)",
                                      "Landlord Invoices Due This Week"],
            "PDC Cheques": ["PDC Incoming This Week",
                            "PDC Outgoing This Week"],
        },
        "shortcuts": ["Sales Invoice", "Purchase Invoice",
                      "Payment Entry", "Journal Entry", "PDC Cheque",
                      "Collection Case"],
        "charts": [],
        "reports": REPORT_LINKS,
    },
    "GM Overview": {
        "icon": "organization",
        "roles": ["General Manager", "Managing Director"],
        "sequence_id": 31.0,
        "ncards": {
            "Portfolio": ["Total Units", "Vacant Units", "Occupancy %",
                          "Active Tenants"],
            "Leasing & Renewals": ["Expiring 30d", "Expiring 60d",
                                   "Expiring 90d",
                                   "Head-Leases Expiring 90d",
                                   "New Agreements This Month",
                                   "Ending This Month",
                                   "Pending GM Approval"],
            "Team Oversight": ["Arrears (QAR)", "Open Requests",
                               "Maintenance Aged 48h+",
                               "Docs Expiring Soon"],
        },
        "shortcuts": ["Tenant Rental Agreement", "Customer", "Unit",
                      "Building", "Maintenance Request"],
        "charts": ["Occupied Units by Building"],
        "reports": [],
    },
    "Legal Docs": {
        "icon": "legal",
        "roles": ["Legal and Documentation", "Managing Director"],
        "sequence_id": 32.0,
        "ncards": {
            "Document Health": ["Docs Expiring Soon", "Docs Expired",
                                "Docs Missing"],
            "Agreements": ["Draft Tenant Agreements",
                           "Draft Landlord Contracts",
                           "Pending GM Approval", "Pending MD Approval"],
        },
        "shortcuts": ["Document Register", "Tenant Rental Agreement",
                      "Landlord Contract", "Building", "Customer",
                      "Supplier"],
        "charts": ["Documents by Status"],
        "reports": [],
    },
    "Maintenance Desk": {
        "icon": "tool",
        "roles": ["Maintenance", "Managing Director"],
        "sequence_id": 33.0,
        "ncards": {
            "Requests": ["Open Requests", "In Progress",
                         "Maintenance Aged 48h+", "Resolved This Month",
                         "Maintenance Spend This Month (QAR)"],
        },
        "shortcuts": ["Maintenance Request", "Building", "Unit"],
        "charts": ["Open Maintenance by Building"],
        "reports": [],
    },
}


def execute():
    _make_cards()
    _make_charts()
    for title, spec in WORKSPACES.items():
        _make_workspace(title, spec)
    frappe.db.commit()


def _make_cards():
    for c in CARDS:
        if frappe.db.exists("Number Card", {"label": c["label"]}):
            continue
        dt = c.get("document_type")
        if dt and not frappe.db.exists("DocType", dt):
            continue
        doc = dict(c)
        doc.update({"doctype": "Number Card", "is_public": 1,
                    "show_percentage_stats": 0,
                    "stats_time_interval": "Daily"})
        frappe.get_doc(doc).insert(ignore_permissions=True)


def _make_charts():
    for c in CHARTS:
        if frappe.db.exists("Dashboard Chart", c["chart_name"]):
            continue
        if not frappe.db.exists("DocType", c["document_type"]):
            continue
        doc = dict(c)
        doc.update({"doctype": "Dashboard Chart", "is_public": 1,
                    "timeseries": 0})
        frappe.get_doc(doc).insert(ignore_permissions=True)


def _card_name(label):
    return frappe.db.get_value("Number Card", {"label": label}, "name")


def _make_workspace(title, spec):
    if frappe.db.exists("Workspace", title):
        return

    blocks = [_qlist("My To-Dos", col=4), _spacer()]
    number_cards, charts, shortcuts, links = [], [], [], []

    for section, labels in spec["ncards"].items():
        blocks.append(_header(section))
        for label in labels:
            name = _card_name(label)
            if not name:
                continue
            blocks.append(_ncard(name))
            number_cards.append({"number_card_name": name, "label": label})

    if spec["charts"]:
        blocks.append(_header("Charts"))
        for ch in spec["charts"]:
            if frappe.db.exists("Dashboard Chart", ch):
                blocks.append(_chart(ch))
                charts.append({"chart_name": ch, "label": ch})

    blocks.append(_header("Shortcuts"))
    for dt in spec["shortcuts"]:
        if frappe.db.exists("DocType", dt):
            blocks.append(_shortcut(dt))
            shortcuts.append({"type": "DocType", "link_to": dt,
                              "label": dt})

    if spec["reports"]:
        blocks.append(_header("Reports"))
        blocks.append(_card("Reports"))
        links.append({"type": "Card Break", "label": "Reports",
                      "link_count": len(spec["reports"])})
        for rp in spec["reports"]:
            links.append({"type": "Link", "link_type": "Report",
                          "link_to": rp, "label": rp,
                          "is_query_report": 1})

    ws = frappe.get_doc({
        "doctype": "Workspace",
        "title": title,
        "label": title,
        "public": 1,
        "module": "Darkbrown",
        "icon": spec["icon"],
        "indicator_color": "green",
        "sequence_id": spec["sequence_id"],
        "content": json.dumps(blocks),
        "roles": [{"role": r} for r in spec["roles"]
                  if frappe.db.exists("Role", r)],
        "number_cards": number_cards,
        "charts": charts,
        "shortcuts": shortcuts,
        "links": links,
        "quick_lists": [{"document_type": "ToDo", "label": "My To-Dos"}],
    })
    ws.insert(ignore_permissions=True)
