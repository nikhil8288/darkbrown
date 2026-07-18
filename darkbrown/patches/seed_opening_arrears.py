"""One-shot seed of opening tenant arrears as submitted Sales Invoices.

Creates one Sales Invoice per due row (July 2026 rent due + old dues),
with is_opening = "Yes" so amounts post against Temporary Opening and do
NOT double-count income already held in Historical Monthly PL.

Past due dates mean the existing auto_open_cases scheduled job will open
Collection Cases automatically on its next run, which feeds get_arrears()
and the MD dashboard Arrears alert.

DRY RUN (matches names, creates nothing — always run this first):
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.dry_run

REAL RUN:
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.run

Idempotent: each invoice carries a remarks tag SEED-ARREARS-<n>; rows whose
tag already exists on a non-cancelled Sales Invoice are skipped.
"""
import csv
import os
import re

import frappe
from frappe.utils import today

CSV = os.path.join(os.path.dirname(__file__), "opening_arrears.csv")


# ---------------------------------------------------------------- matching

def _norm(s):
    s = (s or "").upper()
    s = s.replace("\xa0", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def _customer_index():
    """name-normalised lookup of all Customers."""
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def _match_customer(tenant_name, idx):
    n = _norm(tenant_name)
    if n in idx:
        return idx[n][0], "exact"
    # containment either way (handles 'THASMEER/ SHAMNADH ...' style rows)
    cands = [(k, v) for k, v in idx.items()
             if (n in k or k in n) and len(k) >= 8]
    if len(cands) == 1:
        return cands[0][1][0], "contains"
    # token-overlap fallback: >= 2 shared tokens of length >= 4
    toks = {t for t in n.split() if len(t) >= 4}
    best, best_score = None, 0
    for k, v in idx.items():
        score = len(toks & {t for t in k.split() if len(t) >= 4})
        if score > best_score:
            best, best_score = v[0], score
    if best_score >= 2:
        return best, "fuzzy"
    return None, "unmatched"


def _resolve_accounts():
    company = frappe.defaults.get_global_default("company") or \
        frappe.get_all("Company", limit=1)[0].name
    abbr = frappe.db.get_value("Company", company, "abbr")
    debtor = frappe.db.get_value(
        "Account", {"account_type": "Receivable", "company": company,
                    "is_group": 0}, "name")
    temp_open = frappe.db.get_value(
        "Account", {"account_name": "Temporary Opening", "company": company},
        "name")
    if not temp_open:
        temp_open = frappe.get_doc({
            "doctype": "Account",
            "account_name": "Temporary Opening",
            "company": company,
            "parent_account": frappe.db.get_value(
                "Account", {"root_type": "Asset", "is_group": 1,
                            "company": company,
                            "parent_account": ["is", "not set"]}, "name"),
            "account_type": "Temporary",
        }).insert(ignore_permissions=True).name
    return company, abbr, debtor, temp_open


def _load_rows():
    with open(CSV) as f:
        return list(csv.DictReader(f))


def _report(rows, idx):
    matched, unmatched = [], []
    for i, r in enumerate(rows):
        cust, how = _match_customer(r["tenant_name"], idx)
        (matched if cust else unmatched).append((i, r, cust, how))
    return matched, unmatched


# ---------------------------------------------------------------- commands

def dry_run():
    rows = _load_rows()
    idx = _customer_index()
    matched, unmatched = _report(rows, idx)
    print("=" * 70)
    print("DRY RUN — nothing created")
    print(f"rows: {len(rows)}  matched: {len(matched)}  "
          f"UNMATCHED: {len(unmatched)}")
    print("-" * 70)
    for i, r, cust, how in matched:
        print(f"OK  [{how:8}] {r['tenant_name'][:38]:<38} -> {cust}  "
              f"QAR {float(r['amount']):>9,.0f}")
    if unmatched:
        print("-" * 70)
        print("UNMATCHED — fix these before the real run (edit tenant_name")
        print("in opening_arrears.csv to match the Customer name, or create")
        print("the Customer):")
        for i, r, _, _ in unmatched:
            print(f"??  row {i + 2}: {r['tenant_name']}  "
                  f"({r['property_code']} {r['unit']})  "
                  f"QAR {float(r['amount']):,.0f}")
    total = sum(float(r["amount"]) for r in rows)
    print("-" * 70)
    print(f"TOTAL RECEIVABLE TO SEED: QAR {total:,.2f} "
          f"(expected 216,519.00)")


def run():
    rows = _load_rows()
    idx = _customer_index()
    matched, unmatched = _report(rows, idx)
    if unmatched:
        print(f"ABORTING: {len(unmatched)} unmatched tenant names. "
              f"Run dry_run for the list.")
        return

    company, abbr, debtor, temp_open = _resolve_accounts()
    made = skipped = 0
    for i, r, cust, how in matched:
        tag = "SEED-ARREARS-%d" % (i + 1)
        if frappe.db.exists("Sales Invoice",
                            {"remarks": ["like", "%%%s%%" % tag],
                             "docstatus": ["<", 2]}):
            skipped += 1
            continue
        si = frappe.new_doc("Sales Invoice")
        si.customer = cust
        si.company = company
        si.set_posting_time = 1
        si.posting_date = r["due_date"]
        si.due_date = r["due_date"]
        si.is_opening = "Yes"
        si.debit_to = debtor
        si.remarks = "%s | %s | %s %s | %s" % (
            tag, r["source"], r["property_code"], r["unit"], r["remarks"])
        si.append("items", {
            "item_name": "Opening Arrears - %s %s" % (
                r["property_code"], r["unit"]),
            "description": r["remarks"],
            "qty": 1,
            "rate": float(r["amount"]),
            "income_account": temp_open,
        })
        si.flags.ignore_permissions = True
        si.insert()
        si.submit()
        made += 1
    frappe.db.commit()
    print("created %d invoices, skipped %d (already seeded)" % (made, skipped))
    print("Collection Cases will auto-open on the next scheduled "
          "auto_open_cases run (or trigger it manually via bench execute).")
