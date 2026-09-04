"""The cutover load, driven from a screen instead of a terminal.

Everything here already existed as a `bench execute` entry point. That is a fine
interface for whoever runs the bench and no interface at all for whoever owns
the business, so the four loaders and a diagnostic are wrapped as actions the
Data screen can start on the background worker and stream back into its log.

Nothing new happens here. `run_dry` and `run_load` call the same
`load_customers`, `load_buildings`, `import_tenancies` and
`seed_opening_arrears` a terminal would call, in the same order, and print what
they print. The sequencer's only real job is to stop: each step depends on the
one before it, so continuing past a failure produces a second, more confusing
failure that hides the first.

`diagnose` writes nothing. Its last section onboards one real building and rolls
it back, because a traceback from the actual site beats any amount of inference
from outside it.
"""

import json
import os
import traceback

import frappe

PATCHES = frappe.get_app_path("darkbrown", "patches") if hasattr(
    frappe, "get_app_path") else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patches")

FILES = ["tenancies.csv", "opening_arrears.csv", "buildings_payload.json",
         "customers.json", "ak12_history.csv", "load_buildings.py",
         "load_customers.py", "load_ak12_history.py",
         "tenancy_name_map.csv", "arrears_name_map.csv"]

#: Order matters and is not negotiable. Tenancies resolve against Customers and
#: Units, arrears resolve against Customers, and a Unit cannot exist before its
#: Building. Each entry is (label, dotted module, needs).
STEPS = [
    ("Tenants", "darkbrown.patches.load_customers",
     "432 Customer records"),
    ("Buildings and units", "darkbrown.patches.load_buildings",
     "23 buildings, 305 units, 23 head leases"),
    ("Tenancies", "darkbrown.patches.import_tenancies",
     "266 tenancy agreements"),
    ("Opening arrears", "darkbrown.patches.seed_opening_arrears",
     "nothing - AK-12 carries its full history instead"),
    # History last: it needs the Customers to exist and it posts against them.
    # It is what makes a tenant page show a payment history rather than a
    # balance with no transactions behind it.
    ("Payment history", "darkbrown.patches.load_ak12_history",
     "69 invoices and 69 receipts, 256,400.00 charged / 255,800.00 collected"),
]

BAR = "-" * 72


def _h(t):
    print("\n" + BAR)
    print("  " + t)
    print(BAR)


def _tb():
    return "    " + traceback.format_exc().strip().replace("\n", "\n    ")


# --------------------------------------------------------------- diagnostic

def diagnose():
    """Read-only. Says what the site actually is, then tries one real thing."""
    print("=" * 72)
    print("  DARKBROWN CUTOVER DIAGNOSTIC")
    print("=" * 72)

    _h("1. Are the load files on this server?")
    print("  patches dir: %s" % PATCHES)
    missing = []
    for f in FILES:
        p = os.path.join(PATCHES, f)
        if os.path.exists(p):
            extra = ""
            if f.endswith(".csv"):
                with open(p, encoding="utf-8") as fh:
                    extra = "  %d lines" % sum(1 for _ in fh)
            print("    present  %-26s %8d bytes%s"
                  % (f, os.path.getsize(p), extra))
        else:
            missing.append(f)
            print("    MISSING  %s" % f)
    if missing:
        print("\n  >> The load files are not on this server, so nothing could")
        print("     have run. In GitHub Desktop the new files must be ticked")
        print("     in the Changes list before committing - a commit only")
        print("     includes what is ticked, and these are new files.")

    _h("2. App and schema")
    try:
        print("  installed apps: %s" % ", ".join(frappe.get_installed_apps()))
    except Exception:
        print("  ! could not read installed apps")
    for dt in ["Building", "Unit", "Head Lease", "Tenancy Agreement", "Cheque"]:
        ok = frappe.db.exists("DocType", dt)
        print("    doctype %-22s %s" % (dt, "present" if ok else
                                        "MISSING - migrate has not run"))
    for dt, fn in [("Customer", "db_is_tenant"), ("Supplier", "db_is_landlord")]:
        ok = frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fn})
        print("    field %s.%-20s %s" % (dt, fn, "present" if ok else
                                         "MISSING - migrate has not run"))

    _h("3. Prerequisites the loaders depend on")
    company = frappe.db.get_single_value("DBR Settings", "default_company")
    print("  DBR Settings.default_company: %s"
          % (company or "!! NOT SET - onboarding will refuse every building"))
    if company:
        print("    company record exists: %s"
              % bool(frappe.db.exists("Company", company)))
    for dt, nm in [("Customer Group", "All Customer Groups"),
                   ("Territory", "All Territories")]:
        ok = frappe.db.exists(dt, nm)
        print("  %s '%s': %s" % (dt, nm, "present" if ok else
                                 "!! MISSING - every Customer insert fails"))
        if not ok:
            print("     available here: %s"
                  % frappe.get_all(dt, pluck="name", limit=8))
    sg = frappe.get_all("Supplier Group", filters={"is_group": 0},
                        pluck="name", limit=5)
    print("  Supplier Groups: %s"
          % (sg or "!! NONE - landlord creation will fail"))

    _h("4. What is on the site now")
    for dt in ["Building", "Unit", "Customer", "Supplier", "Head Lease",
               "Tenancy Agreement", "Journal Entry", "Sales Invoice"]:
        try:
            print("    %-22s %6d" % (dt, frappe.db.count(dt)))
        except Exception as e:
            print("    %-22s ? %s" % (dt, e))
    try:
        print("    %-22s %6d" % ("Customers as tenants",
                                 frappe.db.count("Customer", {"db_is_tenant": 1})))
    except Exception:
        pass

    _h("5. Each loader's dry run, with the real error if it raises")
    for label, dotted, _needs in STEPS:
        print("\n  === %s (%s) ===" % (label, dotted.rsplit(".", 1)[-1]))
        try:
            mod = frappe.get_module(dotted)
        except Exception:
            print("    ! cannot import:")
            print(_tb())
            continue
        try:
            mod.dry_run()
        except Exception:
            print("    ! dry_run raised:")
            print(_tb())

    _h("6. One real building, then rolled back")
    p = os.path.join(PATCHES, "buildings_payload.json")
    if not os.path.exists(p):
        print("  payload not on this server, skipped")
    else:
        try:
            with open(p, encoding="utf-8") as fh:
                b = json.load(fh)[0]
            print("  trying %s (%d units)" % (b["building_name"], len(b["units"])))
            from darkbrown.api.portfolio import onboard_building
            onboard_building(json.dumps(b))
            print("    SUCCEEDED - the loaders will work. Rolling back.")
        except Exception:
            print("    ! FAILED:")
            print(_tb())
        finally:
            frappe.db.rollback()
            print("    rolled back, nothing kept")

    print("\n" + "=" * 72)
    print("  END - copy everything above and send it")
    print("=" * 72)


# ---------------------------------------------------------------- sequencer

def _sequence(live):
    word = "LOAD" if live else "DRY RUN"
    print("=" * 72)
    print("  CUTOVER %s" % word)
    print("=" * 72)
    if live:
        print("\n  Writing for real. Each loader skips what already exists,")
        print("  so a re-run after a failure is safe.\n")

    for i, (label, dotted, needs) in enumerate(STEPS, 1):
        _h("%d/%d  %s   (expects %s)" % (i, len(STEPS), label, needs))
        try:
            mod = frappe.get_module(dotted)
        except Exception:
            print("  ! cannot import %s" % dotted)
            print(_tb())
            print("\n  STOPPED at step %d. The load files are probably not on"
                  " this server." % i)
            return False
        try:
            mod.run() if live else mod.dry_run()
        except Exception:
            print("  ! %s raised:" % ("run" if live else "dry_run"))
            print(_tb())
            print("\n  STOPPED at step %d of %d. Steps after this one depend on"
                  % (i, len(STEPS)))
            print("  it, so they were not attempted. Nothing later was touched.")
            return False
        if live:
            frappe.db.commit()

    _h("Result")
    for dt in ["Customer", "Building", "Unit", "Head Lease",
               "Tenancy Agreement"]:
        try:
            print("    %-22s %6d" % (dt, frappe.db.count(dt)))
        except Exception:
            pass
    if live:
        print("\n  Loaded. Open Balance Sheet and Cash Flow - the balance sheet")
        print("  should say Balanced and the cash flow Reconciled.")
    else:
        print("\n  Dry run only. Nothing was written.")
    return True


def run_dry():
    return _sequence(False)


def run_load():
    return _sequence(True)
