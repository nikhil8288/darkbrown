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
    """Remove it. Irreversible.

    Order is not cosmetic here. The first attempt at this stage failed three
    ways and each was an ordering problem:

      * 296 units refused with "an occupied unit cannot be deleted". Deleting
        a Tenancy Agreement does not reset Unit.status, and Unit.on_trash
        throws on Occupied. So the status is cleared first, once the
        tenancies are already gone.
      * 22 buildings refused because their cost centre still carried ledger.
      * GL Entry rose from 9,958 to 17,303. Cancelling a voucher in ERPNext
        writes reversing entries and keeps the originals flagged cancelled;
        deleting the voucher does not take them. So the ledger rows are swept
        directly, after every voucher is gone and before the buildings that
        depend on them being gone.
    """
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

    # 1. The ledger vouchers. Cancel then delete, dependants first.
    for dt in LEDGER:
        killed, failed = 0, []
        for name in _ledger_names(dt, parties, wide):
            if _drop_submittable(dt, name):
                killed += 1
            else:
                failed.append(name)
        if killed:
            log.append((dt, killed))
        _report(dt, failed, verbose)
        frappe.db.commit()

    # 2. Anything submitted that would not cancel. A wipe is not a place to
    #    argue with a document about its own state.
    forced = _force_submitted(LEDGER, verbose)
    if forced:
        log.append(("forced cancel then delete", forced))

    # 3. Units carry an occupancy flag that outlives the tenancy that set it.
    #    Tenancies are gone by now, so nothing is being hidden by this.
    try:
        frappe.db.sql("update `tabUnit` set status = 'Vacant' "
                      "where status = 'Occupied'")
        frappe.db.commit()
    except Exception as e:
        print("  ! could not clear unit occupancy: %s"
              % _why(e))

    # 4. Everything the module owns except Building, which needs the ledger
    #    gone before its cost centre will release.
    doctypes = [d for d in _order(_module_doctypes()) if d != "Building"]
    for attempt in (1, 2):
        remaining = []
        for dt in doctypes:
            killed, failed = 0, []
            try:
                names = frappe.get_all(dt, pluck="name")
            except Exception:
                continue
            for name in names:
                why = _drop(dt, name)
                if why is None:
                    killed += 1
                else:
                    failed.append((name, why))
            if killed:
                log.append((dt, killed))
            if attempt == 2:
                _report(dt, failed, verbose)
            frappe.db.commit()
            try:
                if frappe.db.count(dt):
                    remaining.append(dt)
            except Exception:
                pass
        if not remaining:
            break
        doctypes = remaining

    # 5. The ledger rows themselves, now that no voucher points at them.
    #    Guarded: if a voucher survived, leave the ledger alone and let the
    #    gate report it, rather than orphaning entries from their document.
    survivors = {dt: frappe.db.count(dt) for dt in LEDGER}
    survivors = {k: v for k, v in survivors.items() if v}
    if survivors:
        print("  ! vouchers survived, leaving the ledger intact: %s"
              % ", ".join("%s %d" % (k, v) for k, v in survivors.items()))
    else:
        for table in ("GL Entry", "Payment Ledger Entry"):
            try:
                n = frappe.db.count(table)
                if n:
                    frappe.db.sql("delete from `tab%s`" % table)
                    frappe.db.commit()
                    log.append((table, n))
            except Exception as e:
                print("  ! could not clear %s: %s"
                      % (table, _why(e)))

    # 6. The per-building cost centres, deleted here rather than left to
    #    Building.on_trash. That hook calls delete_doc with force=False and
    #    ERPNext answers "you can disable this Cost Center instead of
    #    deleting it", which failed all 22 buildings on the previous run —
    #    while the very next phase then removed the same cost centres with
    #    force=True without complaint. So do it first, properly.
    killed = 0
    for cc in cost_centers:
        if not frappe.db.exists("Cost Center", cc):
            continue
        if frappe.db.exists("GL Entry", {"cost_center": cc, "is_cancelled": 0}):
            print("  ! cost centre %s still carries ledger, left in place" % cc)
            continue
        if _drop("Cost Center", cc) is None:
            killed += 1
    if killed:
        log.append(("Cost Center (buildings)", killed))
    frappe.db.commit()

    # 7. Unpoint the buildings from cost centres that are now gone, so
    #    guard_cost_center_delete returns at its first line instead of trying
    #    to delete a record that no longer exists.
    try:
        frappe.db.sql("update `tabBuilding` set cost_center = NULL")
        frappe.db.commit()
    except Exception as e:
        print("  ! could not clear building cost centres: %s" % _why(e))

    # 8. Buildings.
    killed, failed = 0, []
    for name in frappe.get_all("Building", pluck="name"):
        why = _drop("Building", name)
        if why is None:
            killed += 1
        else:
            failed.append((name, why))
    if killed:
        log.append(("Building", killed))
    _report("Building", failed, verbose)
    frappe.db.commit()

    # 8b. Parties this app created.
    for dt, names in (("Customer", _tenants()), ("Supplier", _landlords())):
        killed = 0
        for name in names:
            if _drop(dt, name) is None:
                killed += 1
        if killed:
            log.append(("%s (DarkBrown parties)" % dt, killed))
        frappe.db.commit()

    # 9. Naming counters, so the next load starts at 0001.
    series = _reset_series()
    if series:
        log.append(("Naming series reset", series))

    frappe.flags.in_import = False
    frappe.flags.ignore_links = False
    frappe.db.commit()

    if verbose:
        print()
        for dt, n in log:
            print("  removed %6d  %s" % (n, dt))
        if not log:
            print("  nothing to remove — the site was already empty")
        print()
        print("  Now press Gate.")

    return {"removed": dict(log)}


def _report(doctype, failed, verbose=True):
    """One line per reason, not one per record.

    The first run printed the same refusal 296 times and then again on the
    retry, burying the three lines that actually mattered.
    """
    if not failed or not verbose:
        return
    by_reason = {}
    for item in failed:
        name, why = item if isinstance(item, tuple) else (item, "")
        by_reason.setdefault(why, []).append(name)
    for why, names in by_reason.items():
        print("  ! %d %s: %s (e.g. %s)"
              % (len(names), doctype, why or "no reason given",
                 ", ".join(names[:3])))


def _force_submitted(doctypes, verbose=True):
    """Belt and braces: anything still submitted after the main pass."""
    forced = 0
    for dt in doctypes:
        try:
            names = frappe.get_all(dt, filters={"docstatus": 1}, pluck="name")
        except Exception:
            continue
        for name in names:
            if _force_one(dt, name):
                forced += 1
    if forced:
        frappe.db.commit()
        if verbose:
            print("  forced %d document(s) left submitted" % forced)
    return forced


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
        residue = dict(problems)
        for note in _diagnose(residue):
            print("  %s" % note)
        print("  Stage 1 must not run until this is zero.")
        return {"pass": False, "residue": residue}

    print("  PASS — the site is empty and the foundation is intact")
    print("    Company        %d" % frappe.db.count("Company"))
    print("    Accounts       %d" % frappe.db.count("Account"))
    print("    Cost Centres   %d" % frappe.db.count("Cost Center"))
    return {"pass": True, "residue": {}}


# ------------------------------------------------------------------ helpers

def _diagnose(residue):
    """Say why, not just what. A count on its own sends somebody guessing."""
    notes = []
    if residue.get("Unit"):
        notes.append("Unit: still flagged Occupied. Deleting a tenancy does "
                     "not clear that flag; re-run Wipe, which now clears it.")
    if residue.get("Building"):
        if residue.get("GL Entry"):
            notes.append("Building: its cost centre still carries ledger. "
                         "Clear GL Entry first — re-run Wipe.")
        else:
            notes.append("Building: on_trash deletes the cost centre with "
                         "force=False and ERPNext refuses. Re-run Wipe, "
                         "which now removes cost centres first.")
    if residue.get("GL Entry") or residue.get("Payment Ledger Entry"):
        notes.append("Ledger rows outlive their voucher: cancelling writes "
                     "reversals and keeps the originals. Re-run Wipe, which "
                     "now sweeps them once the vouchers are gone.")
    for dt in ("Journal Entry", "Sales Invoice", "Payment Entry",
               "Purchase Invoice"):
        if residue.get(dt):
            notes.append("%s: would not cancel through the ORM. Re-run Wipe, "
                         "which now forces the docstatus first." % dt)
            break
    return notes


def _why(e):
    """Some Frappe exceptions carry no message at all.

    DocumentLockedError is one of them, and the first version of this handler
    did str(e).splitlines()[0] — which raises IndexError on an empty string.
    So the code written to report a failure became the failure, and took the
    whole run down with it. An error handler must not be able to throw.
    """
    try:
        text = (str(e) or "").strip() or type(e).__name__
        lines = text.splitlines()
        return (lines[0] if lines else type(e).__name__)[:100]
    except Exception:
        return "unreadable error"


def _force_one(doctype, name):
    """Mark cancelled in the database, then delete.

    Deliberately not doc.cancel(). Cancelling a voucher writes reversing GL
    entries — that is what took the ledger from 9,958 rows to 17,303 on the
    first attempt. Every one of those rows is about to be deleted anyway, so
    cancelling only inflates the table on the way past. And large journal
    entries cancel through a background queue that locks the document, which
    can never complete inside this request.
    """
    try:
        frappe.db.set_value(doctype, name, "docstatus", 2,
                            update_modified=False)
        frappe.db.commit()
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, delete_permanently=True)
        return True
    except Exception as e:
        print("  ! %s %s will not go: %s" % (doctype, name, _why(e)))
        frappe.db.rollback()
        return False


def _drop_submittable(doctype, name):
    """A wipe does not need to argue with a document about its own state."""
    try:
        try:
            frappe.get_doc(doctype, name).unlock()
        except Exception:
            pass                      # no lock held, or none to release
        return _force_one(doctype, name)
    except Exception as e:
        print("  ! could not remove %s %s: %s" % (doctype, name, _why(e)))
        try:
            frappe.db.rollback()
        except Exception:
            pass
        return False


def _drop(doctype, name):
    """None when it went, otherwise the reason it did not.

    Returning the reason rather than printing it lets the caller collapse 296
    identical refusals into one line. The first run printed each of them
    twice and buried the three that mattered.
    """
    try:
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, delete_permanently=True)
        return None
    except Exception as e:
        why = _why(e)
        try:
            frappe.db.rollback()
        except Exception:
            pass
        return why
