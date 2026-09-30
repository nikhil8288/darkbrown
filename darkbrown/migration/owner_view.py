"""Expose historical landlord bills without fabricating an old agreement."""


def context(frappe, invoice):
    if invoice.get('db_migration_kind') != 'owner_bill' or not invoice.name.startswith('MIG-BILL-'):
        return None
    code = invoice.get('db_migration_building')
    if not code:
        return None
    building = frappe.db.get_value('Building', code, ['company', 'landlord'], as_dict=True)
    if not building or building.company != invoice.company or building.landlord != invoice.supplier:
        raise frappe.ValidationError('Historical landlord bill does not match its source building and supplier')
    return frappe._dict(name=None, building=code, company=invoice.company, landlord=invoice.supplier)


def rows(frappe, allowed=None):
    if not frappe.get_meta('Purchase Invoice').has_field('db_migration_kind'):
        return []
    filters = {'docstatus': 1, 'db_migration_kind': 'owner_bill', 'outstanding_amount': ['>', 0]}
    if allowed is not None:
        if not allowed:
            return []
        filters['db_migration_building'] = ['in', sorted(allowed)]
    result = []
    for invoice in frappe.get_all('Purchase Invoice', filters=filters,
        fields=['name', 'company', 'supplier', 'db_migration_kind', 'db_migration_building',
                'outstanding_amount', 'due_date'], limit_page_length=0):
        source = context(frappe, invoice)
        if not source:
            continue
        result.append({'invoice': invoice.name, 'head_lease': '', 'building': source.building,
            'building_name': frappe.db.get_value('Building', source.building, 'building_name') or source.building,
            'landlord': source.landlord,
            'landlord_name': frappe.db.get_value('Supplier', source.landlord, 'supplier_name') or source.landlord,
            'amount': round(float(invoice.outstanding_amount), 2), 'status': 'Outstanding',
            'due_date': str(invoice.due_date or ''), 'reconstructed': True})
    return result
