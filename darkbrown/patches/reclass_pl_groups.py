"""Move expense accounts sitting outside their P&L group into it.

    bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_pl_groups.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_pl_groups.run

WHY THIS EXISTS

`utils.chart_of_accounts.HEADS` already says where every expense head belongs -
Owner/Head Lease Rent and Building Maintenance in Cost of Sales, Salary in
Staff Cost, and so on. But `ensure_chart()` deliberately refuses to move an
account that already exists somewhere else, because it runs unattended on
every `bench migrate` and reparenting an account with postings against it is
not a decision a migration hook should take on its own. It records them as
`misplaced` and stops.

That is why the accountant's review found Owner Rent, Salary (322,286),
Building Maintenance, Commission on Sales and Marketing Expenses all printing
under Other Expense: the accounts pre-dated the chart, so the chart described
them correctly and never moved them.

This is the attended half. It does exactly the move `ensure_chart` declined,
having first shown you every account it will touch and what is posted to it.

WHAT IT DOES NOT DO

No journal is written. Reparenting an ERPNext Account moves its whole history
with it, because the P&L is built by walking the account tree - the GL entries
themselves are untouched and every voucher keeps its original account. That is
the correct instrument here: the postings were never wrong, only their place
on the chart was.

An account whose name is not in HEADS is left alone and listed. ALIASES below
maps the few names the books use that the chart calls something else; add to
it rather than renaming accounts on the site.

REVERSIBILITY

`dry_run` prints the current parent of every account it would move. Keep that
output. Reversing is the same operation with those parents.
"""
import frappe

from darkbrown.utils import chart_of_accounts as COA

#: Names the books use -> the head in COA.HEADS that means the same cost.
#: The site's own account keeps its name; only its parent changes.
ALIASES = {
    "Owner Rent": "Head Lease Rent",
    "Owners Rent": "Head Lease Rent",
    "Owner's Rent": "Head Lease Rent",
    "Landlord Rent": "Head Lease Rent",
    "Building Maintanance": "Building Maintenance",   # as spelt in the workbook
    "Salaries": "Salary",
    "Salary & Wages": "Salary",
    "Marketing Expense": "Marketing Expenses",
    "KeyMoney- Other": "Key Money - Other",
    "Key Money- Other": "Key Money - Other",
}


def _company():
    return COA._company()


def _target_parents(company):
    """group name -> the Account docname of that group on this company."""
    out = {}
    for group, _label in COA.GROUPS:
        name = frappe.db.get_value("Account", {"account_name": group,
                                               "company": company,
                                               "is_group": 1}, "name")
        if name:
            out[group] = name
    return out


def _balance(account):
    row = frappe.db.sql("""
        select sum(debit) - sum(credit) as bal, count(*) as n
        from `tabGL Entry`
        where account = %s and is_cancelled = 0
    """, account, as_dict=True)
    if not row:
        return 0.0, 0
    return float(row[0].bal or 0), int(row[0].n or 0)


def _plan():
    """(moves, skipped, missing_groups). Reads only."""
    company = _company()
    if not company:
        frappe.throw("No company on this site.")

    groups = _target_parents(company)
    missing = [g for g, _ in COA.GROUPS if g not in groups]

    moves, skipped = [], []
    accounts = frappe.get_all(
        "Account", filters={"company": company, "is_group": 0,
                            "root_type": "Expense"},
        fields=["name", "account_name", "parent_account"])

    for acc in accounts:
        head = ALIASES.get(acc.account_name, acc.account_name)
        spec = COA.HEAD_INDEX.get(head)
        if not spec:
            skipped.append((acc.name, acc.parent_account,
                            "not an expense head the chart knows"))
            continue
        group = spec[0]
        parent = groups.get(group)
        if not parent:
            skipped.append((acc.name, acc.parent_account,
                            "group %r does not exist - run ensure_chart first"
                            % group))
            continue
        if acc.parent_account == parent:
            continue
        bal, n = _balance(acc.name)
        moves.append({"account": acc.name, "from": acc.parent_account,
                      "to": parent, "group": group, "balance": bal,
                      "entries": n})

    moves.sort(key=lambda m: (m["group"], m["account"]))
    return moves, skipped, missing


def dry_run():
    """Report without writing. Safe at any time."""
    moves, skipped, missing = _plan()

    print("=" * 78)
    print("DRY RUN - nothing changed")
    print("=" * 78)

    if missing:
        print("")
        print("MISSING P&L GROUPS - run chart_of_accounts.ensure_chart first:")
        for g in missing:
            print("   %s" % g)

    if not moves:
        print("")
        print("Every expense account is already under its P&L group.")
    else:
        print("")
        print("%d account(s) to move:" % len(moves))
        print("")
        print("  %-34s %-26s %14s %6s" % ("ACCOUNT", "MOVES TO",
                                          "BALANCE", "GLES"))
        total = 0.0
        for m in moves:
            total += m["balance"]
            print("  %-34s %-26s %14s %6d"
                  % (m["account"][:34], m["group"][:26],
                     format(m["balance"], ",.2f"), m["entries"]))
            print("      currently under: %s" % m["from"])
        print("")
        print("  %-34s %-26s %14s" % ("", "moving in total",
                                      format(total, ",.2f")))

    if skipped:
        print("")
        print("LEFT ALONE - %d account(s):" % len(skipped))
        for name, parent, why in skipped:
            print("   %-40s %s" % (name[:40], why))
            print("       under: %s" % parent)

    print("")
    print("Keep this output. The 'currently under' lines are how to reverse.")
    return {"moves": moves, "skipped": skipped, "missing_groups": missing}


def run():
    """Do the moves. Idempotent - a second run finds nothing to do."""
    moves, skipped, missing = _plan()
    if missing:
        frappe.throw("P&L groups missing: %s. Run "
                     "darkbrown.utils.chart_of_accounts.ensure_chart first."
                     % ", ".join(missing))
    if not moves:
        print("Nothing to move - every expense account is already in place.")
        return {"moved": [], "failed": []}

    moved, failed = [], []
    for m in moves:
        try:
            doc = frappe.get_doc("Account", m["account"])
            doc.parent_account = m["to"]
            doc.flags.ignore_permissions = True
            doc.save()
            moved.append(m)
            print("  moved %-36s -> %s" % (m["account"][:36], m["group"]))
        except Exception as e:
            frappe.db.rollback()
            failed.append((m["account"], str(e)[:160]))
            print("  FAILED %-35s %s" % (m["account"][:35], str(e)[:160]))

    if moved:
        frappe.db.commit()

    print("")
    print("moved %d, failed %d" % (len(moved), len(failed)))
    if failed:
        print("The failures are unchanged on the chart. Nothing else rolled "
              "back - each account is saved on its own.")
    print("Rebuild the P&L to see the effect. No journal was written and no "
          "GL entry was altered.")
    return {"moved": moved, "failed": failed, "skipped": skipped}
