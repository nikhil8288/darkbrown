"""Move existing rows onto the renamed document types.

A Select option renamed in the JSON without the data moving with it leaves
every row that held the old value showing something the field no longer
offers: it reads back blank on the form, it disappears from a filter on the
new value, and the first save of that record silently rewrites it.

So the rename is two things and this is the second one. It is idempotent -
run twice, the second pass finds nothing - and it touches no ledger: a
Document Register row is a filing record, not a posting.

    Head Lease        -> Building Agreement
    Tenancy Agreement -> Tenant Agreement

Cheque Batch is deliberately NOT retired. The intake pipeline is keyed on it
(`_push_cheques`, and the missing-date guard in doc_intake_phase2), so it stays
in the stored vocabulary. It is hidden from the manual filing form instead -
see documents.FORM_HIDDEN.
"""

import frappe

RENAMES = {
    "Head Lease": "Building Agreement",
    "Tenancy Agreement": "Tenant Agreement",
}


def execute():
    for doctype in ("Document Register", "Document Archive"):
        if not frappe.db.exists("DocType", doctype):
            continue
        meta = frappe.get_meta(doctype)
        field = meta.get_field("document_type")
        if not field:
            continue
        offered = {o for o in (field.options or "").split("\n") if o}
        for old, new in RENAMES.items():
            if new not in offered:
                # The JSON for this doctype does not carry the new value, so
                # writing it would put the row outside its own Select. The
                # archive only renamed one of the two on purpose.
                continue
            rows = frappe.get_all(doctype, filters={"document_type": old},
                                  pluck="name")
            for name in rows:
                frappe.db.set_value(doctype, name, "document_type", new,
                                    update_modified=False)
            if rows:
                print("  %s: %d rows %s -> %s" % (doctype, len(rows), old, new))
    frappe.db.commit()
