# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Unit.unit_type moves from BHK to BR.

BHK is Indian-market vocabulary that arrived with the ERPNext-flavoured
defaults. Every head-lease schedule, landlord unit list and listing in Doha
reads BR, and unit_type is returned verbatim into the MD dashboard rows and
onward to the Digital CFO, so the stored string is the one the business says.

"Villa" is added at the same time: a villa compound's units are villas, and
its absence is what let the onboarding wizard's property type leak into the
unit type unnoticed.

Idempotent: safe to re-run.
"""

import frappe

RENAME = {
    "1 BHK": "1BR",
    "2 BHK": "2BR",
    "3 BHK": "3BR",
    "4 BHK": "4BR",
}


def execute():
    if not frappe.db.table_exists("Unit"):
        return

    for old, new in RENAME.items():
        moved = frappe.db.count("Unit", {"unit_type": old})
        if not moved:
            continue
        frappe.db.set_value("Unit", {"unit_type": old}, "unit_type", new,
                            update_modified=False)
        frappe.logger().info(
            "unit_type_br_vocabulary: {0} unit(s) moved from {1} to {2}".format(
                moved, old, new))

    # Anything left outside the Select is data the doctype can no longer hold.
    # It is reported rather than guessed at, because the only known cause is
    # the onboarding wizard writing a property type ("Villa compound",
    # "Apartment block", "Mixed use") into the field, and which unit type was
    # actually meant is not recoverable from the record.
    allowed = set(
        frappe.get_meta("Unit").get_field("unit_type").options.split("\n"))
    stray = frappe.db.sql("""
        select unit_type, count(*) as n from `tabUnit`
        where ifnull(unit_type, '') != '' group by unit_type
    """, as_dict=True)
    for row in stray:
        if row.unit_type not in allowed:
            frappe.logger().warning(
                "unit_type_br_vocabulary: {0} unit(s) hold {1!r}, which is not "
                "a unit type. Set them by hand.".format(row.n, row.unit_type))
