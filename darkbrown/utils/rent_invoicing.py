"""Monthly rent invoicing — runs on the 1st of every month.

Tenant side    one draft Sales Invoice per Active Tenant Rental
               Agreement for the current month.
Landlord side  one draft Purchase Invoice per Active Landlord Contract,
               skipped while the contract is still inside its grace
               period (grace_period_days from contract start).

Safety rails
    GENERATION_START  nothing generates for periods before Jul-2026;
                      the Excel books own everything earlier.
    AUTO_SUBMIT       False. Everything lands as Draft for Accounts to
                      review and submit until the job is trusted.
    Idempotent        custom_billing_period + agreement/contract link on
                      the invoice; re-runs and manual replays are no-ops.
                      (Custom fields created by patch
                      create_invoice_custom_fields.)

Manual replay from bench console:
    from darkbrown.utils.rent_invoicing import generate_monthly_invoices
    generate_monthly_invoices()            # current month
    generate_monthly_invoices("2026-08-01")  # specific month
"""

import frappe
from frappe.utils import getdate, nowdate, get_first_day, get_last_day, flt, cint, add_days

GENERATION_START = "2026-07-01"
AUTO_SUBMIT = False

TENANT_ITEM = "Rent"
LANDLORD_ITEM = "Landlord Rent"
INCOME_ACCOUNT = "Rent Income"      # under Direct Income
EXPENSE_ACCOUNT = "Landlord Rent"   # under Direct Expenses


def _company():
    return frappe.db.get_value("Company", {}, ["name", "abbr"], as_dict=True)


def _account(base, abbr):
    name = "%s - %s" % (base, abbr)
    return name if frappe.db.exists("Account", name) else None


def _cost_center(building, abbr):
    return (frappe.db.get_value("Cost Center",
                                {"cost_center_name": building, "is_group": 0},
                                "name")
            or frappe.db.get_value("Company", {}, "cost_center"))


def _period(anchor=None):
    d = getdate(anchor or nowdate())
    start, end = get_first_day(d), get_last_day(d)
    return start, end, start.strftime("%Y-%m")


def generate_monthly_invoices(anchor=None):
    """Scheduler entry point (monthly = 1st of month in Frappe)."""
    start, end, period = _period(anchor)
    if start < getdate(GENERATION_START):
        return  # pre-ERP months belong to the Excel books

    co = _company()
    made_si = _tenant_invoices(start, end, period, co)
    made_pi = _landlord_invoices(start, end, period, co)
    frappe.db.commit()
    frappe.logger("darkbrown").info(
        "rent_invoicing %s: %d sales, %d purchase" % (period, made_si, made_pi))


# ------------------------------------------------------------- tenant side

def _tenant_invoices(start, end, period, co):
    made = 0
    income = _account(INCOME_ACCOUNT, co.abbr)
    for a in frappe.get_all(
            "Tenant Rental Agreement", filters={"status": "Active"},
            fields=["name", "tenant", "building", "unit", "monthly_rent",
                    "start_date", "end_date"]):
        rent = flt(a.monthly_rent)
        if rent <= 0:
            continue
        # lease must overlap the month
        if (a.start_date and getdate(a.start_date) > end) or \
           (a.end_date and getdate(a.end_date) < start):
            continue
        if frappe.db.exists("Sales Invoice",
                            {"custom_rental_agreement": a.name,
                             "custom_billing_period": period,
                             "docstatus": ["<", 2]}):
            continue

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": a.tenant,
            "company": co.name,
            "posting_date": start,
            "due_date": start,
            "custom_rental_agreement": a.name,
            "custom_billing_period": period,
            "cost_center": _cost_center(a.building, co.abbr),
            "items": [{
                "item_code": TENANT_ITEM,
                "qty": 1,
                "rate": rent,
                "income_account": income,
                "cost_center": _cost_center(a.building, co.abbr),
                "description": "Rent %s — %s / %s" % (period, a.building,
                                                      a.unit or ""),
            }],
        })
        si.flags.ignore_permissions = True
        si.insert()
        if AUTO_SUBMIT:
            si.submit()
        made += 1
    return made


# ----------------------------------------------------------- landlord side

def _landlord_invoices(start, end, period, co):
    made = 0
    expense = _account(EXPENSE_ACCOUNT, co.abbr)
    for c in frappe.get_all(
            "Landlord Contract", filters={"status": "Active"},
            fields=["name", "landlord", "building", "total_owner_rent",
                    "contract_start_date", "contract_end_date",
                    "grace_period_days"]):
        amt = flt(c.total_owner_rent)
        if amt <= 0:
            continue
        if (c.contract_start_date and getdate(c.contract_start_date) > end) or \
           (c.contract_end_date and getdate(c.contract_end_date) < start):
            continue
        # grace: nothing is payable while the whole month sits inside the
        # grace window (contract start + grace_period_days)
        g = cint(c.grace_period_days)
        if g and c.contract_start_date and \
                getdate(add_days(c.contract_start_date, g)) >= end:
            continue
        if frappe.db.exists("Purchase Invoice",
                            {"custom_landlord_contract": c.name,
                             "custom_billing_period": period,
                             "docstatus": ["<", 2]}):
            continue

        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": c.landlord,
            "company": co.name,
            "posting_date": start,
            "due_date": start,
            "custom_landlord_contract": c.name,
            "custom_billing_period": period,
            "cost_center": _cost_center(c.building, co.abbr),
            "items": [{
                "item_code": LANDLORD_ITEM,
                "qty": 1,
                "rate": amt,
                "expense_account": expense,
                "cost_center": _cost_center(c.building, co.abbr),
                "description": "Head-lease rent %s — %s" % (period,
                                                            c.building),
            }],
        })
        pi.flags.ignore_permissions = True
        pi.insert()
        if AUTO_SUBMIT:
            pi.submit()
        made += 1
    return made
