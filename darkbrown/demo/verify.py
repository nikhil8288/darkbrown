"""Did it work.

Two questions, asked separately.

First, does the boot payload carry every module? `api.app.seed` drops a module
that returns nothing, and the prototype then falls back to its own demo
figures — which looks fine on screen and hides the fact that nothing is
wired. A module missing from the payload after a seed is a failure, not a
fallback.

Second, do the numbers hold together. Occupancy, arrears, the spread between
head-lease cost and sublease income, the approvals queue. These are checked
against the records rather than against the screen.
"""

import frappe
from frappe.utils import flt

from darkbrown.api import app as app_api

# Every key the seed should produce. Planning and Owners are absent by
# decision — they have no DocTypes behind them yet.
EXPECTED = ["buildings", "units", "cases", "jobs", "moveouts", "tenants",
            "agreements", "invoices", "cheques", "docs", "approvals", "wall"]


def run(verbose=True):
    payload = _payload()
    checks = _checks()

    if verbose:
        print("\nboot payload")
        for key in EXPECTED:
            rows = payload.get(key)
            if rows is None:
                print(f"  MISSING  {key}")
            else:
                n = len(rows) if isinstance(rows, list) else 1
                print(f"  ok  {n:>4}  {key}")

        print("\nchecks")
        for label, ok, detail in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}"
                  + (f"  — {detail}" if detail else ""))

    missing = [k for k in EXPECTED if payload.get(k) is None]
    failed = [c[0] for c in checks if not c[1]]

    return {
        "payload": {k: (len(v) if isinstance(v, list) else 1)
                    for k, v in payload.items()},
        "missing_modules": missing,
        "failed_checks": failed,
        "passed": not missing and not failed,
    }


def _payload():
    try:
        return app_api.seed()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "darkbrown demo verify")
        return {"_error": str(e)}


# --------------------------------------------------------------------- checks

def _checks():
    out = []

    def check(label, condition, detail=""):
        out.append((label, bool(condition), detail))

    buildings = frappe.db.count("Building")
    units = frappe.db.count("Unit")
    check("buildings exist", buildings >= 3, f"{buildings} buildings")
    check("units exist", units >= 20, f"{units} units")

    occupied = frappe.db.count("Unit", {"status": "Occupied"})
    rate = (occupied / units * 100) if units else 0
    check("occupancy between 60% and 95%", 60 <= rate <= 95,
          f"{occupied}/{units} = {rate:.0f}%")

    live = frappe.db.count("Tenancy Agreement", {"status": "Active"})
    check("live tenancies", live >= 15, f"{live} active")

    pending = frappe.db.count("Tenancy Agreement", {"status": "Pending Approval"})
    check("an agreement is sitting in approval", pending >= 1,
          f"{pending} pending")

    # ---- money ---------------------------------------------------------
    sublease = flt(frappe.db.sql("""
        select sum(monthly_rent) from `tabTenancy Agreement`
        where status in ('Active', 'Expiring')""")[0][0])
    headlease = flt(frappe.db.sql(
        "select sum(round(annual_rent / 12, 2)) from `tabHead Lease` where status='Active'"
    )[0][0])
    spread = sublease - headlease
    margin = (spread / sublease * 100) if sublease else 0
    check("sublease income exceeds head-lease cost", spread > 0,
          f"QAR {sublease:,.0f} in vs QAR {headlease:,.0f} out, "
          f"spread QAR {spread:,.0f} ({margin:.0f}%)")

    invoices = frappe.db.count("Sales Invoice", {"docstatus": 1})
    check("invoices were raised", invoices >= 30, f"{invoices} submitted")

    payments = frappe.db.count("Payment Entry", {"docstatus": 1})
    check("receipts were posted", payments >= 20, f"{payments} submitted")

    outstanding = flt(frappe.db.sql("""
        select sum(outstanding_amount) from `tabSales Invoice`
        where docstatus = 1""")[0][0])
    check("some arrears remain", outstanding > 0,
          f"QAR {outstanding:,.0f} outstanding")

    collected = (1 - outstanding / flt(frappe.db.sql(
        "select sum(grand_total) from `tabSales Invoice` where docstatus=1"
    )[0][0] or 1)) * 100
    check("collection rate is realistic (70–99%)", 70 <= collected <= 99,
          f"{collected:.0f}%")

    # ---- cheques -------------------------------------------------------
    cleared = frappe.db.count("Cheque", {"status": "Cleared"})
    # on returned_on, because a replaced bounce no longer says "Returned"
    returned = frappe.db.count("Cheque", {"returned_on": ["is", "set"]})
    replaced = frappe.db.count("Cheque", {"status": "Replaced"})
    check("cheques cleared", cleared >= 20, f"{cleared} cleared")
    check("a cheque bounced", returned >= 1, f"{returned} returned")
    check("a bounce was replaced", replaced >= 1, f"{replaced} replaced")

    batches = frappe.db.count("Deposit Batch", {"status": "Deposited"})
    check("cash was banked on a slip", batches >= 1, f"{batches} batches")

    # ---- operations ----------------------------------------------------
    cases = frappe.db.count("Collection Case",
                            {"status": ["not in", ("Closed", "Cancelled")]})
    check("collection cases are open", cases >= 1, f"{cases} live")

    escalated = frappe.db.count("Collection Case", {"status": "Escalated"})
    check("a case reached escalation", escalated >= 1, f"{escalated} escalated")

    jobs = frappe.db.count("Maintenance Request")
    over = frappe.db.count("Maintenance Request", {"over_ceiling": 1})
    check("maintenance jobs exist", jobs >= 4, f"{jobs} jobs")
    check("a job breached the emergency ceiling", over >= 1,
          f"{over} over ceiling")

    mo = frappe.db.count("Move Out Case",
                         {"status": ["not in", ("Closed", "Cancelled")]})
    check("a move-out is running", mo >= 1, f"{mo} live")

    # ---- documents and approvals --------------------------------------
    docs = frappe.db.count("Document Register")
    superseded = frappe.db.count("Document Register", {"status": "Superseded"})
    check("documents registered", docs >= 8, f"{docs} documents")
    check("a document was superseded", superseded >= 1,
          f"{superseded} superseded")

    try:
        queue = app_api.approvals()
    except Exception:
        queue = []
    reserved = [q for q in queue if q.get("res")]
    check("approvals queue has items", len(queue) >= 2, f"{len(queue)} waiting")
    check("something is reserved to the MD", len(reserved) >= 1,
          f"{len(reserved)} reserved")

    return out
