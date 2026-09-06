"""Clear what `purge` cannot see.

`purge` is scoped by party: tenants are Customers flagged `db_is_tenant`,
landlords are Suppliers flagged `db_is_landlord`, and building cost centres
are read off `Building.cost_center`. That scoping is deliberate and protects
unrelated ERPNext data on a shared site.

The cost is a blind spot. A record that lost its flag, or a cost centre whose
Building was already deleted, is invisible to `preview` - so the Data screen
reports an empty site while the records are still there. The next load then
name-matches against them and rows fail silently.

This module sweeps that residue. It is deliberately NOT part of `purge`:
`purge` may run on a site holding data this app did not create, and must stay
conservative. This runs only on a site that is already meant to be empty, and
refuses otherwise.

Guards, all three of which must pass:

  * no live (uncancelled) GL Entry
  * no Building records
  * the exact confirmation phrase

`preview()` counts and changes nothing.
"""

import frappe

CONFIRM = "CLEAR RESIDUAL DATA"

# Cost centres that belong to the chart of accounts, not to a building.
KEEP_COST_CENTERS = {
    "DarkBrown RealEstate - DBR",
    "Main - DBR",
    "Overhead - DBR",
    "Overhead / Admin - DBR",
}

# Doctypes from an earlier build of this app, still carrying records on the
# site but no longer defined in the codebase. Named explicitly rather than
# detected, so a future ERPNext master can never be swept up by accident.
GHOST_DOCTYPES = [
    "Tenant Rental Agreement",
    "Landlord Contract",
    "PDC Cheque",
]

# Counters to clear so a fresh load numbers from 1. Deleting the row is how
# Frappe restarts a series; there is no Series doctype to update.
SERIES = [
    "ACC-SINV-2026-", "ACC-PAY-2026-", "ACC-PINV-2026-", "ACC-GLE-2026-",
    "CHQ-2026-", "DOC-2026-", "SD-2026-", "TA-2026-", "HL-2026-", "MNT-2026-",
]


# ------------------------------------------------------------------- guards

def _blockers():
    """Reasons this must not run. Empty list means it is safe."""
    out = []

    live = frappe.db.count("GL Entry", {"is_cancelled": 0})
    if live:
        out.append("%d live GL entries - the ledger is not empty" % live)

    buildings = frappe.db.count("Building")
    if buildings:
        out.append("%d Building records - run purge first" % buildings)

    return out


def _orphan_cost_centers():
    """Non-group cost centres that are not chart-of-accounts furniture.

    Only reachable once Buildings are gone, which is exactly when purge stops
    being able to see them.
    """
    out = []
    for name in frappe.get_all("Cost Center", filters={"is_group": 0},
                               pluck="name"):
        if name in KEEP_COST_CENTERS:
            continue
        if frappe.db.exists("GL Entry", {"cost_center": name,
                                         "is_cancelled": 0}):
            continue                      # live ledger against it; leave it
        out.append(name)
    return out


# ------------------------------------------------------------------ preview

def preview():
    """Count what a sweep would remove. Changes nothing."""
    counts = {}

    n = frappe.db.count("GL Entry")
    if n:
        counts["GL Entry (cancelled)"] = n
    n = frappe.db.count("Payment Ledger Entry")
    if n:
        counts["Payment Ledger Entry"] = n

    for dt in GHOST_DOCTYPES:
        if frappe.db.exists("DocType", dt):
            n = frappe.db.count(dt)
            if n:
                counts["%s (ghost)" % dt] = n

    for dt in ("Customer", "Supplier"):
        n = frappe.db.count(dt)
        if n:
            counts[dt] = n

    cc = _orphan_cost_centers()
    if cc:
        counts["Cost Center (orphaned)"] = len(cc)

    return {"counts": counts, "blockers": _blockers(),
            "cost_centers": cc, "confirm": CONFIRM}


# -------------------------------------------------------------------- sweep

def run(confirm=None, verbose=True):
    """Remove the residue. `confirm` must match CONFIRM exactly."""
    if confirm != CONFIRM:
        frappe.throw(
            "Sweep refused. Pass confirm='%s' to go ahead. Run "
            "darkbrown.demo.residuals.preview first to see what would go."
            % CONFIRM)

    blockers = _blockers()
    if blockers:
        frappe.throw("Sweep refused:\n  " + "\n  ".join(blockers))

    frappe.flags.in_import = True
    frappe.flags.ignore_links = True
    log = []

    def _say(text):
        if verbose:
            print(text)

    # 1. Cancelled ledger. Every row here is is_cancelled=1 - the guard above
    #    proves it - so no report or dashboard reads them. Bulk SQL because
    #    delete_doc on 45k rows will not finish inside a request.
    for table in ("Payment Ledger Entry", "GL Entry"):
        n = frappe.db.count(table)
        if n:
            frappe.db.sql("DELETE FROM `tab%s`" % table)
            log.append((table, n))
            _say("  cleared %-28s %6d" % (table, n))
    frappe.db.commit()

    # 2. Records of doctypes this app no longer defines.
    for dt in GHOST_DOCTYPES:
        if not frappe.db.exists("DocType", dt):
            continue
        n = frappe.db.count(dt)
        if not n:
            continue
        frappe.db.sql("DELETE FROM `tab%s`" % dt)
        log.append(("%s (ghost)" % dt, n))
        _say("  cleared %-28s %6d" % (dt, n))
    frappe.db.commit()

    # 3. Parties. delete_doc rather than SQL so child tables, contacts and
    #    addresses go with them.
    for dt in ("Customer", "Supplier"):
        killed = failed = 0
        for name in frappe.get_all(dt, pluck="name"):
            try:
                frappe.delete_doc(dt, name, force=True,
                                  ignore_permissions=True,
                                  delete_permanently=True)
                killed += 1
            except Exception:
                failed += 1
        if killed:
            log.append((dt, killed))
            _say("  cleared %-28s %6d" % (dt, killed))
        if failed:
            log.append(("%s FAILED" % dt, failed))
            _say("  FAILED  %-28s %6d" % (dt, failed))
        frappe.db.commit()

    # 4. Cost centres left behind by deleted Buildings.
    killed = failed = 0
    for name in _orphan_cost_centers():
        try:
            frappe.delete_doc("Cost Center", name, force=True,
                              ignore_permissions=True,
                              delete_permanently=True)
            killed += 1
        except Exception:
            failed += 1
    if killed:
        log.append(("Cost Center (orphaned)", killed))
        _say("  cleared %-28s %6d" % ("Cost Center", killed))
    if failed:
        log.append(("Cost Center FAILED", failed))
        _say("  FAILED  %-28s %6d" % ("Cost Center", failed))
    frappe.db.commit()

    # 5. Naming counters, so the new load numbers from 1.
    wiped = 0
    for s in SERIES:
        try:
            frappe.db.sql("DELETE FROM tabSeries WHERE name = %s", (s,))
            wiped += 1
        except Exception:
            pass
    if wiped:
        log.append(("Naming series cleared", wiped))
        _say("  cleared %-28s %6d" % ("Naming series", wiped))

    frappe.flags.in_import = False
    frappe.flags.ignore_links = False
    frappe.db.commit()
    frappe.clear_cache()

    return {"removed": dict(log), "total": sum(n for _, n in log)}
