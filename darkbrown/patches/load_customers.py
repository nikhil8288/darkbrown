"""Create a Customer for every tenant in the book.

`import_tenancies` refuses to auto-create a Customer, by design — a typo would
otherwise become a party with a ledger. So the tenant list has to exist first.
Names are written exactly as the pack normalised them, which is what makes the
importer's exact-name match resolve without a name map.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.run

Read 92_tenant_name_review.csv BEFORE running this. It lists 17 pairs that are
probably one person under two spellings. Merging after agreements exist against
both is real work; merging now is a line in a text file.
"""
import json, os, re
import frappe

NAMES = os.path.join(os.path.dirname(__file__), "customers.json")
GROUP = "All Customer Groups"
TERRITORY = "All Territories"


def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", s).split())


def _index():
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def dry_run():
    names = json.load(open(NAMES, encoding="utf-8"))
    idx = _index()
    make = [n for n in names if _norm(n) not in idx]
    have = [n for n in names if len(idx.get(_norm(n), [])) == 1]
    ambig = [n for n in names if len(idx.get(_norm(n), [])) > 1]
    print(f"\n  {len(names)} tenant names in the pack")
    print(f"  {len(have)} already exist as a Customer")
    print(f"  {len(make)} would be created")
    print(f"  {len(ambig)} match more than one Customer — these need a hand")
    for n in ambig:
        print(f"    ambiguous: {n} -> {idx[_norm(n)]}")
    dupes = {}
    for n in names:
        dupes.setdefault(_norm(n), []).append(n)
    clash = {k: v for k, v in dupes.items() if len(v) > 1}
    if clash:
        print(f"  {len(clash)} names collide after normalisation:")
        for k, v in clash.items():
            print(f"    {k} <- {v}")
    return {"create": len(make), "exists": len(have), "ambiguous": ambig}


def run():
    names = json.load(open(NAMES, encoding="utf-8"))
    idx = _index()
    made, skipped, failed = 0, 0, []
    for n in names:
        if _norm(n) in idx:
            skipped += 1
            continue
        try:
            doc = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": n,
                "customer_type": "Individual",
                "customer_group": GROUP,
                "territory": TERRITORY,
                "db_is_tenant": 1,
            }).insert(ignore_permissions=True)
            idx[_norm(n)] = [doc.name]
            made += 1
        except Exception as e:
            failed.append((n, str(e)[:140]))
    frappe.db.commit()
    print(f"\n  created {made}, skipped {skipped}, failed {len(failed)}")
    for n, err in failed:
        print(f"    {n}: {err}")
    return {"created": made, "skipped": skipped, "failed": failed}
