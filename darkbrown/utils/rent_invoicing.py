# WARNING: only monthly_reminder is wired, through hooks.py.
# The invoice building below is a second copy of what
# api.finance._rent_invoice does, and it is the copy that does NOT
# run. Two builders for one invoice is how a fix lands in the wrong
# one. Fold this into api.finance and delete the rest.

"""Rent invoicing.

Invoices are generated one building at a time, once per period. The run is
drafted first so the numbers can be read before anything is posted; any line
that differs from the agreement carries a typed reason and needs the General
Manager before the run may issue.

Nothing here writes to the general ledger directly. Sales Invoice does that,
which keeps ERPNext the owner of the ledger.
"""

import frappe
from frappe.utils import (today, getdate, add_days, add_months, flt,
                          get_first_day, get_last_day)


def _company(building):
    return (frappe.db.get_value("Building", building, "company")
            or frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_user_default("Company"))


def _income_account(company):
    return frappe.db.get_value(
        "Company", company, "default_income_account") or frappe.db.get_value(
        "Account", {"company": company, "account_name": "Sales",
                    "is_group": 0}, "name")


def active_tenancies(building, period_start, period_end):
    return frappe.get_all(
        "Tenancy Agreement",
        filters={
            "building": building,
            "status": ["in", ("Active", "Expiring")],
            "start_date": ["<=", period_end],
            "end_date": [">=", period_start],
        },
        fields=["name", "tenant", "unit", "monthly_rent", "start_date",
                "end_date"])


def _prorate(ta, period_start, period_end):
    """A tenancy that starts or ends mid-period is billed for the days it
    actually covers, not the whole month."""
    days_in_period = frappe.utils.date_diff(period_end, period_start) + 1
    covered_from = max(getdate(ta.start_date), getdate(period_start))
    covered_to = min(getdate(ta.end_date), getdate(period_end))
    covered = frappe.utils.date_diff(covered_to, covered_from) + 1
    if covered >= days_in_period:
        return flt(ta.monthly_rent), False
    return flt(ta.monthly_rent) * covered / days_in_period, True


def _recharges(tenant, building):
    """Maintenance recharges ride on the next rent invoice as their own line."""
    return frappe.get_all(
        "Maintenance Request",
        filters={"recharge_to": tenant, "building": building,
                 "rechargeable": 1, "recharge_status": "Pending",
                 "status": "Resolved"},
        fields=["name", "issue", "recharge_amount"])


@frappe.whitelist()
def build_run(building, period_start=None):
    """Draft an Invoice Run for one building. Creates nothing in the ledger."""
    period_start = getdate(period_start or get_first_day(today()))
    period_end = get_last_day(period_start)

    clash = frappe.db.exists("Invoice Run", {
        "building": building, "period_start": period_start,
        "status": ["!=", "Cancelled"]})
    if clash:
        frappe.throw(f"{building} has already been generated for this period "
                     f"as {clash}.")

    tenancies = active_tenancies(building, period_start, period_end)
    if not tenancies:
        frappe.throw(f"No active tenancies in {building} for this period.")

    run = frappe.get_doc({
        "doctype": "Invoice Run",
        "building": building,
        "company": _company(building),
        "period_start": period_start,
        "period_end": period_end,
        "status": "Draft",
    })

    for ta in tenancies:
        amount, prorated = _prorate(ta, period_start, period_end)
        extra = sum(flt(c.amount) for c in frappe.get_all(
            "Tenancy Charge", filters={"parent": ta.name,
                                       "frequency": "Monthly"},
            fields=["amount"]))
        recharge = sum(flt(r.recharge_amount)
                       for r in _recharges(ta.tenant, building))
        run.append("lines", {
            "tenancy_agreement": ta.name,
            "tenant": ta.tenant,
            "unit": ta.unit,
            "agreement_amount": flt(ta.monthly_rent) + extra,
            "invoice_amount": amount + extra + recharge,
            "reason": ("Prorated for part period." if prorated else
                       "Includes maintenance recharge." if recharge else ""),
        })

    run.insert()
    return run.name


@frappe.whitelist()
def issue_run(run_name):
    """Post the run. Allocation order is oldest invoice first, and within an
    invoice rent settles before recharge."""
    run = frappe.get_doc("Invoice Run", run_name)

    if run.status == "Issued":
        frappe.throw("This run has already been issued.")
    if run.has_variance and run.status != "Pending GM":
        frappe.throw("A run with variances needs the General Manager first.")
    if run.status == "Pending GM":
        roles = frappe.get_roles(frappe.session.user)
        if not ({"General Manager", "Managing Director"} & set(roles)):
            frappe.throw("Only the General Manager or the MD may issue a run "
                         "that carries variances.")

    company = run.company
    income = _income_account(company)
    cost_center = frappe.db.get_value("Building", run.building, "cost_center")
    made = 0

    for line in run.lines:
        if line.sales_invoice:
            continue
        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": line.tenant,
            "company": company,
            "posting_date": run.period_start,
            "due_date": run.period_start,
            "cost_center": cost_center,
            "remarks": f"Rent for {getdate(run.period_start):%B %Y} — "
                       f"{line.unit}, {run.building}",
            "items": [{
                "item_name": f"Rent — {line.unit}",
                "description": f"Monthly rent, {getdate(run.period_start):%B %Y}",
                "qty": 1,
                "rate": flt(line.invoice_amount),
                "income_account": income,
                "cost_center": cost_center,
                "uom": "Nos",
            }],
        })
        si.flags.ignore_mandatory = True
        si.insert(ignore_permissions=True)
        si.submit()
        line.db_set("sales_invoice", si.name)
        made += 1

    _close_recharges(run)
    run.db_set({"status": "Issued", "issued_on": frappe.utils.now(),
                "approved_by": frappe.session.user})
    return {"run": run.name, "invoices": made}


def _close_recharges(run):
    for line in run.lines:
        for r in _recharges(line.tenant, run.building):
            frappe.db.set_value("Maintenance Request", r.name,
                                "recharge_status", "Invoiced")


def monthly_reminder():
    """Scheduled. Does not generate anything — invoicing stays a decision a
    person takes per building, so this only says which buildings are due."""
    day = frappe.db.get_single_value("DBR Settings",
                                     "invoice_generation_day") or 1
    if getdate(today()).day != int(day):
        return

    period_start = get_first_day(today())
    pending = []
    for b in frappe.get_all("Building", filters={"status": "Active"},
                            pluck="name"):
        if not frappe.db.exists("Invoice Run", {
                "building": b, "period_start": period_start,
                "status": ["!=", "Cancelled"]}):
            pending.append(b)

    if not pending:
        return
    for user in _accounts_users():
        frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "type": "Alert",
            "subject": f"{len(pending)} buildings due for invoicing",
            "email_content": "Not yet generated this period: "
                             + ", ".join(pending),
        }).insert(ignore_permissions=True)
    frappe.db.commit()


def _accounts_users():
    return [r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ["in", ("Accounts", "Managing Director")]},
        fields=["parent"]) if "@" in (r.parent or "")]
