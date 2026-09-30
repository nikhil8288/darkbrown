"""Reconcile native posted ledgers against source events, never seed reports."""
from collections import defaultdict
from decimal import Decimal
from darkbrown.migration.native_import import document_name
from darkbrown.migration.plan import money


def expected_accounts(batch):
    result = defaultdict(Decimal)
    for event in batch['events']:
        kind = event['kind']
        if kind == 'journal':
            for row in event['lines']:
                result[row['account']] += money(row.get('debit', 0)) - money(row.get('credit', 0))
            continue
        amount = money(event['amount'])
        if kind == 'rent_invoice':
            debit, credit = event['party_account'], event['account']
        elif kind == 'owner_bill':
            debit, credit = event['account'], event['party_account']
        elif kind == 'collection':
            debit, credit = event['clearing_account'], event['party_account']
        elif kind == 'supplier_payment':
            debit, credit = event['party_account'], event['clearing_account']
        else:
            raise ValueError('Unsupported event')
        result[debit] += amount; result[credit] -= amount
    return dict(result)


def verify(frappe, batch):
    names = [document_name(e['kind'], e['key']) for e in batch['events']]
    expected = expected_accounts(batch)
    actual = defaultdict(Decimal); vouchers = defaultdict(lambda: [Decimal(0), Decimal(0)])
    count = 0
    for start in range(0, len(names), 300):
        rows = frappe.get_all('GL Entry', filters={'company': batch['company'],
            'voucher_no': ['in', names[start:start + 300]], 'is_cancelled': 0},
            fields=['voucher_no', 'account', 'debit', 'credit'], limit_page_length=0)
        count += len(rows)
        for row in rows:
            debit, credit = money(row.debit), money(row.credit)
            actual[row.account] += debit - credit
            vouchers[row.voucher_no][0] += debit
            vouchers[row.voucher_no][1] += credit
    for event in batch['events']:
        name = document_name(event['kind'], event['key'])
        expected_debit = (sum((money(r.get('debit', 0)) for r in event['lines']), Decimal(0))
                          if event['kind'] == 'journal' else money(event['amount']))
        if vouchers[name] != [expected_debit, expected_debit]:
            raise ValueError('Native voucher ledger differs from source event')
    if {k: v for k, v in actual.items() if v} != {k: v for k, v in expected.items() if v}:
        raise ValueError('Account balances differ from source-event reconstruction')
    if frappe.db.count('GL Entry', {'company': batch['company'], 'is_cancelled': 0}) != count:
        raise ValueError('Unexpected company ledger entries remain outside this replacement batch')
    tenant_invoices = [document_name(e['kind'], e['key']) for e in batch['events'] if e['kind'] == 'rent_invoice']
    outstanding = Decimal(0)
    for start in range(0, len(tenant_invoices), 300):
        rows = frappe.get_all('Sales Invoice', filters={'name': ['in', tenant_invoices[start:start + 300]],
            'company': batch['company'], 'docstatus': 1}, fields=['name', 'outstanding_amount'], limit_page_length=0)
        if len(rows) != len(tenant_invoices[start:start + 300]):
            raise ValueError('A tenant invoice is missing or unsubmitted')
        outstanding += sum((money(r.outstanding_amount) for r in rows), Decimal(0))
    if outstanding != money(batch['controls']['rent']['planned_rent_due']):
        raise ValueError('Native invoice outstanding differs from supported source receivables')
    return {'balanced': True, 'ledger_rows': count, 'vouchers': len(names),
            'receivable_outstanding': str(outstanding),
            'account_balances': {k: str(v) for k, v in sorted(actual.items())},
            'does_not_resolve': ['unmatched bank movements', 'opening assets and capital',
                                 'unapplied owner payments', 'held source exceptions', 'contract activation']}
