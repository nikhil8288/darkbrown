"""Cross-department to-do handoffs (T1, T3-T5) and the grace-period
alert (N5, no stored date field so it can't be a native Notification).

Assignment = frappe assign_to.add -> creates a ToDo + bell for the
assignee. Round-robin by least open to-dos among users holding the
target role."""

import frappe
from frappe.desk.form import assign_to
from frappe.utils import add_days, getdate, nowdate


# ------------------------------------------------------------ helpers

def _role_users(role):
    users = frappe.get_all(
        "Has Role",
        filters={"role": role, "parenttype": "User"},
        fields=["parent"], pluck="parent")
    return [u for u in users
            if u not in ("Administrator", "Guest")
            and frappe.db.get_value("User", u, "enabled")]


def _least_loaded(users):
    if not users:
        return None
    loads = {u: frappe.db.count("ToDo", {"allocated_to": u,
                                         "status": "Open"})
             for u in users}
    return min(loads, key=loads.get)


def _assign(doctype, name, role, description):
    user = _least_loaded(_role_users(role))
    if not user:
        return
    try:
        assign_to.add({"assign_to": [user], "doctype": doctype,
                       "name": name, "description": description},
                      ignore_permissions=True)
    except assign_to.DuplicateToDoError:
        pass
    except Exception:
        frappe.log_error(title=f"handoff assign failed: {doctype} {name}")


def _already_assigned(doctype, name):
    return frappe.db.exists("ToDo", {"reference_type": doctype,
                                     "reference_name": name,
                                     "status": "Open"})


# ------------------------------------------------- T1: new maintenance

def t1_assign_maintenance(doc, method=None):
    """after_insert on Maintenance Request -> Maintenance team to-do."""
    _assign("Maintenance Request", doc.name, "Maintenance",
            f"New maintenance request: {doc.issue or doc.name} "
            f"({doc.building or ''})")


# ------------------------------------------------- T5: bounced cheque

def t5_assign_bounced(doc, method=None):
    """on_update on PDC Cheque -> recovery to-do for Accounts."""
    if doc.status != "Bounced" or not doc.has_value_changed("status"):
        return
    _assign("PDC Cheque", doc.name, "Accounts",
            f"Bounced cheque {doc.cheque_number or doc.name} "
            f"({doc.party or ''}) - start recovery")


# ------------------------------------- T3/T4: daily expiry-driven todos

def daily_renewal_todos():
    """T3: tenant agreement hits 30 days to expiry -> GM renewal task."""
    target = add_days(nowdate(), 30)
    for a in frappe.get_all("Tenant Rental Agreement",
                            filters={"status": "Active",
                                     "end_date": target},
                            fields=["name", "tenant", "building"]):
        if not _already_assigned("Tenant Rental Agreement", a.name):
            _assign("Tenant Rental Agreement", a.name, "General Manager",
                    f"Agreement {a.name} ({a.tenant or ''}, "
                    f"{a.building or ''}) expires in 30 days - "
                    f"decide renewal")


def daily_document_todos():
    """T4: a party's QID / passport / contract copy hits 30 days to
    expiry -> Legal task. (Originally read expiry_date off the old
    building-documents register; that schema was replaced by the intake
    register, so this now reads Party Document rows.)"""
    if not frappe.db.exists("DocType", "Party Document"):
        return
    target = add_days(nowdate(), 30)
    for d in frappe.get_all("Party Document",
                            filters={"expiry_date": target},
                            fields=["name", "parent", "parenttype",
                                    "document_type", "id_number",
                                    "holder_name"]):
        if not _already_assigned(d.parenttype, d.parent):
            _assign(d.parenttype, d.parent,
                    "Legal and Documentation",
                    f"{d.document_type} expiring in 30 days: "
                    f"{d.holder_name or d.parent} ({d.id_number or ''}) - renew")


# ------------------------------------------------ N5: grace period end

def grace_period_alerts():
    """Bell to Accounts + GM 7 days before a head-lease grace window
    ends (grace end = contract_start_date + grace_period_days)."""
    for lc in frappe.get_all("Landlord Contract",
                             filters={"status": "Active"},
                             fields=["name", "building",
                                     "contract_start_date",
                                     "grace_period_days"]):
        if not (lc.contract_start_date and lc.grace_period_days):
            continue
        grace_end = add_days(getdate(lc.contract_start_date),
                             int(lc.grace_period_days))
        if getdate(nowdate()) != add_days(grace_end, -7):
            continue
        subject = (f"Grace period on {lc.name} ({lc.building or ''}) "
                   f"ends {grace_end} - rent starts")
        for role in ("Accounts", "General Manager"):
            for user in _role_users(role):
                frappe.get_doc({
                    "doctype": "Notification Log",
                    "for_user": user,
                    "type": "Alert",
                    "subject": subject,
                    "document_type": "Landlord Contract",
                    "document_name": lc.name,
                }).insert(ignore_permissions=True)
