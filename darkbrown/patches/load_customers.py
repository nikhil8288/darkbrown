"""Create a Customer for every tenant in the book.

`import_tenancies` refuses to auto-create a Customer, by design — a typo would
otherwise become a party with a ledger. So the tenant list has to exist first.
Names are written exactly as the pack normalised them, which is what makes the
importer's exact-name match resolve without a name map.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.run

WHY THIS WAS REWRITTEN

The previous version filed every Customer under the Customer Group
"All Customer Groups" and the Territory "All Territories". Both are the root
nodes of their trees — group nodes, not leaves — and ERPNext refuses to file a
party against one. It also omitted `ignore_mandatory`, so any mandatory field
left blank on this site failed the insert as well.

Because run() caught the exception per name and reported only a count, the
whole step could fail on every single row and still look like it had run. The
symptom downstream was that `import_tenancies` refused every agreement for an
unmatched tenant, and the Tenants screen — which filters Customer on
`db_is_tenant` — came back completely empty while buildings and units looked
fine.

`darkbrown.api.agreements._tenant()` is the path the running application uses
to create a tenant, and it has worked in production since day one. This module
now does exactly what that function does: resolve a real leaf group, skip
Territory entirely and let ERPNext apply its own default, and set
`ignore_mandatory` on the document. It also prints the first failure in full
rather than a truncated line, so a bad site setup is visible immediately
instead of at the next step.
"""
import json, os, re
import frappe

NAMES = os.path.join(os.path.dirname(__file__), "customers.json")


def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", s).split())


def _index():
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def _group():
    """A leaf Customer Group. Never a group node — ERPNext rejects those."""
    return (frappe.db.get_value("Customer Group",
                                {"customer_group_name": "Commercial",
                                 "is_group": 0}, "name")
            or frappe.db.get_value("Customer Group", {"is_group": 0}, "name"))


def dry_run():
    names = json.load(open(NAMES, encoding="utf-8"))
    idx = _index()
    group = _group()
    print(f"\n  customer group to be used: {group or '!! NONE FOUND'}")
    if not group:
        print("  BLOCKED: this site has no non-group Customer Group. Create one")
        print("           (Commercial) before running.")
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
    return {"create": len(make), "exists": len(have), "ambiguous": ambig,
            "group": group}


def run():
    names = json.load(open(NAMES, encoding="utf-8"))
    group = _group()
    if not group:
        print("\n  ABORTING: no non-group Customer Group exists on this site.")
        return {"created": 0, "skipped": 0, "failed": [], "aborted": True}

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
                "customer_group": group,
                "db_is_tenant": 1,
                "db_tenant_category": "Individual",
            })
            doc.flags.ignore_mandatory = True
            doc.insert(ignore_permissions=True)
            idx[_norm(n)] = [doc.name]
            made += 1
        except Exception as e:
            failed.append((n, str(e)))
    frappe.db.commit()

    print(f"\n  customer group used: {group}")
    print(f"  created {made}, skipped {skipped}, failed {len(failed)}")
    if failed:
        # One full traceback beats fifty truncated ones. If the first name
        # failed, the rest failed for the same reason.
        print("\n  FIRST FAILURE IN FULL:")
        print(f"    {failed[0][0]}")
        for line in str(failed[0][1]).splitlines():
            print(f"    {line}")
        if len(failed) > 1:
            print(f"\n  and {len(failed) - 1} more, almost certainly the same cause:")
            for n, err in failed[1:]:
                print(f"    {n}: {str(err).splitlines()[0][:120]}")
    return {"created": made, "skipped": skipped,
            "failed": [(n, str(e)[:200]) for n, e in failed]}
