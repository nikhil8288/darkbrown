"""Take the site back to genuinely empty before loading AK-12.

    bench --site erp.darkbrown.qa execute darkbrown.patches.full_reset.preview
    bench --site erp.darkbrown.qa execute darkbrown.patches.full_reset.run \\
        --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"

WHY THIS EXISTS RATHER THAN JUST CALLING demo.run.purge

`demo.purge` scopes the parties it removes by flag:

    def _tenants():  return frappe.get_all("Customer", {"db_is_tenant": 1})
    def _landlords(): return frappe.get_all("Supplier", {"db_is_landlord": 1})

That is correct for a site that also holds unrelated ERPNext parties, and wrong
for this one. The diagnostic showed 272 Customers with only 2 carrying the
tenant flag — the rest were created by the abandoned full-portfolio load, whose
customer loader never set the flag because it was failing on a group node. A
plain purge walks straight past all 270 of them and the site is not clean.

`wide=True` does not help: it widens the ledger sweep only. Customer and
Supplier are always scoped by flag.

So this flags every unflagged Customer and Supplier first, which brings them
into the purge's own scope, and then calls the real purge. Nothing here
reimplements deletion — `demo.purge.run` still does that work, leaf-first,
cancelling submitted vouchers before deleting them.

READ THIS BEFORE RUNNING

This assumes the site holds DarkBrown data and nothing else, which is true of
erp.darkbrown.qa. On a site with unrelated customers it would sweep them in.
`preview()` prints exactly what would be flagged and removed and changes
nothing. Run it first.
"""
import frappe

CONFIRM = "REMOVE ALL DARKBROWN DATA"


def _orphans():
    cust = frappe.get_all("Customer",
                          filters={"db_is_tenant": ["!=", 1]}, pluck="name")
    supp = frappe.get_all("Supplier",
                          filters={"db_is_landlord": ["!=", 1]}, pluck="name")
    return cust, supp


def preview():
    from darkbrown.demo import purge as purge_mod

    cust, supp = _orphans()
    print("=" * 72)
    print("  WHAT A RESET WOULD TAKE")
    print("=" * 72)
    print("\n  parties the purge cannot currently see:")
    print("    Customer without db_is_tenant  : %d" % len(cust))
    print("    Supplier without db_is_landlord: %d" % len(supp))
    if cust:
        print("    first few: %s" % ", ".join(cust[:6]))
    print("\n  what purge would remove once they are flagged:")
    counts = purge_mod.preview(wide=True)
    for dt, n in sorted(counts.items()):
        print("    %-34s %6d" % (dt, n))
    total = frappe.db.count("Customer"), frappe.db.count("Supplier")
    print("\n  on the site right now: %d Customers, %d Suppliers" % total)
    print("\n  nothing was changed.")
    return {"unflagged_customers": len(cust), "unflagged_suppliers": len(supp),
            "would_remove": counts}


def run(confirm=None):
    from darkbrown.demo import purge as purge_mod

    if confirm != CONFIRM:
        print("Refused. Pass confirm='%s' to go ahead." % CONFIRM)
        print("Run preview first to see what would go.")
        return {"aborted": True}

    cust, supp = _orphans()
    for name in cust:
        frappe.db.set_value("Customer", name, "db_is_tenant", 1)
    for name in supp:
        frappe.db.set_value("Supplier", name, "db_is_landlord", 1)
    frappe.db.commit()
    print("  flagged %d Customers and %d Suppliers so the purge can see them"
          % (len(cust), len(supp)))

    out = purge_mod.run(confirm=CONFIRM, wide=True)

    left = {dt: frappe.db.count(dt) for dt in
            ("Building", "Unit", "Head Lease", "Tenancy Agreement", "Customer",
             "Supplier", "Sales Invoice", "Payment Entry", "Journal Entry",
             "Collection Case", "Cheque")}
    print("\n  left on the site:")
    for dt, n in left.items():
        print("    %-22s %5d%s" % (dt, n, "" if not n else "   <-- not empty"))
    if any(left.values()):
        print("\n  Anything still standing refused to delete. The purge prints")
        print("  the reason per record above; it is usually a submitted")
        print("  voucher that could not be cancelled.")
    else:
        print("\n  site is empty.")
    return {"purged": out, "left": left}
