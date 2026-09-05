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
    if acc:
        return acc, False
    # A site can genuinely lack one if the chart was built for a business that
    # only ever invoices out. Creating it is better than stopping the load.
    parent = (frappe.db.get_value("Account", {"account_name": "Accounts Payable",
                                              "company": company_name,
                                              "is_group": 1}, "name")
              or frappe.db.get_value("Account", {"account_name":
                                                 "Current Liabilities",
                                                 "company": company_name,
                                                 "is_group": 1}, "name")
              or frappe.db.get_value("Account", {"root_type": "Liability",
                                                 "company": company_name,
                                                 "is_group": 1}, "name"))
    if not parent:
        frappe.throw("No liability group account on %s to file Creditors under."
                     % company_name)
    doc = frappe.get_doc({"doctype": "Account", "account_name": "Creditors",
                          "company": company_name, "parent_account": parent,
                          "root_type": "Liability", "account_type": "Payable",
                          "is_group": 0})
    doc.flags.ignore_permissions = True
    return doc.insert().name, True


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


def cost_centre_for(building):
    """The building's cost centre, written onto the Building if it is missing.

    `Building.cost_center` is read-only and only the after_insert hook writes
    it, so a Building created any other way carries none and every posting
    lands without one - which is what breaks per-building P&L.
    """
    existing = frappe.db.get_value("Building", building, "cost_center")
    if existing and frappe.db.exists("Cost Center", existing):
        return existing, False
    company_name = company()
    abbr = frappe.get_cached_value("Company", company_name, "abbr")
    name = "%s - %s" % (building, abbr)
    if not frappe.db.exists("Cost Center", name):
        parent = frappe.db.get_value("Cost Center",
                                     {"company": company_name, "is_group": 1},
                                     "name")
        if not parent:
            return None, False
        frappe.get_doc({"doctype": "Cost Center", "cost_center_name": building,
                        "company": company_name, "parent_cost_center": parent,
                        "is_group": 0}).insert(ignore_permissions=True)
    frappe.db.set_value("Building", building, "cost_center", name)
    return name, True


def ensure_purchasable(code):
    """An Item flagged sales-only is refused on a Purchase Invoice."""
    row = frappe.db.get_value("Item", code, ["is_purchase_item", "disabled"],
                              as_dict=True)
    if not row:
        return False
    fixed = False
    if not row.is_purchase_item:
        frappe.db.set_value("Item", code, "is_purchase_item", 1)
        fixed = True
    if row.disabled:
        frappe.db.set_value("Item", code, "disabled", 0)
        fixed = True
    return fixed


def ensure_fiscal_years(dates):
    """Calendar years covering every date, created if absent."""
    from frappe.utils import getdate
    fys = frappe.get_all("Fiscal Year", fields=["year_start_date",
                                                "year_end_date"])
    calendar = all(getdate(f.year_start_date).month == 1 for f in fys) if fys \
        else True
    made = []
    for d in sorted({str(x)[:10] for x in dates if x}):
        if any(str(f.year_start_date) <= d <= str(f.year_end_date)
               for f in fys):
            continue
        year = int(d[:4])
        if not calendar or frappe.db.exists("Fiscal Year", str(year)):
            continue
        frappe.get_doc({"doctype": "Fiscal Year", "year": str(year),
                        "year_start_date": "%d-01-01" % year,
                        "year_end_date": "%d-12-31" % year}).insert(
                            ignore_permissions=True)
        fys.append(frappe._dict({"year_start_date": "%d-01-01" % year,
                                 "year_end_date": "%d-12-31" % year}))
        made.append(str(year))
    return made


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
