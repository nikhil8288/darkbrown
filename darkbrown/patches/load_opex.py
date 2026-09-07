"""Post the historical operating expenses.

Run once, from bench console or the Data screen:

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_opex.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_opex.run

`opex_journal.csv` carries every expense line from the accounts workbook,
already split: the heads the books attribute to a building carry that
building's code in `cost_center`, and the ones the books keep company-wide
carry "Overhead". Nothing is apportioned here - the split is the accountant's,
not this loader's.

One Journal Entry per month, not one for the whole period. A single dated
journal would put ten months of cost on one day and every monthly P&L except
that one would read zero, which is no use to anyone reading a trend.

The credit side is `Historical Cutover Control`, for the same reason the rest
of the cutover uses it: none of this money moved through a real bank account
inside the ERP, and those accounts have to open clean at go-live.

Idempotent. Each journal is titled with its period and this pack's tag, and a
period already posted is skipped rather than doubled.
"""
import csv
import os

import frappe

from darkbrown.patches import _ledger_common as L
from darkbrown.utils import chart_of_accounts as COA

CSV = os.path.join(os.path.dirname(__file__), "opex_journal.csv")

#: Written into every journal's remark so a re-run can recognise its own work.
TAG = "[DBR-OPEX-%s]"

EXPECTED_TOTAL = 3209553.15


def _rows():
    if not os.path.exists(CSV):
        frappe.throw("opex_journal.csv is not on the server. Deploy it first.")
    with open(CSV, encoding="utf-8-sig") as f:
        out = []
        for i, r in enumerate(csv.DictReader(f), 2):
            amount = float(r.get("amount") or 0)
            if not amount:
                continue
            out.append({"line": i, "period": (r.get("period") or "").strip(),
                        "head": (r.get("expense_head") or "").strip(),
                        "amount": amount,
                        "cc": (r.get("cost_center") or "").strip(),
                        "source": (r.get("source_description") or "").strip(),
                        "remarks": (r.get("remarks") or "").strip()})
    return out


def _resolve(rows, company):
    """Map every line to a real Account and Cost Center, or say why not."""
    problems, resolved = [], []
    acc_cache, cc_cache = {}, {}

    for r in rows:
        if r["head"] not in acc_cache:
            group = COA.group_of(r["head"])
            if not group:
                acc_cache[r["head"]] = None
            else:
                acc_cache[r["head"]] = frappe.db.get_value(
                    "Account", {"account_name": r["head"], "company": company,
                                "is_group": 0}, "name")
        account = acc_cache[r["head"]]
        if not account:
            problems.append((r, "no account named %r" % r["head"]))
            continue

        if r["cc"] not in cc_cache:
            if r["cc"] == "Overhead":
                cc_cache[r["cc"]] = (
                    frappe.db.get_value("Cost Center",
                                        {"cost_center_name": "Overhead",
                                         "company": company, "is_group": 0}, "name")
                    or frappe.db.get_value("Cost Center",
                                           {"cost_center_name": "Overhead / Admin",
                                            "company": company, "is_group": 0}, "name"))
            else:
                cc_cache[r["cc"]] = frappe.db.get_value(
                    "Building", r["cc"], "cost_center")
        cc = cc_cache[r["cc"]]
        if not cc:
            problems.append((r, "no cost centre for %r" % r["cc"]))
            continue

        if not r["period"]:
            problems.append((r, "no period"))
            continue

        resolved.append(dict(r, account=account, cost_center=cc))
    return resolved, problems


def _by_period(resolved):
    out = {}
    for r in resolved:
        out.setdefault(r["period"], []).append(r)
    return out


def dry_run():
    """Report without writing. Safe to run at any time."""
    company = L.company()
    rows = _rows()
    resolved, problems = _resolve(rows, company)

    total = sum(r["amount"] for r in rows)
    ok = sum(r["amount"] for r in resolved)
    periods = _by_period(resolved)

    print("opex_journal.csv: %d lines, QAR %s" % (len(rows), format(total, ",.2f")))
    print("control total    : QAR %s   %s"
          % (format(EXPECTED_TOTAL, ",.2f"),
             "MATCHES" if abs(total - EXPECTED_TOTAL) < 0.01
             else "DOES NOT MATCH - do not load"))
    print("resolved         : %d lines, QAR %s" % (len(resolved), format(ok, ",.2f")))
    print("journals to post : %d (one a month)" % len(periods))
    print("")
    for p in sorted(periods):
        rs = periods[p]
        bld = sum(r["amount"] for r in rs if r["cc"] != "Overhead")
        ovh = sum(r["amount"] for r in rs if r["cc"] == "Overhead")
        print("  %s  %4d lines   buildings %12s   overhead %12s   %s"
              % (p[:7], len(rs), format(bld, ",.2f"), format(ovh, ",.2f"),
                 "ALREADY POSTED" if _existing(p, company) else ""))
    if problems:
        print("")
        print("WILL NOT LOAD - %d lines:" % len(problems))
        seen = set()
        for r, why in problems:
            if why in seen:
                continue
            seen.add(why)
            print("   line %-5d %-34s %s" % (r["line"], why, r["source"][:30]))
    return {"lines": len(rows), "total": total, "resolved": len(resolved),
            "problems": len(problems), "periods": sorted(periods)}


def _existing(period, company):
    return frappe.db.get_value("Journal Entry",
                               {"company": company, "docstatus": 1,
                                "user_remark": ["like", "%" + TAG % period[:7] + "%"]},
                               "name")


def run(confirm=None):
    """Post the journals. Re-running only fills in months not yet posted."""
    company = L.company()
    rows = _rows()
    total = sum(r["amount"] for r in rows)
    if abs(total - EXPECTED_TOTAL) > 0.01:
        frappe.throw("opex_journal.csv totals %s but the books say %s. "
                     "Refusing to post a P&L that does not tie."
                     % (format(total, ",.2f"), format(EXPECTED_TOTAL, ",.2f")))

    resolved, problems = _resolve(rows, company)
    if problems:
        frappe.throw("%d expense lines cannot be posted. Run dry_run to see "
                     "them. Nothing has been written." % len(problems))

    control = L.control_account(company)
    L.ensure_fiscal_years([r["period"] for r in resolved])

    made, skipped = [], []
    for period in sorted(_by_period(resolved)):
        if _existing(period, company):
            skipped.append(period)
            continue
        lines = _by_period(resolved)[period]

        # one debit a head per cost centre, so the journal reads like the P&L
        agg = {}
        for r in lines:
            agg.setdefault((r["account"], r["cost_center"]), 0.0)
            agg[(r["account"], r["cost_center"])] += r["amount"]

        accounts = []
        for (account, cc), amt in sorted(agg.items()):
            accounts.append({"account": account, "debit_in_account_currency":
                             round(amt, 2), "cost_center": cc})
        accounts.append({"account": control, "credit_in_account_currency":
                         round(sum(agg.values()), 2)})

        je = frappe.get_doc({
            "doctype": "Journal Entry", "voucher_type": "Journal Entry",
            "company": company, "posting_date": _month_end(period),
            "user_remark": ("Historical operating expenses for %s. %s"
                            % (period[:7], TAG % period[:7])),
            "accounts": accounts,
        })
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        made.append((period, je.name, sum(agg.values())))
        frappe.db.commit()

    print("posted %d journals, skipped %d already present" % (len(made), len(skipped)))
    for p, name, amt in made:
        print("   %s  %-18s %14s" % (p[:7], name, format(amt, ",.2f")))
    if skipped:
        print("   already posted: %s" % ", ".join(s[:7] for s in skipped))
    return {"posted": [m[1] for m in made], "skipped": skipped,
            "total": sum(m[2] for m in made)}


def _month_end(period):
    import calendar
    y, m = int(period[:4]), int(period[5:7])
    return "%04d-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1])
