"""One-shot seed of owner-rent cheques payable as PDC Cheque records
(direction = Outgoing). Feeds the MD dashboard "Upcoming Landlord PDC"
alert and chart C2.

DRY RUN (always first):
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.dry_run

REAL RUN:
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.run

Idempotent: keyed on (party, cheque_date, amount); existing matches are
skipped, never duplicated. cheque_number is set to "TBC-<n>" because the
source sheet does not carry cheque numbers — edit each record in the desk
when the numbers are known.
"""
import csv
import os
import re

import frappe

CSV = os.path.join(os.path.dirname(__file__), "pdc_outgoing.csv")


def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def _supplier_index():
    idx = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        idx.setdefault(_norm(s.supplier_name), []).append(s.name)
    return idx


def _match(party, idx):
    n = _norm(party)
    if n in idx:
        return idx[n][0], "exact"
    cands = [(k, v) for k, v in idx.items()
             if (n in k or k in n) and len(k) >= 8]
    if len(cands) == 1:
        return cands[0][1][0], "contains"
    toks = {t for t in n.split() if len(t) >= 4}
    best, score_best = None, 0
    for k, v in idx.items():
        sc = len(toks & {t for t in k.split() if len(t) >= 4})
        if sc > score_best:
            best, score_best = v[0], sc
    if score_best >= 2:
        return best, "fuzzy"
    return None, "unmatched"


def _rows():
    with open(CSV) as f:
        return list(csv.DictReader(f))


def dry_run():
    rows = _rows()
    idx = _supplier_index()
    print("=" * 70)
    print("DRY RUN — nothing created")
    bad = 0
    for r in rows:
        sup, how = _match(r["party"], idx)
        mark = "OK " if sup else "?? "
        bad += 0 if sup else 1
        print(f"{mark}[{how:9}] {r['cheque_date']}  "
              f"{r['party'][:36]:<36} QAR {float(r['amount']):>9,.0f}"
              f"  -> {sup or 'NO SUPPLIER MATCH'}")
    print("-" * 70)
    print(f"rows: {len(rows)}  unmatched: {bad}  "
          f"total: QAR {sum(float(r['amount']) for r in rows):,.0f} "
          f"(expected 538,000)")
    if bad:
        print("Fix unmatched party names in pdc_outgoing.csv (match the "
              "Supplier name) before the real run.")


def run():
    rows = _rows()
    idx = _supplier_index()
    unmatched = [r for r in rows if not _match(r["party"], idx)[0]]
    if unmatched:
        print(f"ABORTING: {len(unmatched)} unmatched suppliers. "
              f"Run dry_run for the list.")
        return
    made = skipped = 0
    for r in rows:
        sup, _ = _match(r["party"], idx)
        exists = frappe.db.exists("PDC Cheque", {
            "party": sup,
            "cheque_date": r["cheque_date"],
            "amount": float(r["amount"]),
        })
        if exists:
            skipped += 1
            continue
        made += 1
        doc = frappe.new_doc("PDC Cheque")
        doc.update({
            "party": sup,
            "direction": "Outgoing",
            "cheque_date": r["cheque_date"],
            "amount": float(r["amount"]),
            "cheque_number": "TBC-%d" % made,
            "status": "Pending",
        })
        doc.flags.ignore_permissions = True
        doc.insert()
    frappe.db.commit()
    print("created %d PDC cheques, skipped %d existing" % (made, skipped))
