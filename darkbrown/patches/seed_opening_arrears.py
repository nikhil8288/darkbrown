"""One-shot seed of opening tenant arrears as submitted Sales Invoices.

Creates one Sales Invoice per due row (July 2026 rent due + old dues),
with is_opening = "Yes" so amounts post against Temporary Opening and do
NOT double-count income already held in Historical Monthly PL.

Past due dates mean the existing auto_open_cases scheduled job will open
Collection Cases automatically on its next run, which feeds get_arrears()
and the MD dashboard Arrears alert.

    STEP 1  bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.dry_run
    STEP 2  map any unmatched names in arrears_name_map.csv, re-run dry_run
    STEP 3  bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.run

MATCHING (A-1, A-3)
    Exact normalised name only. There is no fuzzy fallback: a token-overlap
    match posts one tenant's arrears onto another tenant's receivable, and
    with the shared name components common in this tenant base it fires often.
    Anything that does not match exactly goes in arrears_name_map.csv, which is
    a two-column file a human fills in and commits:

        tenant_name,customer
        THASMEER/ SHAMNADH,CUST-00042

    run() ABORTS while any row is unmatched. It never invents a Customer.

IDEMPOTENCY (A-2)
    Each invoice carries a delimited, zero-padded tag [SEED-ARREARS-001].
    Existing tags are read once, up front, and compared as exact strings.
    The previous version tested `remarks LIKE '%SEED-ARREARS-1%'` per row,
    which also matched -10..-19, so rows 1-7 of a 78-row file were silently
    skipped on any re-run after a partial failure.

This module is deliberately NOT a Frappe patch. It is bench-execute only, so
that a migrate can never post to the ledger as a side effect.
"""
import csv
import os
import re

import frappe

CSV = os.path.join(os.path.dirname(__file__), "opening_arrears.csv")
NAME_MAP = os.path.join(os.path.dirname(__file__), "arrears_name_map.csv")

TAG_PREFIX = "SEED-ARREARS"
TAG_RE = re.compile(r"\[(%s-\d{3})\]" % TAG_PREFIX)

# AK-12 is loaded with its full receipt history by load_ak12_history, so
# arrears fall out of the ledger on their own and nothing is seeded here.
# Seeding as well would double them. The CSV ships with a header and no
# rows; this stays 0.00 until a building is onboarded without its history.
EXPECTED_TOTAL = 0.00


def _tag(i):
    """Delimited and zero-padded so no tag is a substring of another."""
    return "[%s-%03d]" % (TAG_PREFIX, i + 1)


# ---------------------------------------------------------------- matching

def _norm(s):
    s = (s or "").upper()
    s = s.replace("\xa0", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def _customer_index():
    """name-normalised lookup of all Customers.

    A normalised name that resolves to more than one Customer is ambiguous and
    is treated as no match at all — picking the first would be arbitrary.
    """
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def _name_map():
    """Human-curated tenant_name -> Customer docname overrides."""
    if not os.path.exists(NAME_MAP):
        return {}
    out = {}
    with open(NAME_MAP, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            src = _norm(row.get("tenant_name"))
            dest = (row.get("customer") or "").strip()
            if src and dest:
                out[src] = dest
    return out


def _match_customer(tenant_name, idx, overrides):
    n = _norm(tenant_name)
    if n in overrides:
        cust = overrides[n]
        if not frappe.db.exists("Customer", cust):
            return None, "map-target-missing"
        return cust, "mapped"
    hit = idx.get(n)
    if not hit:
        return None, "unmatched"
    if len(hit) > 1:
        return None, "ambiguous"
    return hit[0], "exact"


# ---------------------------------------------------------------- accounts

def _resolve_accounts():
    company = frappe.defaults.get_global_default("company") or \
        frappe.get_all("Company", limit=1)[0].name
    debtor = frappe.db.get_value(
        "Account", {"account_type": "Receivable", "company": company,
                    "is_group": 0}, "name")
    if not debtor:
        frappe.throw("No receivable Account found for company %s." % company)
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
    return company, debtor, temp_open


# ---------------------------------------------------------------- rows

def _load_rows():
    with open(CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _report(rows, idx, overrides):
    matched, unmatched = [], []
    for i, r in enumerate(rows):
        cust, how = _match_customer(r["tenant_name"], idx, overrides)
        (matched if cust else unmatched).append((i, r, cust, how))
    return matched, unmatched


def _existing_tags():
    """Every seed tag already on a non-cancelled Sales Invoice, read in one
    query and compared as an exact string rather than a LIKE prefix."""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"remarks": ["like", "%[" + TAG_PREFIX + "-%"],
                 "docstatus": ["<", 2]},
        fields=["remarks"])
    found = set()
    for r in rows:
        found.update(TAG_RE.findall(r.remarks or ""))
    return found


# ---------------------------------------------------------------- commands

def dry_run():
    rows = _load_rows()
    idx = _customer_index()
    overrides = _name_map()
    matched, unmatched = _report(rows, idx, overrides)
    seeded = _existing_tags()

    print("=" * 72)
    print("DRY RUN - nothing created")
    print("rows: %d  matched: %d  UNMATCHED: %d  already seeded: %d"
          % (len(rows), len(matched), len(unmatched), len(seeded)))
    print("-" * 72)
    for i, r, cust, how in matched:
        mark = "done" if _tag(i).strip("[]") in seeded else "  new"
        print("%s [%-8s] %-38s -> %-16s QAR %9s"
              % (mark, how, r["tenant_name"][:38], cust,
                 format(float(r["amount"]), ",.0f")))
    if unmatched:
        print("-" * 72)
        print("UNMATCHED - run() WILL ABORT until every one of these is")
        print("resolved. Add a line to arrears_name_map.csv for each:")
        print()
        print("tenant_name,customer")
        for i, r, _, how in unmatched:
            print('"%s",          # row %d  %s %s  QAR %s  (%s)'
                  % (r["tenant_name"], i + 2, r["property_code"], r["unit"],
                     format(float(r["amount"]), ",.0f"), how))
    total = sum(float(r["amount"]) for r in rows)
    print("-" * 72)
    print("TOTAL RECEIVABLE TO SEED: QAR %s (expected %s)"
          % (format(total, ",.2f"), format(EXPECTED_TOTAL, ",.2f")))
    if abs(total - EXPECTED_TOTAL) > 0.005:
        print("*** CSV TOTAL DOES NOT MATCH THE EXPECTED FIGURE ***")
    return {"rows": len(rows), "matched": len(matched),
            "unmatched": len(unmatched), "total": total}


def run():
    rows = _load_rows()
    idx = _customer_index()
    overrides = _name_map()
    matched, unmatched = _report(rows, idx, overrides)

    if unmatched:
        print("ABORTING: %d unmatched tenant names." % len(unmatched))
        print("Nothing was created. Run dry_run for the list, then map each")
        print("one in arrears_name_map.csv. This seeder never auto-creates a")
        print("Customer - a phantom party is worse than a stopped run.")
        return {"created": 0, "skipped": 0, "aborted": True}

    total = sum(float(r["amount"]) for r in rows)
    if abs(total - EXPECTED_TOTAL) > 0.005:
        print("ABORTING: CSV total QAR %s does not match the expected %s."
              % (format(total, ",.2f"), format(EXPECTED_TOTAL, ",.2f")))
        return {"created": 0, "skipped": 0, "aborted": True}

    company, debtor, temp_open = _resolve_accounts()
    seeded = _existing_tags()
    made = skipped = 0

    for i, r, cust, how in matched:
        tag = _tag(i)
        if tag.strip("[]") in seeded:
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
    return {"created": made, "skipped": skipped, "aborted": False}
