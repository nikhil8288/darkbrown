"""Stage 0 — empty the site, keeping only the accounting foundation.

`demo.purge` is scoped by party: it removes Customers flagged db_is_tenant,
Suppliers flagged db_is_landlord, and the invoices those parties carry. That
scoping is deliberate and protects a shared site. It is also why the Data
screen reported 4,926 records while the ledger held thousands more: purge's
DOCTYPES list names sixteen doctypes and the app has twenty-seven, so
Historical Monthly PL, Expense Entry, Petty Cash Entry, Weekly Closing and the
bank-statement records were never counted and never removed.

Reloading on top of that residue is what makes a control total impossible to
reconcile. So this stage does not carry a hand-written list. It asks the
database which doctypes the Darkbrown module owns and removes all of them,
which cannot fall out of date when a doctype is added.

What survives, and why:

  * Company, the chart of accounts, the non-building cost centres, bank
    accounts and modes of payment — this is Anoop's accounting design, not
    loaded data. Rebuilding it means re-making those decisions.
  * Users, roles and permissions — people's logins.
  * DBR Settings — the singleton every finance call reads.
  * Document Requirement — configuration, not records.
  * Customer Group, Supplier Group, Territory, Item — ERPNext masters the
    loaders need to exist before they can write anything.

Three entry points, and `run` refuses unless `check` was clean:

    check()   counts every doctype on the site. Writes nothing.
    run()     removes it. Needs the confirmation phrase.
    gate()    proves the site is empty. Fails loudly if it is not.
"""

import frappe

CONFIRM = "REMOVE ALL DARKBROWN DATA"

#: Cancel-then-delete, and order matters: a Payment Entry pointing at an
#: invoice has to go before the invoice can be cancelled.
LEDGER = ["Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice"]

#: Leaf first, for the dependencies we know about. Anything the module owns
#: that is not named here is swept afterwards, so this list being incomplete
#: costs an ordering retry, not a missed record.
KNOWN_ORDER = [
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
    "Document Archive",
    "Cheque",
    "Cheque Book",
    "Historical Monthly PL",
    "Expense Entry",
    "Petty Cash Entry",
    "Weekly Closing",
    "Bank Statement Import",
    "Bank Balance Declaration",
    "Building Scenario",
    "MD Alert Dismissal",
    "Tenancy Agreement",
    "Head Lease",
    "Unit",
    "Building",
]

#: Owned by the module but configuration rather than data.
KEEP_DOCTYPES = {"Document Requirement", "DBR Settings", "Staff Member"}


# ------------------------------------------------------------------ scoping

def _module_doctypes():
    """Every doctype this app owns that holds records.

    Read from the database rather than from a list in this file, so a doctype
    added next month is covered without anyone remembering to come back here.
    """
    rows = frappe.get_all(
        "DocType",
        filters={"module": "Darkbrown", "istable": 0, "issingle": 0},
        pluck="name")
    return [d for d in rows if d not in KEEP_DOCTYPES]


def _order(doctypes):
    """Known leaf-first order first, then whatever else the module owns."""
    known = [d for d in KNOWN_ORDER if d in doctypes]
    rest = sorted(set(doctypes) - set(known))
    return known + rest


def _tenants():
    return frappe.get_all("Customer", filters={"db_is_tenant": 1}, pluck="name")


def _landlords():
    return frappe.get_all("Supplier", filters={"db_is_landlord": 1}, pluck="name")


def _building_cost_centers():
    return [c for c in frappe.get_all("Building", pluck="cost_center") if c]


def _ledger_names(doctype, parties, wide=False):
    if wide:
        return frappe.get_all(doctype, pluck="name")
    field = {"Payment Entry": "party", "Sales Invoice": "customer",
             "Purchase Invoice": "supplier"}.get(doctype)
    if not field or not parties:
        # Journal Entry carries no party field of its own. Scoped runs leave
        # it alone; a wide run takes it.
        return [] if not wide else frappe.get_all(doctype, pluck="name")
    return frappe.get_all(doctype, filters={field: ["in", parties]}, pluck="name")


# -------------------------------------------------------------------- check

def check(wide=1):
    """Count what is on the site. Writes nothing.

    Counts every module doctype, not a chosen few, so the total on screen is
    the real total.
    """
    parties = _tenants() + _landlords()
    counts = {}

    for dt in LEDGER:
        n = len(_ledger_names(dt, parties, bool(int(wide))))
        if n:
            counts[dt] = n

    for dt in _order(_module_doctypes()):
        try:
            n = frappe.db.count(dt)
        except Exception:
            continue
        if n:
            counts[dt] = n

    for label, names in (("Customer (tenants)", _tenants()),
                         ("Supplier (landlords)", _landlords())):
        if names:
            counts[label] = len(names)

    cc = _building_cost_centers()
    if cc:
        counts["Cost Center (buildings)"] = len(cc)

    for dt in ("GL Entry", "Payment Ledger Entry"):
        try:
            n = frappe.db.count(dt)
        except Exception:
            continue
        if n:
            counts[dt] = n

    total = sum(counts.values())
    print("STAGE 0 CHECK")
    print("  %d doctypes carry records" % len(counts))
    for k in sorted(counts, key=lambda x: -counts[x]):
        print("    %-34s %8d" % (k, counts[k]))
    print("  %d records in total" % total)
    if not counts:
        print("  the site is already empty")
    return {"counts": counts, "total": total, "confirm": CONFIRM}


# ---------------------------------------------------------------------- run

def run(confirm=None, wide=1, verbose=True):
    """Remove it. Irreversible."""
    if confirm != CONFIRM:
        frappe.throw("Wipe refused. Pass confirm='%s'. Run check() first."
                     % CONFIRM)

    wide = bool(int(wide))
    log = []
    parties = _tenants() + _landlords()
    cost_centers = _building_cost_centers()

    frappe.flags.in_import = True
    frappe.flags.ignore_links = True

    if verbose:
        print("STAGE 0 RUN")

    # 1. The ledger. Cancel before delete; dependants before dependencies.
    for dt in LEDGER:
        killed = 0
        for name in _ledger_names(dt, parties, wide):
            if _drop_submittable(dt, name):
                killed += 1
        if killed:
            log.append((dt, killed))
        frappe.db.commit()

    # 2. Everything the module owns. Two passes: a record whose dependant was
    #    removed in pass one can go in pass two, so an unknown dependency
    #    costs a retry rather than a manual ordering fix.
    doctypes = _order(_module_doctypes())
    for attempt in (1, 2):
        remaining = []
        for dt in doctypes:
            killed = 0
            try:
                names = frappe.get_all(dt, pluck="name")
            except Exception:
                continue
            for name in names:
                if _drop(dt, name):
                    killed += 1
            if killed:
                log.append((dt, killed))
            frappe.db.commit()
            try:
                if frappe.db.count(dt):
                    remaining.append(dt)
            except Exception:
                pass
        if not remaining:
            break
        doctypes = remaining
        if verbose and attempt == 1:
            print("  retrying %d doctype(s) that still hold records"
                  % len(remaining))

    # 3. Parties this app created.
    for dt, names in (("Customer", _tenants()), ("Supplier", _landlords())):
        killed = 0
        for name in names:
            if _drop(dt, name):
                killed += 1
        if killed:
            log.append(("%s (DarkBrown parties)" % dt, killed))
        frappe.db.commit()

    # 4. Per-building cost centres, now that nothing posts to them. A cost
    #    centre still carrying live ledger is left alone and reported by
    #    gate(), rather than deleted out from under a GL entry.
    killed = 0
    for cc in cost_centers:
        if not frappe.db.exists("Cost Center", cc):
            continue
        if frappe.db.exists("GL Entry", {"cost_center": cc, "is_cancelled": 0}):
            continue
        if _drop("Cost Center", cc):
            killed += 1
    if killed:
        log.append(("Cost Center (buildings)", killed))

    # 5. Naming counters, so the next load starts at 0001 rather than
    #    continuing the numbering of data that no longer exists.
    series = _reset_series()
    if series:
        log.append(("Naming series reset", series))

    frappe.flags.in_import = False
    frappe.flags.ignore_links = False
    frappe.db.commit()

    if verbose:
        for dt, n in log:
            print("  removed %5d  %s" % (n, dt))
        if not log:
            print("  nothing to remove — the site was already empty")

    return {"removed": dict(log)}


def _reset_series():
    """Zero the counters for series this app owns."""
    prefixes = ("HL-", "TA-", "CHQ-", "IR-", "MR-", "MO-", "CC-", "SD-",
                "DB-", "EXP-", "PC-", "WC-", "UB-", "DR-")
    reset = 0
    try:
        rows = frappe.get_all("Series", pluck="name")
    except Exception:
        return 0
    for name in rows:
        if any(name.startswith(p) for p in prefixes):
            try:
                frappe.db.sql("update tabSeries set current = 0 where name = %s",
                              name)
                reset += 1
            except Exception:
                pass
    frappe.db.commit()
    return reset


# --------------------------------------------------------------------- gate

def gate():
    """Prove the site is empty. This is the audit, not the loader's own word.

    Passing means the next stage may run. Failing names what is still there.
    """
    problems = []

    owned = _module_doctypes()
    if not owned:
        # Enumeration failed. Every count below would come back zero and the
        # gate would report a clean site because it could not see one. A gate
        # that passes when it is blind is worse than no gate.
        print("STAGE 0 GATE")
        print("  FAIL — could not enumerate the module's doctypes.")
        print("  Nothing was checked. Run bench migrate and try again.")
        return {"pass": False, "residue": {}, "blind": True}

    for dt in _order(owned):
        try:
            n = frappe.db.count(dt)
        except Exception:
            continue
        if n:
            problems.append((dt, n))

    for dt in LEDGER + ["GL Entry", "Payment Ledger Entry"]:
        try:
            n = frappe.db.count(dt)
        except Exception:
            continue
        if n:
            problems.append((dt, n))

    for label, names in (("Customer (tenants)", _tenants()),
                         ("Supplier (landlords)", _landlords())):
        if names:
            problems.append((label, len(names)))

    # The foundation must have survived. An empty site is not the same as a
    # broken one, and a wipe that took the company with it is worse than one
    # that left residue.
    missing = []
    if not frappe.db.count("Company"):
        missing.append("Company")
    if not frappe.db.count("Account"):
        missing.append("Account (chart of accounts)")
    if not frappe.db.count("Cost Center"):
        missing.append("Cost Center")

    print("STAGE 0 GATE")
    if missing:
        print("  FAIL — the foundation is gone, restore the backup:")
        for m in missing:
            print("    missing  %s" % m)
        return {"pass": False, "missing": missing,
                "residue": dict(problems)}
    if problems:
        print("  FAIL — %d doctype(s) still hold records:" % len(problems))
        for dt, n in problems:
            print("    %-34s %8d" % (dt, n))
        print("  Stage 1 must not run until this is zero.")
        return {"pass": False, "residue": dict(problems)}

    print("  PASS — the site is empty and the foundation is intact")
    print("    Company        %d" % frappe.db.count("Company"))
    print("    Accounts       %d" % frappe.db.count("Account"))
    print("    Cost Centres   %d" % frappe.db.count("Cost Center"))
    return {"pass": True, "residue": {}}


# ------------------------------------------------------------------ helpers

def _drop_submittable(doctype, name):
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
        print("  ! could not remove %s %s: %s"
              % (doctype, name, str(e).splitlines()[0][:80]))
        frappe.db.rollback()
        return False


def _drop(doctype, name):
    try:
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, delete_permanently=True)
        return True
    except Exception as e:
        print("  ! could not remove %s %s: %s"
              % (doctype, name, str(e).splitlines()[0][:80]))
        frappe.db.rollback()
        return False
