"""Persist reconstruction identity without inventing an agreement or bank."""
from contextlib import contextmanager


FIELD_DEFINITIONS = [
    ('db_migration_event', 'Migration event', 'Data', None),
    ('db_migration_kind', 'Reconstruction kind', 'Data', None),
    ('db_migration_building', 'Source building', 'Link', 'Building'),
    ('db_migration_unit_label', 'Source unit label', 'Data', None),
    ('db_migration_party_type', 'Source party type', 'Link', 'DocType'),
    ('db_migration_party', 'Source party', 'Dynamic Link', 'db_migration_party_type'),
    ('db_migration_date_basis', 'Historical posting date basis', 'Small Text', None),
]


def ensure_fields():
    """Schema only; never create or submit a financial document."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    fields = {dt: [dict(fieldname=name, label=label, fieldtype=kind,
                       options=options, read_only=1, no_copy=1, hidden=0)
                   for name, label, kind, options in FIELD_DEFINITIONS]
              for dt in ('Sales Invoice', 'Purchase Invoice', 'Journal Entry')}
    create_custom_fields(fields, update=True)


@contextmanager
def posting_scope(frappe, event, doctype, name):
    previous = frappe.flags.get('darkbrown_migration_document')
    frappe.flags.darkbrown_migration_document = (doctype, name, event['key'])
    try:
        yield
    finally:
        frappe.flags.darkbrown_migration_document = previous


def validate_metadata(doc, method=None):
    import frappe
    fields = [x[0] for x in FIELD_DEFINITIONS]
    before = doc.get_doc_before_save()
    if not any(doc.get(k) for k in fields) and not (before and any(before.get(k) for k in fields)):
        return
    if before and all(before.get(k) == doc.get(k) for k in fields):
        return
    expected = (doc.doctype, doc.name, doc.get('db_migration_event'))
    if frappe.session.user != 'Administrator' or frappe.flags.get('darkbrown_migration_document') != expected:
        raise frappe.PermissionError('Reconstruction metadata can only be set by the approved migration importer')


def values_for(frappe, doctype, event):
    if not frappe.get_meta(doctype).has_field('db_migration_event'):
        raise ValueError('Migration metadata schema is not installed')
    party_type = 'Supplier' if event['kind'] in ('owner_bill', 'supplier_payment') else 'Customer'
    return {'db_migration_event': event['key'], 'db_migration_kind': event['kind'],
            'db_migration_building': event.get('building'),
            'db_migration_unit_label': event.get('unit'),
            'db_migration_party_type': party_type if event.get('party') else None,
            'db_migration_party': event.get('party'),
            'db_migration_date_basis': event.get('date_basis', 'Source date')}
