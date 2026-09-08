"""Drive the fix-pack patches against stub_frappe with real data.

    cd verify && python3 fixpack.py

Imports the REAL shipped modules. A pass means the file that deploys works,
not a replica of it.
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import stub_frappe as S  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print("  %-58s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAIL.append("%s %s" % (name, detail))


# ---------------------------------------------------------------- fixtures

COMPANY = "DarkBrown Real Estate"
CONTROL = "Historical Cutover Control - DBR"


def seed_accounts():
    """A chart shaped like the one the accountant found: the five groups
    exist, but the heads Anoop flagged sit under Other Expense."""
    rows = [
        {"name": "Expenses - DBR", "account_name": "Expenses",
         "company": COMPANY, "is_group": 1, "root_type": "Expense",
         "parent_account": None},
        {"name": "Other Expense - DBR", "account_name": "Other Expense",
         "company": COMPANY, "is_group": 1, "root_type": "Expense",
         "parent_account": "Expenses - DBR"},
    ]
    for g, _label in [("Cost of Sales", 0), ("Staff Cost", 0),
                      ("Operating Expenses", 0),
                      ("Depreciation and Amortisation", 0),
                      ("Bank and Finance Charges", 0)]:
        rows.append({"name": "%s - DBR" % g, "account_name": g,
                     "company": COMPANY, "is_group": 1,
                     "root_type": "Expense",
                     "parent_account": "Expenses - DBR"})

    # The five Anoop named, all misfiled.
    misfiled = ["Building Maintenance", "Commission on Sales",
                "Marketing Expenses", "Salary", "Owner Rent"]
    for a in misfiled:
        rows.append({"name": "%s - DBR" % a, "account_name": a,
                     "company": COMPANY, "is_group": 0,
                     "root_type": "Expense",
                     "parent_account": "Other Expense - DBR"})
    # One already in the right place, must not be touched.
    rows.append({"name": "Audit Fees - DBR", "account_name": "Audit Fees",
                 "company": COMPANY, "is_group": 0, "root_type": "Expense",
                 "parent_account": "Operating Expenses - DBR"})
    # One the chart does not know, must be left alone and reported.
    rows.append({"name": "Sundry Bits - DBR", "account_name": "Sundry Bits",
                 "company": COMPANY, "is_group": 0, "root_type": "Expense",
                 "parent_account": "Other Expense - DBR"})
    rows.append({"name": CONTROL, "account_name": "Historical Cutover Control",
                 "company": COMPANY, "is_group": 0, "root_type": "Asset",
                 "parent_account": "Current Assets - DBR"})
    S.DB["Account"] = rows
    S.DB["Company"] = [{"name": COMPANY}]
    S.DB["DBR Settings"] = [{"default_company": COMPANY}]


def test_reclass_pl_groups():
    print("\nreclass_pl_groups")
    seed_accounts()
    from darkbrown.patches import reclass_pl_groups as R
    moves, skipped, missing = R._plan()

    moved = {m["account"] for m in moves}
    check("no missing P&L groups", not missing, str(missing))
    check("Owner Rent is moved (via ALIASES)", "Owner Rent - DBR" in moved)
    check("Salary is moved", "Salary - DBR" in moved)
    check("Building Maintenance is moved", "Building Maintenance - DBR" in moved)
    check("Commission on Sales is moved", "Commission on Sales - DBR" in moved)
    check("Marketing Expenses is moved", "Marketing Expenses - DBR" in moved)
    check("correctly-filed Audit Fees is NOT moved",
          "Audit Fees - DBR" not in moved)
    check("unknown account is left alone",
          "Sundry Bits - DBR" not in moved)
    check("unknown account is reported",
          any(s[0] == "Sundry Bits - DBR" for s in skipped))
    check("exactly 5 accounts move", len(moves) == 5, str(sorted(moved)))

    targets = {m["account"]: m["group"] for m in moves}
    check("Owner Rent -> Cost of Sales",
          targets.get("Owner Rent - DBR") == "Cost of Sales")
    check("Salary -> Staff Cost",
          targets.get("Salary - DBR") == "Staff Cost")
    check("Marketing Expenses -> Cost of Sales",
          targets.get("Marketing Expenses - DBR") == "Cost of Sales")

    # Idempotency: apply the moves, re-plan, expect nothing left.
    for m in moves:
        for row in S.DB["Account"]:
            if row["name"] == m["account"]:
                row["parent_account"] = m["to"]
    moves2, _, _ = R._plan()
    check("second run finds nothing to do", not moves2, str(moves2))


def test_requeue_receipts():
    print("\nrequeue_history_receipts")
    from darkbrown.patches import requeue_history_receipts as Q

    rows = list(csv.DictReader(
        open(os.path.join(ROOT, "darkbrown", "patches",
                          "portfolio_history.csv"), encoding="utf-8-sig")))
    # The site as it stands: receipts posted at the OLD amount, which was
    # Received alone. Reconstruct that from the workbook-derived remarks.
    old_amounts = []
    for r in rows:
        coll = float(r["collected"])
        note = r.get("remarks") or ""
        adj = 0.0
        for bit in note.split("|"):
            bit = bit.strip()
            if bit.startswith("advance "):
                adj += float(bit.split()[1])
            elif bit.startswith("prior due recovered "):
                adj += float(bit.split()[-1])
        old_amounts.append(round(coll - adj, 2))

    S.DB["Payment Entry"] = [
        {"name": "PE-%05d" % (i + 1), "reference_no": Q._receipt_no(i),
         "paid_amount": old_amounts[i], "docstatus": 1,
         "posting_date": "2026-01-05", "party": "CUST-%d" % i}
        for i, r in enumerate(rows) if old_amounts[i]
    ]

    stale, agreeing, absent = Q._plan()
    absent_value = sum(a[1] for a in absent)
    delta = sum(s["should_be"] - s["was"] for s in stale) + absent_value
    check("26 receipts to cancel", len(stale) == 26, str(len(stale)))
    check("127 receipts to create fresh", len(absent) == 127, str(len(absent)))
    check("cancellations move 32,952.00",
          abs(sum(s["should_be"] - s["was"] for s in stale) - 32952.00) < 0.01)
    check("new receipts add 311,160.00", abs(absent_value - 311160.00) < 0.01,
          "%.2f" % absent_value)
    check("whole correction is 344,112.00", abs(delta - 344112.00) < 0.01,
          "%.2f" % delta)
    check("untouched receipts left alone", agreeing == len(
        S.DB["Payment Entry"]) - len(stale), str(agreeing))

    # After the loader re-posts, a second run must find nothing.
    for pe in S.DB["Payment Entry"]:
        for s in stale:
            if pe["reference_no"] == s["tag"]:
                pe["paid_amount"] = s["should_be"]
    stale2, _, _ = Q._plan()
    check("second run finds nothing to cancel", not stale2, str(len(stale2)))


def test_control_account_unpacking():
    print("\ncontrol account tuple unpacking")
    import re
    for mod in ("reclass_cutover_credits", "load_opex"):
        p = os.path.join(ROOT, "darkbrown", "patches", "%s.py" % mod)
        if not os.path.exists(p):
            continue
        src = open(p).read()
        bad = re.search(r"^\s*\w+\s*=\s*L\.control_account\([^)]*\)\s*$",
                        src, re.M)
        check("%s unpacks (name, created)" % mod, bad is None,
              bad.group(0).strip() if bad else "")


def test_csv_totals():
    print("\nportfolio_history.csv control totals")
    rows = list(csv.DictReader(
        open(os.path.join(ROOT, "darkbrown", "patches",
                          "portfolio_history.csv"), encoding="utf-8-sig")))
    rent = sum(float(r["rent"]) for r in rows)
    coll = sum(float(r["collected"]) for r in rows)
    check("rent = 5,306,783.00", abs(rent - 5306783.00) < 0.005, "%.2f" % rent)
    check("collected = 5,182,581.00", abs(coll - 5182581.00) < 0.005,
          "%.2f" % coll)
    check("outstanding = 124,202.00", abs(rent - coll - 124202.00) < 0.005,
          "%.2f" % (rent - coll))
    over = [r for r in rows if float(r["collected"]) - float(r["rent"]) > 0.005]
    check("no row over-allocates against its invoice", not over, str(len(over)))

    from darkbrown.patches import load_portfolio_history as H
    check("loader control total matches the CSV",
          abs(H.EXPECTED_COLLECTED - coll) < 0.005,
          "%.2f vs %.2f" % (H.EXPECTED_COLLECTED, coll))


if __name__ == "__main__":
    test_csv_totals()
    test_reclass_pl_groups()
    test_requeue_receipts()
    test_control_account_unpacking()

    print("")
    if FAIL:
        print("%d FAILURE(S)" % len(FAIL))
        for f in FAIL:
            print("   %s" % f)
        sys.exit(1)
    print("all checks passed")
