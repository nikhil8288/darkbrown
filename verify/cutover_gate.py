"""Step 6 abort gate and the ledger-clean gate, run against the shipped files.

Both bugs this covers were gates that could not tell two things apart:

  * `load_portfolio_headlease.run` asked whether the preflight list was empty
    instead of whether anything in it was a blocker. On a company with
    perpetual inventory switched on the list is never empty, so step 6 aborted
    on every site - including one with nothing wrong with it.

  * `cutover._ledger_state` looked for the retired AK12 pilot remark tags. The
    portfolio loaders write DB-HIST-INV and DB-HL-INV, so the pack's own
    invoices counted as foreign and `run_load` refused the re-run that the
    sequencer promises is safe.

Nothing here is a replica. The real modules are imported and executed against
`stub_frappe`, and `_rows` reads a real CSV written to the path the shipped
loader looks at, so a pass means the shipped file behaves.
"""

import contextlib
import csv
import importlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BUILDINGS = ["AK-%02d" % i for i in range(1, 24)]          # 23 buildings
ACCRUED = 3669500.00
PAID = 3459500.00

fails = []


def quiet(fn, *a, **kw):
    """The loaders print a full row listing. Keep the result readable."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def check(label, got, want):
    ok = got == want
    print("  %-4s %-58s got %r" % ("PASS" if ok else "FAIL", label, got))
    if not ok:
        fails.append("%s: expected %r, got %r" % (label, want, got))


def write_csv(path):
    """135 rows across 23 buildings, hitting the control totals exactly."""
    n = 135
    per = round(ACCRUED / n, 2)
    paid_per = round(PAID / n, 2)
    rows = []
    for i in range(n):
        rows.append({
            "building": BUILDINGS[i % len(BUILDINGS)],
            "period": "2026-%02d-01" % ((i % 12) + 1),
            "amount": per,
            "accrued_on": "2026-%02d-01" % ((i % 12) + 1),
            "paid_on": "2026-%02d-05" % ((i % 12) + 1),
            "paid_amount": paid_per,
            "mode": "Cheque",
            "remarks": "ASSUMED" if i % 3 == 0 else "",
        })
    # absorb rounding drift into the first row so the totals tie exactly
    rows[0]["amount"] = round(ACCRUED - per * (n - 1), 2)
    rows[0]["paid_amount"] = round(PAID - paid_per * (n - 1), 2)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def site(perpetual=1, missing_hl=None, missing_supplier=None):
    """A healthy portfolio, with one defect optionally introduced."""
    import stub_frappe as F
    F.DB.clear()
    F.DB["Company"] = [{"name": "DarkBrown", "enable_perpetual_inventory":
                        perpetual}]
    F.DB["Building"] = [{"name": b} for b in BUILDINGS]
    F.DB["Head Lease"] = [{"name": "HL-" + b, "building": b,
                           "landlord": "SUP-" + b}
                          for b in BUILDINGS if b != missing_hl]
    F.DB["Supplier"] = [{"name": "SUP-" + b} for b in BUILDINGS
                        if b != missing_supplier]
    F.DB["DBR Settings"] = [{"default_company": "DarkBrown"}]
    return F


def load(tmp):
    """Import the shipped modules fresh against the stub."""
    for m in list(sys.modules):
        if m.startswith("darkbrown"):
            del sys.modules[m]
    import stub_frappe as F
    sys.modules["frappe"] = F.frappe
    sys.modules["frappe.utils"] = F.frappe.utils
    sys.path.insert(0, tmp)
    hl = importlib.import_module("darkbrown.patches.load_portfolio_headlease")
    return hl


def main():
    sys.path.insert(0, HERE)
    tmp = tempfile.mkdtemp()
    shutil.copytree(os.path.join(ROOT, "darkbrown"),
                    os.path.join(tmp, "darkbrown"))
    write_csv(os.path.join(tmp, "darkbrown", "patches",
                           "owner_rent_history.csv"))

    print("\n=== step 6 preflight severity ===")

    F = site(perpetual=1)
    hl = load(tmp)
    hl.L.company = lambda: "DarkBrown"
    hl._heal = lambda: None      # needs a chart of accounts; not under test
    pre = quiet(hl._preflight)
    check("perpetual inventory on, otherwise healthy: entries", len(pre), 1)
    check("  ...and it is tagged a warning", pre[0][0], hl.WARNING)
    check("  ...so blockers", len(hl._blockers(pre)), 0)
    check("  ...dry_run reports ok", quiet(hl.dry_run)["ok"], True)

    F = site(perpetual=0)
    hl = load(tmp)
    hl.L.company = lambda: "DarkBrown"
    hl._heal = lambda: None      # needs a chart of accounts; not under test
    check("perpetual inventory off: entries", len(quiet(hl._preflight)), 0)

    print("\n=== step 6 still stops on a real blocker ===")

    F = site(perpetual=1, missing_hl="AK-07")
    hl = load(tmp)
    hl.L.company = lambda: "DarkBrown"
    hl._heal = lambda: None      # needs a chart of accounts; not under test
    pre = quiet(hl._preflight)
    b = hl._blockers(pre)
    check("head lease missing on the 7th building: blockers", len(b), 1)
    check("  ...names the building", "AK-07" in b[0][2], True)
    check("  ...dry_run reports not ok", quiet(hl.dry_run)["ok"], False)
    check("  ...run aborts", quiet(hl.run).get("aborted"), True)

    F = site(perpetual=1, missing_supplier="AK-11")
    hl = load(tmp)
    hl.L.company = lambda: "DarkBrown"
    hl._heal = lambda: None      # needs a chart of accounts; not under test
    b = hl._blockers(quiet(hl._preflight))
    check("landlord Supplier missing: blockers", len(b), 1)
    check("  ...it is the landlord check", b[0][1], "landlord")

    F = site(perpetual=1)
    hl = load(tmp)
    hl.L.company = lambda: None
    pre = quiet(hl._preflight)
    check("no default_company: is a blocker", pre[0][0], hl.BLOCKER)

    print("\n=== ledger-clean gate tags ===")

    for m in list(sys.modules):
        if m.startswith("darkbrown"):
            del sys.modules[m]
    import stub_frappe as F2
    F2.DB.clear()
    cut = importlib.import_module("darkbrown.api.cutover")
    si, pi = cut._pack_tags()
    check("sales tags accept the portfolio loader", "DB-HIST-INV" in si, True)
    check("sales tags still accept the AK12 pilot", "AK12-HIST-INV" in si,
          True)
    check("purchase tags accept the portfolio loader", "DB-HL-INV" in pi, True)

    F2.DB["Sales Invoice"] = [
        {"name": "SI-1", "docstatus": 1, "is_opening": "No",
         "remarks": "[DB-HIST-INV-00001] | DB_HISTORY | AK-01"},
        {"name": "SI-2", "docstatus": 1, "is_opening": "No",
         "remarks": "[AK12-HIST-INV-00002] | pilot"}]
    F2.DB["Purchase Invoice"] = [
        {"name": "PI-1", "docstatus": 1,
         "remarks": "[DB-HL-INV-00001] | landlord rent"}]
    st = quiet(cut._ledger_state)
    check("pack's own portfolio + pilot invoices: foreign", st["foreign"], 0)
    check("  ...so the ledger reads clean", st["clean"], True)

    F2.DB["Sales Invoice"].append(
        {"name": "SI-3", "docstatus": 1, "is_opening": "No",
         "remarks": "manual invoice typed by a human"})
    st = quiet(cut._ledger_state)
    check("a genuinely foreign invoice is still caught", st["foreign"], 1)
    check("  ...so the ledger is not clean", st["clean"], False)

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (18, len(fails)))
    for f in fails:
        print("  !", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
