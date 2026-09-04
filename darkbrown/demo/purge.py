"""Take the site back to an empty portfolio.

What this removes: every DarkBrown record, and the ERPNext records this app
created — the Sales Invoices, Payment Entries and Journal Entries raised
against DarkBrown parties, the tenant Customers, the landlord Suppliers and
the per-building Cost Centres.

What it leaves alone: the Company, the chart of accounts, bank accounts,
users, roles, DBR Settings, Document Requirements, and any Customer or
Supplier this app did not create. Scoping is by party, not by doctype, so a
site that happens to carry unrelated ERPNext data keeps it.

Nothing here is reversible. `preview()` counts without touching anything and
is the safe way to see what a purge would take.
"""

import frappe

CONFIRM = "REMOVE ALL DARKBROWN DATA"

# Leaf first. A doctype is only removed once nothing that points at it is left.
DOCTYPES = [
    "Move Out Case",
    "Collection Case",
    "Security Deposit",
    "Maintenance Request",
    "Utility Bill",
    "Utility Meter",
    "Deposit Batch",
    "Invoice Run",
    "Agreement Amendment",
    "Document Register",
    "Cheque",
    "Cheque Book",
    "Tenancy Agreement",
    "Head Lease",
    "Unit",
    "Building",
]

# Order matters: a Payment Entry pointing at an invoice has to go first, or
# the invoice cannot be cancelled.
#
# Purchase Invoice was missing until now, and the omission was invisible while
# nothing in the app posted one. It does now (head-lease cost), and a site that
# had a portfolio-wide landlord run on it kept every one of those invoices
# through a "successful" purge - leaving the whole landlord expense and the
# matching Creditors balance on a ledger that reported itself as empty.
LEDGER = ["Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice"]


# ------------------------------------------------------------------- scoping

def _tenants():
    return frappe.get_all("Customer", filters={"db_is_tenant": 1}, pluck="name")


def _landlords():
    return frappe.get_all("Supplier", filters={"db_is_landlord": 1}, pluck="name")


def _building_cost_centers():
    return [c for c in frappe.get_all("Building", pluck="cost_center") if c]


def _ledger_names(doctype, parties, wide=False):
    """Ledger documents belonging to this app.

    Scoped to DarkBrown parties unless `wide`, in which case everything in the
    doctype goes. Wide is for a site that only ever held DarkBrown data and
    where a stray invoice against a deleted party would otherwise survive.
    """
    if wide:
        return frappe.get_all(doctype, pluck="name")

    field = {"Payment Entry": "party", "Sales Invoice": "customer"}.get(doctype)
    if not field:
        # Journal Entries carry parties on child rows.
        rows = frappe.get_all(
            "Journal Entry Account",
            filters={"party": ["in", parties or [""]]},
            pluck="parent", distinct=True)
        return list(set(rows))
    if not parties:
        return []
    return frappe.get_all(doctype, filters={field: ["in", parties]}, pluck="name")


# ------------------------------------------------------------------- preview

def preview(wide=False):
    """Count everything a purge would remove. Changes nothing."""
    parties = _tenants() + _landlords()
    counts = {}

    for dt in LEDGER:
        names = _ledger_names(dt, parties, wide)
        if names:
            counts[dt] = len(names)

    for dt in DOCTYPES:
        n = frappe.db.count(dt)
        if n:
            counts[dt] = n

    if _tenants():
        counts["Customer (tenants)"] = len(_tenants())
    if _landlords():
        counts["Supplier (landlords)"] = len(_landlords())
    cc = _building_cost_centers()
    if cc:
        counts["Cost Center (buildings)"] = len(cc)

    return counts


# --------------------------------------------------------------------- purge

def run(confirm=None, wide=False, verbose=True):
    """Remove everything. `confirm` must be the exact phrase in CONFIRM."""
    if confirm != CONFIRM:
        frappe.throw(
            f"Purge refused. Pass confirm='{CONFIRM}' to go ahead. "
            f"Run darkbrown.demo.run.preview first to see what would go.")

    log = []
    parties = _tenants() + _landlords()
    cost_centers = _building_cost_centers()

    frappe.flags.in_import = True          # quieter validation on delete
    frappe.flags.ignore_links = True

    # 1. The ledger, newest dependency first. A Sales Invoice cannot be
    #    cancelled while a submitted Payment Entry still points at it.
    for dt in LEDGER:
        names = _ledger_names(dt, parties, wide)
        killed = 0
        for name in names:
            if _drop_submittable(dt, name):
                killed += 1
        if killed:
            log.append((dt, killed))
        frappe.db.commit()

    # 2. DarkBrown's own records. Deleting the voucher above already took its
    #    GL and payment-ledger rows with it, so there is no residue to sweep.
    for dt in DOCTYPES:
        killed = 0
        for name in frappe.get_all(dt, pluck="name"):
            if _drop(dt, name):
                killed += 1
        if killed:
            log.append((dt, killed))
        frappe.db.commit()

    # 3. Parties this app created.
    for dt, names in (("Customer", _tenants()), ("Supplier", _landlords())):
        killed = 0
        for name in names:
            if _drop(dt, name):
                killed += 1
        if killed:
            log.append((f"{dt} (DarkBrown parties)", killed))
        frappe.db.commit()

    # 4. Per-building cost centres, now that nothing posts to them.
    killed = 0
    for cc in cost_centers:
        if not frappe.db.exists("Cost Center", cc):
            continue
        if frappe.db.exists("GL Entry", {"cost_center": cc, "is_cancelled": 0}):
            continue                      # still carries live ledger; leave it
        if _drop("Cost Center", cc):
            killed += 1
    if killed:
        log.append(("Cost Center (buildings)", killed))

    frappe.flags.in_import = False
    frappe.flags.ignore_links = False
    frappe.db.commit()

    if verbose:
        for dt, n in log:
            print(f"  removed {n:>5}  {dt}")
        if not log:
            print("  nothing to remove — the site was already empty")

    return {"removed": dict(log)}


# ------------------------------------------------------------------- helpers

def _drop_submittable(doctype, name):
    """Cancel if submitted, then delete. Survives a document that refuses."""
    try:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, delete_permanently=True)
        return True
    except Exception as e:
        frappe.db.rollback()
        print(f"  ! could not remove {doctype} {name}: {e}")
        return False


def _drop(doctype, name):
    try:
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, ignore_on_trash=True,
                          delete_permanently=True)
        return True
    except Exception as e:
        frappe.db.rollback()
        print(f"  ! could not remove {doctype} {name}: {e}")
        return False
