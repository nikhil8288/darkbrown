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
         "customers.json", "portfolio_history.csv", "owner_rent_history.csv",
         "keymoney_history.csv", "opex_journal.csv",
         "load_buildings.py", "load_customers.py",
         "load_portfolio_history.py", "load_portfolio_headlease.py",
         "_ledger_common.py", "cutover_doctor.py",
         "tenancy_name_map.csv", "arrears_name_map.csv"]

#: Order matters and is not negotiable. Tenancies resolve against Customers and
#: Units, arrears resolve against Customers, and a Unit cannot exist before its
#: Building. Each entry is (label, dotted module, needs).
STEPS = [
    ("Tenants", "darkbrown.patches.load_customers",
     "599 Customers"),
    ("Buildings and units", "darkbrown.patches.load_buildings",
     "22 buildings, 296 units, 15 landlords"),
    ("Tenancies", "darkbrown.patches.import_tenancies",
     "219 agreements; 77 units carry a tenant name but no signed agreement"),
    ("Opening arrears", "darkbrown.patches.seed_opening_arrears",
     "nothing - the rent history carries the arrears instead"),
    # These two post against the Customers and the Head Leases, so they run
    # last. Together they are what puts income AND cost on the P&L; the rent
    # side alone gives a statement with revenue and no cost of sales.
    ("Rent history", "darkbrown.patches.load_portfolio_history",
     "1,780 invoices and receipts; 5,306,783.00 charged, "
     "4,838,469.00 collected"),
    ("Operating expenses", "darkbrown.patches.load_opex",
     "3,209,553.15 across 10 monthly journals; the per-building heads carry "
     "their building's cost centre, the rest sit on Overhead"),
    ("Head-lease cost", "darkbrown.patches.load_portfolio_headlease",
     "145 purchase invoices and payments; 3,669,500.00 accrued, "
     "3,459,500.00 paid, 210,000.00 payable"),
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
                with open(p, "rb") as fh:
                    raw = fh.read()
                extra = "  %d lines" % raw.count(b"\n")
                if raw.startswith(b"\xef\xbb\xbf"):
                    extra += "  !! BYTE-ORDER MARK - the loaders strip it, but this file was written by Excel"
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
    else:
        print("""
  READ THIS BEFORE THE OUTPUT BELOW.

  A dry run writes nothing, so nothing a step would have created exists for
  the steps after it. On an empty site that means:

    step 3  every tenancy reports "tenant: unmatched" and "building not
            found", because steps 1 and 2 created no Customers and no
            Buildings
    step 5  every rent row reports "no Customer named ..."
    step 6  every head-lease row reports "building not on the site"

  Those are the dry run describing itself, not defects in the data. They
  disappear on the real run, where each step commits before the next starts.

  What IS worth reading in a dry run:

    step 1  how many Customers already exist, and whether any name is
            ambiguous - an ambiguous name is a real blocker
    step 2  that all 23 buildings say CREATE and each names a real landlord
    step 3  the row count and any problem that is NOT "unmatched" or "not
            found" - a bad date, a nil rent, a duplicate key, two live
            tenancies on one unit
    steps 5 and 6  the control totals against the expected figures above

  To see steps 3, 5 and 6 judged properly, run steps 1 and 2 for real first,
  then dry-run the rest.
""")

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


#: Every voucher this pack writes carries one of these. Sales and purchase
#: invoices carry it in `remarks`, journals in `user_remark`.
#:
#: The guard below used to look only for the AK-12 pilot tags. When the
#: orchestrator was rewired to the portfolio loaders the tags changed and this
#: list did not, so a site holding nothing but this pack's own vouchers read as
#: dirty and "Load for real" refused - silently, because it returns its reason
#: rather than printing it, and the screen showed only "Done." The pilot tags
#: stay recognised so a site loaded from the old pack is still read correctly.
OWN_SI_TAGS = ("[DB-HIST-INV-", "[AK12-HIST-INV-")
OWN_PI_TAGS = ("[DB-HL-INV-", "[AK12-HL-INV-")
OWN_JE_TAGS = ("[DBR-OPEX-",)


def _own(text, tags):
    text = text or ""
    return any(t in text for t in tags)


def _ledger_state():
    """What is on the GL, and whether it is safe to load onto.

    Counting records cannot tell you a load went wrong: the loaders are
    idempotent, so on a dirty site every voucher is skipped as already-present
    and the wrong ones stay. Counting GL rows can.

    A ledger made only of this pack's own vouchers is not a problem - that is
    a half-finished load, and re-running is how you finish it. What must stop
    a load is a voucher this pack did not write, because the loaders will skip
    past it and leave its amount on the statements.
    """
    live = frappe.db.count("GL Entry", {"is_cancelled": 0})

    opening = untagged_si = 0
    for d in frappe.get_all("Sales Invoice", filters={"docstatus": 1},
                            fields=["remarks", "is_opening"], limit=5000):
        if (d.is_opening or "") == "Yes":
            opening += 1
        elif not _own(d.remarks, OWN_SI_TAGS):
            untagged_si += 1
    untagged_pi = sum(
        1 for d in frappe.get_all("Purchase Invoice", filters={"docstatus": 1},
                                  fields=["remarks"], limit=5000)
        if not _own(d.remarks, OWN_PI_TAGS))
    journals = sum(
        1 for d in frappe.get_all("Journal Entry", filters={"docstatus": 1},
                                  fields=["user_remark"], limit=5000)
        if not _own(d.user_remark, OWN_JE_TAGS))

    foreign = opening + untagged_si + untagged_pi + journals
    return {"gl_rows": live, "opening_invoices": opening,
            "untagged_sales_invoices": untagged_si,
            "untagged_purchase_invoices": untagged_pi,
            "journal_entries": journals, "foreign": foreign,
            "empty": live == 0, "clean": foreign == 0}


def run_dry():
    return _sequence(False)


def run_load():
    """The Data screen's "Load for real" button.

    It refuses on a site that already has a ledger, because the loaders are idempotent, so on a dirty site
    they skip everything and report success while the wrong vouchers stay put.
    This button cannot reset - that stays on the bench, where it needs a typed
    confirmation phrase - so all it can do here is stop and say so.
    """
    st = _ledger_state()
    if not st["clean"]:
        return {"aborted": True, "reason": "ledger not empty", "ledger": st,
                "message": (
                    "This ledger carries %d vouchers that did not come from "
                    "this pack: %d revision-5 opening rent invoices, %d other "
                    "rent invoices, %d landlord invoices, %d journal entries. "
                    "Loading again would skip everything already created and "
                    "leave those in place. Clear it from the bench first: "
                    "bench --site <site> execute darkbrown.patches.cutover_doctor.run "
                    "to see exactly what is there."
                    % (st["foreign"], st["opening_invoices"],
                       st["untagged_sales_invoices"],
                       st["untagged_purchase_invoices"],
                       st["journal_entries"]))}
    return _sequence(True)
