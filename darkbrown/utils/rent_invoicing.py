"""Rent invoicing: the generation calendar and the monthly reminder.

WHAT THIS MODULE USED TO BE

It carried a second, complete invoice builder - active_tenancies, _prorate,
_recharges, build_run, issue_run - duplicating api.finance.build_invoice_run /
_rent_invoice / issue_invoice_run. Its own header said so: "only
monthly_reminder is wired... it is the copy that does NOT run."

That dead copy was not harmless. It posted invoices dated today with a due date
inside the period, which core ERPNext rejects ("Due Date cannot be before
Posting"), and patches/run_july_billing.py worked around it by monkey-patching
validate_due_date to a no-op for the duration of a migrate. The live engine in
api.finance never had the bug - it posts at run.period_start and derives the
due date forward from there - so the workaround existed entirely to prop up
code nobody called.

The builder is gone. api.finance is the one engine.

WHAT REMAINS

GENERATION_START, because it is the date invoice generation begins rather than
a dashboard setting, and both api.charts and api.md_dashboard import it from
here so the two cannot drift.

monthly_reminder, which is wired through hooks.py. It generates nothing:
invoicing stays a decision a person takes per building, and this only says
which buildings are due.
"""

import frappe
from frappe.utils import today, getdate, get_first_day

# ERPNext starts carrying real money from this date. Before it, the manual
# Excel books are authoritative and live in Historical Monthly PL.
GENERATION_START = "2026-07-01"


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
