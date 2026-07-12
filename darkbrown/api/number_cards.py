"""Whitelisted methods backing Custom Number Cards on the role
workspaces.

Each returns a pre-formatted STRING, not {"value": n}: the v15 widget
(number_card_widget.js get_number_for_custom_card) renders non-object
returns verbatim, while object returns fall into currency formatting.
Strings give exact control ("97.1%", "QAR 12,345", plain counts)."""

import frappe
from frappe.utils import add_days, nowdate


@frappe.whitelist()
def vacant_units():
    # Same truth source as the MD dashboard: Unit.occupancy_status.
    return str(frappe.db.count("Unit", {"occupancy_status": "Vacant"}))


@frappe.whitelist()
def occupancy_pct():
    total = frappe.db.count("Unit")
    if not total:
        return "0%"
    vacant = frappe.db.count("Unit", {"occupancy_status": "Vacant"})
    return f"{round((total - vacant) * 100.0 / total, 1)}%"


@frappe.whitelist()
def arrears_total():
    val = frappe.db.sql(
        """select ifnull(sum(outstanding_amount), 0)
           from `tabSales Invoice`
           where docstatus = 1 and outstanding_amount > 0
             and due_date < %s""", nowdate())[0][0]
    return f"QAR {round(val or 0):,}"


@frappe.whitelist()
def maintenance_aged_48h():
    n = frappe.db.sql(
        """select count(*) from `tabMaintenance Request`
           where status in ('Open', 'In Progress')
             and ifnull(reported_on, creation)
                 < (now() - interval 48 hour)""")[0][0]
    return str(n)


def _expiring(dt, date_field, days):
    return frappe.db.count(dt, {
        "status": "Active",
        date_field: ["between", [nowdate(), add_days(nowdate(), days)]],
    })


@frappe.whitelist()
def tra_expiring_30():
    return str(_expiring("Tenant Rental Agreement", "end_date", 30))


@frappe.whitelist()
def tra_expiring_60():
    return str(_expiring("Tenant Rental Agreement", "end_date", 60))


@frappe.whitelist()
def tra_expiring_90():
    return str(_expiring("Tenant Rental Agreement", "end_date", 90))


@frappe.whitelist()
def headlease_expiring_90():
    return str(_expiring("Landlord Contract", "contract_end_date", 90))


def _pending(state):
    n = 0
    for dt in ("Tenant Rental Agreement", "Landlord Contract"):
        if frappe.db.has_column(dt, "workflow_state"):
            n += frappe.db.count(dt, {"workflow_state": state})
    return n


@frappe.whitelist()
def pending_gm_approvals():
    return str(_pending("Pending GM Approval"))


@frappe.whitelist()
def pending_md_approvals():
    return str(_pending("Pending MD Approval"))
