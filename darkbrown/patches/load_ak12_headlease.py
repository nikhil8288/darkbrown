"""Nine months of head-lease rent owed to the landlord and paid to him.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_ak12_headlease.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_ak12_headlease.run

WHY THIS EXISTS

The P&L had income and no cost. Nothing in the application posts the head
lease to the ledger: `Head Lease.payments` is a schedule the cheque screens
read, the MD dashboard counts unpaid Purchase Invoices, and no code path ever
creates one. So the spread - the only number this business is about - could
never appear on a statement, historically or going forward.

This loads the history. One Purchase Invoice per month against the landlord
(item "Landlord Rent", Head Lease Rent expense, the building's cost centre,
linked to the Head Lease record) and one Payment Entry paying it. Together
with load_ak12_history that gives income 256,400, cost 162,000, spread
94,400 for Nov-2025 to Jul-2026, and a balance sheet that balances on its own.

THE PAYMENT DATES ARE ASSUMED

`ak12_headlease.csv` says so in every row: `paid_on` is set to the accrual
date because the workbook carries no landlord payment history. The P&L does
not care; the cash flow and the payables balance do. Correct `paid_on`,
`paid_amount` and `mode` from the landlord cheque book before running, or
leave `paid_on` blank on any row not yet paid and it stays payable.

IDEMPOTENCY

`[AK12-HL-INV-nnn]` in the invoice remarks, `AK12-HL-PAY-nnn` as the payment
reference. Re-runs skip what exists. Control total 162,000.00 or it aborts.
"""
import csv
import os
import re

import frappe
from frappe.utils import flt, getdate

from darkbrown.patches import _ledger_common as L

CSV = os.path.join(os.path.dirname(__file__), "ak12_headlease.csv")
INV_TAG = "AK12-HL-INV"
PAY_TAG = "AK12-HL-PAY"
INV_RE = re.compile(r"\[(%s-\d{3})\]" % INV_TAG)

EXPECTED_ACCRUED = 162000.00


def _rows():
    if not os.path.exists(CSV):
        frappe.throw("%s not found." % CSV)
    with open(CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r["building"], r["period"]))
    return rows


def _existing():
    inv = set()
    for r in frappe.get_all("Purchase Invoice",
                            filters={"remarks": ["like", "%[" + INV_TAG + "-%"],
                                     "docstatus": ["<", 2]},
                            fields=["remarks"]):
        inv.update(INV_RE.findall(r.remarks or ""))
    pay = set(frappe.get_all("Payment Entry",
                             filters={"reference_no": ["like", PAY_TAG + "-%"],
                                      "docstatus": ["<", 2]},
                             pluck="reference_no"))
    return inv, pay


def _head_lease(building):
    hl = frappe.get_all("Head Lease", filters={"building": building},
                        fields=["name", "landlord"], order_by="start_date desc",
                        limit=1)
    if not hl:
        frappe.throw("No Head Lease on %s - load the building first." % building)
    return hl[0].name, hl[0].landlord


def _checks(rows):
    problems = []
    accrued = 0.0
    for i, r in enumerate(rows):
        if not frappe.db.exists("Building", r["building"]):
            problems.append((i, "building %r not on the site" % r["building"]))
        try:
            getdate(r["accrued_on"])
        except Exception:
            problems.append((i, "accrued_on unreadable"))
        if (r.get("paid_on") or "").strip():
            try:
                getdate(r["paid_on"])
            except Exception:
                problems.append((i, "paid_on unreadable"))
            if flt(r.get("paid_amount")) > flt(r["amount"]):
                problems.append((i, "paid_amount exceeds amount"))
        accrued += flt(r["amount"])
    ok = abs(accrued - EXPECTED_ACCRUED) < 0.005
    return problems, accrued, ok


def dry_run():
    rows = _rows()
    problems, accrued, ok = _checks(rows)
    inv_seen, pay_seen = _existing()
    paid = sum(flt(r["paid_amount"]) for r in rows if (r.get("paid_on") or "").strip())
    assumed = sum(1 for r in rows if "ASSUMED" in (r.get("remarks") or ""))
    print("=" * 76)
    print("DRY RUN - nothing created")
    print("=" * 76)
    print("  rows %d | PROBLEMS %d | invoices on site %d | payments on site %d"
          % (len(rows), len(problems), len(inv_seen), len(pay_seen)))
    for r in rows:
        print("  %-6s %s  accrue %10.2f on %s   pay %10.2f on %s  %s"
              % (r["building"], r["period"][:7], flt(r["amount"]),
                 r["accrued_on"], flt(r["paid_amount"]),
                 r["paid_on"] or "-", r.get("mode") or ""))
    print("-" * 76)
    print("  accrued %12s   (expected %s)"
          % (format(accrued, ",.2f"), format(EXPECTED_ACCRUED, ",.2f")))
    print("  paid    %12s" % format(paid, ",.2f"))
    print("  payable %12s" % format(accrued - paid, ",.2f"))
    if assumed:
        print("\n  %d rows carry ASSUMED payment dates. The P&L is right either"
              " way; the cash flow" % assumed)
        print("  and payables are only right once these come from the "
              "landlord cheque book.")
    if not ok:
        print("\n  *** CONTROL TOTAL DOES NOT MATCH - run() WILL ABORT ***")
    for i, why in problems:
        print("  L%-4d %s" % (i + 2, why))
    return {"rows": len(rows), "problems": len(problems), "accrued": accrued,
            "paid": paid, "ok": ok}


def run():
    rows = _rows()
    problems, accrued, ok = _checks(rows)
    if problems or not ok:
        print("ABORTING: dry_run is not clean. Nothing was created.")
        dry_run()
        return {"invoices": 0, "payments": 0, "aborted": True}

    company = L.company()
    payable = L.payable(company)
    cash = L.cash_account(company)
    expense, made_acc = L.expense_account(company)
    item = L.item("Landlord Rent", sales=False, purchase=True)
    print("  expense account: %s%s" % (expense, "  (created)" if made_acc else ""))
    print("  paid from      : %s" % cash)

    inv_seen, pay_seen = _existing()
    made_inv = made_pay = skip_inv = skip_pay = 0

    for i, r in enumerate(rows):
        inv_no, pay_no = ("%s-%03d" % (INV_TAG, i + 1),
                          "%s-%03d" % (PAY_TAG, i + 1))
        hl, landlord = _head_lease(r["building"])
        cc = L.cost_center(r["building"])
        on = getdate(r["accrued_on"])
        amount = flt(r["amount"])

        if inv_no in inv_seen:
            skip_inv += 1
            pi_name = frappe.db.get_value(
                "Purchase Invoice",
                {"remarks": ["like", "%[" + inv_no + "]%"], "docstatus": 1},
                "name")
        else:
            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = landlord
            pi.company = company
            pi.set_posting_time = 1
            pi.posting_date = on
            pi.bill_date = on
            pi.due_date = on
            pi.credit_to = payable
            pi.cost_center = cc
            pi.custom_landlord_contract = hl
            pi.custom_billing_period = r["period"][:7]
            pi.remarks = "[%s] | AK12_HEADLEASE | %s | %s | %s" % (
                inv_no, r["building"], r["period"][:7], r.get("remarks") or "")
            pi.append("items", {
                "item_code": item,
                "item_name": "Head lease rent - %s" % r["building"],
                "description": "Head lease rent, %s, %s" % (r["building"],
                                                            r["period"][:7]),
                "qty": 1,
                "rate": amount,
                "expense_account": expense,
                "cost_center": cc,
            })
            pi.flags.ignore_mandatory = True
            pi.flags.ignore_permissions = True
            pi.insert(ignore_permissions=True)
            pi.submit()
            pi_name = pi.name
            made_inv += 1

        paid_on = (r.get("paid_on") or "").strip()
        paid = flt(r.get("paid_amount"))
        if paid_on and paid:
            if pay_no in pay_seen:
                skip_pay += 1
            else:
                pe = frappe.new_doc("Payment Entry")
                pe.payment_type = "Pay"
                pe.company = company
                pe.posting_date = getdate(paid_on)
                pe.party_type = "Supplier"
                pe.party = landlord
                pe.paid_from = cash
                pe.paid_to = payable
                pe.paid_amount = paid
                pe.received_amount = paid
                pe.mode_of_payment = r.get("mode") or "Cheque"
                pe.reference_no = pay_no
                pe.reference_date = getdate(paid_on)
                pe.append("references", {
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": pi_name,
                    "allocated_amount": paid,
                })
                pe.flags.ignore_mandatory = True
                pe.flags.ignore_permissions = True
                pe.insert(ignore_permissions=True)
                pe.submit()
                made_pay += 1
        frappe.db.commit()

    print("\n  purchase invoices created %d, skipped %d" % (made_inv, skip_inv))
    print("  landlord payments created %d, skipped %d" % (made_pay, skip_pay))
    print("  accrued %s" % format(accrued, ",.2f"))
    return {"invoices": made_inv, "payments": made_pay, "aborted": False}
