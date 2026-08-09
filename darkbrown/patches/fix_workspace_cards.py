"""Batch 4 fixups (12-Jul):

1. Re-run the Building Documents -> Document Register migration with
   the generalized child-table discovery (original run found nothing;
   the UI-built child table wasn't named "Building Document").
   Row-level markers keep this idempotent.

2. "New Agreements This Month" counted `creation` - every imported
   record was created this month, so it read 266. Re-point to
   `start_date`.
"""

import json

import frappe

from darkbrown.patches import migrate_building_documents


def execute():
    # 1. re-run doc migration with discovery
    migrate_building_documents.execute()

    # 2. fix the New Agreements card filter
    name = frappe.db.get_value("Number Card",
                               {"label": "New Agreements This Month"},
                               "name")
    if name:
        frappe.db.set_value("Number Card", name, "filters_json",
                            json.dumps([["Tenancy Agreement",
                                         "start_date", "Timespan",
                                         "this month"]]))

    frappe.db.commit()
