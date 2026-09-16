"""Idempotent, non-posting launch accounting configuration.

ERPNext's Account and Mode of Payment records remain authoritative.  This
module adds only semantic leaves required by the locked launch model and maps
Cash/Cheque modes to their holding accounts.  It does not create a Bank
Account, tax template, voucher or GL Entry.
"""

import frappe


ACCOUNT_REQUIREMENTS = (
    ("rent_income", ("Rental Income", "Rent Income"), "Income",
     ("Direct Income", "Income")),
    ("security_deposit_liability", ("Security Deposits Held",), "Liability",
     ("Current Liabilities", "Liabilities")),
    ("tenant_recharge", ("Tenant Recharge Income", "Tenant Recharges"), "Income",
     ("Direct Income", "Income")),
    ("cheque_clearing", ("Cheques in Hand", "Cheque Clearing"), "Asset",
     ("Cash and Bank Accounts", "Current Assets", "Assets")),
)


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or (frappe.get_all("Company", limit=1) or [{}])[0].get("name"))


def _parent(company, root_type, preferred):
    for label in preferred:
        name = frappe.db.get_value("Account", {
            "company": company, "account_name": label, "is_group": 1,
        }, "name")
        if name:
            return name
    return (frappe.db.get_value("Account", {
        "company": company, "root_type": root_type, "is_group": 1,
        "parent_account": ["is", "not set"],
    }, "name") or frappe.db.get_value("Account", {
        "company": company, "root_type": root_type, "is_group": 1,
    }, "name"))


def _ensure_account(company, labels, root_type, preferred_parents):
    for label in labels:
        existing = frappe.db.get_value(
            "Account", {"company": company, "account_name": label},
            ["name", "root_type", "is_group"], as_dict=True)
        if not existing:
            continue
        if existing.root_type != root_type or existing.is_group:
            frappe.throw(
                f"{label} exists but is not a {root_type} leaf account.")
        return existing.name
    label = labels[0]
    parent = _parent(company, root_type, preferred_parents)
    if not parent:
        frappe.throw(f"No {root_type} group exists for {label}.")
    return frappe.get_doc({
        "doctype": "Account", "account_name": label, "company": company,
        "parent_account": parent, "root_type": root_type, "is_group": 0,
    }).insert(ignore_permissions=True).name


def _find_cash_account(company):
    for label in ("Cash Clearing", "Cash in Hand"):
        account = frappe.db.get_value("Account", {
            "company": company, "account_name": label, "is_group": 0,
        }, "name")
        if account:
            return account
    # Localized charts often name the standard cash leaf differently.  Its
    # ERPNext account_type is the stable semantic signal, so reuse it rather
    # than creating a duplicate merely to obtain an English label.
    return frappe.db.get_value("Account", {
        "company": company, "account_type": "Cash", "is_group": 0,
        "disabled": 0,
    }, "name")


def _map_mode(company, mode, account):
    if not account or not frappe.db.exists("Mode of Payment", mode):
        return False
    existing = frappe.db.get_value("Mode of Payment Account", {
        "parent": mode, "company": company,
    }, ["name", "default_account"], as_dict=True)
    if existing:
        if mode == "Cash":
            mapped = frappe.db.get_value("Account", existing.default_account,
                                         ["root_type", "account_type", "is_group", "disabled"],
                                         as_dict=True)
            if mapped and mapped.root_type == "Asset" and \
                    mapped.account_type == "Cash" and not mapped.is_group and \
                    not mapped.disabled:
                return False
        if existing.default_account != account:
            frappe.throw(
                f"Mode of Payment {mode} is mapped to an unexpected account.")
        return False
    doc = frappe.get_doc("Mode of Payment", mode)
    doc.append("accounts", {"company": company, "default_account": account})
    doc.save(ignore_permissions=True)
    return True


def ensure_launch_foundation(company=None):
    """Create missing semantic accounts and mode mappings, never vouchers."""
    company = company or _company()
    if not company:
        return {"configured": False, "reason": "no_company"}
    if frappe.db.get_value("Company", company, "default_currency") != "QAR":
        frappe.throw("DarkBrown launch accounting requires a QAR company.")

    accounts = {}
    for role, labels, root_type, parents in ACCOUNT_REQUIREMENTS:
        accounts[role] = _ensure_account(company, labels, root_type, parents)
    cash = _find_cash_account(company)
    if not cash:
        frappe.throw("A Cash in Hand or Cash Clearing account is required.")
    mapped = {
        "Cash": _map_mode(company, "Cash", cash),
        "Cheque": _map_mode(company, "Cheque", accounts["cheque_clearing"]),
    }
    return {"configured": True, "accounts": accounts,
            "cash_account": cash, "mode_mappings_created": mapped}
