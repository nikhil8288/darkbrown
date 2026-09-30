"""Compile source rent/collection evidence into native posting instructions.

Pure transformation: never imports frappe, writes a site, or invents a party.
Unresolved records remain explicit exceptions. Account IDs are supplied by the
site mapping; an advance application is not a new collection.
"""
import calendar
import re
from collections import Counter
from decimal import Decimal
from darkbrown.migration.evidence import digest
from darkbrown.migration.plan import money
from darkbrown.migration.native_import import document_name


def unit_key(value, building=None):
    value = ' '.join((value or '').upper().split())
    # Only standardize the optional separator between a floor prefix and its
    # number. Preserve subdivisions (/1), letters, and leading zeroes.
    value = re.sub(r'^([A-Z]+)-?(\d+)', r'\1-\2', value)
    # User-approved physical-room alias, limited to the TWR buildings.
    if building and building.startswith('TWR-'):
        value = re.sub(r'^F-(?=\d)', 'R-', value)
    return value


def party_key(identity):
    # Keep identically named occupants of different units separate until there
    # is actual identity evidence. Do not merge people using fuzzy name matching.
    name = ' '.join((identity.get('tenant_name') or '').upper().split())
    if not name or not identity.get('building') or not identity.get('unit'):
        return None
    return 'MIG-CUST-' + digest([identity['building'], unit_key(identity['unit'], identity['building']), name])[:24].upper()


def compile_rent(groups, mapping):
    required = {'receivable', 'rent_income', 'collections_clearing',
                'tenant_advances', 'cost_centers', 'company', 'site', 'territory'}
    if required - mapping.keys():
        raise ValueError('Incomplete account/site mapping')
    masters = {}; events = []; exceptions = []; totals = Counter(); seen = set()
    for group in groups:
        if group['aggregation'] != 'none' or len(group['evidence']) != 1:
            raise ValueError('Unresolved source collision')
        source = group['evidence'][0]
        key = source['economic_event_key']
        if key in seen:
            raise ValueError('Duplicate economic event')
        seen.add(key)
        identity = source['identity']; party = party_key(identity)
        period = source['service_period']; rent = source['rent_amount']
        evidence = [source['source']]
        amounts = source['source_amounts']
        # Reconcile supplied amounts independently even when a party is absent.
        for field, val in [('rent', rent), *amounts.items()]:
            if val is not None:
                totals['source_' + field] += money(val)
        if not party or not period or rent is None:
            exceptions.append({'key': key, 'source': evidence, 'identity': identity,
                               'reason': 'missing_party_period_or_rent',
                               'rent_amount': rent, 'amounts': amounts})
            continue
        rent = money(rent)
        received = money(amounts['recorded_received']) if amounts['recorded_received'] is not None else Decimal(0)
        advance = money(amounts['advance_applied']) if amounts['advance_applied'] is not None else Decimal(0)
        previous = -money(amounts['previous_due_received_adjustment']) if amounts['previous_due_received_adjustment'] is not None else Decimal(0)
        # Missing columns remain missing in the retained source. A blank creates
        # no payment event; it is never asserted to be proof of zero collection.
        if min(rent, received, advance, previous) < 0 or received + advance + previous > rent:
            raise ValueError('Source requires credit/overpayment review: ' + key)
        net = amounts.get('net_due')
        if net is not None and money(net) != rent - received - advance - previous:
            raise ValueError('Source receivable arithmetic mismatch: ' + key)
        if identity['building'] == 'MT-21' and period >= '2026-08' and rent:
            raise ValueError('Revenue after confirmed MT-21 termination')
        cc = mapping['cost_centers'].get(identity['building'])
        if not cc:
            raise ValueError('Unmapped building cost center')
        masters.setdefault(party, {'doctype': 'Customer', 'name': party,
            'values': {'customer_name': identity['tenant_name'].strip(),
                       'customer_type': 'Individual', 'customer_group': 'Tenant', 'db_is_tenant': 1,
                       'territory': mapping['territory']}, 'source': evidence})
        if evidence[0] not in masters[party]['source']:
            masters[party]['source'].extend(evidence)
        year, month = map(int, period.split('-'))
        month_end = f'{period}-{calendar.monthrange(year, month)[1]:02d}'
        desc = f"Historical rent | {identity['building']} | {identity['unit']} | {period}"
        base = {'source': evidence, 'description': desc, 'building': identity['building'],
                'unit': unit_key(identity['unit'], identity['building']), 'service_period': period,
                'party': party, 'party_account': mapping['receivable'],
                'cost_center': cc}
        if rent:
            invoice_key = key + ':invoice'
            events.append({**base, 'key': invoice_key, 'kind': 'rent_invoice',
                'posting_date': period + '-01', 'due_date': month_end,
                'date_basis': 'First day of supported rent service month; reconstructed billing',
                'amount': str(rent), 'account': mapping['rent_income'], 'item': 'Rent'})
            totals['planned_rent'] += rent
        else:
            continue
        for suffix, value, posting, date_basis in [
            ('received', received, month_end, 'Month-end of source rent period; actual receipt date unknown'),
            ('previous_due_received', previous, '2026-09-30', 'Pre-live cutover convention; later collection date unknown'),
        ]:
            if value:
                events.append({**base, 'key': key + ':' + suffix, 'kind': 'collection',
                    'posting_date': posting, 'date_basis': date_basis,
                    'description': desc + ' | ' + suffix + ' | receiving account unknown',
                    'amount': str(value), 'invoice_key': invoice_key,
                    'actual_receipt_date': None, 'payment_method': None,
                    'clearing_account': mapping['collections_clearing']})
                totals['planned_' + suffix] += value
        if advance:
            events.append({**base, 'key': key + ':advance_application', 'kind': 'journal',
                'posting_date': month_end,
                'date_basis': 'Month-end application of source-recorded tenant advance',
                'description': desc + ' | advance applied, not a new cash receipt',
                'lines': [
                    {'account': mapping['tenant_advances'], 'debit': str(advance), 'cost_center': cc},
                    {'account': mapping['receivable'], 'party_type': 'Customer', 'party': party,
                     'credit': str(advance), 'reference_type': 'Sales Invoice',
                     'reference_name': document_name('rent_invoice', invoice_key), 'cost_center': cc},
                ]})
            totals['planned_advance_application'] += advance
    # Receipts must follow all invoices, and applications must follow receipts.
    events.sort(key=lambda e: ({'rent_invoice': 0, 'collection': 1, 'journal': 2}[e['kind']], e['posting_date'], e['key']))
    totals['planned_rent_due'] = totals['planned_rent'] - totals['planned_received'] - totals['planned_previous_due_received'] - totals['planned_advance_application']
    result = {'schema_version': 1, 'site': mapping['site'], 'company': mapping['company'],
              'masters': sorted(masters.values(), key=lambda x: x['name']), 'events': events,
              'exceptions': exceptions, 'controls': {k: str(v) for k, v in totals.items()},
              'provisional_items': ['Tenant advance funding/opening balance remains unreconciled; do not invent a second cash receipt.',
                  'Customer type is an administrative default; entity classification requires source review.',
                  'Historical party identity is scoped to source building/unit/name; no fuzzy identity merges.'],
              'scope': 'rent_and_supported_collections_only', 'complete_replacement': False}
    result['batch_checksum'] = digest(result)
    return result
