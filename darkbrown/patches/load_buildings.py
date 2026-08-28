"""Create the 23 live buildings and their 305 units.

There is no bulk building importer; `portfolio.onboard_building` is one wizard
call per building, and it is atomic — a building and every one of its units, or
nothing. This drives that endpoint once per building rather than asking anyone
to type 305 unit rows into a form.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.run

Idempotent: a building that already exists is skipped, never merged. Terminated
buildings are not created here — they carry no unit inventory, so the wizard
would refuse them anyway. Onboard those by hand if their cheques need a home.
"""
import json, os
import frappe

PAYLOAD = os.path.join(os.path.dirname(__file__), "buildings_payload.json")


def _load():
    with open(PAYLOAD, encoding="utf-8") as fh:
        return json.load(fh)


def dry_run():
    """Report what would happen. Writes nothing."""
    data = _load()
    company = frappe.db.get_single_value("DBR Settings", "default_company")
    print(f"\ncompany: {company or '!! NOT SET — onboarding will fail'}")
    exists = skip = make = 0
    units = 0
    for b in data:
        if frappe.db.exists("Building", b["building_name"]):
            exists += 1
            print(f"  SKIP   {b['building_name']:10s} already exists")
            continue
        make += 1
        units += len(b["units"])
        sup = b["landlord"]["supplier_name"]
        known = frappe.db.exists("Supplier", {"supplier_name": sup})
        print(f"  CREATE {b['building_name']:10s} {len(b['units']):3d} units  "
              f"landlord {'found' if known else 'NEW'}: {sup[:40]}")
    print(f"\n  {make} buildings to create ({units} units), {exists} already present")
    if not company:
        print("  BLOCKED: set default_company in DBR Settings first.")
    return {"create": make, "units": units, "exists": exists}


def run():
    """Create them. Each building is its own transaction."""
    from darkbrown.api.portfolio import onboard_building
    data = _load()
    made, skipped, failed = [], [], []
    for b in data:
        if frappe.db.exists("Building", b["building_name"]):
            skipped.append(b["building_name"])
            continue
        try:
            onboard_building(json.dumps(b))
            frappe.db.commit()
            made.append(b["building_name"])
            print(f"  created {b['building_name']:10s} {len(b['units']):3d} units")
        except Exception as e:
            frappe.db.rollback()
            failed.append((b["building_name"], str(e)[:160]))
            print(f"  ! FAILED {b['building_name']}: {str(e)[:160]}")
    print(f"\n  created {len(made)}, skipped {len(skipped)}, failed {len(failed)}")
    for nm, err in failed:
        print(f"    {nm}: {err}")
    return {"created": made, "skipped": skipped, "failed": failed}
