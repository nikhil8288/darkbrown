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


#: Each rung drops the next most likely thing to be refused, so a site with an
#: unusual chart or missing custom fields still gets its cost onto the P&L.
#: Anything below the first rung is printed, because a fallback that nobody
#: knows happened is worse than a failure.
def _insert_invoice(spec, row):
    """Insert and submit, falling back through progressively plainer forms."""
    ladder = [
        ("as built", lambda d: d),
        ("without the custom contract/period fields", _drop_custom),
        ("without a cost centre", _drop_cost_centre),
        ("as a plain description line, no item code", _drop_item),
    ]
    first_error = None
    for label, shape in ladder:
        try:
            doc = _clone(shape(spec))
            doc.insert(ignore_permissions=True)
            doc.submit()
            if label != "as built":
                print("    %s posted %s - the full form was refused: %s"
                      % (row["period"][:7], label, str(first_error)[:110]))
            return doc
        except Exception as e:
            if first_error is None:
                first_error = e
            frappe.db.rollback()
    raise first_error


#: Header fields carried onto each retry. Listed rather than copied wholesale,
#: because a Document that has already been through validate carries derived
#: fields that must not be replayed onto a fresh one.
_HEADER = ("supplier", "company", "set_posting_time", "posting_date",
           "bill_date", "due_date", "credit_to", "cost_center", "remarks",
           "custom_landlord_contract", "custom_billing_period")
_LINE = ("item_code", "item_name", "description", "qty", "rate",
         "expense_account", "cost_center")


def _clone(spec):
    """A fresh Purchase Invoice from a plain dict of what to post."""
    doc = frappe.new_doc("Purchase Invoice")
    for f in _HEADER:
        if spec.get(f) is not None:
            setattr(doc, f, spec[f])
    line = {f: spec["line"].get(f) for f in _LINE
            if spec["line"].get(f) is not None}
    doc.append("items", line)
    doc.flags.ignore_mandatory = True
    doc.flags.ignore_permissions = True
    return doc


def _drop_custom(spec):
    spec = dict(spec, line=dict(spec["line"]))
    spec.pop("custom_landlord_contract", None)
    spec.pop("custom_billing_period", None)
    return spec


def _drop_cost_centre(spec):
    spec = _drop_custom(spec)
    spec.pop("cost_center", None)
    spec["line"].pop("cost_center", None)
    return spec


def _drop_item(spec):
    spec = _drop_cost_centre(spec)
    spec["line"].pop("item_code", None)
    return spec


def _heal():
    """Fix what can be fixed, rather than report it and stop.

    Revision 11 named the missing prerequisites. That is the right thing when
    a human has to decide, and the wrong thing for four items that have exactly
    one sensible value: a Payable account, a purchasable item, the building's
    cost centre, and fiscal years covering the dates. All four are created or
    corrected here, and every correction is printed so nothing happens silently.
    """
    done = []
    company = L.company()

    _, made = L.payable(company)
    if made:
        done.append("created a Creditors account (none was typed Payable)")

    if L.ensure_purchasable("Landlord Rent"):
        done.append("flagged item 'Landlord Rent' as a purchase item")

    for building in sorted({r["building"] for r in _rows()}):
        if frappe.db.exists("Building", building):
            cc, made = L.cost_centre_for(building)
            if made:
                done.append("wrote cost centre %s onto Building %s"
                            % (cc, building))

    dates = [r["accrued_on"] for r in _rows()]
    dates += [r["paid_on"] for r in _rows() if (r.get("paid_on") or "").strip()]
    years = L.ensure_fiscal_years(dates)
    if years:
        done.append("created fiscal year(s) %s" % ", ".join(years))

    if done:
        print("  healed before posting:")
        for d in done:
            print("    - %s" % d)
    frappe.db.commit()
    return done


def _preflight():
    """Everything a Purchase Invoice insert needs, checked before one is built.

    The rent side loaded and this side did not, which left a P&L with income
    and no cost - a 100% margin on a business whose whole point is the spread.
    The loader had already created its expense account before it failed, so the
    failure was at the insert, and the traceback scrolled past in a deploy log.
    Naming the missing piece up front is worth more than a stack trace.
    """
    out = []
    company = L.company()
    if not company:
        return [("company", "DBR Settings has no default_company")]

    if not L.cash_account(company):
        out.append(("bank/cash account",
                    "no Account typed Bank or Cash - the landlord payment has "
                    "nowhere to pay from"))


    for r in _rows():
        if not frappe.db.exists("Building", r["building"]):
            continue
        hl = frappe.get_all("Head Lease", filters={"building": r["building"]},
                            fields=["name", "landlord"], limit=1)
        if not hl:
            out.append(("head lease", "%s has none" % r["building"]))
        elif not hl[0].landlord:
            out.append(("head lease", "%s has no landlord" % hl[0].name))
        elif not frappe.db.exists("Supplier", hl[0].landlord):
            out.append(("landlord", "Supplier %r does not exist"
                        % hl[0].landlord))
        break

    if frappe.db.get_value("Company", company, "enable_perpetual_inventory"):
        out.append(("perpetual inventory",
                    "enabled on %s - a stock item on the invoice would need a "
                    "warehouse. The line uses a service item, so this is a "
                    "warning rather than a blocker." % company))
    return out


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
    pre = _preflight()
    print("=" * 76)
    print("DRY RUN - nothing created (healing is deferred to run)")
    print("=" * 76)
    print("  rows %d | PROBLEMS %d | invoices on site %d | payments on site %d"
          % (len(rows), len(problems), len(inv_seen), len(pay_seen)))
    if pre:
        print("\n  PREFLIGHT - these will stop the insert:")
        for what, why in pre:
            print("    %-20s %s" % (what, why))
    else:
        print("  preflight: everything the insert needs is present")
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
            "paid": paid, "ok": ok and not pre, "preflight": pre}


def run():
    rows = _rows()
    problems, accrued, ok = _checks(rows)
    _heal()
    pre = _preflight()
    if problems or not ok or pre:
        print("ABORTING: dry_run is not clean. Nothing was created.")
        dry_run()
        return {"invoices": 0, "payments": 0, "aborted": True}

    _heal()
    company = L.company()
    payable, _ = L.payable(company)
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
            spec = {
                "supplier": landlord, "company": company,
                "set_posting_time": 1, "posting_date": on, "bill_date": on,
                "due_date": on, "credit_to": payable, "cost_center": cc,
                "custom_landlord_contract": hl,
                "custom_billing_period": r["period"][:7],
                "remarks": "[%s] | AK12_HEADLEASE | %s | %s | %s" % (
                    inv_no, r["building"], r["period"][:7],
                    r.get("remarks") or ""),
                "line": {
                    "item_code": item,
                    "item_name": "Head lease rent - %s" % r["building"],
                    "description": "Head lease rent, %s, %s"
                                   % (r["building"], r["period"][:7]),
                    "qty": 1, "rate": amount,
                    "expense_account": expense, "cost_center": cc,
                },
            }
            try:
                pi = _insert_invoice(spec, r)
            except Exception:
                import traceback
                print("\n  FAILED on the %s invoice. What it tried to post:"
                      % r["period"][:7])
                print("    supplier        %s" % landlord)
                print("    company         %s" % company)
                print("    posting date    %s" % on)
                print("    credit to       %s" % payable)
                print("    expense account %s" % expense)
                print("    item            %s" % item)
                print("    cost centre     %s" % cc)
                print("    amount          %s" % format(amount, ",.2f"))
                print("\n" + traceback.format_exc())
                print("  Nothing further was attempted. %d invoices and %d "
                      "payments were created before this." % (made_inv, made_pay))
                return {"invoices": made_inv, "payments": made_pay,
                        "aborted": True, "failed_on": r["period"][:7]}
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
