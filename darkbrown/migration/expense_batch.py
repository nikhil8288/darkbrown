"""Reconstruct aggregate expense facts with explicit unresolved counterparts.

Amounts come from individual source category/period cells, with narrowly listed
accountant corrections. No report total is a posting input. Owner rent is
excluded here because it is posted through Purchase Invoices.
"""
import re
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from darkbrown.migration.prepare import values, lineage, period, columns
from darkbrown.migration.plan import money
from darkbrown.migration.owner_batch import last_day


ACCOUNT_ALIASES = {
    'Building Maintanance': 'Building Maintenance',
    'Electricity office': 'Electricity Office',
    'KEYMONEY PROPERTIES': 'Key Money', 'KEYMONEY OTHER PROPERTIES': 'Key Money - Other',
    'Repairs & Maintanance': 'Repairs & Maintenance',
    'Repairs & Maintanance Equipments': 'Repairs & Maintenance Equipment',
    'Repairs & Maintanance Vehicle': 'Repairs & Maintenance Vehicle',
    'Sponsor fees': 'Sponsor Fees',
}


def allocate(amount, weights):
    total = sum(weights.values(), Decimal(0))
    if total <= 0 or any(v < 0 for v in weights.values()):
        raise ValueError('Invalid approved allocation weights')
    exact = {k: amount * v / total for k, v in weights.items()}
    result = {k: v.quantize(Decimal('.01'), rounding=ROUND_DOWN) for k, v in exact.items()}
    cents = int((amount - sum(result.values(), Decimal(0))) * 100)
    order = sorted(exact, key=lambda k: (-(exact[k] - result[k]), k))
    for key in order[:cents]: result[key] += Decimal('.01')
    if sum(result.values(), Decimal(0)) != amount:
        raise ValueError('Allocation lost money')
    return result


def approved_amount(source_row, month, original, proposed, corrections):
    if original == proposed:
        return True
    decision = corrections.get(str(source_row) + ':' + month)
    if not decision or not decision.get('approval_reference'):
        return False
    expected = money(decision['original']) if decision['original'] is not None else None
    return original == expected and proposed == money(decision['approved'])


def compile_expenses(rows, mapping):
    original = {}; detail = []; direct = defaultdict(list); weights = {}; weight_sources = []
    for row in rows:
        name = Path(row['source_file']).name; v = values(row)
        if name == 'Monthwise  P& L Till July August September 2026.xlsx' and row['worksheet'] == 'PL 30092026':
            original[row['row']] = row
        elif name == 'DarkBrown_Month_Wise_Expenses.xlsx':
            if row['worksheet'] == 'Expense detail' and row['row'] > 6:
                detail.append(row)
            elif row['worksheet'] == 'Building cost records' and v.get('C', '').isdigit():
                direct[(v['A'], int(v['C']))].append(row)
            elif row['worksheet'] == 'Allocation basis' and set(v) == {'A', 'B'} and v['A'] in mapping['cost_centers']:
                weight = Decimal(v['B'])
                if not 0 <= weight <= 1:
                    continue
                if v['A'] in weights:
                    raise ValueError('Duplicate approved allocation weight')
                weights[v['A']] = weight; weight_sources.append(lineage(row))
    if (set(weights) != set(mapping['cost_centers']).intersection(weights) or not weights
            or abs(sum(weights.values(), Decimal(0)) - Decimal(1)) > Decimal('0.000000001')):
        raise ValueError('Unresolved building weights')
    events = []; exceptions = []; total = Decimal(0); seen = set(); categories = defaultdict(Decimal)
    for row in detail:
        v = values(row)
        if not v.get('E'):
            continue
        match = re.fullmatch(r'PL 30092026!([A-Z]+)(\d+)', v.get('G', ''))
        if not match:
            raise ValueError('Unresolved expense source cell')
        col, number = match[1], int(match[2])
        if number == 6:  # posted once as owner bills
            continue
        month = '2025-10' if v['A'] == 'Oct 2025*' else period(v['A'])
        amount = money(v['E'])
        if amount < 0:
            raise ValueError('Expense credit requires review')
        if amount == 0:
            continue
        raw = original.get(number)
        if not raw:
            raise ValueError('Missing original expense row')
        cell = columns(raw).get(col)
        if cell and cell['type'] == 'e':
            raise ValueError('Formula error is not a financial input')
        raw_amount = money(cell['value']) if cell and cell.get('value') is not None else None
        if not approved_amount(number, month, raw_amount, amount, mapping.get('expense_corrections', {})):
            raise ValueError('Unapproved change from original expense cell')
        key = f'aggregate-expense:{number}:{month}'
        if key in seen:
            raise ValueError('Duplicate category/period expense')
        seen.add(key)
        label = v['D'].strip(); label = ACCOUNT_ALIASES.get(label, label)
        account = mapping['expense_accounts'].get(label)
        if not account:
            raise ValueError('Unmapped expense account: ' + label)
        allocated = defaultdict(Decimal); sources = [lineage(raw), lineage(row)]
        for item in direct.get((month, number), []):
            d = values(item)
            allocated[d['B']] += money(d['D']); sources.append(lineage(item))
        residual = amount - sum(allocated.values(), Decimal(0))
        if residual < 0:
            raise ValueError('Direct allocation exceeds source expense')
        if residual:
            for code, value in allocate(residual, weights).items(): allocated[code] += value
            sources.extend(weight_sources)
        if number == 21:
            counterpart = mapping['accumulated_depreciation']; meaning = 'approved depreciation; gross asset register pending'
        else:
            group = 'preoperative' if number == 22 else 'key_money' if number in (12, 13) else 'payroll' if 23 <= number <= 29 else 'operating'
            counterpart = mapping['expense_counterparts'][group]
            meaning = 'unresolved historical ' + group + ' funding/payable counterpart; not evidence of payment'
            exceptions.append({'key': key, 'reason': meaning, 'amount': str(amount), 'source': sources[:2]})
        lines = [{'account': account, 'debit': str(value), 'cost_center': mapping['cost_centers'][code]}
                 for code, value in sorted(allocated.items()) if value]
        lines.append({'account': counterpart, 'credit': str(amount)})
        events.append({'key': key, 'kind': 'journal', 'posting_date': last_day(month),
            'description': f"Reconstructed aggregate expense | {v['C']} | {month} | {meaning}",
            'source': sources, 'date_basis': 'Source financial period with approved timing corrections; not management reallocation timing',
            'lines': lines, 'source_category': number, 'source_description': v['C'],
            'original_source_amount': str(raw_amount) if raw_amount is not None else None,
            'approved_amount': str(amount), 'counterpart_status': 'pending_reconciliation' if number != 21 else 'asset_register_pending'})
        total += amount; categories[str(number)] += amount
    return {'events': events, 'exceptions': exceptions, 'non_owner_expenses': str(total),
            'category_totals': {k: str(v) for k, v in categories.items()},
            'complete_replacement': False,
            'warning': 'Provisional counterpart accounts do not establish that expenses were paid or that supplier/payroll balances are reconciled.'}
