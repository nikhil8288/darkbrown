"""Where did the cutover load actually stop? One command, no writes.

    bench --site erp.darkbrown.qa execute darkbrown.patches.cutover_doctor.run

Reports what is on the site against what the pack expects, in load order, and
names the first step that has not completed. Every count is read straight from
the database; nothing here is inferred from a previous run's output.
"""
import json
import os

import frappe

HERE = os.path.dirname(__file__)

EXPECT = [
    ("Customer",          365, "load_customers",   "customers.json"),
    ("Building",           23, "load_buildings",   "buildings_payload.json"),
    ("Unit",              305, "load_buildings",   "buildings_payload.json"),
    ("Head Lease",         22, "load_buildings",   "buildings_payload.json"),
    ("Tenancy Agreement", 442, "import_tenancies", "tenancies.csv"),
]


def _count(dt, filters=None):
    try:
        return frappe.db.count(dt, filters or {})
    except Exception as e:
        return "ERROR: %s" % str(e)[:60]


def run():
    print("=" * 74)
    print("CUTOVER DOCTOR - reads only, writes nothing")
    print("=" * 74)

    company = frappe.db.get_single_value("DBR Settings", "default_company")
    print("\ndefault_company : %s" % (company or "!! NOT SET"))

    print("\nfiles in darkbrown/patches/")
    for f in ("customers.json", "buildings_payload.json", "tenancies.csv",
              "portfolio_history.csv", "owner_rent_history.csv",
              "keymoney_history.csv", "opex_journal.csv"):
        p = os.path.join(HERE, f)
        print("  %-26s %s" % (f, "%d bytes" % os.path.getsize(p)
                              if os.path.exists(p) else "!! MISSING"))

    print("\nrecords on the site")
    first_gap = None
    for dt, want, step, src in EXPECT:
        got = _count(dt)
        mark = "ok" if got == want else "<<<"
        if got != want and first_gap is None:
            first_gap = (dt, got, want, step)
        print("  %-20s %6s / %-6d %s" % (dt, got, want, mark))

    print("\ntenants flagged db_is_tenant : %s" % _count("Customer", {"db_is_tenant": 1}))
    print("landlords flagged db_is_landlord: %s" % _count("Supplier", {"db_is_landlord": 1}))
    print("units reading Occupied         : %s" % _count("Unit", {"status": "Occupied"}))
    print("units reading Vacant           : %s" % _count("Unit", {"status": "Vacant"}))
    print("live tenancies                 : %s"
          % _count("Tenancy Agreement", {"status": ["in", ("Active", "Expiring")]}))

    missing_cc = [b.name for b in frappe.get_all(
        "Building", fields=["name", "cost_center"]) if not b.cost_center]
    print("\nbuildings without a cost centre : %d %s"
          % (len(missing_cc), missing_cc[:8] or ""))
    if missing_cc:
        print("  The after_insert hook creates one per building. A blank one means")
        print("  the company has no group cost centre for it to hang off.")

    print("\nGL Entry rows                   : %s" % _count("GL Entry"))
    print("Sales Invoice (rent history)    : %s"
          % _count("Sales Invoice", {"remarks": ["like", "%DB-HIST-INV-%"]}))
    print("Purchase Invoice (owner rent)   : %s"
          % _count("Purchase Invoice", {"remarks": ["like", "%DB-HL-INV-%"]}))

    print("\n" + "-" * 74)
    if first_gap:
        dt, got, want, step = first_gap
        print("FIRST GAP: %s is %s, expected %d." % (dt, got, want))
        print("The step that fills it is %s." % step)
        print("Run its dry_run and read the output before the real run:")
        print("  bench --site erp.darkbrown.qa execute "
              "darkbrown.patches.%s.dry_run" % step)
        if dt == "Tenancy Agreement" and _count("Customer") != 365:
            print()
            print("NOTE: Customer is not 365 either. import_tenancies refuses every")
            print("row whose tenant it cannot match and creates nothing, so fix the")
            print("customer load first - the tenancy step will keep aborting until")
            print("the parties exist.")
    else:
        print("All five masters are at their expected counts.")
        print("Next: load_portfolio_history.dry_run, then "
              "load_portfolio_headlease.dry_run.")
    print("-" * 74)
    return {"company": company, "first_gap": first_gap}
