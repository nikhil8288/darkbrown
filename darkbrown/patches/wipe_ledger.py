"""Remove every accounting document by direct table delete.

Two ways to run it, and the first needs no deploy:

  A. bench --site erp.darkbrown.qa console
     then paste the contents of WIPE_CONSOLE.txt

  B. bench --site erp.darkbrown.qa execute darkbrown.patches.wipe_ledger.run

WHY THIS EXISTS RATHER THAN A BETTER PURGE

Three attempts at clearing this ledger failed in three different places, and
all three shared one assumption: that a document can be removed by asking
ERPNext to remove it. It cannot, once the document is orphaned. Cancelling a
Purchase Invoice re-reads its supplier to build the GL reversal; the supplier
was deleted by an earlier purge; so cancel raises, the purge catches the
exception, and the invoice stays. Every fix along that path was a fix to the
catching, not to the cause.

This does not use the document layer at all. `frappe.db.delete` issues a
DELETE against the table. Nothing is validated, no link is re-read, no
controller runs. An orphan is just a row.

That is blunt, and it is only appropriate because of what this site is: a
cutover site with no history worth preserving. Everything it should hold comes
from the CSVs in this folder and reloads in a minute. On a live ledger this
would be the wrong tool entirely.

WHAT IT DOES NOT TOUCH

Company, chart of accounts, cost centres, fiscal years, items, users, roles,
DBR Settings, Document Requirements, Staff Members. Configuration survives,
transactions do not. Party balances are derived from the GL, so they correct
themselves once the GL is empty.

AFTER RUNNING IT

    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.check
    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.load
"""
import frappe

#: Dependency-first so the printout reads sensibly. Order does not otherwise
#: matter - nothing here is validated.
DOCS = [
    "Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice",
    "Period Closing Voucher", "Bank Transaction", "Dunning",
    # The ledgers themselves, in case a voucher was removed and left rows.
    "GL Entry", "Payment Ledger Entry", "Accounts Closing Balance",
    "Advance Payment Ledger Entry", "Repost Accounting Ledger",
    "Repost Payment Ledger", "Unreconcile Payment",
    # DarkBrown's own records.
    "Move Out Case", "Collection Case", "Security Deposit",
    "Maintenance Request", "Utility Bill", "Utility Meter", "Deposit Batch",
    "Invoice Run", "Agreement Amendment", "Document Register", "Cheque",
    "Cheque Book", "Head Lease Payment", "Tenancy Agreement", "Head Lease",
    "Unit", "Building", "Bank Statement Import", "Bank Balance Declaration",
    "Weekly Closing", "Petty Cash Entry", "Document Archive",
    "Building Scenario", "MD Alert Dismissal", "Historical Monthly PL",
]

#: Parties go only if they carry the DarkBrown flag, so a Customer or Supplier
#: belonging to something else on the site is left alone.
PARTIES = [("Customer", "db_is_tenant"), ("Supplier", "db_is_landlord")]


def _children(doctype):
    """Child tables of a doctype, so no orphaned rows are left behind."""
    try:
        return {o for o in frappe.get_all(
            "DocField",
            filters={"parent": doctype,
                     "fieldtype": ["in", ("Table", "Table MultiSelect")]},
            pluck="options") if o}
    except Exception:
        return set()


def preview():
    """Read-only. What run() would remove."""
    print("=" * 66)
    print("  WIPE PREVIEW - nothing is removed")
    print("=" * 66)
    total = 0
    for dt in DOCS:
        if frappe.db.table_exists(dt):
            n = frappe.db.count(dt)
            if n:
                total += n
                print("  %-34s %7d" % (dt, n))
    for dt, flag in PARTIES:
        n = frappe.db.count(dt, {flag: 1})
        if n:
            total += n
            print("  %-34s %7d  (flagged only)" % (dt, n))
    print("  %-34s %7d" % ("TOTAL", total))
    return {"total": total}


def run():
    removed, failed = 0, []
    print("=" * 66)
    print("  WIPE - direct table delete, no document validation")
    print("=" * 66)

    for dt in DOCS:
        if not frappe.db.table_exists(dt):
            continue
        n = frappe.db.count(dt)
        if not n:
            continue
        try:
            for child in _children(dt):
                if frappe.db.table_exists(child):
                    frappe.db.delete(child, {"parenttype": dt})
            frappe.db.delete(dt)
            frappe.db.commit()
            removed += n
            print("  removed %7d  %s" % (n, dt))
        except Exception as e:
            frappe.db.rollback()
            failed.append((dt, str(e)[:120]))
            print("  ! %-30s %s" % (dt, str(e)[:120]))

    for dt, flag in PARTIES:
        names = frappe.get_all(dt, filters={flag: 1}, pluck="name")
        if not names:
            continue
        try:
            for child in _children(dt):
                if frappe.db.table_exists(child):
                    frappe.db.delete(child, {"parenttype": dt,
                                             "parent": ["in", names]})
            frappe.db.delete(dt, {flag: 1})
            frappe.db.commit()
            removed += len(names)
            print("  removed %7d  %s (flagged)" % (len(names), dt))
        except Exception as e:
            frappe.db.rollback()
            failed.append((dt, str(e)[:120]))
            print("  ! %-30s %s" % (dt, str(e)[:120]))

    gl = frappe.db.count("GL Entry")
    print("\n  removed %d documents" % removed)
    print("  GL Entry rows remaining: %d%s"
          % (gl, "" if not gl else "   <-- SOMETHING IS STILL THERE"))
    if failed:
        print("\n  these tables refused:")
        for dt, why in failed:
            print("    %-30s %s" % (dt, why))
    elif not gl:
        print("\n  The ledger is empty. Next:")
        print("    ...ak12_rebuild.check")
        print("    ...ak12_rebuild.load")
    return {"removed": removed, "gl_rows": gl, "failed": failed}
