"""Source-backed operational masters; missing legal evidence stays explicit."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path

from darkbrown.migration.evidence import digest
from darkbrown.migration.prepare import values, lineage, building, normalized
from darkbrown.migration.rent_batch import party_key, unit_key


OWNER_MASTER = 'DarkBrown_Owner_Agreements_Building_Level_v2(2).xlsx'
TENANT_MASTER = 'DarkBrown_Tenancy_Master_300_v28(1).xlsx'


def source_date(value):
    if not value:
        return None
    try:
        result = date(1899, 12, 30) + timedelta(days=int(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return result.isoformat() if date(2000, 1, 1) <= result <= date(2100, 1, 1) else None


def compile_masters(rows, rent_groups, mapping):
    owners = []; tenants = []
    for row in rows:
        file = Path(row['source_file']).name
        if file == OWNER_MASTER and row['worksheet'] == 'Owner Agreement Master' and row['row'] > 1:
            owners.append(row)
        if file == TENANT_MASTER and row['worksheet'] == 'Tenancy Master' and row['row'] > 1:
            tenants.append(row)
    masters = []; suppliers = {}; buildings = {}; units = {}; customers = {}; agreements = []; exceptions = []
    for row in owners:
        v = values(row); code = building(v.get('B'))
        correction = None
        if code == 'TWR-16' and v.get('C') == '39' and v.get('AQ') == 'AGREEMENT, 35,39.pdf':
            code = 'TWR-39'
            correction = 'Approved TWR-39 identity: building number 39 and 35/39 agreement; source code/name mislabeled TWR-16.'
        if not code or not v.get('I'):
            raise ValueError('Missing owner/building identity')
        if code in buildings:
            raise ValueError('Unresolved duplicate building')
        supplier = 'MIG-OWNER-' + digest(normalized(v['I']))[:24].upper()
        suppliers.setdefault(supplier, {'doctype': 'Supplier', 'name': supplier,
            'values': {'supplier_name': v['I'].strip(), 'supplier_group': mapping['supplier_group'],
                       'supplier_type': 'Company', 'db_is_landlord': 1}, 'source': [lineage(row)]})
        notes = {'source': lineage(row), 'original_name': v.get('A'), 'mapping_correction': correction,
                 'contract_terms': v, 'reconstructed': True, 'signed_evidence_pending': True}
        bvalues = {'building_name': code, 'landlord': supplier, 'company': mapping['company'],
                   'status': 'Exited' if code == 'MT-21' else 'Active',
                   'cost_center': mapping['cost_centers'][code], 'building_no': v.get('C'),
                   'area_name': v.get('D'), 'zone_no': v.get('E'), 'street_no': v.get('F'),
                   'notes': '<p>Reconstructed from owner master. Signed evidence remains pending where not supplied.</p>'}
        if code == 'MT-21':
            bvalues['exit_date'] = '2026-07-31'
        buildings[code] = {'doctype': 'Building', 'name': code, 'values': bvalues,
                           'source': [lineage(row)], 'migration_evidence': notes}
        start, end = source_date(v.get('Q')), source_date(v.get('R'))
        if code == 'MT-21':
            end = '2026-07-31'
        if not start or not end or start >= end or not v.get('V'):
            exceptions.append({'doctype': 'Head Lease', 'building': code, 'reason': 'unresolved_dates_or_rent', 'source': lineage(row)})
        else:
            agreements.append({'doctype': 'Head Lease', 'name': 'MIG-HL-' + code,
                'values': {'naming_series': 'HL-.YYYY.-.####', 'building': code, 'landlord': supplier,
                    'company': mapping['company'], 'status': 'Draft', 'start_date': start, 'end_date': end,
                    'annual_rent': str(Decimal(v['V'])),
                    'payment_frequency': 'Quarterly' if code == 'TV-20' else 'Monthly',
                    'notes': '<p>Reconstructed terms; activate only after migration evidence approval.</p><p>' + escape(v.get('T') or '') + '</p>'},
                'source': [lineage(row)], 'migration_evidence': notes,
                'activation_pending': True})
    def unit_record(code, number, row_source):
        number = unit_key(number, code)
        if code not in buildings or not number:
            raise ValueError('Unit lacks verified building/number')
        name = code + '-' + number
        record = units.setdefault(name, {'doctype': 'Unit', 'name': name,
            'values': {'building': code, 'unit_no': number, 'status': 'Not Ready'},
            'source': [row_source]})
        if row_source not in record['source']:
            record['source'].append(row_source)
        return name
    for group in rent_groups:
        for r in group['evidence']:
            identity = r['identity']
            unit_record(identity['building'], identity['unit'], r['source'])
    for row in tenants:
        v = values(row); code = building(v.get('B')); number = normalized(v.get('C'))
        if code == 'TWR-16' and v.get('S') == '39':
            # Same approved correction as the owner master: retain TWR-39 as
            # a separate building, using the physical building number.
            code = 'TWR-39'
        if not code or not number or not v.get('D'):
            exceptions.append({'doctype': 'Tenancy Agreement', 'reason': 'incomplete_identity', 'source': lineage(row)})
            continue
        unit = unit_record(code, number, lineage(row))
        ident = {'building': code, 'unit': number, 'tenant_name': v['D']}
        customer = party_key(ident)
        customers.setdefault(customer, {'doctype': 'Customer', 'name': customer,
            'values': {'customer_name': v['D'].strip(), 'customer_type': 'Individual',
                       'customer_group': 'Tenant', 'territory': mapping['territory'], 'db_is_tenant': 1},
            'source': [lineage(row)]})
        start, end = source_date(v.get('K')), source_date(v.get('L'))
        mode_text = (v.get('O') or '').lower()
        mode = 'Cheque' if 'cheque' in mode_text else 'Cash' if 'cash' in mode_text else 'Transfer' if 'transfer' in mode_text else None
        if not start or not end or start >= end or not mode or not v.get('N') or not v.get('I'):
            exceptions.append({'doctype': 'Tenancy Agreement', 'unit': unit,
                'reason': 'unresolved_date_mode_rent_or_contract_reference', 'source': lineage(row),
                'source_values': v})
            continue
        key = digest([code, unit_key(number, code), normalized(v['D']), v['I'], start, end])[:24].upper()
        agreements.append({'doctype': 'Tenancy Agreement', 'name': 'MIG-TA-' + key,
            'values': {'naming_series': 'TA-.YYYY.-.####', 'tenant': customer, 'unit': unit,
                'building': code, 'company': mapping['company'], 'status': 'Draft',
                'start_date': start, 'end_date': end, 'monthly_rent': str(Decimal(v['N'])),
                'payment_mode': mode, 'payment_frequency': 'Monthly',
                'qid_number': v.get('E'), 'mobile_no': v.get('G'),
                'notes': '<p>Source contract ' + escape(v['I']) + '; signed document pending where not supplied.</p>'},
            'source': [lineage(row)], 'migration_evidence': {'source_values': v},
            'activation_pending': True})
    masters.extend(sorted(suppliers.values(), key=lambda x: x['name']))
    masters.extend(sorted(customers.values(), key=lambda x: x['name']))
    masters.extend(sorted(buildings.values(), key=lambda x: x['name']))
    masters.extend(sorted(units.values(), key=lambda x: x['name']))
    masters.extend(sorted(agreements, key=lambda x: (x['doctype'], x['name'])))
    return {'masters': masters, 'exceptions': exceptions,
            'building_suppliers': {code: r['values']['landlord'] for code, r in buildings.items()},
            'complete_replacement': False}
