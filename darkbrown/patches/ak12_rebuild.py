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

REVISION = 5
CONFIRM = "REMOVE ALL DARKBROWN DATA"
HERE = os.path.dirname(os.path.abspath(__file__))

#: Every file this load reads, with the string that proves it is the fixed
#: version. A file that exists but is the old copy is the failure mode that
#: cost three attempts, so existence alone is not enough.
DEPLOYED = [
    ("ak12_rebuild.py",       "REVISION = 5"),
    ("load_ak12_history.py",  "AK12-HIST-INV"),
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

#: What the pack produces. verify() checks each of these.
EXPECT = {
    "Building": 1, "Unit": 8, "Head Lease": 1, "Supplier": 1,
    "Customer": 9, "Tenancy Agreement": 11,
    "Sales Invoice": 69, "Payment Entry": 69,
    "units_occupied": 7, "units_vacant": 1,
    "tenancies_live": 7, "tenancies_expired": 4,
    "charged": 256400.00, "collected": 255800.00, "outstanding": 600.00,
}

#: The history spans these months; a Fiscal Year must cover each.
HISTORY_DATES = ("2025-11-05", "2026-07-05")

BAR = "-" * 72


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
    if any(left.values()):
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

    if not _checked:
        r = check()
        if not r["ready"]:
            print("\n  LOAD NOT STARTED - check is not clean.")
            return {"aborted": True, "at": "check"}

    company = frappe.db.get_single_value("DBR Settings", "default_company")
    fy_state, fy_msg = _fiscal_years(company, create=True)
    print("\n  fiscal years: %s" % fy_msg)
    if fy_state != "ok":
        print("\n  LOAD NOT STARTED - fiscal years are not in place.")
        return {"aborted": True, "at": "fiscal year"}

    _h("load 1/4  Customers (9)")
    try:
        out = load_customers.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "customers"}
    if out.get("aborted") or out.get("failed"):
        print("\n  STOPPED at customers. Nothing after this was attempted.")
        return {"aborted": True, "at": "customers"}

    _h("load 2/4  Building, units, head lease")
    try:
        out = load_buildings.run()
    except Exception:
        print(_tb())
        return {"aborted": True, "at": "buildings"}
    if out.get("failed"):
        print("\n  STOPPED at buildings. Nothing after this was attempted.")
        return {"aborted": True, "at": "buildings"}

    _h("load 3/4  Tenancy agreements (11)")
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

    _h("load 4/4  Payment history (69 invoices, 69 receipts)")
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
    got["outstanding"] = round(sum(float(i.outstanding_amount or 0)
                                   for i in inv), 2)
    got["collected"] = round(sum(float(p) for p in frappe.get_all(
        "Payment Entry", filters={"docstatus": 1}, pluck="paid_amount")), 2)

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
