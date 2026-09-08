"""Cancel the historical receipts whose amount no longer matches the CSV.

    bench --site erp.darkbrown.qa execute darkbrown.patches.requeue_history_receipts.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.requeue_history_receipts.run

WHY THIS EXISTS

`load_portfolio_history` is idempotent on the receipt tag: if `DB-HIST-RCP-nnnnn`
is already on the site the row is skipped. That is right for a re-run after a
partial failure and wrong after the CSV itself is corrected - the amended rows
would be skipped at their old amounts and the correction would silently do
nothing.

So the stale receipts have to go before the loader runs again. This cancels
exactly those, and nothing else.

WHAT IT TOUCHES

Only Payment Entries whose `reference_no` starts with the historical receipt
tag AND whose `paid_amount` differs from the CSV's `collected` for that row.
A receipt that already agrees with the CSV is left alone, so re-running this
after the loader finds nothing to do.

Invoices are never touched. `rent` did not change - only `collected` did - so
every Sales Invoice on the site is still correct and cancelling them would
throw away the correct side of the ledger for no reason.

CANCELLING, NOT DELETING

The cancelled entries stay as docstatus 2 with their GL reversed. The audit
trail shows a receipt posted and withdrawn, which is what happened.
"""
import csv
import os

import frappe
from frappe.utils import flt

CSV = os.path.join(os.path.dirname(__file__), "portfolio_history.csv")
RCP_TAG = "DB-HIST-RCP"


def _receipt_no(i):
    return "%s-%05d" % (RCP_TAG, i + 1)


def _rows():
    if not os.path.exists(CSV):
        frappe.throw("portfolio_history.csv is not on the server. Deploy first.")
    with open(CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _plan():
    """(stale, agreeing, absent). Reads only."""
    rows = _rows()
    want = {}
    for i, r in enumerate(rows):
        want[_receipt_no(i)] = flt(r["collected"])

    posted = {}
    for pe in frappe.get_all(
            "Payment Entry",
            filters={"reference_no": ["like", RCP_TAG + "-%"], "docstatus": 1},
            fields=["name", "reference_no", "paid_amount", "posting_date",
                    "party"]):
        posted[pe.reference_no] = pe

    stale, agreeing = [], 0
    for tag, amount in want.items():
        pe = posted.get(tag)
        if not pe:
            continue
        if abs(flt(pe.paid_amount) - amount) < 0.005:
            agreeing += 1
            continue
        stale.append({"tag": tag, "name": pe.name, "party": pe.party,
                      "posting_date": pe.posting_date,
                      "was": flt(pe.paid_amount), "should_be": amount})

    absent = [t for t, a in want.items() if a and t not in posted]
    stale.sort(key=lambda s: s["tag"])
    return stale, agreeing, absent


def dry_run():
    """Report without writing. Safe at any time."""
    stale, agreeing, absent = _plan()

    print("=" * 78)
    print("DRY RUN - nothing cancelled")
    print("=" * 78)
    print("")
    print("  receipts already matching the CSV : %d  (left alone)" % agreeing)
    print("  receipts to cancel and re-post    : %d" % len(stale))
    print("  rows with no receipt on the site  : %d  (loader will create)"
          % len(absent))

    if not stale:
        print("")
        print("Nothing to cancel. Either the correction is already in, or the")
        print("corrected portfolio_history.csv is not on the server - check")
        print("that load_portfolio_history.dry_run reports collected")
        print("5,182,581.00 and not 4,838,469.00.")
        return {"stale": [], "agreeing": agreeing}

    was = sum(s["was"] for s in stale)
    should = sum(s["should_be"] for s in stale)
    print("")
    print("  %-20s %-12s %14s %14s" % ("RECEIPT", "DATE", "POSTED", "SHOULD BE"))
    for s in stale[:25]:
        print("  %-20s %-12s %14s %14s"
              % (s["tag"], s["posting_date"],
                 format(s["was"], ",.2f"), format(s["should_be"], ",.2f")))
    if len(stale) > 25:
        print("  ... and %d more" % (len(stale) - 25))

    print("")
    print("  posted total    %14s" % format(was, ",.2f"))
    print("  corrected total %14s" % format(should, ",.2f"))
    print("  difference      %14s" % format(should - was, ",.2f"))
    print("")
    print("Expect the difference to be 344,112.00 - the advance (240,250) plus")
    print("the prior due recovered (103,862). Any other number means the CSV on")
    print("the server is not the one in the fix pack. Stop and check.")
    return {"stale": stale, "agreeing": agreeing, "absent": absent}


def run():
    """Cancel the stale receipts. Then re-run load_portfolio_history.run."""
    stale, agreeing, absent = _plan()
    if not stale:
        print("Nothing to cancel.")
        return {"cancelled": [], "failed": []}

    delta = sum(s["should_be"] - s["was"] for s in stale)
    if abs(delta - 344112.00) > 0.01:
        frappe.throw(
            "The correction would move %s, expected 344,112.00. That is not "
            "the advance and prior-due figure Anoop signed off. Refusing to "
            "cancel %d receipts on a number nobody has agreed."
            % (format(delta, ",.2f"), len(stale)))

    cancelled, failed = [], []
    for s in stale:
        try:
            doc = frappe.get_doc("Payment Entry", s["name"])
            doc.flags.ignore_permissions = True
            doc.cancel()
            cancelled.append(s)
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            failed.append((s["tag"], str(e)[:160]))
            print("  FAILED %-20s %s" % (s["tag"], str(e)[:160]))

    print("")
    print("cancelled %d, failed %d" % (len(cancelled), len(failed)))
    if failed:
        print("The failures are still posted at their old amounts. Fix them")
        print("before running the loader, or those rows stay wrong.")
        return {"cancelled": cancelled, "failed": failed}

    print("")
    print("Now run:")
    print("  bench --site erp.darkbrown.qa execute "
          "darkbrown.patches.load_portfolio_history.run")
    print("It will re-create these %d receipts at the corrected amounts."
          % len(cancelled))
    return {"cancelled": cancelled, "failed": failed}
