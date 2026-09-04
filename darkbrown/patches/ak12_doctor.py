"""What is actually on this ledger, and where each piece came from.

    bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_doctor.run

Read-only. Creates nothing, changes nothing, deletes nothing. Run it whenever
a screen shows a number you do not believe, and send me the output.

WHY IT EXISTS

The general ledger showed 155 journals, 401,000 of Landlord Rent, 256,400 sat
in Temporary Opening, and zero income - on a site that was supposed to hold one
building. Every one of those figures is explainable, but only by reading the
vouchers, and until now there was no way to read them short of clicking through
the desk. Counting records told us the load ran. This says what the load ran
*onto*.

WHAT IT SEPARATES

Vouchers fall into eras, and each era has a fingerprint:

  revision 6      Sales Invoices tagged [AK12-HIST-INV-nnn] posting to a real
                  income account; Purchase Invoices tagged [AK12-HL-INV-nnn].
                  What the current pack creates.

  revision 5      the same [AK12-HIST-INV-nnn] tag but `is_opening = Yes` and
                  the debit parked in Temporary Opening. These are the ones
                  that make the P&L read zero. Revision 6 skips them rather
                  than fixing them, because their tag already exists - so a
                  load onto a site that still has them changes nothing and
                  looks like it worked.

  legacy          anything else. On this site that means the abandoned
                  portfolio-wide work: landlord invoices with no DarkBrown
                  tag, ERPNext's own "No Remarks" against them, dated in a
                  single batch and covering buildings that are no longer on
                  the site.

A clean revision-6 site has only the first group. Anything in the other two
means `reset` has not been run since, and the statements are a blend of eras.
"""
import re
from collections import defaultdict

import frappe
from frappe.utils import flt

BAR = "-" * 74
HIST_RE = re.compile(r"\[(AK12-HIST-INV-\d{3})\]")
HL_RE = re.compile(r"\[(AK12-HL-INV-\d{3})\]")


def _h(t):
    print("\n" + BAR + "\n  " + t + "\n" + BAR)


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company"))


def run():
    company = _company()
    print("=" * 74)
    print("  AK-12 DOCTOR - read only, nothing is changed")
    print("  company: %s" % company)
    print("=" * 74)

    verdict = []

    # ------------------------------------------------------------ the ledger
    _h("1. GL Entry by account")
    rows = frappe.get_all(
        "GL Entry", filters={"is_cancelled": 0},
        fields=["account", "sum(debit) as dr", "sum(credit) as cr",
                "count(name) as n"],
        group_by="account", limit=500)
    if not rows:
        print("    the ledger is empty")
    tot_dr = tot_cr = 0.0
    for r in sorted(rows, key=lambda x: -(flt(x.dr) + flt(x.cr))):
        tot_dr += flt(r.dr)
        tot_cr += flt(r.cr)
        print("    %-38s dr %13s  cr %13s  (%d rows)"
              % (str(r.account)[:38], format(flt(r.dr), ",.2f"),
                 format(flt(r.cr), ",.2f"), r.n))
    print("    %-38s dr %13s  cr %13s   %s"
          % ("TOTAL", format(tot_dr, ",.2f"), format(tot_cr, ",.2f"),
             "balanced" if abs(tot_dr - tot_cr) < 0.01 else "OUT OF BALANCE"))

    # Money in Temporary Opening is the revision-5 signature.
    temp = frappe.db.get_value("Account", {"account_name": "Temporary Opening",
                                           "company": company}, "name")
    if temp:
        t = [r for r in rows if r.account == temp]
        bal = round(flt(t[0].dr) - flt(t[0].cr), 2) if t else 0.0
        if abs(bal) >= 0.01:
            verdict.append(
                "Temporary Opening holds %s. That is revision-5 opening "
                "invoices; income reads zero until they are gone."
                % format(abs(bal), ",.2f"))

    # ------------------------------------------------------- vouchers by era
    _h("2. Sales Invoices by era")
    si = frappe.get_all(
        "Sales Invoice", filters={"docstatus": 1},
        fields=["name", "customer", "posting_date", "grand_total",
                "outstanding_amount", "is_opening", "remarks"], limit=5000)
    eras = defaultdict(lambda: [0, 0.0])
    for d in si:
        tagged = bool(HIST_RE.search(d.remarks or ""))
        if tagged and (d.is_opening or "") == "Yes":
            era = "revision 5 (opening entry - WRONG)"
        elif tagged:
            era = "revision 6 (real income)"
        else:
            era = "legacy / not from this pack"
        eras[era][0] += 1
        eras[era][1] += flt(d.grand_total)
    for era in sorted(eras):
        print("    %-38s %4d invoices  %13s"
              % (era, eras[era][0], format(eras[era][1], ",.2f")))
    if not si:
        print("    none")
    if "revision 5 (opening entry - WRONG)" in eras:
        verdict.append(
            "%d rent invoices are revision-5 opening entries. Revision 6 will "
            "SKIP them (their tag already exists), so loading again fixes "
            "nothing - they have to be removed by reset."
            % eras["revision 5 (opening entry - WRONG)"][0])

    _h("3. Purchase Invoices by era")
    pi = frappe.get_all(
        "Purchase Invoice", filters={"docstatus": 1},
        fields=["name", "supplier", "posting_date", "grand_total",
                "outstanding_amount", "remarks"], limit=5000)
    eras = defaultdict(lambda: [0, 0.0, 0.0, set()])
    for d in pi:
        era = ("revision 6 (head-lease cost)" if HL_RE.search(d.remarks or "")
               else "legacy / not from this pack")
        e = eras[era]
        e[0] += 1
        e[1] += flt(d.grand_total)
        e[2] += flt(d.outstanding_amount)
        e[3].add(str(d.posting_date))
    for era in sorted(eras):
        e = eras[era]
        dates = sorted(e[3])
        span = dates[0] if len(dates) == 1 else "%s..%s" % (dates[0], dates[-1])
        print("    %-32s %4d invoices  %13s  unpaid %12s  %s"
              % (era, e[0], format(e[1], ",.2f"), format(e[2], ",.2f"), span))
    if not pi:
        print("    none")
    if "legacy / not from this pack" in eras:
        e = eras["legacy / not from this pack"]
        verdict.append(
            "%d landlord invoices totalling %s are NOT from this pack. Until "
            "now the purge did not cover Purchase Invoice at all, so they "
            "survived every reset and put their whole cost on the P&L."
            % (e[0], format(e[1], ",.2f")))

    _h("4. Payment Entries")
    pe = frappe.get_all("Payment Entry", filters={"docstatus": 1},
                        fields=["payment_type", "sum(paid_amount) as amt",
                                "count(name) as n"],
                        group_by="payment_type", limit=20)
    for r in pe:
        print("    %-10s %4d  %13s" % (r.payment_type, r.n,
                                       format(flt(r.amt), ",.2f")))
    if not pe:
        print("    none")
    pay = [r for r in pe if r.payment_type == "Pay"]
    if pi and not pay:
        verdict.append(
            "There are landlord invoices and no landlord payments, so "
            "Creditors carries the full amount and the cash flow understates "
            "what left the business.")

    # ------------------------------------------------------- what should be
    _h("5. What is on the site")
    for dt in ("Building", "Unit", "Head Lease", "Tenancy Agreement",
               "Customer", "Supplier"):
        n = frappe.db.count(dt)
        extra = ""
        if dt == "Building":
            extra = "  (%s)" % (", ".join(frappe.get_all(dt, pluck="name")[:8])
                                or "none")
        print("    %-20s %5d%s" % (dt, n, extra))
    suppliers = {s.name for s in frappe.get_all("Supplier", fields=["name"])}
    orphan = {d.supplier for d in pi if d.supplier not in suppliers}
    if orphan:
        print("\n    landlord invoices against suppliers no longer on the "
              "site: %s" % ", ".join(sorted(orphan)[:6]))

    buildings = set(frappe.get_all("Building", pluck="name"))
    print("\n    buildings referenced by cost centre on live GL entries:")
    ccs = frappe.get_all("GL Entry", filters={"is_cancelled": 0},
                         fields=["cost_center", "count(name) as n"],
                         group_by="cost_center", limit=100)
    for c in ccs:
        print("      %-40s %5d rows" % (str(c.cost_center or "(none)")[:40],
                                        c.n))

    # ------------------------------------------------------------- diagnosis
    _h("Diagnosis")
    if not verdict:
        print("  Nothing unexpected. Every voucher on this ledger came from")
        print("  revision 6 of the pack.")
    else:
        for i, v in enumerate(verdict, 1):
            print("  %d. %s" % (i, v))
        print("\n  All of these are cleared the same way, and only this way:")
        print("      ...ak12_rebuild.reset --kwargs \"{'confirm': "
              "'REMOVE ALL DARKBROWN DATA'}\"")
        print("      ...ak12_rebuild.load")
        print("  reset now empties the GL and refuses to report success while")
        print("  a single live GL Entry remains. load refuses to start unless")
        print("  the GL is empty, which is what should have stopped this.")
    return {"verdict": verdict, "clean": not verdict}
