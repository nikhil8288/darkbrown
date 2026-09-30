"""Historical receipt view backed by native Journal Entries, not invented cash."""


def rows(frappe, allowed=None):
    if not frappe.get_meta('Journal Entry').has_field('db_migration_kind'):
        return []
    filters = {'db_migration_kind': 'collection', 'docstatus': ['in', [1, 2]]}
    if allowed is not None:
        if not allowed:
            return []
        filters['db_migration_building'] = ['in', sorted(allowed)]
    result = []
    for row in frappe.get_all('Journal Entry', filters=filters,
        fields=['name', 'posting_date', 'total_debit', 'docstatus', 'db_migration_party',
                'db_migration_building', 'db_migration_unit_label', 'db_migration_date_basis'],
        limit_page_length=0, order_by='posting_date desc, name desc'):
        if not row.name.startswith('MIG-RCPT-'):
            continue
        party = frappe.db.get_value('Customer', row.db_migration_party, 'customer_name') or row.db_migration_party
        result.append({'id': row.name, 't': row.db_migration_party, 'tn': party, 'party': party,
            'kind': 'Historical collection', 'amt': float(row.total_debit),
            'when': str(row.posting_date), 'date': str(row.posting_date),
            'mode': 'Unknown — historical record', 'ref': 'Reconstructed', 'chq': '', 'stmt': '',
            'acct': 'Historical collections clearing', 'un': 0,
            'st': 'Cancelled' if row.docstatus == 2 else 'Issued',
            'alloc': 'Cancelled' if row.docstatus == 2 else 'Allocated', 'by': 'Historical reconstruction',
            'b': row.db_migration_building, 'u': row.db_migration_unit_label,
            'reconstructed': True, 'date_basis': row.db_migration_date_basis})
    return result


def detail(frappe, name):
    from darkbrown.permissions import require_building_access
    doc = frappe.get_doc('Journal Entry', name)
    if doc.get('db_migration_kind') != 'collection' or not name.startswith('MIG-RCPT-'):
        raise frappe.DoesNotExistError('Not a reconstructed receipt')
    if not doc.get('db_migration_building'):
        raise frappe.PermissionError('Historical receipt has no verified building scope')
    require_building_access(doc.db_migration_building)
    hit = [r for r in rows(frappe, {doc.db_migration_building}) if r['id'] == name]
    if not hit:
        raise frappe.DoesNotExistError('Historical receipt is not submitted')
    result = hit[0]; applied = []; unallocated = 0
    for line in doc.accounts:
        if line.party_type != 'Customer' or not line.credit_in_account_currency:
            continue
        if line.reference_type == 'Sales Invoice' and line.reference_name:
            inv = frappe.db.get_value('Sales Invoice', line.reference_name, ['grand_total', 'outstanding_amount'], as_dict=True)
            applied.append({'dt': 'Sales Invoice', 'id': line.reference_name,
                'total': float(inv.grand_total), 'alloc': float(line.credit_in_account_currency),
                'left': float(inv.outstanding_amount)})
        else:
            unallocated += float(line.credit_in_account_currency)
    result.update(applied=applied, un=unallocated, inv=', '.join(r['id'] for r in applied),
                  cheque=None, remarks=doc.user_remark or '')
    return result
