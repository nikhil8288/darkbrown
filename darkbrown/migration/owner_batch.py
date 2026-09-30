"""Compile one approved owner-charge allocation and supported paid amounts.

The allocation review maps original charges; it is not appended as a second
expense source. Payable snapshots never create another bill or inferred payment.
"""
import calendar
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from darkbrown.migration.prepare import values, lineage, normalized, period
from darkbrown.migration.plan import money
from darkbrown.migration.evidence import digest


ALIASES = {
    'AIN KHALID-12': 'AK-12', 'DOHA AL JADEEDA-21': 'DAJ-21',
    'MATHAR QADEEM -56': 'MQ-56', 'MANSOURA - 130': 'MR-130',
    'MUAITHER-21': 'MT-21', 'OLD AL GHANIM-48': 'OG-48',
    'THUMAMA-20': 'TV-20', 'THUMAMA-27': 'TV-27',
    'THUMAMA-66': 'TV-66', 'THUMAMA-68': 'TV-68',
    'UMM GUWAILINA-20': 'UG-20', 'UMM GHUWAILINA-169/180': 'UG-169',
    'UMM GHUWAILINA-169 /180': 'UG-169', 'TWAR-10 VILLAS': 'TWR-GROUP',
}


def last_day(month):
    year, number = map(int, month.split('-'))
    return f'{month}-{calendar.monthrange(year, number)[1]:02d}'


def compile_owners(rows, mapping, building_suppliers):
    charges = defaultdict(list); paid_rows = []; exceptions = []; events = []
    controls = defaultdict(Decimal)
    for row in rows:
        filename = Path(row['source_file']).name; v = values(row)
        if filename == 'DarkBrown_Month_Wise_Expenses.xlsx' and row['worksheet'] == 'Building cost records' and v.get('C') == '6':
            if not v.get('F') or not v.get('E'):
                raise ValueError('Owner allocation lacks source/decision provenance')
            charges[(v['A'], v['B'])].append(row)
        elif filename == 'Month Wise Owners Rent till July 2026(1).xlsx' and row['worksheet'] == 'Owners Rent' and v.get('A', '').isdigit():
            paid_rows.append(row)
    bill_keys = {}; bill_amounts = {}
    for (month, code), group in sorted(charges.items()):
        total = sum((money(values(r)['D']) for r in group), Decimal(0))
        if total < 0:
            raise ValueError('Owner credit requires separate review')
        if not total:
            continue
        if code == 'MT-21' and month >= '2026-08':
            raise ValueError('Owner charge after confirmed termination')
        if code not in building_suppliers:
            raise ValueError('Owner allocation has no supplier mapping')
        key = 'owner-rent:' + code + ':' + month
        bill_keys[(month, code)] = key; bill_amounts[(month, code)] = total
        events.append({'key': key, 'kind': 'owner_bill',
            'posting_date': month + '-01', 'due_date': last_day(month), 'service_period': month,
            'party': building_suppliers[code], 'party_account': mapping['payable'],
            'account': mapping['owner_expense'], 'item': 'Landlord Rent',
            'building': code, 'cost_center': mapping['cost_centers'][code],
            'amount': str(total), 'source': [lineage(r) for r in group],
            'description': f'Reconstructed owner rent | {code} | {month}; source schedule overrides simple contract multiplication.',
            'date_basis': 'Approved source reporting period; October opening bucket retains original Aug–Oct period in lineage.',
            'allocation_basis': [values(r) for r in group]})
        controls['owner_bills'] += total
    seen_paid = set()
    for row in paid_rows:
        v = values(row); code = ALIASES.get(normalized(v.get('B')))
        if not code:
            raise ValueError('Unmapped owner property')
        val = v.get('D')
        if val is None:
            exceptions.append({'reason': 'paid_amount_not_supplied', 'source': lineage(row)})
            continue
        amount = money(val)
        controls['source_paid_column'] += amount
        if not amount:
            continue
        if amount < 0:
            raise ValueError('Negative owner payment requires refund review')
        if 'RETURN' in normalized(v.get('G')):
            exceptions.append({'reason': 'returned_payment_requires_settlement_confirmation',
                               'amount': str(amount), 'source': lineage(row), 'building': code})
            controls['held_returned_payments'] += amount
            continue
        month = '2025-10' if v.get('F') == 'Aug to Oct 2025' else period(v.get('F'))
        economic = (month, code)
        if economic in seen_paid:
            raise ValueError('Duplicate owner paid aggregate')
        seen_paid.add(economic)
        if code == 'TWR-GROUP':
            suppliers = {p for b, p in building_suppliers.items() if b.startswith('TWR-')}
            if len(suppliers) != 1:
                raise ValueError('TWR group supplier ambiguity')
            supplier = next(iter(suppliers)); reference = None
            exceptions.append({'reason': 'group_payment_unallocated_to_individual_villa_bills',
                'amount': str(amount), 'source': lineage(row)})
        else:
            supplier = building_suppliers[code]
            reference = bill_keys.get(economic)
        allocated = min(amount, bill_amounts.get(economic, Decimal(0))) if reference else Decimal(0)
        for suffix, part, invoice in [('allocated', allocated, reference), ('unallocated', amount - allocated, None)]:
            if not part:
                continue
            event = {'key': f'owner-paid:{code}:{month}:{suffix}', 'kind': 'supplier_payment',
                'posting_date': last_day(month), 'service_period': month,
                'party': supplier, 'party_account': mapping['payable'],
                'clearing_account': mapping['payments_clearing'], 'amount': str(part),
                'source': [lineage(row)], 'description': f'Source-recorded owner rent paid | {code} | {month} | {suffix}',
                'date_basis': 'Month-end of source period; actual payment date/destination unknown',
                'actual_payment_date': None, 'building': None if code == 'TWR-GROUP' else code}
            if invoice:
                event['invoice_key'] = invoice
            events.append(event); controls['planned_owner_payments'] += part
    return {'events': events, 'exceptions': exceptions,
            'controls': {k: str(v) for k, v in controls.items()},
            'complete_replacement': False,
            'remaining': ['August/September settlements and latest payable reconciliation; never derive payments solely from balances.',
                          'TWR group allocations remain unapplied where no villa-specific payment evidence exists.']}
