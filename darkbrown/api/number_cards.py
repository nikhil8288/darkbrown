"""Whitelisted methods backing Custom Number Cards on the role
workspaces. Each returns {"value": n, "fyi": ""} per the Number Card
Custom-type contract."""

import frappe
from frappe.utils import add_days, nowdate


def _card(value, fyi=""):
    return {"value": value, "fyi": fyi}


def _active_tra_units():
    return {r.unit for r in frappe.get_all(
        "Tenant Rental Agreement", filters={"status": "Active"},
        fields=["unit"]) if r.unit}


@frappe.whitelist()
def vacant_units():
    total = frappe.db.count("Unit")
    return _card(max(total - len(_active_tra_units()), 0))


@frappe.whitelist()
def occupancy_pct():
    total = frappe.db.count("Unit")
    occ = len(_active_tra_units())
    return _card(round(occ * 100.0 / total, 1) if total else 0)


@frappe.whitelist()
def arrears_total():
    val = frappe.db.sql(
        """select ifnull(sum(outstanding_amount), 0)
           from `tabSales Invoice`
           where docstatus = 1 and outstanding_amount > 0
             and due_date < %s""", nowdate())[0][0]
    return _card(round(val or 0))


@frappe.whitelist()
def maintenance_aged_48h():
    n = frappe.db.sql(
        """select count(*) from `tabMaintenance Request`
           where status in ('Open', 'In Progress')
             and ifnull(reported_on, creation)
                 < (now() - interval 48 hour)""")[0][0]
    return _card(n)


def _expiring(dt, date_field, days):
    return frappe.db.count(dt, {
        "status": "Active",
        date_field: ["between", [nowdate(), add_days(nowdate(), days)]],
    })


@frappe.whitelist()
def tra_expiring_30():
    return _card(_expiring("Tenant Rental Agreement", "end_date", 30))


@frappe.whitelist()
def tra_expiring_60():
    return _card(_expiring("Tenant Rental Agreement", "end_date", 60))


@frappe.whitelist()
def tra_expiring_90():
    return _card(_expiring("Tenant Rental Agreement", "end_date", 90))


@frappe.whitelist()
def headlease_expiring_90():
    return _card(_expiring("Landlord Contract", "contract_end_date", 90))


def _pending(state):
    n = 0
    for dt in ("Tenant Rental Agreement", "Landlord Contract"):
        if frappe.db.has_column(dt, "workflow_state"):
            n += frappe.db.count(dt, {"workflow_state": state})
    return n


@frappe.whitelist()
def pending_gm_approvals():
    return _card(_pending("Pending GM Approval"))


@frappe.whitelist()
def pending_md_approvals():
    return _card(_pending("Pending MD Approval"))
