"""Clean rebuild: empty the site, load AK-12 with its tenants and their
payment history, prove the result. Four commands, run in this order.

    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.check
    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.reset \\
        --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.load
    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.verify

or the whole thing in one go:

    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.rebuild \\
        --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"

WHAT CHANGED IN REVISION 6 - THE STATEMENTS

Revision 5 loaded the records correctly and the ledger wrongly, so the trial
balance, P&L, balance sheet and cash flow all read nonsense. Two causes, both
in the load, not in `api/statements.py` (which was querying the GL honestly -
there was simply nothing right in the GL to find):

  1. The rent invoices posted as opening entries. `is_opening = "Yes"` parks
     the debit in Temporary Opening and recognises no income. That was the
     right call while the manual books still owned these months, but the site
     has been emptied and AK-12 is now the whole ledger, so there is nothing
     to double-count against. Result: P&L income 0, a 256,400 credit stuck in
     Temporary Opening on the trial balance, and a balance sheet that netted
     itself to nothing. Now they post as real income - item "Rent", Rental
     Income, the building's cost centre - exactly like the live invoicer.

  2. The head-lease cost was never in the ledger at all, historically or
     otherwise. Nothing in the application posts it: `Head Lease.payments` is
     a schedule the cheque screens read, the MD dashboard counts unpaid
     Purchase Invoices, and no code path anywhere creates one. So the spread,
     the one number this business turns on, could not appear on any statement.
     `load_ak12_headlease` posts the nine months as Purchase Invoices against
     AL MADAR with matching payments.

Together: income 256,400, cost 162,000, spread 94,400. `verify` now runs the
real `api.statements` endpoints and checks those numbers, plus that the
balance sheet balances and the cash flow reconciles, rather than only counting
records.

Going forward the same two accounts are used by `api.finance`'s live invoice
run, so August onward books itself the same way. The landlord side does not
yet have a live counterpart - see the note at the end of DEPLOY.md.

WHY `check` EXISTS

Three loads in a row failed the same way, and the cause was never the site:
the fixed files had not reached it. A zip unpacked to the wrong folder, or a
commit in GitHub Desktop with new files left unticked, deploys nothing and
looks identical to a load that ran. `check` reads the files that are actually
on the server, prints this pack's REVISION, and refuses to say "ready" unless
every fix it depends on is present in the deployed source. If `check` does not
print `REVISION 5`, stop: the deploy did not land, and nothing below will work.

WHY `reset` DOES MORE THAN `demo.purge`

`demo/purge.py` only deletes Customers flagged `db_is_tenant` and Suppliers
flagged `db_is_landlord`. The abandoned full-portfolio load left ~270
Customers on the site without the flag, so a purge walked past them and the
site never came back clean. `reset` flags every party first so the purge can
see them, runs the purge wide, then sweeps the data doctypes the purge does not
list (Historical Monthly PL, Weekly Closing, Petty Cash, bank imports and so
on). It leaves Company, accounts, users, roles, DBR Settings, Document
Requirements and Staff Members alone - those are configuration, not data.

WHY `load` STOPS

Each step depends on the one before. Tenancies resolve against Customers and
Units; history posts against Customers. A step that fails stops the run and
prints why, rather than letting the next step fail on the consequences.

`verify` is the proof: it counts what is on the site and compares it with what
the pack should have produced. Every line must say ok.
"""
import json
import os
import traceback

import frappe
from frappe.utils import getdate

REVISION = 10
CONFIRM = "REMOVE ALL DARKBROWN DATA"
HERE = os.path.dirname(os.path.abspath(__file__))

#: Every file this load reads, with the string that proves it is the fixed
#: version. A file that exists but is the old copy is the failure mode that
#: cost three attempts, so existence alone is not enough.
DEPLOYED = [
    ("ak12_rebuild.py",       "REVISION = 10"),
    ("wipe_ledger_once.py",   "no buildings"),
    ("wipe_ledger.py",        "direct table delete"),
    ("ak12_doctor.py",        "AK-12 DOCTOR"),
    ("load_ak12_history.py",  "income_account(company)"),
    ("load_ak12_headlease.py", "AK12-HL-INV"),
    ("_ledger_common.py",     "Head Lease Rent"),
    ("ak12_headlease.csv",    "Head lease HL AK-12"),
    ("load_customers.py",     "had the tenant flag switched on"),
    ("import_tenancies.py",   'open(path, encoding="utf-8-sig")'),
    ("seed_opening_arrears.py", "EXPECTED_TOTAL = 0.00"),
    ("load_buildings.py",     "def run"),
    ("customers.json",        "MUHAMMED ASHIQUE PARACHOLAKUZHI"),
    ("buildings_payload.json", '"AK-12"'),
    ("tenancies.csv",         "PLACEHOLDER RENEWAL (RN02)"),
    ("ak12_history.csv",      "Revenue sheet row"),
    ("opening_arrears.csv",   "source,property_code"),
]

#: Data doctypes demo.purge does not list. Config doctypes are deliberately
#: absent: DBR Settings, Document Requirement, Staff Member.
EXTRA = [
    "Bank Statement Import", "Bank Balance Declaration", "Weekly Closing",
    "Petty Cash Entry", "Document Archive", "Building Scenario",
    "MD Alert Dismissal", "Historical Monthly PL",
]

#: What the pack produces. verify() checks each of these, records first and
#: then the statements themselves - the point of the load is that the P&L,
#: balance sheet and cash flow come out right with nobody adjusting them.
EXPECT = {
    "Building": 1, "Unit": 8, "Head Lease": 1, "Supplier": 1,
    "Customer": 9, "Tenancy Agreement": 11,
    "Sales Invoice": 69, "Purchase Invoice": 9, "Payment Entry": 78,
    "units_occupied": 7, "units_vacant": 1,
    "tenancies_live": 7, "tenancies_expired": 4,
    "charged": 256400.00, "collected": 255800.00, "receivable": 600.00,
    "accrued": 162000.00, "paid_landlord": 162000.00, "payable": 0.00,
}

#: The statements, over the whole history window. Income less head-lease cost
#: is the spread; cash is what came in less what went out; the balance sheet
#: must balance and the cash flow must reconcile on their own arithmetic.
EXPECT_STATEMENTS = {
    "pl_income": 256400.00, "pl_expense": 162000.00, "pl_net": 94400.00,
    "bs_assets": 94400.00, "bs_difference": 0.00,
    "cf_closing": 93800.00, "cf_difference": 0.00,
}

#: The statement window: first month of history to the end of the last.
STATEMENT_FROM = "2025-11-01"
STATEMENT_TO = "2026-07-31"

#: The history spans these months; a Fiscal Year must cover each.
HISTORY_DATES = ("2025-11-05", "2026-07-05")

BAR = "-" * 72


def _force_drop(doctype, name):
    """Remove a voucher that will not cancel.

    The normal path is cancel-then-delete, and it is the right one: cancelling
    reverses the GL properly. It fails on an *orphaned* voucher - one whose
    supplier, customer or cost centre has already been deleted - because
    cancel re-reads those links to build the reversal. The purge catches the
    exception and moves on, which is how eight landlord invoices survived a
    purge that reported success and left 182,000 of expense on an otherwise
    empty site.

    So: try the correct path first, and only if it raises, mark the voucher
    cancelled and delete its ledger rows directly. That is a blunt instrument
    and it is limited to reset, where the whole ledger is going anyway.
    """
    try:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                          ignore_missing=True, delete_permanently=True)
        frappe.db.commit()
        return "cancelled"
    except Exception as first:
        frappe.db.rollback()
        try:
            frappe.db.set_value(doctype, name, "docstatus", 2,
                                update_modified=False)
            for dt in ("GL Entry", "Payment Ledger Entry"):
                if frappe.db.exists("DocType", dt):
                    frappe.db.delete(dt, {"voucher_type": doctype,
                                          "voucher_no": name})
            frappe.delete_doc(doctype, name, force=True,
                              ignore_permissions=True, ignore_missing=True,
                              ignore_on_trash=True, delete_permanently=True)
            frappe.db.commit()
            print("      forced %s %s (would not cancel: %s)"
                  % (doctype, name, str(first)[:90]))
            return "forced"
        except Exception as second:
            frappe.db.rollback()
            print("      ! %s %s survived both attempts: %s"
                  % (doctype, name, str(second)[:90]))
            return "stuck"


def _orphan_sweep():
    """Anything still posting to the GL after the purge, removed by force."""
    seen, out = set(), {"cancelled": 0, "forced": 0, "stuck": 0}
    for r in frappe.get_all("GL Entry", filters={"is_cancelled": 0},
                            fields=["voucher_type", "voucher_no"],
                            group_by="voucher_type, voucher_no", limit=5000):
        key = (r.voucher_type, r.voucher_no)
        if key in seen:
            continue
        seen.add(key)
        out[_force_drop(r.voucher_type, r.voucher_no)] += 1
    return out


def _ledger_state():
    """What is on the GL, and whether it is safe to load onto.

    This is the check that was missing. Revision 6 gated on `check`, which
    reads files and site settings and says nothing about the ledger, so a
    `load` onto a site still carrying revision-5 opening invoices and a
    portfolio-wide landlord run did nothing visible and reported success:
    every rent invoice was skipped as already-present, and the wrong ones
    stayed. Counting records cannot see that. Counting GL rows can.
    """
    live = frappe.db.count("GL Entry", {"is_cancelled": 0})

    opening = untagged_si = 0
    for d in frappe.get_all("Sales Invoice", filters={"docstatus": 1},
                            fields=["remarks", "is_opening"], limit=5000):
        if (d.is_opening or "") == "Yes":
            opening += 1
        elif "[AK12-HIST-INV-" not in (d.remarks or ""):
            untagged_si += 1
    untagged_pi = sum(
        1 for d in frappe.get_all("Purchase Invoice", filters={"docstatus": 1},
                                  fields=["remarks"], limit=5000)
        if "[AK12-HL-INV-" not in (d.remarks or ""))
    journals = frappe.db.count("Journal Entry", {"docstatus": 1})

    # A ledger made only of this pack's own vouchers is not a problem: that is
    # a half-finished load, and re-running is how you finish it. What must
    # stop a load is a voucher this pack did not write, because the loaders
    # will skip past it and leave its amount on the statements.
    foreign = opening + untagged_si + untagged_pi + journals
    return {"gl_rows": live, "opening_invoices": opening,
            "untagged_sales_invoices": untagged_si,
            "untagged_purchase_invoices": untagged_pi,
            "journal_entries": journals, "foreign": foreign,
            "empty": live == 0, "clean": foreign == 0}


def _h(t):
    print("\n" + BAR + "\n  " + t + "\n" + BAR)


def _tb():
    return "    " + traceback.format_exc().strip().replace("\n", "\n    ")


def _count(dt, filters=None):
    try:
        return frappe.db.count(dt, filters or {})
    except Exception:
        return None


# ------------------------------------------------------------------- check

def check():
    """Read-only. Is the fixed pack on this server, and can the site take it?"""
    ok = True
    print("=" * 72)
    print("  AK-12 REBUILD - REVISION %d" % REVISION)
    print("=" * 72)

    _h("1. Deployed files (read from %s)" % HERE)
    for fname, proof in DEPLOYED:
        p = os.path.join(HERE, fname)
        if not os.path.exists(p):
            print("    MISSING  %s" % fname)
            ok = False
            continue
        raw = open(p, "rb").read()
        bom = raw.startswith(b"\xef\xbb\xbf")
        has = proof.encode("utf-8") in raw
        print("    %s  %-26s %7d bytes%s%s"
              % ("ok     " if has else "OLD    ", fname, len(raw),
                 "   BOM (harmless now, loaders strip it)" if bom else "",
                 "" if has else "   <-- not the revision-%d file" % REVISION))
        ok = ok and has
    try:
        import darkbrown.api.cutover as cutover
        src = open(cutover.__file__.replace(".pyc", ".py"), "rb").read()
        has = b"load_ak12_history" in src
        print("    %s  %-26s%s" % ("ok     " if has else "OLD    ",
                                    "api/cutover.py",
                                    "" if has else
                                    "   <-- Data screen still lacks the history step"))
        ok = ok and has
    except Exception:
        print("    ?       api/cutover.py could not be read")

    _h("2. Site prerequisites")
    company = frappe.db.get_single_value("DBR Settings", "default_company")
    print("    DBR Settings.default_company : %s"
          % (company or "!! NOT SET - set it, then re-run check"))
    ok = ok and bool(company)
    if company:
        recv = frappe.db.get_value("Account", {"account_type": "Receivable",
                                               "company": company,
                                               "is_group": 0}, "name")
        print("    receivable account           : %s" % (recv or "!! NONE"))
        ok = ok and bool(recv)
        cash = frappe.db.get_value("Account", {"account_type": ["in", ("Bank", "Cash")],
                                               "company": company,
                                               "is_group": 0}, "name")
        print("    bank/cash account            : %s" % (cash or "!! NONE"))
        ok = ok and bool(cash)
    cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    sg = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
    print("    leaf Customer Group          : %s" % (cg or "!! NONE"))
    print("    leaf Supplier Group          : %s" % (sg or "!! NONE"))
    ok = ok and bool(cg and sg)
    for mop in ("Cash", "Cheque"):
        present = frappe.db.exists("Mode of Payment", mop)
        print("    Mode of Payment '%s'%s: %s"
              % (mop, " " * (7 - len(mop)), "present" if present else "!! MISSING"))
        ok = ok and bool(present)
    for dt, fn in (("Customer", "db_is_tenant"), ("Supplier", "db_is_landlord")):
        present = frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn})
        print("    field %s.%-14s : %s" % (dt, fn, "present" if present
                                            else "!! MISSING - bench migrate"))
        ok = ok and bool(present)
    fy_state, fy_msg = _fiscal_years(company, create=False)
    print("    fiscal years                 : %s" % fy_msg)
    ok = ok and fy_state != "blocked"

    _h("3. What is on the site now")
    for dt in ("Building", "Unit", "Head Lease", "Tenancy Agreement",
               "Customer", "Supplier", "Sales Invoice", "Payment Entry",
               "Journal Entry", "Collection Case", "Cheque") + tuple(EXTRA):
        n = _count(dt)
        if n is None:
            continue
        line = "    %-26s %6d" % (dt, n)
        if dt == "Customer":
            line += "   (%d flagged as tenant)" % (_count(dt, {"db_is_tenant": 1}) or 0)
        if dt == "Supplier":
            line += "   (%d flagged as landlord)" % (_count(dt, {"db_is_landlord": 1}) or 0)
        print(line)

    _h("Verdict")
    if ok:
        print("  READY. Next: reset (with the confirm phrase), then load.")
    else:
        print("  NOT READY. Fix every line marked !! or OLD above first.")
        print("  OLD means the file on this server is not the revision-%d copy:"
              % REVISION)
        print("  the deploy did not land. Re-unzip over the repo root, make sure")
        print("  every file is ticked in GitHub Desktop, commit, deploy, re-run.")
    return {"ready": ok, "revision": REVISION}


def _fiscal_years(company, create):
    """Every history date must fall inside a Fiscal Year or the invoices refuse
    to post. Reports, and with create=True adds calendar years to match the
    site's existing convention."""
    fys = frappe.get_all("Fiscal Year", fields=["name", "year_start_date",
                                                "year_end_date"])
    if not fys:
        return "blocked", "!! NONE on the site - create one in ERPNext first"
    calendar = all(getdate(f.year_start_date).month == 1
                   and getdate(f.year_start_date).day == 1 for f in fys)
    missing = []
    for d in HISTORY_DATES:
        d = getdate(d)
        if not any(getdate(f.year_start_date) <= d <= getdate(f.year_end_date)
                   for f in fys):
            missing.append(d.year)
    missing = sorted(set(missing))
    have = ", ".join(sorted(f.name for f in fys))
    if not missing:
        return "ok", "%s - covers %s to %s" % (have, *HISTORY_DATES)
    years = ", ".join(str(y) for y in missing)
    if not calendar:
        return ("blocked", "%s - !! nothing covers %s, and the fiscal years "
                "here are not calendar years, so create it by hand first"
                % (have, years))
    if not create:
        return "fixable", "%s - nothing covers %s; load() adds it" % (have, years)
    for y in missing:
        frappe.get_doc({"doctype": "Fiscal Year", "year": str(y),
                        "year_start_date": "%d-01-01" % y,
                        "year_end_date": "%d-12-31" % y}).insert(
                            ignore_permissions=True)
    frappe.db.commit()
    return "ok", "created calendar year(s) %s" % years


# ------------------------------------------------------------------- reset

def reset(confirm=None):
    """Empty the site. Destructive, irreversible, needs the exact phrase."""
    from darkbrown.demo import purge as purge_mod

    if confirm != CONFIRM:
        print("Refused. Pass confirm='%s' to go ahead." % CONFIRM)
        print("Run check first to see what is on the site.")
        return {"aborted": True}

    _h("reset 1/3  flag every party so the purge can see it")
    cust = frappe.get_all("Customer", filters={"db_is_tenant": ["!=", 1]},
                          pluck="name")
    supp = frappe.get_all("Supplier", filters={"db_is_landlord": ["!=", 1]},
                          pluck="name")
    for name in cust:
        frappe.db.set_value("Customer", name, "db_is_tenant", 1,
                            update_modified=False)
    for name in supp:
        frappe.db.set_value("Supplier", name, "db_is_landlord", 1,
                            update_modified=False)
    frappe.db.commit()
    print("    flagged %d Customers and %d Suppliers" % (len(cust), len(supp)))

    _h("reset 2/3  purge (ledger, DarkBrown records, parties, cost centres)")
    out = purge_mod.run(confirm=CONFIRM, wide=True, verbose=True)

    _h("reset 3/3  data doctypes the purge does not list")
    frappe.flags.in_import = True
    frappe.flags.ignore_links = True
    swept = {}
    for dt in EXTRA:
        if not frappe.db.exists("DocType", dt):
            continue
        n = 0
        for name in frappe.get_all(dt, pluck="name"):
            try:
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True,
                                  ignore_missing=True, ignore_on_trash=True,
                                  delete_permanently=True)
                n += 1
            except Exception as e:
                print("    ! could not remove %s %s: %s" % (dt, name, e))
        if n:
            swept[dt] = n
            print("    removed %5d  %s" % (n, dt))
        frappe.db.commit()
    frappe.flags.in_import = False
    frappe.flags.ignore_links = False
    if not swept:
        print("    nothing to remove")

    _h("left on the site")
    left = {}
    for dt in ("Building", "Unit", "Head Lease", "Tenancy Agreement",
               "Customer", "Supplier", "Sales Invoice", "Payment Entry",
               "Journal Entry", "Collection Case", "Cheque") + tuple(EXTRA):
        n = _count(dt)
        if n is None:
            continue
        left[dt] = n
        print("    %-26s %5d%s" % (dt, n, "" if not n else "   <-- NOT EMPTY"))
    st = _ledger_state()
    if st["gl_rows"]:
        _h("reset 4/4  vouchers still posting to the ledger")
        print("    %d GL entries survived the purge. Almost always these are"
              % st["gl_rows"])
        print("    orphans - the party they were written against is already")
        print("    gone, so they cannot be cancelled the normal way.")
        swept = _orphan_sweep()
        print("\n    cancelled %d, forced %d, stuck %d"
              % (swept["cancelled"], swept["forced"], swept["stuck"]))
        st = _ledger_state()

    print("\n    %-26s %5d%s" % ("GL Entry (live)", st["gl_rows"],
                                 "" if not st["gl_rows"] else "   <-- NOT EMPTY"))
    if st["gl_rows"]:
        left["GL Entry"] = st["gl_rows"]
        print("\n  The ledger still has entries. That is what matters, more "
              "than the")
        print("  record counts above - a leftover voucher puts its whole "
              "amount on")
        print("  the P&L. What is left, by account:")
        for r in frappe.get_all("GL Entry", filters={"is_cancelled": 0},
                                fields=["account", "voucher_type",
                                        "count(name) as n",
                                        "sum(debit) as dr", "sum(credit) as cr"],
                                group_by="account, voucher_type", limit=200):
            print("      %-34s %-16s %4d rows  dr %12s cr %12s"
                  % (str(r.account)[:34], r.voucher_type, r.n,
                     format(float(r.dr or 0), ",.2f"),
                     format(float(r.cr or 0), ",.2f")))

    if any(left.values()):
        print("\n  Nothing on the document layer can shift what is left. Use")
        print("  the direct table delete instead - it needs no deploy:")
        print("      bench --site erp.darkbrown.qa console")
        print("  then paste darkbrown/patches/WIPE_CONSOLE.txt, or run")
        print("      ...darkbrown.patches.wipe_ledger.run")
        print("\n  Something refused to delete. The reason is printed per record")
        print("  above - usually a submitted voucher that could not be cancelled.")
        print("  Fix that record in the desk and run reset again; it is safe to")
        print("  repeat.")
    else:
        print("\n  site is empty")
    return {"purged": out, "swept": swept, "left": left}


# -------------------------------------------------------------------- load

def load(_checked=False):
    """Customers -> building and units -> tenancies -> history. Stops on the
    first failure. Safe to re-run: every loader skips what already exists."""
    from darkbrown.patches import load_customers, load_buildings
    from darkbrown.patches import import_tenancies, load_ak12_history
    from darkbrown.patches import load_ak12_headlease

    if not _checked:
        r = check()
        if not r["ready"]:
            print("\n  LOAD NOT STARTED - check is not clean.")
            return {"aborted": True, "at": "check"}

    st = _ledger_state()
    if st["clean"] and not st["empty"]:
        print("\n  This site already carries %d GL entries, all of them from "
              "this pack." % st["gl_rows"])
        print("  Treating it as a half-finished load and resuming; every step "
              "below")
        print("  skips what it has already created.")
    if not st["clean"]:
        _h("LOAD NOT STARTED - this ledger has vouchers the pack did not write")
        print("    live GL entries                       %6d" % st["gl_rows"])
        print("    revision-5 opening rent invoices      %6d"
              % st["opening_invoices"])
        print("    rent invoices not from this pack      %6d"
              % st["untagged_sales_invoices"])
        print("    landlord invoices not from this pack  %6d"
              % st["untagged_purchase_invoices"])
        print("    journal entries                       %6d"
              % st["journal_entries"])
        print("""
  Loading onto this would not fix it. Every rent invoice already carries its
  [AK12-HIST-INV-nnn] tag, so the loader skips all 69 and the wrong ones stay
  exactly where they are - which is why the last load appeared to do nothing.

  Run the doctor to see what is there:
      ...ak12_doctor.run
  then clear it and load in one go:
      ...ak12_rebuild.rebuild --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
""")
        return {"aborted": True, "at": "dirty ledger", "ledger": st}

    company = frappe.db.get_single_value("DBR Settings", "default_company")
    fy_state, fy_msg = _fiscal_years(company, create=True)
    print("\n  fiscal years: %s" % fy_msg)
    if fy_state != "ok":
        print("\n  LOAD NOT STARTED - fiscal years are not in place.")
        return {"aborted": True, "at": "fiscal year"}

    _h("load 1/5  Customers (9)")
    try:
        out = load_customers.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "customers"}
    if out.get("aborted") or out.get("failed"):
        print("\n  STOPPED at customers. Nothing after this was attempted.")
        return {"aborted": True, "at": "customers"}

    _h("load 2/5  Building, units, head lease")
    try:
        out = load_buildings.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "buildings"}
    if out.get("failed"):
        print("\n  STOPPED at buildings. Nothing after this was attempted.")
        return {"aborted": True, "at": "buildings"}

    _h("load 3/5  Tenancy agreements (11)")
    try:
        d = import_tenancies.dry_run()
        if d.get("problems") or d.get("conflicts"):
            print("\n  STOPPED at tenancies - dry run is not clean (see above).")
            return {"aborted": True, "at": "tenancies"}
        out = import_tenancies.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "tenancies"}
    if out.get("aborted"):
        return {"aborted": True, "at": "tenancies"}

    _h("load 4/5  Rent history (69 invoices, 69 receipts)")
    try:
        d = load_ak12_history.dry_run()
        if d.get("problems") or not d.get("ok"):
            print("\n  STOPPED at history - dry run is not clean (see above).")
            return {"aborted": True, "at": "history"}
        out = load_ak12_history.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "history"}
    if out.get("aborted"):
        return {"aborted": True, "at": "history"}

    _h("load 5/5  Head-lease cost (9 purchase invoices, 9 payments)")
    try:
        d = load_ak12_headlease.dry_run()
        if d.get("problems") or not d.get("ok"):
            print("\n  STOPPED at head lease - dry run is not clean (above).")
            return {"aborted": True, "at": "head lease"}
        out = load_ak12_headlease.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "head lease"}
    if out.get("aborted"):
        return {"aborted": True, "at": "head lease"}

    return verify()


# ------------------------------------------------------------------ verify

def verify():
    """Count what is on the site against what the pack should produce."""
    _h("verify")
    got = {}
    for dt in ("Building", "Unit", "Head Lease", "Supplier", "Customer",
               "Tenancy Agreement"):
        got[dt] = _count(dt) or 0
    got["Sales Invoice"] = _count("Sales Invoice", {"docstatus": 1}) or 0
    got["Purchase Invoice"] = _count("Purchase Invoice", {"docstatus": 1}) or 0
    got["Payment Entry"] = _count("Payment Entry", {"docstatus": 1}) or 0
    got["units_occupied"] = _count("Unit", {"status": "Occupied"}) or 0
    got["units_vacant"] = _count("Unit", {"status": "Vacant"}) or 0
    got["tenancies_live"] = _count(
        "Tenancy Agreement", {"status": ["in", ("Active", "Expiring")]}) or 0
    got["tenancies_expired"] = _count(
        "Tenancy Agreement", {"status": "Expired"}) or 0
    inv = frappe.get_all("Sales Invoice", filters={"docstatus": 1},
                         fields=["customer", "grand_total", "outstanding_amount"])
    got["charged"] = round(sum(float(i.grand_total or 0) for i in inv), 2)
    got["receivable"] = round(sum(float(i.outstanding_amount or 0)
                                  for i in inv), 2)
    pin = frappe.get_all("Purchase Invoice", filters={"docstatus": 1},
                         fields=["grand_total", "outstanding_amount"])
    got["accrued"] = round(sum(float(i.grand_total or 0) for i in pin), 2)
    got["payable"] = round(sum(float(i.outstanding_amount or 0)
                               for i in pin), 2)
    got["collected"] = round(sum(float(p) for p in frappe.get_all(
        "Payment Entry", filters={"docstatus": 1, "payment_type": "Receive"},
        pluck="paid_amount")), 2)
    got["paid_landlord"] = round(sum(float(p) for p in frappe.get_all(
        "Payment Entry", filters={"docstatus": 1, "payment_type": "Pay"},
        pluck="paid_amount")), 2)

    all_ok = True
    for k, want in EXPECT.items():
        g = got.get(k)
        ok = (abs(float(g) - float(want)) < 0.005) if isinstance(want, float) \
            else g == want
        all_ok = all_ok and ok
        if isinstance(want, float):
            print("    %-20s %12s  expected %12s  %s"
                  % (k, format(g, ",.2f"), format(want, ",.2f"),
                     "ok" if ok else "<-- MISMATCH"))
        else:
            print("    %-20s %12s  expected %12s  %s"
                  % (k, g, want, "ok" if ok else "<-- MISMATCH"))

    all_ok = _statements() and all_ok

    print()
    by = {}
    for i in inv:
        by[i.customer] = by.get(i.customer, 0.0) + float(i.outstanding_amount or 0)
    owing = {c: round(v, 2) for c, v in by.items() if abs(v) >= 0.005}
    names = {c.name: c.customer_name for c in frappe.get_all(
        "Customer", fields=["name", "customer_name"])}
    if owing:
        print("    outstanding by tenant:")
        for c, v in sorted(owing.items(), key=lambda x: -x[1]):
            print("      %-34s %10s" % (names.get(c, c)[:34], format(v, ",.2f")))
    else:
        print("    nobody owes anything")

    units = frappe.get_all("Unit", filters={"building": "AK-12"},
                           fields=["unit_no", "status"], order_by="unit_no")
    if units:
        print("\n    units: " + ", ".join("%s %s" % (u.unit_no, u.status)
                                          for u in units))

    print("\n  " + ("ALL OK - AK-12 is loaded." if all_ok else
                     "MISMATCH - read the lines above; do not go live on this."))
    return {"ok": all_ok, "got": got}


def _statements():
    """Run the real statement endpoints and check the numbers they return.

    This is the part that was wrong. Counting records proves the load ran;
    only the statements prove the ledger underneath it is right. Called as
    Administrator, so `guard` lets it through the same way the Finance screens
    do for an Accounts user.
    """
    from darkbrown.api import statements

    _h("statements  %s to %s" % (STATEMENT_FROM, STATEMENT_TO))
    got = {}
    try:
        pl = statements.profit_and_loss(STATEMENT_FROM, STATEMENT_TO)
        got["pl_income"] = round(float(pl["income"]), 2)
        got["pl_expense"] = round(float(pl["expense"]), 2)
        got["pl_net"] = round(float(pl["net"]), 2)
        bs = statements.balance_sheet(STATEMENT_TO)
        got["bs_assets"] = round(float(bs["assets"]), 2)
        got["bs_difference"] = round(float(bs["difference"]), 2)
        cf = statements.cash_flow(STATEMENT_FROM, STATEMENT_TO)
        got["cf_closing"] = round(float(cf["closing"]), 2)
        got["cf_difference"] = round(float(cf["difference"]), 2)
    except Exception:
        print(_tb())
        print("\n    a statement endpoint raised - the ledger is not usable")
        return False

    ok = True
    for k, want in EXPECT_STATEMENTS.items():
        g = got.get(k)
        hit = g is not None and abs(g - want) < 0.005
        ok = ok and hit
        print("    %-16s %14s  expected %14s  %s"
              % (k, format(g, ",.2f") if g is not None else "-",
                 format(want, ",.2f"), "ok" if hit else "<-- MISMATCH"))

    print("\n    spread on AK-12 over the window: %s income less %s "
          "head-lease cost = %s"
          % (format(got["pl_income"], ",.2f"), format(got["pl_expense"], ",.2f"),
             format(got["pl_net"], ",.2f")))
    print("    balance sheet %s | cash flow %s"
          % ("balances" if bs.get("balanced") else "DOES NOT BALANCE",
             "reconciles" if cf.get("reconciled") else "DOES NOT RECONCILE"))
    ok = ok and bool(bs.get("balanced")) and bool(cf.get("reconciled"))

    # Nothing should be sitting in Temporary Opening: revision 5 left the whole
    # 256,400 there, which is what made every statement read wrong.
    company = frappe.db.get_single_value("DBR Settings", "default_company")
    temp = frappe.db.get_value("Account", {"account_name": "Temporary Opening",
                                           "company": company}, "name")
    if temp:
        rows = frappe.get_all("GL Entry",
                              filters={"account": temp, "is_cancelled": 0},
                              fields=["sum(debit) as dr", "sum(credit) as cr"])
        bal = round(float(rows[0].dr or 0) - float(rows[0].cr or 0), 2) \
            if rows else 0.0
        hit = abs(bal) < 0.005
        ok = ok and hit
        print("    Temporary Opening %s  %s"
              % (format(bal, ",.2f"),
                 "ok - empty" if hit else
                 "<-- money parked here means opening entries got posted"))
    return ok


# ----------------------------------------------------------------- rebuild

def rebuild(confirm=None):
    """check -> reset -> load -> verify, one command."""
    r = check()
    if not r["ready"]:
        return {"aborted": True, "at": "check"}
    r = reset(confirm)
    if r.get("aborted"):
        return r
    if any(r.get("left", {}).values()):
        print("\n  LOAD NOT STARTED - the site is not empty after reset.")
        return {"aborted": True, "at": "reset"}
    return load(_checked=True)
