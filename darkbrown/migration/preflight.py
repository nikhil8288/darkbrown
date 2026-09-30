"""Read-only native batch preflight; never creates accounts or posts documents."""
from darkbrown.migration.native_import import validate_batch
from darkbrown.migration.metadata import FIELD_DEFINITIONS


def inspect(frappe, batch):
    validate_batch(batch)
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    if str(frappe.local.site) != batch['site']:
        raise ValueError('Wrong target site')
    if frappe.db.get_value('Company', batch['company'], 'default_currency') != 'QAR':
        raise ValueError('Wrong company currency')
    issues = []; requirements = {}; cost_centers = set(); items = set()
    master_ids = {(m['doctype'], m['name']) for m in batch['masters']}

    def require(name, kind=None, root=None, clearing=False):
        if not name:
            raise ValueError('Missing account identity')
        value = (kind, root, clearing)
        previous = requirements.get(name)
        if previous and previous != value and value != (None, None, False):
            if previous != (None, None, False):
                raise ValueError('Conflicting account requirements')
        if name not in requirements or value != (None, None, False):
            requirements[name] = value

    for event in batch['events']:
        kind = event['kind']
        if event.get('cost_center'):
            cost_centers.add(event['cost_center'])
        if kind in {'rent_invoice', 'owner_bill'}:
            selling = kind == 'rent_invoice'
            require(event['party_account'], 'Receivable' if selling else 'Payable')
            require(event['account'], root='Income' if selling else 'Expense')
            items.add(event['item'])
        elif kind in {'collection', 'supplier_payment'}:
            collecting = kind == 'collection'
            require(event['party_account'], 'Receivable' if collecting else 'Payable')
            require(event['clearing_account'], root='Asset' if collecting else 'Liability', clearing=True)
        else:
            for line in event['lines']:
                require(line['account'])
                if line.get('cost_center'):
                    cost_centers.add(line['cost_center'])
    for name, (kind, root, clearing) in sorted(requirements.items()):
        row = frappe.db.get_value('Account', name,
            ['company', 'is_group', 'disabled', 'account_type', 'root_type', 'account_currency'], as_dict=True)
        if not row:
            issues.append({'kind': 'missing_account', 'name': name}); continue
        if (row.company != batch['company'] or row.is_group or row.disabled
                or row.account_currency not in (None, '', 'QAR')
                or kind and row.account_type != kind or root and row.root_type != root
                or clearing and row.account_type in ('Bank', 'Cash', 'Receivable', 'Payable')):
            issues.append({'kind': 'invalid_account', 'name': name})
    for name in sorted(cost_centers):
        row = frappe.db.get_value('Cost Center', name, ['company', 'is_group', 'disabled'], as_dict=True)
        if not row or row.company != batch['company'] or row.is_group or row.disabled:
            issues.append({'kind': 'invalid_cost_center', 'name': name})
    for name in sorted(items):
        if not frappe.db.exists('Item', {'name': name, 'disabled': 0, 'is_stock_item': 0}):
            issues.append({'kind': 'missing_or_unsuitable_item', 'name': name})
    for doctype in ('Sales Invoice', 'Purchase Invoice', 'Journal Entry'):
        meta = frappe.get_meta(doctype)
        for field, _, _, _ in FIELD_DEFINITIONS:
            if not meta.has_field(field):
                issues.append({'kind': 'missing_metadata', 'doctype': doctype, 'field': field})
    for master in batch['masters']:
        meta = frappe.get_meta(master['doctype'])
        for field in master['values']:
            if not meta.has_field(field):
                issues.append({'kind': 'missing_master_field', 'doctype': master['doctype'], 'field': field})
        for field in meta.fields:
            value = master['values'].get(field.fieldname)
            if field.fieldtype == 'Link' and value and (field.options, value) not in master_ids:
                if not frappe.db.exists(field.options, value):
                    issues.append({'kind': 'missing_master_link', 'doctype': master['doctype'],
                                   'name': master['name'], 'field': field.fieldname})
    return {'schema_version': 1, 'site': batch['site'], 'company': batch['company'],
            'batch_checksum': batch['batch_checksum'], 'passed': not issues,
            'issues': issues, 'accounts_checked': len(requirements),
            'cost_centers_checked': len(cost_centers), 'writes_performed': False,
            'does_not_verify': ['document_submission', 'cleanup', 'restore', 'contract_activation']}
