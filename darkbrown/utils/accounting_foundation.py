"""Read-only launch accounting foundation audit.

ERPNext remains the ledger. This module names the minimum semantic roles that
DarkBrown workflows will use and inspects an existing company configuration;
it deliberately creates and posts nothing.
"""

import frappe


ACCOUNT_ROLES = {
    "receivable_control": ("Receivable", ("Debtors", "Accounts Receivable")),
    "payable_control": ("Payable", ("Creditors", "Accounts Payable")),
    "rent_income": ("Income", ("Rental Income", "Rent Income")),
    "head_lease_expense": ("Expense", ("Head Lease Rent",)),
    "security_deposit_liability": ("Liability", ("Security Deposits Held",)),
    "tenant_recharge": ("Income", ("Tenant Recharge Income", "Tenant Recharges")),
    "maintenance_expense": ("Expense", ("Building Maintenance",)),
    "cash_clearing": ("Asset", ("Cash Clearing", "Cash in Hand")),
    "cheque_clearing": ("Asset", ("Cheques in Hand", "Cheque Clearing")),
}


def _find_account(company, names):
    for name in names:
        account = frappe.db.get_value(
            "Account", {"company": company, "account_name": name,
                        "is_group": 0}, "name")
        if account:
            return account
    return None


def audit(company=None):
    """Return sanitized configuration facts; do not include balances or parties."""
    company = (company or frappe.db.get_single_value("DBR Settings", "default_company")
               or frappe.defaults.get_user_default("Company"))
    if not company or not frappe.db.exists("Company", company):
        return {"ok": False, "company_configured": False,
                "missing": ["company"]}

    company_row = frappe.db.get_value(
        "Company", company,
        ["default_currency", "default_receivable_account",
         "default_payable_account", "cost_center"], as_dict=True)
    accounts = {role: _find_account(company, candidates)
                for role, (_root, candidates) in ACCOUNT_ROLES.items()}
    # Company defaults are authoritative when populated, even when their
    # localized labels are not among the candidate names above.
    accounts["receivable_control"] = (company_row.default_receivable_account
                                      or accounts["receivable_control"])
    accounts["payable_control"] = (company_row.default_payable_account
                                   or accounts["payable_control"])
    fiscal_year = frappe.db.exists("Fiscal Year", {
        "year_start_date": ["<=", frappe.utils.today()],
        "year_end_date": [">=", frappe.utils.today()], "disabled": 0})
    cost_center_root = frappe.db.exists("Cost Center", {
        "company": company, "is_group": 1})
    tax_templates = frappe.db.count("Sales Taxes and Charges Template", {
        "company": company, "disabled": 0})
    modes = {mode: bool(frappe.db.exists("Mode of Payment", mode))
             for mode in ("Cash", "Cheque", "Bank Transfer")}
    missing = [role for role, account in accounts.items() if not account]
    if not fiscal_year:
        missing.append("current_fiscal_year")
    if not cost_center_root:
        missing.append("cost_center_hierarchy")
    return {
        "ok": company_row.default_currency == "QAR" and not missing,
        "company_configured": True,
        "currency": company_row.default_currency,
        "accounts": accounts,
        "modes_of_payment": modes,
        "current_fiscal_year": bool(fiscal_year),
        "cost_center_hierarchy": bool(cost_center_root),
        "enabled_sales_tax_templates": tax_templates,
        "missing": missing,
    }
