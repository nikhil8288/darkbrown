"""Stage 9 — key money.

The premium paid to take a building on, and the premium paid on buildings that
were bid for and lost. 1,419,551 across the two, which is exactly the amount
stage 8 left out of the expense workbook's master tab — key money appears in
both workbooks and loading it from each would have doubled it.

**The two halves come from different places, because only one of them is in the
key money workbook.** `Key Money` is there, 1,212,250, laid out per building per
month. `Key Money - Other` is not; its 207,301 sits in the expense workbook's
segregate tab. They are separate heads in the chart for a good reason: money
paid on a building that was won attaches to that building, and money paid on one
that was lost has no building to attach to. The second is a Common cost, reaching
the buildings through the allocation rather than the ledger.

**It stays in cost of sales.** Both heads sit above gross margin at the
accountant's direction, not below it — that decision is recorded in
`chart_of_accounts` and this stage does not revisit it.

**The first period runs July to October 2025.** The key money workbook lumps
those four months where the owner-rent register lumped three, so the labels do
not line up with stage 6's. They are not meant to: this is when a premium was
paid, not when rent accrued.

Like stage 8, these load as drafts and post nothing. UG-169 has no key money
column in the workbook — it paid none.
"""

import frappe

from darkbrown.load import common as C
from darkbrown.utils.chart_of_accounts import (BUILDING, COMMON, basis_of,
                                               ensure_overhead_cost_center)

STAGE = "9"
SOURCE = "key_money.csv"


def _money(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _account(head, company):
    """The docname of an expense head on this company's chart.

    Accounts are named "Salary - DBR". The chart module works in bare names,
    so the two have to be introduced to each other.
    """
    for name in (head, "%s - %s" % (head, frappe.db.get_value(
            "Company", company, "abbr") or "")):
        if frappe.db.exists("Account", name):
            return name
    hit = frappe.db.get_value("Account", {"company": company, "is_group": 0,
                                          "account_name": head}, "name")
    return hit


def _resolve(rows):
    company = C.company()
    centres = {b["name"]: b["cost_center"] for b in frappe.get_all(
        "Building", fields=["name", "cost_center"])}
    overhead = ensure_overhead_cost_center(company)

    existing = set()
    for e in frappe.get_all("Expense Entry",
                            fields=["expense_date", "expense_head", "amount",
                                    "building"]):
        existing.add((str(e.expense_date), e.expense_head,
                      round(float(e.amount or 0), 2), e.building or ""))

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        head = (r.get("expense_head") or "").strip()
        b = (r.get("building") or "").strip()
        date = (r.get("expense_date") or "").strip()
        amount = _money(r.get("amount"))

        def bad(column, value, rule, message):
            problems.append(C.Problem(SOURCE, i, column, value, rule, message))

        key = (date, head, amount, b)
        if key in seen:
            bad("expense_head", head, "duplicate_in_file",
                "same cost as row %d" % seen[key])
            continue
        seen[key] = i

        if amount is None or amount <= 0:
            bad("amount", r.get("amount"), "amount_required",
                "an expense is always a positive amount")
        basis = basis_of(head)
        if not basis:
            bad("expense_head", head, "head_not_in_chart",
                "not a head this app knows — add it to "
                "utils.chart_of_accounts first")
        elif basis != (r.get("basis") or "").strip():
            bad("basis", r.get("basis"), "basis_disagrees_with_chart",
                "the chart says %s" % basis)

        account = _account(head, company)
        if head and not account:
            bad("expense_head", head, "account_missing",
                "no Account on this company's chart — run Ensure Chart")

        centre = None
        if basis == BUILDING:
            if not b:
                bad("building", b, "building_required",
                    "a building cost has to name its building")
            elif b not in centres:
                bad("building", b, "building_unresolved",
                    "no Building on the site")
            elif not centres.get(b):
                bad("building", b, "no_cost_center",
                    "the building has no cost centre, so the cost would not "
                    "reach its P&L")
            else:
                centre = centres[b]
        elif basis == COMMON:
            if b:
                bad("building", b, "common_cost_with_building",
                    "a common cost does not post to a building")
            centre = overhead
            if not centre:
                bad("building", b, "no_overhead_centre",
                    "there is no Overhead cost centre on the company")

        # the site stores the account docname, "Salary - DBR", not the bare
        # head. Comparing the two is how stage 4 came to reload itself.
        plan.append({"row": i, "raw": r, "head": head, "account": account,
                     "basis": basis, "building": b, "date": date,
                     "amount": amount, "centre": centre,
                     "existing": (date, account, amount, b) in existing})
    return plan, problems


def _totals(plan):
    out = {"Building": 0.0, "Common": 0.0}
    for p in plan:
        if p["amount"]:
            out[p["basis"] or "Common"] = out.get(p["basis"] or "Common",
                                                  0.0) + p["amount"]
    return out


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    t = _totals(plan)
    fresh = [p for p in plan if not p["existing"]]
    heads = sorted({p["head"] for p in plan})

    def q(v):
        return frappe.utils.fmt_money(v, currency="QAR")

    print("STAGE 9 CHECK — key money")
    print("  %s: %d rows, %d to create" % (SOURCE, len(rows), len(fresh)))
    print("  %d head(s) across %d month(s)"
          % (len(heads), len({p["date"] for p in plan})))
    print("  on buildings held   %s" % q(t.get("Building", 0)))
    print("  on buildings lost   %s" % q(t.get("Common", 0)))
    print("  total               %s" % q(sum(t.values())))
    print("  %d building(s) paid key money"
          % len({p["building"] for p in plan if p["building"]}))
    print("  these load as drafts. Nothing posts to the ledger until somebody "
          "decides to submit them.")
    C.report(problems)
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "problems": len(problems),
            "clean": not problems}


def run():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 9 refused: %d problem(s). Run Check."
                     % len(problems))

    company = C.company()
    made, failed = 0, []
    print("STAGE 9 RUN — key money")
    for p in plan:
        if p["existing"]:
            continue
        try:
            e = frappe.new_doc("Expense Entry")
            e.expense_date = p["date"]
            e.expense_head = p["account"]
            e.amount = p["amount"]
            e.basis = p["basis"]
            e.building = p["building"] or None
            e.cost_center = p["centre"]
            e.payment_mode = "Unpaid"
            e.description = (p["raw"].get("description") or p["head"])[:140]
            e.reference = (p["raw"].get("period_label") or "").strip()[:140]
            e.company = company
            e.notes = ("Loaded from the July 2026 cutover. Left as a draft: "
                       "submitting would post a journal into a closed period.")
            e.flags.ignore_permissions = True
            # see the module docstring — the checks validate would make have
            # already been made in _resolve, against the same chart
            e.flags.ignore_validate = True
            e.flags.ignore_mandatory = True
            e.insert()
            made += 1
            if made % 200 == 0:
                frappe.db.commit()
                print("      %d..." % made)
        except Exception as ex:
            frappe.db.rollback()
            text = (str(ex) or "").strip() or type(ex).__name__
            failed.append(("%s %s %s" % (p["date"], p["head"], p["building"]),
                           (text.splitlines() or ["?"])[0][:90]))
    frappe.db.commit()

    if failed:
        C.report([C.Problem(SOURCE, "-", "expense_head", n, "insert_failed", w)
                  for n, w in failed])
    print("  created %d cost line(s), all as drafts" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def reload():
    print("STAGE 9 RELOAD — key money")
    return run()


def gate():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    t = _totals(plan)

    # Stages 8 and 9 both write Expense Entry. Each counts only the heads in
    # its own worksheet, or loading the second would fail the first's gate.
    mine = {p["account"] for p in plan if p["account"]}
    site = [s for s in frappe.get_all(
        "Expense Entry",
        fields=["name", "amount", "basis", "building", "cost_center",
                "docstatus", "expense_head"])
        if s.get("expense_head") in mine]
    on_site = len(site)
    submitted = len([s for s in site if s.get("docstatus") == 1])
    site_total = round(sum(float(s.get("amount") or 0) for s in site), 2)
    want_total = round(sum(t.values()), 2)
    no_centre = len([s for s in site if not s.get("cost_center")])
    stray = len([s for s in site
                 if s.get("basis") == COMMON and s.get("building")])
    journals = len([s for s in site if s.get("docstatus") == 1])

    checks = [
        ("every key money line in the worksheet exists", on_site == len(plan),
         "%d on site vs %d expected" % (on_site, len(plan))),
        ("the amounts reconcile", abs(site_total - want_total) < 1.0,
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(site_total, currency="QAR"),
            frappe.utils.fmt_money(want_total, currency="QAR"))),
        ("nothing was submitted", not submitted,
         "all %d are drafts" % on_site if not submitted
         else "%d submitted — a journal has been posted" % submitted),
        ("every line has a cost centre", not no_centre,
         "none missing" if not no_centre else "%d without one" % no_centre),
        ("no common cost sits on a building", not stray,
         "none" if not stray else "%d would post to the wrong centre" % stray),
        ("the ledger is untouched", not journals,
         "no journals from this stage"),
        ("the worksheet still resolves cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
