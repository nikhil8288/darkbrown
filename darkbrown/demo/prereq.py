"""What has to exist before any DarkBrown record can be written.

A fresh ERPNext site usually has a company from the setup wizard and little
else. This makes sure there is a company in QAR, two bank accounts to deposit
into, the modes of payment the finance module names, and a DBR Settings
singleton pointing at all of it.

Everything is find-or-create. Running it twice changes nothing the second
time.
"""

import frappe

COMPANY = "DarkBrown Real Estate"
ABBR = "DBR"
CURRENCY = "QAR"

# Two banks, because the real business runs two and the reconciliation story
# only makes sense with more than one.
BANKS = [
    {"bank": "Qatar National Bank", "account_name": "QNB Current — Operations",
     "iban": "QA12QNBA000000000000011122233"},
    {"bank": "Doha Bank", "account_name": "Doha Bank Current — Collections",
     "iban": "QA44DOHB000000000000055566677"},
]

MODES = ["Cash", "Cheque", "Bank Transfer"]


def ensure(verbose=True):
    company = _company()
    accounts = [_bank_account(b, company) for b in BANKS]
    _modes()
    _settings(company, accounts[0])
    frappe.db.commit()

    if verbose:
        print(f"  company        {company}")
        for a in accounts:
            print(f"  bank account   {a}")
    return {"company": company, "bank_accounts": accounts}


# ------------------------------------------------------------------- company

def _company():
    existing = frappe.db.get_single_value("DBR Settings", "default_company")
    if existing and frappe.db.exists("Company", existing):
        return existing

    name = frappe.db.get_value("Company", {"default_currency": CURRENCY}, "name") \
        or frappe.db.get_value("Company", {}, "name")
    if name:
        return name

    doc = frappe.get_doc({
        "doctype": "Company",
        "company_name": COMPANY,
        "abbr": ABBR,
        "default_currency": CURRENCY,
        "country": "Qatar",
        "create_chart_of_accounts_based_on": "Standard Template",
        "chart_of_accounts": "Standard",
    })
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return doc.name


# -------------------------------------------------------------- bank account

def _bank_account(spec, company):
    if not frappe.db.exists("Bank", spec["bank"]):
        frappe.get_doc({"doctype": "Bank", "bank_name": spec["bank"]}) \
            .insert(ignore_permissions=True)

    name = f"{spec['account_name']} - {spec['bank']}"
    if frappe.db.exists("Bank Account", name):
        return name

    gl = _gl_bank_account(company)
    doc = frappe.get_doc({
        "doctype": "Bank Account",
        "account_name": spec["account_name"],
        "bank": spec["bank"],
        "is_company_account": 1,
        "company": company,
        "account": gl,
        "iban": spec["iban"],
    })
    doc.flags.ignore_mandatory = True
    return doc.insert(ignore_permissions=True).name


def _gl_bank_account(company):
    """The ledger account behind the bank account. Payment Entry posts here."""
    return (frappe.db.get_value("Company", company, "default_bank_account")
            or frappe.db.get_value("Account", {"company": company,
                                               "account_type": "Bank",
                                               "is_group": 0}, "name")
            or frappe.db.get_value("Account", {"company": company,
                                               "account_type": "Cash",
                                               "is_group": 0}, "name"))


# ------------------------------------------------------------------- payment

def _modes():
    for mode in MODES:
        if frappe.db.exists("Mode of Payment", mode):
            continue
        frappe.get_doc({
            "doctype": "Mode of Payment",
            "mode_of_payment": mode,
            "type": "Cash" if mode == "Cash" else "Bank",
        }).insert(ignore_permissions=True)


# ------------------------------------------------------------------ settings

def _settings(company, bank_account):
    doc = frappe.get_single("DBR Settings")
    doc.default_company = company
    doc.default_bank_account = bank_account
    if not doc.amendment_md_threshold:
        # Q14 sits open at a provisional QAR 50,000. The demo runs on that
        # figure so the routing can be seen working; change it here when the
        # number is confirmed.
        doc.amendment_md_threshold = 50000
    doc.flags.ignore_mandatory = True
    doc.save(ignore_permissions=True)
