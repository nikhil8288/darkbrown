"""Stage 11 — the ledger.

The first stage that posts. Everything before this put records on the site and
left the GL empty on purpose; this turns twelve months of them into journals so
ERPNext can produce a P&L.

    revenue, rent charged            5,306,783
    head lease rent                 -3,669,500     gross spread 1,637,283, 30.9%
    operating costs                 -1,790,008     = -152,725
    key money                       -1,419,551     = -1,572,276

**That loss is the answer, not a fault.** Key money is a premium paid to take a
lease on, and charging 1,419,551 of it to cost of sales in the first ten months
is what turns a business with a 31% gross spread into a loss-making one. It is
in cost of sales at the accountant's direction and stays there. Anyone reading
the P&L needs to know the year carries the whole of it.

**Everything contras to `Historical Cutover Control`.** No real bank account is
touched, so nothing here can disturb a bank reconciliation. When every voucher
has posted, that account holds the net of the period — the balance stage 12
reclassifies into bank, receivables and deposits at the cutover date.

**The costs post through `Expense Entry`, not through hand-built journals.**
Stages 8 and 9 already put 2,850 of them on the site as drafts. Submitting them
uses the app's own posting code, which means the cost centre logic, the basis
rule and the narration are the ones the rest of the system uses rather than a
second implementation that drifts. Revenue has no such doctype, so it posts as
one journal per building per period.

**Cancelling in ERPNext does not remove anything.** It writes reversing entries
and keeps the originals — the wipe took the GL from 9,958 rows to 17,303 doing
exactly that. So this stage refuses to run twice over the same voucher, and
anything already submitted is left alone rather than reposted.

Kahramaa and wifi post from the opex file, not from the history records, which
carry the same figures for reporting. Posting both would double them.
"""

import frappe

from darkbrown.load import common as C
from darkbrown.utils.chart_of_accounts import ensure_chart

STAGE = "11"
HISTORY = "portfolio_history.csv"

CONTROL = "Historical Cutover Control"
INCOME_PREFERENCE = ("Rental Income", "Rent Income")
MARKER = "cutover-11"


def _money(value):
    try:
        return round(float(str(value or "0").replace(",", "")), 2)
    except ValueError:
        return None


def _control_account(company, create=False):
    """The account every historical posting contras to.

    Typed Cash because `ExpenseEntry.validate` will not accept a `paid_from`
    that is neither Bank nor Cash, and typing it Bank would put it in front of
    the bank reconciliation, which is the one place it must never appear.
    """
    hit = frappe.db.get_value("Account", {"company": company,
                                          "account_name": CONTROL}, "name")
    if hit or not create:
        return hit
    parent = None
    for candidate in ("Current Assets", "Cash In Hand", "Application of Funds "
                      "(Assets)", "Assets"):
        parent = frappe.db.get_value("Account", {"company": company,
                                                 "account_name": candidate,
                                                 "is_group": 1}, "name")
        if parent:
            break
    if not parent:
        parent = frappe.db.get_value("Account", {"company": company,
                                                 "root_type": "Asset",
                                                 "is_group": 1}, "name")
    if not parent:
        frappe.throw("No asset group on the chart to build %s under." % CONTROL)
    doc = frappe.get_doc({"doctype": "Account", "account_name": CONTROL,
                          "parent_account": parent, "company": company,
                          "account_type": "Cash", "is_group": 0,
                          "root_type": "Asset"})
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def _income_account(company):
    for name in INCOME_PREFERENCE:
        hit = frappe.db.get_value("Account", {"company": company,
                                              "account_name": name,
                                              "is_group": 0}, "name")
        if hit:
            return hit, [n for n in INCOME_PREFERENCE if n != name
                         and frappe.db.get_value(
                             "Account", {"company": company,
                                         "account_name": n}, "name")]
    return None, []


def _resolve(rows):
    company = C.company()
    control = _control_account(company)
    income, rivals = _income_account(company)
    centres = {b["name"]: b["cost_center"] for b in frappe.get_all(
        "Building", fields=["name", "cost_center"])}

    # Head lease rent posts as an Expense Entry, which carries no marker of
    # its own. Without this the second run posts all 145 again — and a doubled
    # cost cannot be taken back out, only reversed on top.
    lease_head = frappe.db.get_value(
        "Account", {"company": company, "account_name": "Head Lease Rent"},
        "name")
    leased = set()
    for e in frappe.get_all("Expense Entry", filters={"docstatus": 1},
                            fields=["building", "expense_date",
                                    "expense_head"]):
        if e.get("expense_head") == lease_head:
            leased.add((e.get("building"), str(e.get("expense_date") or "")))

    posted = set()
    for j in frappe.get_all("Journal Entry",
                            filters={"docstatus": 1}, fields=["user_remark"]):
        r = j.get("user_remark") or ""
        if MARKER in r:
            posted.add(r.split(MARKER, 1)[1].strip())

    plan, problems = [], []
    for i, r in enumerate(rows, start=2):
        b = (r.get("building") or "").strip()
        label = (r.get("period_label") or "").strip()
        charged = _money(r.get("rent_charged"))
        owner = _money(r.get("owner_rent"))
        end = (r.get("period_end") or "").strip()

        def bad(column, value, rule, message):
            problems.append(C.Problem(HISTORY, i, column, value, rule, message))

        if b not in centres:
            bad("building", b, "building_unresolved", "no Building on the site")
        elif not centres[b]:
            bad("building", b, "no_cost_center",
                "a posting against it would not reach its P&L")
        if charged is None or owner is None:
            bad("rent_charged", r.get("rent_charged"), "not_a_number",
                "could not be read as an amount")
            continue

        tag = "%s %s" % (b, label)
        plan.append({"row": i, "building": b, "label": label, "end": end,
                     "charged": charged, "owner": owner,
                     "centre": centres.get(b), "tag": tag,
                     "posted": tag in posted,
                     "leased": (b, end) in leased})

    drafts = frappe.get_all("Expense Entry", filters={"docstatus": 0},
                            fields=["name", "amount"])
    live = frappe.get_all("Expense Entry", filters={"docstatus": 1},
                          fields=["name", "amount"])

    if not control:
        problems.append(C.Problem(HISTORY, "-", CONTROL, "", "no_control",
                                  "the control account does not exist yet; "
                                  "Run creates it"))
    if not income:
        problems.append(C.Problem(HISTORY, "-", "income", "",
                                  "no_income_account",
                                  "no Rental Income or Rent Income account on "
                                  "the chart to credit"))
    return plan, problems, {"company": company, "control": control,
                            "income": income, "rivals": rivals,
                            "drafts": drafts, "live": live}


def check():
    rows = C.rows(HISTORY)
    plan, problems, ctx = _resolve(rows)
    rev = sum(p["charged"] for p in plan if not p["posted"])
    own = sum(p["owner"] for p in plan if not p["leased"])
    drafts = sum(float(d["amount"] or 0) for d in ctx["drafts"])

    def q(v):
        return frappe.utils.fmt_money(v, currency="QAR")

    print("STAGE 11 CHECK — the ledger")
    print("  this stage POSTS. Everything before it left the GL empty.")
    print("  contra account   %s" % (ctx["control"] or
                                     "%s — Run will create it" % CONTROL))
    print("  income account   %s" % (ctx["income"] or "NONE FOUND"))
    if ctx["rivals"]:
        print("      note: %s also exists. Nothing posts to it; if it holds a "
              "balance that is demo residue for Anoop."
              % ", ".join(ctx["rivals"]))
    print("  %d revenue journal(s)      %s" % (len([p for p in plan
                                                    if not p["posted"]
                                                    and p["charged"]]), q(rev)))
    print("  %d head lease entr(ies)    %s" % (len([p for p in plan
                                                    if not p["leased"]
                                                    and p["owner"]]), q(own)))
    print("  %d cost draft(s) to submit %s" % (len(ctx["drafts"]), q(drafts)))
    print("  result for the period      %s" % q(rev - own - drafts))
    print("      the loss is key money: 1,419,551 of lease premium charged to "
          "cost of sales in ten months, at the accountant's direction.")
    if ctx["live"]:
        print("  %d entr(ies) are already submitted and will be left alone"
              % len(ctx["live"]))
    if any(p["posted"] for p in plan):
        print("  %d period(s) already posted and will be skipped"
              % len([p for p in plan if p["posted"]]))
    C.report(problems)
    if problems and ctx["control"]:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"problems": len(problems), "clean": not problems}


def run():
    rows = C.rows(HISTORY)
    company = C.company()
    ensure_chart(company)
    _control_account(company, create=True)

    plan, problems, ctx = _resolve(rows)
    hard = [p for p in problems if p.rule != "no_control"]
    if hard:
        C.report(hard)
        C.write_exceptions(STAGE, hard)
        frappe.throw("Stage 11 refused: %d problem(s). Run Check." % len(hard))

    control, income = ctx["control"], ctx["income"]
    journals, entries, failed = 0, 0, []
    print("STAGE 11 RUN — the ledger")
    print("  contra %s, income %s" % (control, income))

    for p in plan:
        if p["posted"] or not p["charged"]:
            continue
        try:
            je = frappe.get_doc({
                "doctype": "Journal Entry", "voucher_type": "Journal Entry",
                "company": company, "posting_date": p["end"],
                "user_remark": "Rent charged %s · %s %s"
                               % (p["label"], MARKER, p["tag"]),
                "accounts": [
                    {"account": control, "debit_in_account_currency":
                     p["charged"], "cost_center": p["centre"]},
                    {"account": income, "credit_in_account_currency":
                     p["charged"], "cost_center": p["centre"]},
                ]})
            je.flags.ignore_permissions = True
            je.insert()
            je.submit()
            frappe.db.commit()
            journals += 1
        except Exception as e:
            frappe.db.rollback()
            failed.append(("revenue %s" % p["tag"],
                           (str(e).splitlines() or ["?"])[0][:90]))

    for p in plan:
        if not p["owner"] or p["leased"]:
            continue
        try:
            e = frappe.new_doc("Expense Entry")
            e.expense_date = p["end"]
            e.expense_head = frappe.db.get_value(
                "Account", {"company": company,
                            "account_name": "Head Lease Rent"}, "name")
            e.amount = p["owner"]
            e.building = p["building"]
            e.payment_mode = "Bank"
            e.paid_from = control
            e.description = "Head lease rent %s %s" % (p["building"],
                                                       p["label"])
            e.company = company
            e.flags.ignore_permissions = True
            e.insert()
            e.submit()
            frappe.db.commit()
            entries += 1
        except Exception as ex:
            frappe.db.rollback()
            failed.append(("head lease %s" % p["tag"],
                           (str(ex).splitlines() or ["?"])[0][:90]))

    done = 0
    for d in ctx["drafts"]:
        try:
            doc = frappe.get_doc("Expense Entry", d["name"])
            if doc.docstatus != 0:
                continue
            doc.payment_mode = "Bank"
            doc.paid_from = control
            doc.flags.ignore_permissions = True
            doc.save()
            doc.submit()
            done += 1
            if done % 200 == 0:
                frappe.db.commit()
                print("      %d cost entr(ies) submitted..." % done)
        except Exception as ex:
            frappe.db.rollback()
            failed.append((d["name"], (str(ex).splitlines() or ["?"])[0][:90]))
    frappe.db.commit()

    if failed:
        C.report([C.Problem(HISTORY, "-", "posting", n, "post_failed", w)
                  for n, w in failed])
    print("  %d revenue journal(s), %d head lease entr(ies), %d cost entr(ies)"
          % (journals, entries, done))
    print("  Now press Gate.")
    return {"journals": journals, "head_lease": entries, "costs": done,
            "failed": len(failed)}


def reload():
    print("STAGE 11 RELOAD — the ledger")
    return run()


def gate():
    rows = C.rows(HISTORY)
    plan, problems, ctx = _resolve(rows)
    company = ctx["company"]
    control = ctx["control"]

    want_rev = round(sum(p["charged"] for p in plan), 2)
    want_own = round(sum(p["owner"] for p in plan), 2)
    # head lease rent, plus everything stages 8 and 9 put on the site
    want_cost = want_own
    for f in ("opex.csv", "key_money.csv"):
        want_cost += round(sum(float(x.get("amount") or 0)
                               for x in C.rows(f)), 2)
    want_cost = round(want_cost, 2)

    gl = frappe.get_all("GL Entry", filters={"is_cancelled": 0},
                        fields=["account", "debit", "credit", "cost_center"])
    income_cr = round(sum(float(g.credit or 0) for g in gl
                          if g.account == ctx["income"]), 2)
    ctrl_dr = round(sum(float(g.debit or 0) for g in gl
                        if g.account == control), 2)
    ctrl_cr = round(sum(float(g.credit or 0) for g in gl
                        if g.account == control), 2)
    no_centre = len([g for g in gl if not g.cost_center])
    banks = {a["name"] for a in frappe.get_all(
        "Account", filters={"company": company, "account_type": "Bank"},
        fields=["name"])}
    real_bank = len([g for g in gl if g.account in banks])

    drafts = frappe.db.count("Expense Entry", {"docstatus": 0})
    submitted = frappe.db.count("Expense Entry", {"docstatus": 1})
    costs = round(sum(float(e.amount or 0) for e in frappe.get_all(
        "Expense Entry", filters={"docstatus": 1}, fields=["amount"])), 2)
    unlinked = len([e for e in frappe.get_all(
        "Expense Entry", filters={"docstatus": 1},
        fields=["name", "journal_entry"]) if not e.journal_entry])

    def money(a, b):
        return abs(round(a, 2) - round(b, 2)) < 1.0

    checks = [
        ("the ledger has entries", bool(gl), "%d GL row(s)" % len(gl)),
        ("revenue posted in full", money(income_cr, want_rev),
         "%s credited vs %s expected"
         % (frappe.utils.fmt_money(income_cr, currency="QAR"),
            frappe.utils.fmt_money(want_rev, currency="QAR"))),
        ("every cost entry is submitted", not drafts,
         "%d submitted, none left as drafts" % submitted if not drafts
         else "%d still draft" % drafts),
        ("every submitted cost wrote a journal", not unlinked,
         "all linked" if not unlinked else "%d without one" % unlinked),
        ("cost posted in full", money(costs, want_cost),
         "%s posted vs %s expected"
         % (frappe.utils.fmt_money(costs, currency="QAR"),
            frappe.utils.fmt_money(want_cost, currency="QAR"))),
        ("nothing posted to a real bank account", not real_bank,
         "everything contras to %s" % control if not real_bank
         else "%d row(s) hit a Bank account" % real_bank),
        ("every posting has a cost centre", not no_centre,
         "none missing" if not no_centre else "%d without one" % no_centre),
        ("the control account carries the period",
         money(ctrl_dr - ctrl_cr, want_rev - costs),
         "%s vs %s expected"
         % (frappe.utils.fmt_money(ctrl_dr - ctrl_cr, currency="QAR"),
            frappe.utils.fmt_money(want_rev - costs, currency="QAR"))),
        ("the worksheet still resolves cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
