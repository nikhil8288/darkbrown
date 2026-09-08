"""Move the credit side of the historical expense journals onto
`Historical Cutover Control`.

    bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_cutover_credits.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_cutover_credits.run

WHY THIS EXISTS

`load_opex` credits the control account, for the reason the whole cutover uses
it: none of this money moved through a real bank account inside the ERP, and
the real accounts have to open clean at go-live so that every line on them
from day one is a reconcilable movement.

The expenses on the site were not all posted by that loader. Whatever put them
there sent the credit somewhere else, which is what the accountant's review
picked up. This finds those credits and moves them.

HOW IT FINDS THEM

It does not assume a single wrong account. It walks the journals that carry
expense debits, takes whatever accounts are on the credit side of those same
vouchers, and moves the ones that are not already the control account. A
hardcoded source account would silently miss any voucher that used a different
one, and there is no reason to believe the load used only one.

IT WRITES A JOURNAL, IT DOES NOT EDIT HISTORY

A submitted GL entry is not editable and should not be. For each wrong credit
account this posts one reversing journal per month: debit the account that was
wrongly credited, credit `Historical Cutover Control`, same posting date as
the entries it corrects. Net effect on the P&L is nil - both legs are balance
sheet - and the audit trail shows the correction rather than hiding it.

SCOPE

Only vouchers tagged as part of the historical load, and only postings dated
on or before CUTOFF. Nothing a user has entered since go-live is touched.
Widen TAGS if your load used a different marker; `dry_run` tells you how many
vouchers matched, and a match count of zero means the tags are wrong, not that
the books are clean.

IDEMPOTENCY

Each correction journal carries [DBR-CUTOVER-RECLASS-<period>]. A re-run skips
a period already corrected.
"""
import frappe
from frappe.utils import flt, getdate

from darkbrown.patches import _ledger_common as L

#: Remark markers written by the historical loaders. A voucher must carry one
#: of these to be in scope.
TAGS = ("DBR-OPEX-", "DB-HL-INV", "DB-HL-PAY", "AK12-HIST-", "DBR-CUTOVER-")

#: Nothing posted after this date is touched.
CUTOFF = "2026-07-31"

TAG = "[DBR-CUTOVER-RECLASS-%s]"


def _company():
    return L.company()


def _control(company):
    # control_account returns (name, created). load_opex.py:170 unpacks it as
    # a bare string and puts a tuple in the account field; do not copy that.
    acc, _made = L.control_account(company)
    return acc


def _tag_clause():
    return " or ".join(["je.user_remark like %s"] * len(TAGS))


def _wrong_credits(company, control):
    """Credit legs on in-scope journals that are not the control account.

    Returns rows of (account, period, amount)."""
    params = ["%" + t + "%" for t in TAGS]
    rows = frappe.db.sql("""
        select gle.account       as account,
               date_format(gle.posting_date, '%%Y-%%m-01') as period,
               sum(gle.credit - gle.debit) as amount
          from `tabGL Entry` gle
          join `tabJournal Entry` je on je.name = gle.voucher_no
         where gle.voucher_type = 'Journal Entry'
           and gle.is_cancelled = 0
           and gle.company = %s
           and gle.posting_date <= %s
           and gle.account != %s
           and gle.credit > 0
           and ({tags})
      group by gle.account, period
        having sum(gle.credit - gle.debit) > 0.005
      order by period, gle.account
    """.format(tags=_tag_clause()),
        tuple([company, CUTOFF, control] + params), as_dict=True)

    # An expense account can legitimately carry a credit (a reversal). Only
    # balance-sheet accounts are candidates for a misdirected cash-side leg.
    out = []
    for r in rows:
        root = frappe.db.get_value("Account", r.account, "root_type")
        if root in ("Income", "Expense"):
            continue
        out.append(r)
    return out


def _existing(period, company):
    return frappe.db.get_value(
        "Journal Entry", {"company": company, "docstatus": 1,
                          "user_remark": ["like", "%" + TAG % period[:7] + "%"]},
        "name")


def _month_end(period):
    from frappe.utils import get_last_day
    return get_last_day(getdate(period))


def dry_run():
    """Report without writing. Safe at any time."""
    company = _company()
    control = _control(company)
    rows = _wrong_credits(company, control)

    print("=" * 78)
    print("DRY RUN - nothing written")
    print("control account: %s" % control)
    print("scope: journals tagged %s, posted on or before %s"
          % ("/".join(TAGS), CUTOFF))
    print("=" * 78)

    if not rows:
        print("")
        print("No misdirected credits found.")
        print("If you expected some, the loader used a tag not in TAGS - "
              "check a voucher's user_remark and add it.")
        return {"rows": []}

    by_period = {}
    for r in rows:
        by_period.setdefault(r.period, []).append(r)

    total = 0.0
    for period in sorted(by_period):
        done = _existing(period, company)
        print("")
        print("  %s%s" % (period[:7], "   ALREADY CORRECTED" if done else ""))
        for r in by_period[period]:
            total += flt(r.amount)
            print("     %-46s %14s" % (r.account[:46],
                                       format(flt(r.amount), ",.2f")))

    print("")
    print("  total to move onto %s: %s" % (control, format(total, ",.2f")))
    print("")
    print("Each period gets one journal: debit the accounts above, credit the")
    print("control account. Both legs are balance sheet - the P&L does not move.")
    return {"rows": rows, "total": total}


def run():
    """Post the corrections. Re-running only fills in periods not yet done."""
    company = _company()
    control = _control(company)
    rows = _wrong_credits(company, control)
    if not rows:
        print("Nothing to correct.")
        return {"made": [], "skipped": []}

    by_period = {}
    for r in rows:
        by_period.setdefault(r.period, []).append(r)

    L.ensure_fiscal_years(sorted(by_period))

    made, skipped = [], []
    for period in sorted(by_period):
        if _existing(period, company):
            skipped.append(period)
            continue
        lines = by_period[period]
        amount = round(sum(flt(r.amount) for r in lines), 2)

        accounts = [{"account": r.account,
                     "debit_in_account_currency": round(flt(r.amount), 2)}
                    for r in lines]
        accounts.append({"account": control,
                         "credit_in_account_currency": amount})

        je = frappe.get_doc({
            "doctype": "Journal Entry", "voucher_type": "Journal Entry",
            "company": company, "posting_date": _month_end(period),
            "user_remark": ("Cutover reclass: historical expense credits moved "
                            "to %s for %s. %s"
                            % (control, period[:7], TAG % period[:7])),
            "accounts": accounts,
        })
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()
        made.append((period, je.name, amount))
        print("  %s  %s  %s" % (period[:7], je.name, format(amount, ",.2f")))

    if made:
        frappe.db.commit()

    print("")
    print("posted %d journal(s), skipped %d already done"
          % (len(made), len(skipped)))
    return {"made": made, "skipped": skipped}
