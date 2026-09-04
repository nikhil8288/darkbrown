"""Accounts the history loaders post to. One place, so income and cost land
where the P&L can see them and every loader agrees on the names.

Nothing here is an opening entry. The site was emptied and AK-12 is the whole
ledger, so the nine months of history ARE the books: rent is income, the head
lease is cost, and the statements derive from that with no manual layer to
double-count against.
"""
import frappe

INCOME_ACCOUNT = "Rental Income"
EXPENSE_ACCOUNT = "Head Lease Rent"


def company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or frappe.get_all("Company", limit=1)[0].name)


def _leaf_under(root_type, name, company_name, prefer_groups):
    """A leaf account called `name`; created under the first matching group
    if absent. Never a root, never a group."""
    acc = frappe.db.get_value("Account", {"account_name": name,
                                          "company": company_name,
                                          "is_group": 0}, "name")
    if acc:
        return acc, False
    parent = None
    for g in prefer_groups:
        parent = frappe.db.get_value("Account", {"account_name": g,
                                                 "company": company_name,
                                                 "is_group": 1}, "name")
        if parent:
            break
    if not parent:
        parent = frappe.db.get_value("Account", {"root_type": root_type,
                                                 "company": company_name,
                                                 "is_group": 1}, "name")
    if not parent:
        frappe.throw("No %s group account on %s to file %r under."
                     % (root_type, company_name, name))
    doc = frappe.get_doc({"doctype": "Account", "account_name": name,
                          "company": company_name, "parent_account": parent,
                          "root_type": root_type, "is_group": 0})
    doc.flags.ignore_permissions = True
    return doc.insert().name, True


def income_account(company_name):
    return _leaf_under("Income", INCOME_ACCOUNT, company_name,
                       ("Direct Income", "Income"))


def expense_account(company_name):
    return _leaf_under("Expense", EXPENSE_ACCOUNT, company_name,
                       ("Direct Expenses", "Expenses"))


def receivable(company_name):
    acc = frappe.db.get_value("Account", {"account_type": "Receivable",
                                          "company": company_name,
                                          "is_group": 0}, "name")
    if not acc:
        frappe.throw("No receivable Account for %s." % company_name)
    return acc


def payable(company_name):
    acc = frappe.db.get_value("Account", {"account_type": "Payable",
                                          "company": company_name,
                                          "is_group": 0}, "name")
    if not acc:
        frappe.throw("No payable Account for %s." % company_name)
    return acc


def cash_account(company_name):
    """Same choice api.finance._paid_to makes with no bank account set."""
    bank = frappe.db.get_single_value("DBR Settings", "default_bank_account")
    if bank:
        gl = frappe.db.get_value("Bank Account", bank, "account")
        if gl:
            return gl
        if frappe.db.exists("Account", bank):
            return bank
    return (frappe.db.get_value("Account", {"company": company_name,
                                            "account_type": "Bank",
                                            "is_group": 0}, "name")
            or frappe.db.get_value("Account", {"company": company_name,
                                               "account_type": "Cash",
                                               "is_group": 0}, "name"))


def item(code, sales, purchase):
    """The non-stock service Item the invoice line uses. Same two the live
    invoicer uses ("Rent", "Landlord Rent"), created if setup never ran."""
    if frappe.db.exists("Item", code):
        return code
    group = (frappe.db.get_value("Item Group", {"item_group_name": "Services"},
                                 "name")
             or frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
    doc = frappe.get_doc({"doctype": "Item", "item_code": code,
                          "item_name": code, "item_group": group,
                          "stock_uom": "Nos", "is_stock_item": 0,
                          "is_sales_item": 1 if sales else 0,
                          "is_purchase_item": 1 if purchase else 0})
    doc.flags.ignore_mandatory = True
    return doc.insert(ignore_permissions=True).name


def cost_center(building):
    return frappe.db.get_value("Building", building, "cost_center") or None
