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
        'Bank Account': [{'name': 'Bank Ref', 'account': 'Bank - SYN',
                          'company': 'SYN', 'is_company_account': 1}],
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
        'Building': [{'name': 'A', 'building_name': 'Building A'},
                     {'name': 'B', 'building_name': 'Building B'}],
        'Unit': [{'name': 'UNIT-A', 'building': 'A'},
                 {'name': 'UNIT-B', 'building': 'B'}],
        'Payment Entry': [], 'Sales Invoice': [], 'Cheque': [],
        'User Permission': ([{'user': S.SESSION['user'], 'allow': 'Building',
                             'for_value': 'A'}] if scoped else []),
        'Tenancy Agreement': [{'name': 'TA-A', 'tenant': 'TEN-A', 'building': 'A',
                               'unit': 'UNIT-A', 'status': 'Active'},
                              {'name': 'TA-B', 'tenant': 'TEN-B', 'building': 'B',
                               'unit': 'UNIT-B', 'status': 'Active'}],
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
    assert recorded['custom_remarks'] == 1
    assert recorded['remarks'] == 'Cash collected by acc@example.invalid.'
    assert result['allocated'] == result['on_account'] == 30.55
    result = finance.record_receipt({**payload, 'reference': '',
                                     'request_id': 'abcdef0123456789'})
    assert result['payment_entry']
    recorded = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')][-1]
    assert recorded['reference_no'].startswith('DBR-')
    # The stub's submit() does not persist docstatus back to its in-memory DB.
    S.DB['Payment Entry'][-1]['docstatus'] = 1
    S.DB['Payment Entry'][-1]['posting_date'] = '2026-09-24'
    try:
        finance.record_receipt({**payload, 'reference': '',
                                'request_id': 'abcdef0123456789'})
    except S.ValidationError:
        pass
    else:
        raise AssertionError('a retried blank-reference receipt was posted twice')
    try:
        finance.record_receipt({**payload, 'mode': 'Cheque'})
    except S.ValidationError:
        pass
    else:
        raise AssertionError('cheque receipt was posted twice')


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


def test_banking_existing_cash_receipt_moves_cash_once():
    setup()
    S.DB['Unit'] = [{'name': 'U-A', 'building': 'A'}]
    S.DB['Tenancy Agreement'][0]['unit'] = 'U-A'
    S.DB['Payment Entry'] = [receipt('PE-CASH', 1, 30.55)]
    S.DB['Deposit Batch'] = [{
        'name': 'BATCH-A', 'status': 'Draft', 'company': 'SYN',
        'bank_account': 'Bank Ref', 'prepared_by': S.SESSION['user'],
        'slip_no': None,
        'lines': [S.Doc('Deposit Batch Line', {
            'payment_type': 'Cash', 'payment_entry': 'PE-CASH', 'cheque': None,
            'tenant': 'TEN-A', 'unit': 'U-A', 'amount': 30.55})],
    }]
    result = finance.deposit_batch('BATCH-A', on='2026-09-25')
    assert result['status'] == 'Deposited'
    assert not [c for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    entries = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Journal Entry')]
    assert len(entries) == 1, entries
    assert entries[0]['cheque_no'] == 'BATCH-A'
    assert entries[0]['cheque_date'] == '2026-09-25'
    assert entries[0]['accounts'] == [
        {'account': 'Bank - SYN', 'debit_in_account_currency': 30.55},
        {'account': 'Cash - SYN', 'credit_in_account_currency': 30.55}], entries


def test_cheque_logging_is_deferred():
    setup()
    S.DB['Tenancy Agreement'][0].update(monthly_rent=2600, unit='U-A',
                                        cheques_held=0)
    S.DB['Unit'] = [{'name': 'U-A', 'building': 'A'}]
    try:
        finance.log_cheque({'direction': 'Incoming', 'cheque_no': '12345'})
    except S.ValidationError as exc:
        assert 'deferred' in str(exc)
    else:
        raise AssertionError('cheque logging is still enabled')
    assert not [c for c in S.CALLS if c[:2] == ('insert', 'Cheque')]


def test_received_cheque_waits_for_batch_and_clearing():
    setup()
    S.DB['Sales Invoice'] = [{'name': 'SI-A', 'customer': 'TEN-A',
                              'posting_date': finance.today(), 'docstatus': 1,
                              'outstanding_amount': 100,
                              'custom_rental_agreement': 'TA-A'}]
    payload = {'tenant': 'TEN-A', 'amount': 100, 'on': finance.today(),
               'mode': 'Cheque', 'invoice': 'SI-A', 'bank_account': 'Bank Ref',
               'reference': 'BANK-CLEAR-1'}
    try:
        finance.record_receipt(dict(payload, cleared=True))
    except S.ValidationError as exc:
        assert 'deposit it in a batch' in str(exc)
    else:
        raise AssertionError('direct cheque receipt settled an invoice')
    recorded = finance.record_incoming_cheque(dict(payload,
        cheque_no='12345', cheque_bank='Drawer Bank', cheque_date=finance.today()))
    assert recorded['status'] == 'Received'
    assert not [c for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert S.DB['Cheque'][0]['unit'] == 'UNIT-A'
    assert S.DB['Cheque'][0]['sales_invoice'] == 'SI-A'
    candidates = finance.deposit_candidates()['cheques']
    assert len(candidates) == 1 and candidates[0]['id'] == recorded['cheque']
    finance.present_cheque(recorded['cheque'], 'Bank Ref', finance.today())
    try:
        finance.clear_cheque(recorded['cheque'])
    except S.ValidationError as exc:
        assert 'matched bank statement' in str(exc)
    else:
        raise AssertionError('a cheque cleared without a bank statement')
    S.DB['Cheque'][0]['deposit_batch'] = 'BATCH-A'
    S.DB['Bank Statement Import'] = [{'name': 'STMT-A', 'bank_account': 'Bank Ref'}]
    S.DB['Bank Statement Line'] = [{'name': 'LINE-A', 'parent': 'STMT-A',
        'status': 'Matched', 'matched_type': 'Deposit Batch',
        'matched_ref': 'BATCH-A', 'txn_date': finance.today()}]
    result = finance.clear_cheque(recorded['cheque'], finance.today())
    posted = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert len(posted) == 1 and posted[0]['paid_to'] == 'Bank - SYN', posted
    assert posted[0]['mode_of_payment'] == 'Cheque'
    assert posted[0]['references'][0]['reference_name'] == 'SI-A'
    assert result['payment_entry']
    assert finance.clear_cheque(recorded['cheque'])['payment_entry'] == result['payment_entry']
    assert len([c for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]) == 1


def landlord_fixture(scoped=False):
    setup(scoped=scoped)
    S.DB['Building'] = [{'name': 'A', 'building_name': 'Building A'},
                        {'name': 'B', 'building_name': 'Building B'}]
    S.DB['Supplier'] = [{'name': 'SUP-A', 'supplier_name': 'Landlord A'},
                        {'name': 'SUP-B', 'supplier_name': 'Landlord B'}]
    S.DB['Head Lease'] = [{'name': 'HL-A', 'building': 'A',
                           'landlord': 'SUP-A', 'company': 'SYN'},
                          {'name': 'HL-B', 'building': 'B',
                           'landlord': 'SUP-B', 'company': 'SYN'}]
    S.DB['Purchase Invoice'] = [
        {'name': 'PI-A', 'supplier': 'SUP-A', 'company': 'SYN',
         'custom_landlord_contract': 'HL-A', 'docstatus': 1,
         'outstanding_amount': 500, 'posting_date': finance.today(),
         'due_date': finance.today()},
        {'name': 'PI-B', 'supplier': 'SUP-B', 'company': 'SYN',
         'custom_landlord_contract': 'HL-B', 'docstatus': 1,
         'outstanding_amount': 200, 'posting_date': finance.today(),
         'due_date': finance.today()}]


def test_landlord_payments_post_to_selected_bill():
    landlord_fixture()
    rows = finance.landlord_payments()['rows']
    assert [(r['building'], r['landlord'], r['amount']) for r in rows] == [
        ('A', 'SUP-A', 500), ('B', 'SUP-B', 200)]
    base = {'invoice': 'PI-A', 'amount': 300, 'mode': 'Bank transfer',
            'bank_account': 'Bank Ref', 'on': finance.today(),
            'reference': 'LANDLORD-001'}
    result = finance.record_landlord_payment(base)
    posted = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert len(posted) == 1 and posted[0]['paid_from'] == 'Bank - SYN', posted
    assert posted[0]['references'] == [{
        'reference_doctype': 'Purchase Invoice', 'reference_name': 'PI-A',
        'allocated_amount': 300}], posted
    assert result['invoice'] == 'PI-A'
    # The stub records submit() without persisting its docstatus in the DB row.
    S.DB['Payment Entry'][0]['docstatus'] = 1
    S.DB['Payment Entry'][0]['posting_date'] = finance.today()
    try:
        finance.record_landlord_payment(base)
    except S.ValidationError as exc:
        assert 'already recorded' in str(exc)
    else:
        raise AssertionError('duplicate landlord payment posted')


def test_landlords_without_bills_remain_visible():
    landlord_fixture()
    S.DB['Supplier'].append({'name': 'SUP-C', 'supplier_name': 'Landlord C',
                              'db_is_landlord': 1})
    S.DB['Building'].append({'name': 'C', 'building_name': 'Building C',
                              'landlord': 'SUP-C'})
    rows = finance.landlord_payments()['rows']
    assert any(r['landlord'] == 'SUP-C' and r['amount'] == 0
               and not r['invoice'] for r in rows)


def test_landlord_scope_and_cheque_details():
    landlord_fixture(scoped=True)
    assert [r['invoice'] for r in finance.landlord_payments()['rows']] == ['PI-A']
    base = {'invoice': 'PI-A', 'amount': 100, 'mode': 'Cheque',
            'bank_account': 'Bank Ref', 'on': finance.today()}
    try:
        finance.record_landlord_payment(base)
    except S.ValidationError as exc:
        assert 'cheque number and date' in str(exc)
    else:
        raise AssertionError('landlord cheque without details posted')
    try:
        finance.record_landlord_payment(dict(base, invoice='PI-B',
            cheque_no='45678', cheque_date=finance.today()))
    except S.PermissionError_:
        pass
    else:
        raise AssertionError('payment to another building was permitted')
    result = finance.record_landlord_payment(dict(
        base, cheque_no='45678', cheque_date=finance.today()))
    assert result['invoice'] == 'PI-A'
    assert result['cheque'] and S.DB['Cheque'][0]['purchase_invoice'] == 'PI-A'
    assert S.DB['Cheque'][0]['status'] == 'Issued'
    posted = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert len(posted) == 1 and posted[0]['paid_from'] == 'Bank - SYN'


def test_landlord_cash_uses_cash_ledger():
    landlord_fixture()
    finance.record_landlord_payment({
        'invoice': 'PI-A', 'amount': 100, 'mode': 'Cash',
        'on': finance.today(), 'reference': 'CASH-RECEIPT-1'})
    posted = [c[2] for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert len(posted) == 1 and posted[0]['paid_from'] == 'Cash - SYN'


def test_agreement_bills_post_automatically_from_cutover():
    landlord_fixture()
    S.DB['Head Lease'][0].update(start_date='2026-09-15',
        end_date='2027-09-14', rent_free_days=0, monthly_rent=3100,
        annual_rent=37200, cost_center='CC-A', status='Active')
    S.DB['Purchase Invoice'] = []
    S.DB['Account'].append({'name': 'Head Lease Rent - SYN',
        'account_name': 'Head Lease Rent', 'company': 'SYN', 'is_group': 0})
    S.DB['Cost Center'] = [{'name': 'CC-A'}]
    S.DB['Item Group'] = [{'name': 'Services', 'item_group_name': 'Services'}]
    assert finance.generate_head_lease_bills('2026-09-27')['created'] == []
    assert not S.DB['Purchase Invoice']
    try:
        finance.generate_head_lease_bills('2027-10-01')
    except S.ValidationError as exc:
        assert 'future month' in str(exc)
    else:
        raise AssertionError('future landlord bills were allowed')
    result = finance.build_head_lease_payable('A', '2026-10-01')
    assert result['created'] and result['status'] == 'Submitted', result
    bill = next(c[2] for c in S.CALLS if c[:2] == ('insert', 'Purchase Invoice'))
    assert bill['posting_date'].isoformat() == '2026-10-01'
    assert bill['items'][0]['rate'] == 3100
    assert not [c for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    assert any(c[:2] == ('submit', 'Purchase Invoice') for c in S.CALLS)
    S.DB['Purchase Invoice'][0].update(docstatus=1, grand_total=3100)
    again = finance.build_head_lease_payable('A', '2026-10-01')
    assert not again['created'] and again['invoice'] == result['invoice']
    assert len(S.DB['Purchase Invoice']) == 1


def test_landlord_legacy_draft_must_match_agreement():
    landlord_fixture()
    S.DB['Head Lease'][0].update(start_date='2026-01-01',
        end_date='2027-01-01', rent_free_days=0, monthly_rent=150,
        annual_rent=1800, cost_center='CC-A', status='Active')
    S.DB['Account'].append({'name': 'Head Lease Rent - SYN',
        'account_name': 'Head Lease Rent', 'company': 'SYN', 'is_group': 0})
    S.DB['Purchase Invoice'].append({
        'name': 'PI-DRAFT', 'supplier': 'SUP-A', 'company': 'SYN',
        'custom_landlord_contract': 'HL-A', 'docstatus': 0,
        'custom_billing_period': '2026-10-01', 'grand_total': 150,
        'outstanding_amount': 0, 'posting_date': '2026-10-01',
        'due_date': '2026-10-31', 'items': [{'item_code': 'Other',
        'qty': 1, 'rate': 150, 'expense_account': 'Head Lease Rent - SYN',
        'cost_center': 'CC-A'}]})
    drafts = [r for r in finance.landlord_payments()['rows']
              if r['status'] == 'Needs review']
    assert len(drafts) == 1 and drafts[0]['amount'] == 150
    try:
        finance.build_head_lease_payable('A', '2026-10-01')
    except S.ValidationError as exc:
        assert 'differs from the agreement' in str(exc)
    else:
        raise AssertionError('a mismatched draft landlord bill was posted')
    assert not any(c[:2] == ('submit', 'Purchase Invoice') for c in S.CALLS)
    S.DB['Purchase Invoice'][-1]['items'][0]['item_code'] = 'Landlord Rent'
    result = finance.build_head_lease_payable('A', '2026-10-01')
    assert result['status'] == 'Submitted'
    assert any(c[:2] == ('submit', 'Purchase Invoice') for c in S.CALLS)


def test_schedule_only_landlord_payment_is_blocked():
    landlord_fixture()
    try:
        finance.pay_head_lease('HL-A', 'ROW-A')
    except S.ValidationError as exc:
        assert 'does not post a payment' in str(exc)
    else:
        raise AssertionError('schedule marked paid without a Payment Entry')


def test_new_batch_rejects_missing_cheques():
    setup()
    try:
        finance.create_deposit_batch({'bank_account': 'Bank Ref', 'lines': [
            {'type': 'Cheque', 'cheque': 'CHQ-1', 'amount': 50}]})
    except S.ValidationError as exc:
        assert 'not a received tenant cheque' in str(exc) or 'CHQ-1' in str(exc)
    else:
        raise AssertionError('missing cheque accepted in a new deposit batch')


def test_received_cheque_batch_derives_identity_and_presents_once():
    setup()
    S.DB['Cheque'] = [{'name': 'CHQ-A', 'direction': 'Incoming',
        'status': 'Received', 'company': 'SYN', 'party': 'TEN-A',
        'cheque_no': '112233', 'cheque_date': finance.today(),
        'unit': 'UNIT-A', 'building': 'A', 'amount': 75,
        'deposit_batch': None, 'payment_entry': None}]
    original = S.Doc.append
    def typed_append(doc, key, row):
        return original(doc, key, S.Doc('Deposit Batch Line', row))
    S.Doc.append = typed_append
    try:
        result = finance.create_deposit_batch({'bank_account': 'Bank Ref',
            'date': finance.today(), 'lines': [
                {'type': 'Cheque', 'cheque': 'CHQ-A', 'amount': 999,
                 'tenant': 'TEN-B', 'unit': 'UNIT-B'}]})
        batch = S.DB['Deposit Batch'][0]
        assert result['total'] == 75 and batch['lines'][0]['tenant'] == 'TEN-A'
        assert batch['lines'][0]['unit'] == 'UNIT-A'
        assert S.DB['Cheque'][0]['status'] == 'Received'
        finance.deposit_batch(result['batch'], on=finance.today())
        assert S.DB['Cheque'][0]['status'] == 'Deposited'
        assert S.DB['Cheque'][0]['bank_account'] == 'Bank Ref'
        assert not [c for c in S.CALLS if c[:2] == ('insert', 'Payment Entry')]
    finally:
        S.Doc.append = original


def test_cheque_image_must_be_private_and_attached():
    setup()
    S.DB['Cheque'] = [{'name': 'CHQ-A', 'direction': 'Incoming',
        'party': 'TEN-A', 'building': 'A', 'unit': 'UNIT-A',
        'amount': 75, 'cheque_no': '112233', 'status': 'Received'}]
    S.DB['File'] = [{'name': 'FILE-A', 'file_url': '/private/files/cheque.png',
        'attached_to_doctype': 'Cheque', 'attached_to_name': 'CHQ-A',
        'is_private': 1}]
    try:
        finance.attach_payment_cheque_image('CHQ-A', '/files/public.png')
    except S.ValidationError as exc:
        assert 'private image' in str(exc)
    else:
        raise AssertionError('public cheque image accepted')
    result = finance.attach_payment_cheque_image(
        'CHQ-A', '/private/files/cheque.png')
    assert result['scan'] == S.DB['Cheque'][0]['scan']


def test_optional_slip_image_attaches_to_batch():
    setup()
    S.DB['Deposit Batch'] = [{'name': 'DEP-A', 'status': 'Draft',
                              'company': 'SYN', 'prepared_by': S.SESSION['user'],
                              'lines': []}]
    S.DB['File'] = [{'name': 'FILE-A', 'file_url': '/private/files/slip.jpg',
                     'attached_to_doctype': 'Deposit Batch',
                     'attached_to_name': 'DEP-A', 'is_private': 1}]
    result = finance.attach_deposit_slip('DEP-A', '/private/files/slip.jpg')
    assert result['slip_scan'] == '/private/files/slip.jpg'
    assert S.DB['Deposit Batch'][0]['slip_scan'] == result['slip_scan']


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
             test_banking_existing_cash_receipt_moves_cash_once,
             test_cheque_logging_is_deferred,
             test_received_cheque_waits_for_batch_and_clearing,
             test_landlord_payments_post_to_selected_bill,
             test_landlords_without_bills_remain_visible,
             test_landlord_scope_and_cheque_details,
             test_landlord_cash_uses_cash_ledger,
             test_agreement_bills_post_automatically_from_cutover,
             test_landlord_legacy_draft_must_match_agreement,
             test_schedule_only_landlord_payment_is_blocked,
             test_new_batch_rejects_missing_cheques,
             test_received_cheque_batch_derives_identity_and_presents_once,
             test_cheque_image_must_be_private_and_attached,
             test_optional_slip_image_attaches_to_batch,
             test_dirham_allocation, test_gl_above_old_cap):
    test()
    print('PASS', test.__name__)
