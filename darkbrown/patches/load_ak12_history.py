"""Nine months of rent charged and rent received, per tenant, per unit.
Revision 6: posts as real income, not opening entries.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_ak12_history.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_ak12_history.run

WHAT THIS CREATES

One Sales Invoice per month of rent charged and one Payment Entry per month of
rent actually collected, allocated against that invoice. That is what makes a
tenant page show a payment history instead of a blank ledger, and it is what
makes arrears real: outstanding is what was charged minus what was paid, not a
number typed into a seed file.

WHY THESE ARE REAL INCOME, NOT OPENING ENTRIES

Revision 5 posted them with `is_opening = "Yes"`, which parks the debit in
Temporary Opening and recognises nothing. That was right when the manual
books still held these months; now the site has been emptied and AK-12 is the
whole ledger, so there is nothing to double-count against and an opening
entry just hides the income. The P&L read zero, the balance sheet netted to
zero, the trial balance showed a 256,400 credit in Temporary Opening. Same
shape as the live invoicer now: item "Rent", Rental Income, the building's
cost centre, posted on the 1st of the month, due on the 5th.

HOW "COLLECTED" IS DERIVED

The Revenue sheet has four money columns per month. Cash in hand for a month is

    collected = Received + Advance - Previous Due Rcvd

Advance is money received early. Previous Due Rcvd is negative when an earlier
shortfall was later recovered, so subtracting it adds the recovery back. Rent
minus collected then reproduces the workbook's own Net Rent Due exactly:
600.00, all of it G-01B. The control totals below enforce that.

TENANT ATTRIBUTION IS PER ROW, NOT PER UNIT

G-01A changed hands (Muhammed Ashique Paracholakuzhi to Dec-2025, Mohammed
Saeed Abdul Azeez from Mar-2026). The tenant named on each row owns that row's
invoice and receipt. Keying by unit would credit one tenant's money to another.

IDEMPOTENCY

Every invoice carries `[AK12-HIST-INV-nnn]` in its remarks and every receipt
carries `AK12-HIST-RCP-nnn` as its reference number, zero-padded and delimited
so no tag is a prefix of another. A re-run after a partial failure skips
exactly what it already created. Rows are read in a fixed sort order, so the
numbering is stable across runs.

Bench-execute only, never a Frappe patch: this posts to the ledger.
"""
import csv
import os
import re

import frappe
from frappe.utils import flt, getdate

from darkbrown.patches import _ledger_common as L

CSV = os.path.join(os.path.dirname(__file__), "ak12_history.csv")

INV_TAG = "AK12-HIST-INV"
RCP_TAG = "AK12-HIST-RCP"
INV_RE = re.compile(r"\[(%s-\d{3})\]" % INV_TAG)

#: Straight off the workbook's Reconciliation sheet. run() aborts on a mismatch
#: rather than post a ledger that does not tie to its source.
EXPECTED_RENT = 256400.00
EXPECTED_COLLECTED = 255800.00


def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", s).split())


def _rows():
    if not os.path.exists(CSV):
        frappe.throw("%s not found." % CSV)
    with open(CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r["unit"], r["month"], r["tenant_name"]))
    return rows


def _customer_index():
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def _resolve(rows, idx):
    """Exact normalised match only. No fuzzy fallback: tenants here share name
    tokens, and a token-overlap match posts one tenant's history onto another
    tenant's ledger."""
    resolved, problems = [], []
    for i, r in enumerate(rows):
        hits = idx.get(_norm(r["tenant_name"]), [])
        if len(hits) == 1:
            resolved.append((i, r, hits[0]))
        elif not hits:
            problems.append((i, r, "no Customer named %s" % r["tenant_name"]))
        else:
            problems.append((i, r, "%s matches %d Customers: %s"
                             % (r["tenant_name"], len(hits), hits)))
    return resolved, problems


def _existing():
    """Tags already on the site, read once, compared as exact strings."""
    inv = set()
    for r in frappe.get_all("Sales Invoice",
                            filters={"remarks": ["like", "%[" + INV_TAG + "-%"],
                                     "docstatus": ["<", 2]},
                            fields=["remarks", "name"]):
        for t in INV_RE.findall(r.remarks or ""):
            inv.add(t)
    rcp = set(frappe.get_all("Payment Entry",
                             filters={"reference_no": ["like", RCP_TAG + "-%"],
                                      "docstatus": ["<", 2]},
                             pluck="reference_no"))
    return inv, rcp


def _invoice_no(i):
    return "%s-%03d" % (INV_TAG, i + 1)


def _receipt_no(i):
    return "%s-%03d" % (RCP_TAG, i + 1)


def _posted(month):
    """Invoiced on the 1st, like the live invoicer (run.period_start)."""
    return getdate(month).replace(day=1)


def _due(month):
    """Rent falls due on the 5th, which is what the agreements say."""
    return getdate(month).replace(day=5)


def _totals(rows):
    rent = sum(flt(r["rent"]) for r in rows)
    coll = sum(flt(r["collected"]) for r in rows)
    ok = (abs(rent - EXPECTED_RENT) < 0.005
          and abs(coll - EXPECTED_COLLECTED) < 0.005)
    return rent, coll, ok


# ------------------------------------------------------------------ commands

def dry_run():
    rows = _rows()
    idx = _customer_index()
    resolved, problems = _resolve(rows, idx)
    inv_seen, rcp_seen = _existing()
    rent, coll, ok = _totals(rows)

    print("=" * 76)
    print("DRY RUN - nothing created")
    print("=" * 76)
    print("  rows %d | resolved %d | PROBLEMS %d"
          % (len(rows), len(resolved), len(problems)))
    print("  invoices already on site %d | receipts already on site %d"
          % (len(inv_seen), len(rcp_seen)))

    per = {}
    for i, r, cust in resolved:
        a = per.setdefault((r["unit"], r["tenant_name"]), [0.0, 0.0, 0])
        a[0] += flt(r["rent"])
        a[1] += flt(r["collected"])
        a[2] += 1
    print("-" * 76)
    for k in sorted(per):
        a = per[k]
        print("  %-6s %-32s %2d mo  charged %9.2f  paid %9.2f  due %8.2f"
              % (k[0], k[1][:32], a[2], a[0], a[1], a[0] - a[1]))
    print("-" * 76)
    print("  rent charged   %12s   (expected %s)"
          % (format(rent, ",.2f"), format(EXPECTED_RENT, ",.2f")))
    print("  cash collected %12s   (expected %s)"
          % (format(coll, ",.2f"), format(EXPECTED_COLLECTED, ",.2f")))
    print("  outstanding    %12s" % format(rent - coll, ",.2f"))

    if not ok:
        print("\n  *** CONTROL TOTALS DO NOT MATCH - run() WILL ABORT ***")
    if problems:
        print("\nPROBLEMS - run() WILL ABORT until every one is resolved:")
        for i, r, why in problems:
            print("  L%-4d %-6s %-10s %s" % (i + 2, r["unit"], r["month"], why))
    elif ok:
        print("\n  No problems. run() would post %d invoices and %d receipts."
              % (len([1 for i, r, c in resolved
                      if _invoice_no(i) not in inv_seen and flt(r["rent"])]),
                 len([1 for i, r, c in resolved
                      if _receipt_no(i) not in rcp_seen
                      and flt(r["collected"])])))
    return {"rows": len(rows), "problems": len(problems),
            "rent": rent, "collected": coll, "ok": ok}


def run():
    rows = _rows()
    idx = _customer_index()
    resolved, problems = _resolve(rows, idx)

    if problems:
        print("ABORTING: %d rows could not be resolved. Nothing was created."
              % len(problems))
        print("Run dry_run for the list. This loader never auto-creates a")
        print("Customer - a phantom party is worse than a stopped run.")
        return {"invoices": 0, "receipts": 0, "aborted": True}

    rent, coll, ok = _totals(rows)
    if not ok:
        print("ABORTING: control totals do not match the source workbook.")
        print("  rent charged   %s (expected %s)"
              % (format(rent, ",.2f"), format(EXPECTED_RENT, ",.2f")))
        print("  cash collected %s (expected %s)"
              % (format(coll, ",.2f"), format(EXPECTED_COLLECTED, ",.2f")))
        return {"invoices": 0, "receipts": 0, "aborted": True}

    from darkbrown.api.finance import _receipt

    company = L.company()
    debtor = L.receivable(company)
    income, made_acc = L.income_account(company)
    item = L.item("Rent", sales=True, purchase=False)
    cc = L.cost_center("AK-12")
    print("  income account : %s%s" % (income, "  (created)" if made_acc else ""))
    print("  cost centre    : %s" % (cc or "!! none on Building AK-12"))
    inv_seen, rcp_seen = _existing()
    made_inv = made_rcp = skip_inv = skip_rcp = 0

    for i, r, cust in resolved:
        due = _due(r["month"])
        inv_no, rcp_no = _invoice_no(i), _receipt_no(i)
        amount = flt(r["rent"])
        paid = flt(r["collected"])

        si_name = None
        if amount:
            if inv_no in inv_seen:
                skip_inv += 1
                si_name = frappe.db.get_value(
                    "Sales Invoice",
                    {"remarks": ["like", "%[" + inv_no + "]%"], "docstatus": 1},
                    "name")
            else:
                si = frappe.new_doc("Sales Invoice")
                si.customer = cust
                si.company = company
                si.set_posting_time = 1
                si.posting_date = _posted(r["month"])
                si.due_date = due
                si.debit_to = debtor
                si.cost_center = cc
                si.custom_billing_period = r["month"][:7]
                si.remarks = "[%s] | AK12_HISTORY | %s %s | %s | %s" % (
                    inv_no, r["building"], r["unit"], r["month"], r["remarks"])
                si.append("items", {
                    "item_code": item,
                    "item_name": "Rent - %s" % r["unit"],
                    "description": "Rent for %s, %s" % (r["unit"],
                                                        r["month"][:7]),
                    "qty": 1,
                    "rate": amount,
                    "income_account": income,
                    "cost_center": cc,
                })
                si.flags.ignore_mandatory = True
                si.flags.ignore_permissions = True
                si.insert(ignore_permissions=True)
                si.submit()
                si_name = si.name
                made_inv += 1

        if paid:
            if rcp_no in rcp_seen:
                skip_rcp += 1
            else:
                _receipt(cust, paid, due, mode=r.get("mode") or "Cheque",
                         reference=rcp_no, invoice=si_name)
                made_rcp += 1

        frappe.db.commit()

    print("\n  invoices created %d, skipped %d (already posted)"
          % (made_inv, skip_inv))
    print("  receipts created %d, skipped %d (already posted)"
          % (made_rcp, skip_rcp))
    print("  charged %s, collected %s, outstanding %s"
          % (format(rent, ",.2f"), format(coll, ",.2f"),
             format(rent - coll, ",.2f")))
    return {"invoices": made_inv, "receipts": made_rcp, "aborted": False}
