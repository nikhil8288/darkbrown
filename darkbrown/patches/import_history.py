"""One-shot import of the manual P&L into Historical Monthly PL.

Run once, from bench console:
    bench --site erp.darkbrown.qa execute darkbrown.patches.import_history.run

Idempotent: existing records for a period+building are overwritten, not
duplicated.
"""
import csv, os
import frappe

CSV = os.path.join(os.path.dirname(__file__), "history_by_building.csv")


def run():
    with open(CSV) as f:
        rows = list(csv.DictReader(f))

    made = updated = 0
    for r in rows:
        # Markhiya master lease is one line in the sheet covering ten villas.
        # Keep it as one row; splitting it would invent numbers we don't have.
        bldg = ("Markhiya (10 villas · master lease)"
                if r["building"] == "__MARKHIYA_MASTER__" else r["building"])

        name = "HPL-%s-%s" % (r["label"].replace(" ", ""), bldg.replace(" ", ""))[:140]

        if frappe.db.exists("Historical Monthly PL", name):
            doc = frappe.get_doc("Historical Monthly PL", name)
            updated += 1
        else:
            doc = frappe.new_doc("Historical Monthly PL")
            doc.name = name
            made += 1

        doc.update({
            "period_end": r["period_end"],
            "period_label": r["label"],
            "is_lump_period": int(r["is_lump"]),
            "building": bldg,
            "rent_received": float(r["rent_received"]),
            "owner_rent": float(r["owner_rent"]),
            "kahrama": float(r["kahrama"]),
            "wifi": float(r["wifi"]),
            "profit": float(r["profit"]),
        })
        doc.flags.ignore_permissions = True
        doc.save()

    frappe.db.commit()
    print("created %d, updated %d" % (made, updated))
