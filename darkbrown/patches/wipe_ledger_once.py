"""Clear the stale cutover ledger during a deploy. Runs once, then never again.

WHY A PATCH

Every route tried so far needed either a working purge (which cannot remove an
orphaned voucher) or a shell (which is not always to hand). Frappe runs the
patches listed in `patches.txt` automatically during `bench migrate`, which
Frappe Cloud runs for you on every deploy, and records each one in Patch Log so
it never runs twice. Pushing the repo and clicking update is a thing that has
already been proven to work on this project. This uses only that.

THE GUARD - READ THIS BEFORE TRUSTING IT

A patch that empties the ledger is a dangerous thing to leave registered
forever. If the Patch Log were ever cleared, or the app installed on another
site, an unguarded version would silently destroy a live general ledger.

So it refuses unless the site has **no Building records at all**. That is a
precise description of the only state in which this is safe: a cutover site
that has been purged down to nothing except vouchers that will not cancel. The
moment AK-12 loads, Building becomes 1 and this patch can never do anything
again, Patch Log or no Patch Log.

It also refuses if it finds a rent invoice this pack wrote (`AK12-HIST-INV`),
because that means a real load has happened and the ledger is wanted.

WHAT IT REMOVES

Exactly what `wipe_ledger.run` removes, by the same direct table deletes:
every accounting document and every DarkBrown record, plus Customers and
Suppliers carrying the tenant/landlord flag. Company, chart of accounts, cost
centres, fiscal years, items, users, roles and DBR Settings are untouched.

AFTER IT RUNS

    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.check
    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.load

or the Data screen's Load for real, which now refuses on a dirty ledger and
will let you through once this has run.
"""
import frappe

from darkbrown.patches import wipe_ledger


def execute():
    buildings = frappe.db.count("Building")
    if buildings:
        print("  [wipe_ledger_once] SKIPPED - %d Building record(s) on this "
              "site." % buildings)
        print("  [wipe_ledger_once] This patch only ever runs on a site that "
              "has been")
        print("  [wipe_ledger_once] purged to nothing. It will not touch a "
              "loaded ledger.")
        return

    loaded = frappe.db.count("Sales Invoice",
                             {"remarks": ["like", "%AK12-HIST-INV-%"],
                              "docstatus": 1})
    if loaded:
        print("  [wipe_ledger_once] SKIPPED - %d rent invoices from the AK-12 "
              "pack are" % loaded)
        print("  [wipe_ledger_once] already posted. That ledger is wanted.")
        return

    gl = frappe.db.count("GL Entry")
    if not gl:
        print("  [wipe_ledger_once] nothing to do - the ledger is already "
              "empty.")
        return

    print("  [wipe_ledger_once] no buildings, %d GL rows: clearing the stale "
          "cutover ledger." % gl)
    out = wipe_ledger.run()
    if out.get("gl_rows"):
        # Do not fail the migrate over it - a raised patch aborts the whole
        # deploy and leaves the site on the old build. Say so loudly instead.
        print("  [wipe_ledger_once] WARNING: %d GL rows survived. Run "
              "darkbrown.patches.ak12_doctor.run" % out["gl_rows"])
    else:
        print("  [wipe_ledger_once] done - the ledger is empty.")
