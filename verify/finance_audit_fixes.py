"""Synthetic source/stub regression for 2026-09-24 finance findings.

Run with: python verify/finance_audit_fixes.py
Real Frappe posting, transaction locks, and browser behavior need post-deploy checks.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import stub_frappe as S
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from darkbrown.api import finance, expenses, accounting
from darkbrown.darkbrown.doctype.expense_entry.expense_entry import ExpenseEntry
from darkbrown.utils import allocation


def setup(scoped=False):
    S.CALLS.clear()
    S.DB.clear()
    S.SESSION.update(user='acc@example.invalid', roles=['Accounts'])
    S.frappe.session.user = S.SESSION['user']
    S.DB.update({
        'DBR Settings': [{'default_company': 'SYN',
                          'default_bank_account': 'Bank Ref'}],
        'Company': [{'name': 'SYN'}],
        'Bank Account': [{'name': 'Bank Ref', 'account': 'Bank - SYN'}],
        'Account': [
            {'name': 'Bank - SYN', 'account_name': 'Bank', 'company': 'SYN',
             'root_type': 'Asset', 'account_type': 'Bank', 'is_group': 0,
             'disabled': 0},
            {'name': 'Cash - SYN', 'account_name': 'Cash', 'company': 'SYN',
             'root_type': 'Asset', 'account_type': 'Cash', 'is_group': 0,
             'disabled': 0},
            {'name': 'Petty Cash - SYN', 'account_name': 'Petty Cash',
             'company': 'SYN', 'root_type': 'Asset', 'account_type': 'Cash',
             'is_group': 0, 'disabled': 0},
            {'name': 'Historical Cutover Control - SYN',
             'account_name': 'Historical Cutover Control', 'company': 'SYN',
             'root_type': 'Asset', 'account_type': 'Cash', 'is_group': 0,
             'disabled': 0},
            {'name': 'Office Rent - SYN', 'account_name': 'Office Rent',
             'company': 'SYN', 'root_type': 'Expense', 'is_group': 0}],
        'Customer': [{'name': 'TEN-A', 'customer_name': 'Synthetic tenant A'},
                     {'name': 'TEN-B', 'customer_name': 'Synthetic tenant B'}],
        'Payment Entry': [], 'Sales Invoice': [], 'Cheque': [],
        'User Permission': ([{'user': S.SESSION['user'], 'allow': 'Building',
                             'for_value': 'A'}] if scoped else []),
        'Tenancy Agreement': [{'name': 'TA-A', 'tenant': 'TEN-A', 'building': 'A'},
                              {'name': 'TA-B', 'tenant': 'TEN-B', 'building': 'B'}],
    })


def receipt(name, state, amount, party='TEN-A', mode='Cash', reference='SYN-R1'):
    return {'name': name, 'payment_type': 'Receive', 'party': party,
            'posting_date': '2026-09-24', 'paid_amount': amount,
            'mode_of_payment': mode, 'reference_no': reference,
            'paid_to': 'Cash - SYN', 'docstatus': state,
            'unallocated_amount': amount, 'owner': 'Administrator',
            'references': [], 'remarks': ''}


def test_states_and_totals():
    setup()
    S.DB['Payment Entry'] = [receipt('SUB', 1, 30.55),
                             receipt('DRAFT', 0, 30.55),
                             receipt('CANCELLED', 2, 30.55)]
    result = finance.receipts()
    assert result['value'] == result['unallocated'] == 30.55, result
    assert result['counts'] == {'issued': 1, 'draft': 1, 'cancelled': 1,
                                 'cash': 1, 'cheque': 0}, result
    assert {r['id']: r['st'] for r in result['rows']} == {
        'SUB': 'Issued', 'DRAFT': 'Draft', 'CANCELLED': 'Cancelled'}
    assert finance.receipt('DRAFT')['st'] == 'Draft'


def test_caps_and_scope():
    setup(scoped=True)
    S.DB['Payment Entry'] = [receipt(f'R{i:03}', 1, 1, reference=f'R{i:03}')
                             for i in range(301)] + [
        receipt('OTHER', 1, 9999, party='TEN-B')]
    result = finance.receipts()
    assert result['counts']['issued'] == 301, result
    assert result['value'] == 301 and result['total'] == 301, result
    assert result['capped'] and len(result['rows']) == 300
    assert 'OTHER' not in {r['id'] for r in result['rows']}
    result = finance.receipts(limit=5)
    assert result['value'] == 301 and len(result['rows']) == 5
    assert finance.receipts(q='R300')['value'] == 1


def test_cash_and_duplicate():
    setup()
    pe, _, _ = finance._receipt('TEN-A', 30.55, '2026-09-24',
                                mode='Cash', reference='SYN-R2')
    stored = next(c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry'))
    assert pe and stored['paid_to'] == 'Cash - SYN', stored
    setup()
    finance._receipt('TEN-A', 30.55, '2026-09-24', 'Bank Ref',
                     mode='Cash', reference='SYN-BATCH')
    stored = next(c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry'))
    assert stored['paid_to'] == 'Bank - SYN', stored
    setup()
    S.DB['Payment Entry'] = [receipt('EXISTING', 1, 30.55)]
    payload = {'tenant': 'TEN-A', 'amount': 30.55, 'on': '2026-09-24',
               'reference': 'SYN-R1', 'mode': 'Cash'}
    try:
        finance.record_receipt(payload)
    except S.ValidationError as exc:
        assert 'already has a submitted receipt' in str(exc), exc
    else:
        raise AssertionError('duplicate was posted')
    assert not any(c[:2] == ('insert', 'Payment Entry') for c in S.CALLS)
    S.DB['Payment Entry'][0]['docstatus'] = 2
    result = finance.record_receipt(payload)
    assert result['payment_entry']
    recorded = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')][-1]
    assert recorded['paid_to'] == 'Cash - SYN'
    assert recorded['remarks'] == 'Cash collected by acc@example.invalid.'
    assert result['allocated'] == result['on_account'] == 30.55
    for changed in ({**payload, 'reference': ''},
                    {**payload, 'mode': 'Cheque'}):
        try:
            finance.record_receipt(changed)
        except S.ValidationError:
            pass
        else:
            raise AssertionError('unsupported receipt was posted')


def test_petty_source():
    setup()
    banks = expenses.heads()['banks']
    assert 'Petty Cash - SYN' not in banks and 'Bank - SYN' in banks
    assert 'Historical Cutover Control - SYN' not in banks
    entry = S.Doc('Expense Entry', {'company': 'SYN',
                                   'expense_head': 'Office Rent - SYN',
                                   'amount': 5.25, 'payment_mode': 'Cash',
                                   'paid_from': 'Petty Cash - SYN',
                                   'building': None})
    try:
        ExpenseEntry.validate(entry)
    except S.ValidationError as exc:
        assert 'petty cash movement' in str(exc), exc
    else:
        raise AssertionError('expense form bypassed petty register')


def test_dirham_allocation():
    for amount in (0.01, 0.49, 0.50, 12.35, 23.45, 45.80, -12.35):
        shares = allocation.split(amount, {'A': 1, 'B': 1, 'C': 1})
        assert round(sum(shares.values()), 2) == amount, (amount, shares)
    assert allocation.split(0.01, {'A': 1, 'B': 1}) == {
        'A': 0.01, 'B': 0.0}
    assert allocation.split(5.25, {'A': 0, 'B': 0}) == {
        'A': 2.63, 'B': 2.62}


def test_gl_above_old_cap():
    setup()
    S.DB['GL Entry'] = [
        {'name': f'GLE-{i:05}', 'company': 'SYN', 'is_cancelled': 0,
         'posting_date': '2026-09-24', 'account': 'Bank - SYN',
         'debit': 1, 'credit': 1, 'voucher_type': 'Journal Entry',
         'voucher_no': f'JV-{i}', 'owner': 'Administrator'}
        for i in range(20001)]
    assert len(accounting._gl('SYN', '2026-09-01', '2026-09-24')) == 20001


for test in (test_states_and_totals, test_caps_and_scope,
             test_cash_and_duplicate, test_petty_source,
             test_dirham_allocation, test_gl_above_old_cap):
    test()
    print('PASS', test.__name__)
