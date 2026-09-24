"""Loads the REAL doctype JSON into the stub's schema, imports the REAL
darkbrown modules, and exercises the paths the audit flagged."""
import sys, json, glob, os, traceback, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stub_frappe as S
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

# ---- real doctype JSON -> stub schema (so Select validation is the real one)
for f in glob.glob(REPO + '/darkbrown/darkbrown/doctype/*/*.json'):
    d = json.load(open(f))
    if d.get('doctype') != 'DocType': continue
    S.SCHEMA[d['name']] = {
        x['fieldname']: (x['fieldtype'], x.get('options'), x.get('default'))
        for x in d.get('fields', [])}
for core, fields in {
    'Sales Invoice': {'name':('Data',None,None),'customer':('Link',None,None),
        'outstanding_amount':('Currency',None,None),'grand_total':('Currency',None,None),
        'docstatus':('Int',None,None),'remarks':('Text',None,None),'due_date':('Date',None,None),
        'posting_date':('Date',None,None)},
    'Purchase Invoice': {'name':('Data',None,None),'supplier':('Link',None,None),
        'outstanding_amount':('Currency',None,None),'grand_total':('Currency',None,None),
        'docstatus':('Int',None,None),'remarks':('Text',None,None),
        'due_date':('Date',None,None),'posting_date':('Date',None,None),
        'custom_landlord_contract':('Link','Head Lease',None),
        'custom_billing_period':('Data',None,None)},
    'Payment Entry': {'name':('Data',None,None),'docstatus':('Int',None,None),
        'reference_no':('Data',None,None),'party':('Link',None,None),
        'paid_amount':('Currency',None,None),'posting_date':('Date',None,None),
        'reference_date':('Date',None,None),'party_type':('Data',None,None),
        'unallocated_amount':('Currency',None,None),'remarks':('Text',None,None)},
    'Journal Entry': {'name':('Data',None,None),'company':('Link',None,None),
        'posting_date':('Date',None,None),'user_remark':('Text',None,None),
        'accounts':('Table',None,None),'docstatus':('Int',None,None)},
    'Account': {'name':('Data',None,None),'account_name':('Data',None,None)},
    'Customer': {'name':('Data',None,None),'customer_name':('Data',None,None)},
    'Supplier': {'name':('Data',None,None),'supplier_name':('Data',None,None)},
    'Company': {'name':('Data',None,None),'abbr':('Data',None,None)},
    'Cost Center': {'name':('Data',None,None),'cost_center_name':('Data',None,None)},
    'Bank Account': {'name':('Data',None,None),'account':('Link',None,None)},
    'ToDo': {'name':('Data',None,None)}, 'Has Role': {'parent':('Data',None,None)},
    'Notification Log': {'name':('Data',None,None)}, 'User': {'name':('Data',None,None)},
    'DocType': {'name':('Data',None,None)},
}.items():
    S.SCHEMA[core] = fields

import scanners
import glob, os

PASS, FAIL = [], []
def check(name, fn):
    S.CALLS.clear(); S.THROWN.clear()
    try:
        fn(); PASS.append(name)
    except AssertionError as e:
        FAIL.append((name, "ASSERT: %s" % e))
    except Exception as e:
        FAIL.append((name, "%s: %s" % (type(e).__name__, e)))

def reset():
    S.DB.clear()
    S.DB.update({
        'Company':[{'name':'DarkBrown RealEstate','abbr':'DB'}],
        'DBR Settings':[{'default_company':'DarkBrown RealEstate',
                         'default_bank_account':'QNB Main',
                         'returned_cheque_charge_account':'Bank Charges - DB',
                         'presentation_notice_days':14,
                         'default_tenancy_notice_days':60}],
        'Account':[{'name':'Historical Cutover Control - DB',
                    'account_name':'Historical Cutover Control',
                    'root_type':'Asset','account_type':'Cash','is_group':0,
                    'disabled':0,'company':'DarkBrown RealEstate'},
                   {'name':'Bank Charges - DB','account_name':'Bank Charges',
                    'account_type':'Expense Account','is_group':0},
                   {'name':'QNB Main - DB','account_name':'QNB Main',
                    'account_type':'Bank','root_type':'Asset','is_group':0,
                    'disabled':0,'company':'DarkBrown RealEstate'},
                   {'name':'Security Deposits Held - DB',
                    'account_name':'Security Deposits Held','is_group':0,
                    'company':'DarkBrown RealEstate'},
                   {'name':'Tenant Recharge Income - DB',
                    'account_name':'Tenant Recharge Income','is_group':0,
                    'company':'DarkBrown RealEstate'},
                   {'name':'Utility Recovery - DB',
                    'account_name':'Utility Recovery','root_type':'Income',
                    'is_group':0,'company':'DarkBrown RealEstate'},
                   {'name':'Cash - DB','account_name':'Cash','account_type':'Cash',
                    'root_type':'Asset','is_group':0,'disabled':0,
                    'company':'DarkBrown RealEstate'}],
        'Bank Account':[{'name':'QNB Main','account':'QNB Main - DB'}],
        'Cost Center':[{'name':'Al Sadd - DB','cost_center_name':'Al Sadd','is_group':0}],
        'Customer':[{'name':'CUST-001','customer_name':'Mohammed Abdul Rahman'},
                    {'name':'CUST-002','customer_name':'Mohammed Abdul Kareem'}],
        'Supplier':[{'name':'SUP-001','supplier_name':'Al Adekhar Real Estate LLC'}],
        'Unit':[], 'Building':[{'name':'Al Sadd'}],
        'Cheque':[], 'Security Deposit':[], 'Head Lease Payment':[],
        'Move Out Case':[],
        'Collection Case':[], 'Sales Invoice':[], 'Purchase Invoice':[],
        'Payment Entry':[], 'Journal Entry':[],
        'Tenancy Agreement':[], 'Head Lease':[], 'Building':[{'name':'Al Sadd'}],
        'Has Role':[{'parent':'acc@darkbrown.qa','role':'Accounts','parenttype':'User'}],
        'User':[{'name':'acc@darkbrown.qa','enabled':1}],
        'ToDo':[], 'Document Register':[], 'Document Requirement':[],
        'Notification Log':[], 'DocType':[{'name':'Cheque'},{'name':'Party Document'}],
    })

def mkcheque(**kw):
    d = {'name':'CHQ-001','direction':'Incoming','party_type':'Customer',
         'party':'CUST-001','status':'Received','cheque_no':'000123',
         'cheque_date':'2026-08-01','amount':5000.0,'building':'Al Sadd',
         'bank':'QNB','company':'DarkBrown RealEstate','head_lease':None,
         'tenancy_agreement':None,'unit':None,'payment_entry':None,
         'bank_account':'QNB Main','presented_on':None,'deposit_batch':None,
         'return_charge':0,'returned_on':None,'return_reason':None,
         'return_notes':None,'replaced_by':None,'cleared_on':None}
    d.update(kw); S.DB['Cheque'].append(d); return d

# =====================================================================
print("="*72); print("VERIFYING THE SHIPPED MODULES"); print("="*72)

# ---- A. every module still imports
def t_imports():
    import importlib
    mods = []
    for f in glob.glob(REPO+'/darkbrown/**/*.py', recursive=True):
        rel = os.path.relpath(f, REPO)[:-3].replace('/', '.')
        if rel.endswith('.__init__'): rel = rel[:-9]
        mods.append(rel)
    bad = []
    for m in sorted(set(mods)):
        try: importlib.import_module(m)
        except Exception as e: bad.append((m, "%s: %s" % (type(e).__name__, e)))
    assert not bad, "unimportable: %s" % bad[:6]
check("all 150 modules import against a stubbed Frappe", t_imports)

# ---- B. the old crash sites are gone
def t_no_phantom_fields():
    bad = scanners.phantom_fields(REPO)
    assert not bad, "phantom Cheque fields still referenced:\n    " + "\n    ".join(bad)
check("no live code reads a non-existent Cheque field", t_no_phantom_fields)

def t_no_bounced_status():
    bad = scanners.bounced_status(REPO)
    assert not bad, "status 'Bounced' still used as a value:\n    " + "\n    ".join(bad)
check("status 'Bounced' no longer used as a filter or assignment", t_no_bounced_status)

# ---- C. one engine
def t_single_engine():
    from darkbrown.utils import cheques, pdc_accounting
    from darkbrown.api import doc_intake_phase2
    import inspect
    for mod, fn in [(cheques,'clear_cheque'), (cheques,'return_cheque'),
                    (cheques,'replace_cheque'), (pdc_accounting,'mark_cleared'),
                    (pdc_accounting,'mark_bounced'),
                    (doc_intake_phase2,'mark_cleared_v2')]:
        src = inspect.getsource(getattr(mod, fn))
        assert 'from darkbrown.api import finance' in src or \
               'from darkbrown.api.finance' in src, \
               "%s.%s does not delegate to finance" % (mod.__name__, fn)
        assert 'frappe.new_doc("Payment Entry")' not in src, \
               "%s.%s still builds its own Payment Entry" % (mod.__name__, fn)
check("all former engines delegate to api.finance", t_single_engine)

# ---- D. clear_cheque behaviour
def t_clear_posts_receipt():
    reset(); mkcheque()
    from darkbrown.api import finance
    r = finance.clear_cheque('CHQ-001')
    assert r['status'] == 'Cleared', r
    assert any(c[0]=='insert' and c[1]=='Payment Entry' for c in S.CALLS), \
        "no Payment Entry posted"
check("clear_cheque posts a receipt to the ledger", t_clear_posts_receipt)

def t_security_refused():
    reset(); mkcheque()
    S.DB['Security Deposit'].append({'name':'SD-1','receipt_cheque':'CHQ-001'})
    from darkbrown.api import finance
    try:
        finance.clear_cheque('CHQ-001'); assert False, "security cheque was cleared as income"
    except S.ValidationError:
        assert 'SECURITY' in S.THROWN[-1]
check("a security cheque cannot be cleared as income", t_security_refused)

def t_headlease_marked():
    reset(); mkcheque(direction='Outgoing', party_type='Supplier',
                      party='SUP-001', status='Issued', head_lease='HL-001')
    S.DB['Head Lease Payment'].append({'name':'HLP-1','cheque':'CHQ-001','status':'Due'})
    from darkbrown.api import finance
    finance.clear_cheque('CHQ-001')
    assert S.DB['Head Lease Payment'][0]['status'] == 'Cleared', S.DB['Head Lease Payment']
check("clearing an outgoing cheque marks its Head Lease Payment", t_headlease_marked)

def t_outgoing_clear_posts_supplier_payment():
    reset(); mkcheque(direction='Outgoing', party_type='Supplier',
                      party='SUP-001', status='Issued', head_lease='HL-001')
    S.DB['Purchase Invoice'].append({'name':'PINV-1','supplier':'SUP-001',
        'docstatus':1,'outstanding_amount':5000,'posting_date':'2026-07-01',
        'custom_landlord_contract':'HL-001'})
    from darkbrown.api import finance
    r = finance.clear_cheque('CHQ-001')
    assert r['payment_entry'], r
    rows = [c for c in S.CALLS if c[0]=='insert' and c[1]=='Payment Entry']
    assert rows and rows[0][2]['payment_type'] == 'Pay', rows
    assert rows[0][2]['party_type'] == 'Supplier', rows[0][2]
    assert rows[0][2]['references'][0]['reference_doctype'] == 'Purchase Invoice'
check("clearing an outgoing cheque posts and allocates a supplier payment",
      t_outgoing_clear_posts_supplier_payment)

def t_money_amount_guards():
    reset()
    from darkbrown.api import finance
    for payload in ({'tenant':'CUST-001','amount':-1},
                    {'tenant':'CUST-001','amount':0}):
        try:
            finance.record_receipt(json.dumps(payload))
            assert False, "non-positive receipt accepted"
        except S.ValidationError:
            pass
    try:
        finance.log_cheque(json.dumps({'party':'CUST-001','cheque_no':'1',
                                       'amount':-10}))
        assert False, "negative cheque accepted"
    except S.ValidationError:
        pass
check("receipts and cheques reject non-positive amounts", t_money_amount_guards)

def t_outgoing_headlease_cheque_is_contract_scoped():
    reset()
    S.DB['Head Lease'].append({
        'name':'HL-001', 'building':'Al Sadd', 'landlord':'SUP-001',
        'status':'Active', 'start_date':'2026-01-01', 'end_date':'2026-12-31'})
    from darkbrown.api import finance
    r = finance.log_cheque(json.dumps({
        'direction':'Outgoing', 'party':'SUP-001', 'cheque_no':'9001',
        'cheque_date':'2026-09-22', 'amount':5000,
        'purpose':'Head-lease rent'}))
    made = next(x for x in S.DB['Cheque'] if x['name'] == r['cheques'][0])
    assert made['head_lease'] == 'HL-001', made
    assert made['building'] == 'Al Sadd', made
check("outgoing landlord cheques inherit their unambiguous Head Lease",
      t_outgoing_headlease_cheque_is_contract_scoped)

def t_outgoing_headlease_cheque_refuses_ambiguity():
    reset()
    for name in ('HL-001', 'HL-002'):
        S.DB['Head Lease'].append({
            'name':name, 'building':'Al Sadd', 'landlord':'SUP-001',
            'status':'Active', 'start_date':'2026-01-01',
            'end_date':'2026-12-31'})
    from darkbrown.api import finance
    try:
        finance.log_cheque(json.dumps({
            'direction':'Outgoing', 'party':'SUP-001', 'cheque_no':'9002',
            'cheque_date':'2026-09-22', 'amount':5000,
            'purpose':'Head-lease rent'}))
        assert False, "ambiguous landlord cheque was accepted"
    except S.ValidationError:
        assert 'multiple Head Leases' in S.THROWN[-1], S.THROWN[-1]
check("outgoing landlord cheques refuse ambiguous contract allocation",
      t_outgoing_headlease_cheque_refuses_ambiguity)

def t_landlord_detail_cheque_carries_party_and_headlease_purpose():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "fbtn('Record cheque to landlord','landlord-cheque',{ll:l.n})" in src, \
        "landlord detail cheque action does not carry its Supplier party"
    block = src[src.index("'landlord-cheque':{", src.index("const WIRE")):
                src.index("'amend-invoice':{", src.index("const WIRE"))]
    assert "party:(d.__ctx&&d.__ctx.ll)||null" in block, \
        "landlord cheque payload does not send the selected Supplier"
    assert "purpose:'Head-lease rent'" in block, \
        "landlord cheque payload does not activate Head Lease allocation"
check("landlord detail cheque sends its party and Head Lease purpose",
      t_landlord_detail_cheque_carries_party_and_headlease_purpose)

def t_outgoing_cheque_uses_payment_language():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "c.dir==='out'&&c.st==='Deposited'?'Presented':c.st" in src, \
        "presented outgoing cheques are still labelled Deposited"
    assert "[['Mark cleared','Funds paid']" in src, \
        "outgoing cheque clearing is still described as funds received"
    assert "c.dir!=='out'&&c.st==='Deposited'" in src, \
        "outgoing presented cheques still inflate the incoming deposit count"
check("outgoing cheque lifecycle uses payment language",
      t_outgoing_cheque_uses_payment_language)

def t_outgoing_return_form_uses_supplier_language():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "ret&&!outgoing?fld({k:'next'" in src, \
        "outgoing return still offers tenant collection actions"
    assert "A returned outgoing cheque reverses the payment." in src, \
        "outgoing return does not explain the supplier-payment reversal"
    assert "The supplier Payment Entry is cancelled, the payable reopens" in src, \
        "outgoing return still describes tenant arrears instead of the payable"
check("outgoing return form uses supplier-payment language",
      t_outgoing_return_form_uses_supplier_language)

def t_cheque_form_does_not_truncate_parties():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "TENANTS.slice(0,24)" not in src, \
        "cheque drawer list still hides tenants after the first 24"
    assert "LL.map(l=>l.n).slice(0,12)" not in src, \
        "cheque payee list still hides landlords after the first 12"
check("cheque form offers every live tenant and landlord",
      t_cheque_form_does_not_truncate_parties)

def t_cleared_cheque_can_be_returned():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "'Cleared':[['Mark returned'" in src, \
        "cleared cheques cannot reach the server return/reversal workflow"
    assert "'Cleared':[['Reverse'" not in src, \
        "cleared cheque still offers the unsupported Reverse action"
check("cleared cheque UI reaches the return and ledger-reversal workflow",
      t_cleared_cheque_can_be_returned)

def t_cheque_feed_includes_outgoing():
    import inspect
    from darkbrown.api import app
    src = inspect.getsource(app.cheques)
    assert '"direction": "Incoming"' not in src, \
        "live cheque feed still filters outgoing cheques out"
    assert '"dir": "out" if c.direction == "Outgoing" else "in"' in src, \
        "outgoing cheque direction is not sent to the custom UI"
    assert '"Supplier"' in src and 'supplier_name' in src, \
        "outgoing cheque payees are not resolved from Supplier"
check("custom cheque register includes outgoing supplier cheques",
      t_cheque_feed_includes_outgoing)

def t_outgoing_cheque_accounting_copy():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "Payable debited, bank credited" in src
    assert "oldest open supplier bill" in src
    assert "supplier payment was reversed and the payable reopened" in src
check("outgoing cheque page describes supplier accounting correctly",
      t_outgoing_cheque_accounting_copy)

def t_cheque_history_uses_recorded_dates():
    import inspect
    from darkbrown.api import app
    src = inspect.getsource(app.cheques)
    for field in ('"creation"', '"presented_on"', '"cleared_on"',
                  '"returned_on"'):
        assert field in src, "cheque feed does not read %s" % field
    assert '"hist": hist' in src
    assert app.CHQ_STATE["Returned"] == "Returned", \
        "server still asks the shell to synthesize a returned event"
check("cheque history is built from persisted lifecycle dates",
      t_cheque_history_uses_recorded_dates)

def t_operational_forms_do_not_backdate():
    src = open(REPO + '/darkbrown/shell/index.html').read()
    assert "d:'2026-07-27'" not in src, \
        "an operational form still defaults transactions to the prototype date"
    assert src.count("d:ISO(TODAY)") >= 3
    cheque_form = src[src.index("FORMS['log-cheque']"):
                      src.index("FORMS['cheque-action']")]
    assert "l:'Date on the cheque',t:'date',d:ISO(TODAY)" in cheque_form
    batch_form = src[src.index("'deposit-batch':{t:"):
                     src.index("'start-close':{t:")]
    assert "date:ISO(TODAY)" in batch_form
check("operational forms default to the live date", t_operational_forms_do_not_backdate)

def t_cheque_purpose_and_note_are_persisted():
    import inspect
    from darkbrown.api import app, finance
    create_src = inspect.getsource(finance.log_cheque)
    feed_src = inspect.getsource(app.cheques)
    assert '"purpose": data.get("purpose")' in create_src
    assert '"notes": data.get("notes")' in create_src
    assert '"purpose", "notes"' in feed_src
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "d.agr==='Deposit, not rent'?'Deposit':'Rent'" in shell
    assert "['Purpose',c.purpose||'Not recorded']" in shell
    reset()
    S.SCHEMA['Cheque'].setdefault('name', ('Data', None, None))
    result = finance.log_cheque({
        'direction': 'Incoming', 'party': 'CUST-001', 'building': 'Al Sadd',
        'cheque_no': 'PURPOSE-1', 'cheque_date': '2026-09-21',
        'amount': 100, 'purpose': 'Deposit', 'notes': 'Synthetic test',
    })
    saved = next(c for c in S.DB['Cheque'] if c['name'] == result['cheques'][0])
    assert saved['purpose'] == 'Deposit'
    assert saved['notes'] == 'Synthetic test'
check("cheque purpose and note survive the live API round trip",
      t_cheque_purpose_and_note_are_persisted)

# ---- E. return books the charge
def t_return_books_charge():
    reset(); mkcheque(status='Presented', tenancy_agreement='TA-1')
    from darkbrown.api import finance
    r = finance.return_cheque('CHQ-001', reason='Insufficient Funds', charge=150)
    assert r['status'] == 'Returned', r
    jes = [c for c in S.CALLS if c[0]=='insert' and c[1]=='Journal Entry']
    assert jes, "bank charge was not booked"
    accts = jes[0][2]['accounts']
    assert abs(accts[0]['debit_in_account_currency'] - 150) < 0.01, accts
    assert abs(accts[1]['credit_in_account_currency'] - 150) < 0.01, accts
    assert r['charge_unbooked'] is False
check("return_cheque books the bank charge to the P&L", t_return_books_charge)

def t_charge_unbooked_reported():
    reset(); mkcheque(status='Presented')
    S.DB['DBR Settings'][0]['returned_cheque_charge_account'] = None
    from darkbrown.api import finance
    r = finance.return_cheque('CHQ-001', reason='Stop Payment', charge=150)
    assert r['charge_unbooked'] is True, "unbooked charge not reported"
check("an unconfigured charge account is reported, not silently dropped", t_charge_unbooked_reported)

def t_return_preserves_cleared_history():
    """A return reverses money, not the historical fact it once cleared."""
    import inspect
    from darkbrown.api import finance
    src = inspect.getsource(finance.return_cheque)
    capture = src.index('cleared_on = doc.cleared_on')
    cancel = src.index('pe.cancel()')
    reload_ = src.index('doc.reload()')
    restore = src.index('doc.cleared_on = cleared_on')
    assert capture < cancel < reload_ < restore, \
        "return flow does not restore the cleared audit timestamp after cancellation"
check("returning a cleared cheque preserves its Cleared history event",
      t_return_preserves_cleared_history)

# ---- F. handoff now fires
def t_t5_fires():
    reset(); c = mkcheque(status='Returned')
    from darkbrown.utils import handoffs
    doc = S.Doc('Cheque', dict(c)); doc._changed.add('status')
    handoffs.t5_assign_bounced(doc)
    assert any(x[0]=='assign' for x in S.CALLS), "T5 recovery to-do did not fire"
def t_t5_quiet_on_cleared():
    reset(); c = mkcheque(status='Cleared')
    from darkbrown.utils import handoffs
    doc = S.Doc('Cheque', dict(c)); doc._changed.add('status')
    handoffs.t5_assign_bounced(doc)
    assert not any(x[0]=='assign' for x in S.CALLS), "T5 fired on a cleared cheque"
check("T5 recovery to-do fires on a Returned cheque", t_t5_fires)
check("T5 stays quiet on a cleared cheque", t_t5_quiet_on_cleared)

def t_hooks_wired():
    import re
    src = open(REPO+'/darkbrown/hooks.py').read()
    assert 'handoffs.t5_assign_bounced' in src, "T5 not in doc_events"
    assert 'handoffs.t1_assign_maintenance' in src, "T1 not in doc_events"
    assert 'handoffs.nightly' in src, "handoffs.nightly not scheduled"
check("handoffs are registered in hooks.py", t_hooks_wired)

# ---- G. reconciliation
def t_recon_amount_guard():
    reset(); mkcheque(cheque_no='000123', amount=45000.0, status='Presented')
    from darkbrown.utils import reconciliation
    pe = S.Doc('Payment Entry', {'name':'PE-1','reference_no':'000123',
        'party':'CUST-001','paid_amount':5000.0,'posting_date':'2026-08-10',
        'party_type':'Customer'})
    reconciliation._settle_cheque(pe)
    assert S.DB['Cheque'][0]['status'] != 'Cleared', \
        "a 5,000 payment cleared a 45,000 cheque"
def t_recon_exact_clears():
    reset(); mkcheque(cheque_no='000123', amount=5000.0, status='Presented')
    from darkbrown.utils import reconciliation
    pe = S.Doc('Payment Entry', {'name':'PE-1','reference_no':'000123',
        'party':'CUST-001','paid_amount':5000.0,'posting_date':'2026-08-10',
        'party_type':'Customer'})
    reconciliation._settle_cheque(pe)
    assert S.DB['Cheque'][0]['status'] == 'Cleared', "matching payment did not clear"
def t_recon_cancel_state():
    reset(); mkcheque(status='Cleared', payment_entry='PE-1', presented_on='2026-08-05')
    from darkbrown.utils import reconciliation
    reconciliation.on_payment_cancel(S.Doc('Payment Entry', {'name':'PE-1'}))
    assert S.DB['Cheque'][0]['status'] == 'Presented', \
        "cancel moved a presented cheque to %s" % S.DB['Cheque'][0]['status']
check("reconciliation refuses a payment that does not match the amount", t_recon_amount_guard)
check("reconciliation clears on an exact amount match", t_recon_exact_clears)
check("cancelling a payment restores the prior cheque state", t_recon_cancel_state)

# ---- H. seeders

# ---- I. rent derivation agrees
def t_rent_agrees():
    import re
    src = open(REPO+'/darkbrown/api/command.py').read()
    assert 'sum(annual_rent) / 12' not in src and 'sum(annual_rent)/12' not in src
    assert src.count('sum(round(annual_rent / 12, 2))') == 3, \
        "expected 3 unified derivations, found %d" % src.count('sum(round(annual_rent / 12, 2))')
    hl = open(REPO+'/darkbrown/darkbrown/doctype/head_lease/head_lease.py').read()
    assert 'flt((self.annual_rent or 0) / 12.0, 2)' in hl
    # the two must produce the same number
    for annual in (100000, 64000, 45500, 123456.78):
        assert abs(round(annual/12, 2) - S.flt(annual/12.0, 2)) < 0.005
check("stored monthly rent and the dashboard sum agree", t_rent_agrees)

# ---- J. seed() distinguishes empty from failed
def t_seed_empty_vs_failed():
    import inspect
    from darkbrown.api import app
    src = inspect.getsource(app.seed)
    assert 'if rows is not None:' in src, "seed() still uses `if rows:`"
    assert 'rows = None' in src, "failure path does not mark the panel absent"
check("seed() sends [] for empty and omits only on failure", t_seed_empty_vs_failed)

def t_shim_reason_valid():
    reset(); mkcheque(status='Presented')
    from darkbrown.utils import pdc_accounting
    r = pdc_accounting.mark_bounced('CHQ-001')      # no reason supplied
    assert 'Returned' in r['msg'], r
    opts = [o.strip() for o in S.SCHEMA['Cheque']['return_reason'][1].split('\n') if o.strip()]
    assert S.DB['Cheque'][0]['return_reason'] in opts, S.DB['Cheque'][0]['return_reason']
check("mark_bounced defaults to a valid return_reason", t_shim_reason_valid)

# ---- K. guards still hold on every endpoint
def t_guards():
    eps = scanners.endpoints(REPO)
    assert len(eps) >= 100, "only found %d endpoints - scanner broke" % len(eps)
    ungated = ["%s:%s" % (f, n) for f, n, g, _ in eps if not g]
    guests  = ["%s:%s" % (f, n) for f, n, _, gu in eps if gu]
    assert not ungated, "ungated endpoints: %s" % ungated
    assert not guests, "guest-accessible endpoints: %s" % guests
    print("        (%d whitelisted endpoints, all gated)" % len(eps))
check("every whitelisted endpoint is still role-gated", t_guards)


# ---- L. tenancy importer
def _mkinst(cls, **kw):
    """Build a controller instance without Document.__init__, so the real
    method under test runs against real field values. The stub Doc keeps state
    in the dict and tracks writes in _changed, both of which __init__ would
    normally set up."""
    inst = cls.__new__(cls)
    object.__setattr__(inst, '_changed', set())
    object.__setattr__(inst, 'flags', S.types.SimpleNamespace())
    dict.update(inst, kw)
    return inst


# ---- M. unit occupancy
def t_occupancy():
    from darkbrown.darkbrown.doctype.tenancy_agreement import tenancy_agreement as ta
    def sync(unit_status, ta_status, other_live=False):
        reset()
        S.DB['Unit'].append({'name': 'U1', 'building': 'Al Sadd', 'status': unit_status})
        if other_live:
            S.DB['Tenancy Agreement'].append({'name':'TA-OTHER','unit':'U1','status':'Active'})
        inst = ta.TenancyAgreement.__new__(ta.TenancyAgreement)
        inst.__dict__.update({'name':'TA-1','unit':'U1','status':ta_status})
        inst._sync_unit_occupancy()
        return S.DB['Unit'][0]['status']
    assert sync('Occupied','Expiring') == 'Occupied', "Expiring emptied an occupied unit"
    assert sync('Occupied','Expired', other_live=True) == 'Occupied', \
        "importing history emptied a unit that is let"
    assert sync('Under Maintenance','Active') == 'Under Maintenance'
    assert sync('Not Ready','Active') == 'Not Ready'
    assert sync('Reserved','Expired') == 'Reserved'
    assert sync('Vacant','Active') == 'Occupied'
    assert sync('Occupied','Terminated') == 'Vacant'
check("unit occupancy survives Expiring, history and ops statuses", t_occupancy)

# ---- N. financial records are not casually deletable
def t_no_delete():
    import json
    LEDGER = {'Cheque','Security Deposit','Deposit Batch','Invoice Run','Utility Bill',
              'Petty Cash Entry','Tenancy Agreement','Head Lease','Head Lease Payment',
              'Weekly Closing','Bank Statement Import'}
    bad, untracked = [], []
    for f in glob.glob(REPO + '/darkbrown/**/*.json', recursive=True):
        j = json.load(open(f))
        if j.get('doctype') != 'DocType' or j['name'] not in LEDGER: continue
        for pm in j.get('permissions', []):
            if pm.get('delete') and pm.get('role') != 'System Manager':
                bad.append("%s: %s" % (j['name'], pm['role']))
        if not j.get('track_changes'): untracked.append(j['name'])
    assert not bad, "business roles can still delete: %s" % bad
    assert not untracked, "no change tracking on: %s" % untracked
check("only System Manager can delete a financial record", t_no_delete)

# ---- O. one invoice builder, no validation suppression
def t_one_invoice_builder():
    import inspect
    from darkbrown.utils import rent_invoicing
    src = inspect.getsource(rent_invoicing)
    for gone in ('def build_run', 'def issue_run', 'def active_tenancies', 'def _prorate'):
        assert gone not in src, "%s still duplicates api.finance" % gone
    assert 'GENERATION_START' in src and 'def monthly_reminder' in src
    from darkbrown.api import charts
    assert charts.GENERATION_START == rent_invoicing.GENERATION_START

def t_no_validation_suppression():
    bad = []
    for f in glob.glob(REPO + '/darkbrown/**/*.py', recursive=True):
        for i, line in scanners.code_only(f):
            if 'validate_due_date' in line and 'noop' in line:
                bad.append("%s:%d" % (os.path.basename(f), i))
    assert not bad, "core validation still monkey-patched: %s" % bad
check("rent_invoicing no longer duplicates the invoice builder", t_one_invoice_builder)
check("no code suppresses ERPNext due-date validation", t_no_validation_suppression)

# ---- P. launch-safe billing periods and approval
def _agreement(**kw):
    base = dict(name='TA-1', start_date='2026-01-15', end_date='2026-12-31',
                payment_frequency='Monthly')
    base.update(kw)
    return S.types.SimpleNamespace(**base)

def t_partial_month_billing():
    from darkbrown.api import finance
    a = _agreement()
    window = finance._billing_window(a, '2026-01-01')
    assert tuple(map(str, window)) == ('2026-01-15', '2026-01-31'), window
    assert finance._prorated_monthly(3100, *window) == 1700, window

def t_frequency_cycle_billing():
    from darkbrown.api import finance
    a = _agreement(payment_frequency='Quarterly')
    assert finance._billing_window(a, '2026-02-01') is None
    window = finance._billing_window(a, '2026-01-01')
    assert tuple(map(str, window)) == ('2026-01-15', '2026-03-31'), window
    assert finance._prorated_monthly(3100, *window) == 7900, window

def t_final_partial_cycle():
    from darkbrown.api import finance
    a = _agreement(start_date='2026-01-01', end_date='2026-03-10',
                   payment_frequency='Quarterly')
    window = finance._billing_window(a, '2026-01-01')
    assert tuple(map(str, window)) == ('2026-01-01', '2026-03-10'), window
    assert finance._prorated_monthly(3100, *window) == 7200, window

def t_issue_requires_approval_and_manager():
    import inspect
    from darkbrown.api import finance
    src = inspect.getsource(finance.issue_invoice_run)
    assert 'guard(MD, GM)' in src and 'guard(MD, GM, ACC)' not in src
    assert 'doc.status != "Pending GM"' in src

def t_invoice_carries_idempotency_keys():
    import inspect
    from darkbrown.api import finance
    src = inspect.getsource(finance._rent_invoice)
    assert 'custom_rental_agreement' in src
    assert 'custom_billing_period' in src
    assert 'docstatus' in src
    assert 'items = []' in src
    assert 'if flt(line.agreement_amount) > 0:' in src
    assert 'omit rent completely' in src
    schema = S.SCHEMA['Invoice Run Line']
    assert schema['charge_snapshot'][0] == 'Long Text'

def t_head_lease_rent_free_accrual():
    from darkbrown.api import finance
    lease = S.types.SimpleNamespace(start_date='2026-01-01',
                                    end_date='2026-12-31',
                                    rent_free_days=14)
    window = finance._head_lease_accrual_window(lease, '2026-01-01')
    assert tuple(map(str, window)) == ('2026-01-15', '2026-01-31'), window
    assert finance._prorated_monthly(3100, *window) == 1700

def t_head_lease_accrues_monthly():
    from darkbrown.api import finance
    lease = S.types.SimpleNamespace(start_date='2026-01-01',
                                    end_date='2026-03-10',
                                    rent_free_days=0,
                                    payment_frequency='Quarterly')
    feb = finance._head_lease_accrual_window(lease, '2026-02-01')
    mar = finance._head_lease_accrual_window(lease, '2026-03-01')
    assert finance._prorated_monthly(3100, *feb) == 3100
    assert finance._prorated_monthly(3100, *mar) == 1000

def t_head_lease_payable_is_draft_and_approved():
    import inspect
    from darkbrown.api import finance
    build = inspect.getsource(finance.build_head_lease_payable)
    issue = inspect.getsource(finance.issue_head_lease_payable)
    assert '.submit()' not in build
    assert 'custom_landlord_contract' in build
    assert 'custom_billing_period' in build
    assert 'expense_account' in build and 'cost_center' in build
    assert 'guard(MD, GM)' in issue and 'guard(MD, GM, ACC)' not in issue
    assert 'pi.submit()' in issue

def t_invoice_reference_repair_is_registered():
    import inspect
    from darkbrown.patches import repair_invoice_reference_links as repair
    patches = open(REPO + '/darkbrown/patches.txt').read()
    assert 'darkbrown.patches.repair_invoice_reference_links' in patches
    src = inspect.getsource(repair)
    assert 'Tenancy Agreement' in src
    assert '("Purchase Invoice", "custom_landlord_contract", "Head Lease"' in src
    assert 'clear_cache' in src

check("partial first month follows signed agreement dates", t_partial_month_billing)
check("quarterly rent bills only at the contract cycle", t_frequency_cycle_billing)
check("final billing cycle stops at the agreement end", t_final_partial_cycle)
check("only GM or MD can issue an approved run", t_issue_requires_approval_and_manager)
check("rent invoices carry persisted idempotency keys", t_invoice_carries_idempotency_keys)
check("Head Lease rent-free days reduce the first accrual", t_head_lease_rent_free_accrual)
check("Head Lease cost accrues monthly despite quarterly payment", t_head_lease_accrues_monthly)
check("Head Lease payable stays draft until GM or MD approval", t_head_lease_payable_is_draft_and_approved)
check("invoice reference links are repaired after DocType rename", t_invoice_reference_repair_is_registered)

# ---- W. Stage 0 wipe

def t_wipe_covers_every_doctype():
    """The wipe must not carry a list that can go stale.

    KNOWN_ORDER only fixes deletion order; anything missing from it is still
    swept by the catch-all pass. But a doctype named there that no longer
    exists is a sign the list has drifted, and drift is how Historical
    Monthly PL and Expense Entry went uncounted for months.
    """
    import json as _json
    from darkbrown.load import stage_00_wipe as w0
    base = REPO + '/darkbrown/darkbrown/doctype'
    owned = []
    for d in sorted(os.listdir(base)):
        f = os.path.join(base, d, d + '.json')
        if not os.path.exists(f):
            continue
        j = _json.load(open(f))
        if j.get('istable') or j.get('issingle'):
            continue
        owned.append(j['name'])
    stale = [d for d in w0.KNOWN_ORDER if d not in owned]
    assert not stale, "KNOWN_ORDER names doctypes that do not exist: %s" % stale
    uncovered = [d for d in owned
                 if d not in w0.KNOWN_ORDER and d not in w0.KEEP_DOCTYPES]
    assert not uncovered, \
        "doctypes with no explicit order: %s" % uncovered
    print("        (%d doctypes owned, %d ordered, %d kept by design)"
          % (len(owned), len(w0.KNOWN_ORDER), len(w0.KEEP_DOCTYPES)))

def t_wipe_refuses_without_phrase():
    from darkbrown.load import stage_00_wipe as w0
    for bad in (None, "", "remove all darkbrown data", "REMOVE ALL DATA"):
        try:
            w0.run(confirm=bad)
            assert False, "wipe ran on confirm=%r" % bad
        except S.ValidationError:
            pass

def t_wipe_gate_tells_residue_from_ruin():
    """Two different failures the gate must not confuse.

    A site still holding records is a wipe that did not finish. A site with no
    Company is a wipe that took the accounting foundation with it. Reporting
    the second as the first would send somebody looking for stray records when
    what they need is the backup.
    """
    from darkbrown.load import stage_00_wipe as w0

    reset()

    # Blind: the module's doctypes cannot be enumerated. Every count would
    # come back zero, so the gate must refuse rather than report a clean site.
    out = w0.gate()
    assert out["pass"] is False and out.get("blind"), \
        "gate passed while unable to see any doctype"

    # Sighted, with a Building still on the site.
    S.DB["DocType"] = [{"name": "Building", "module": "Darkbrown",
                        "istable": 0, "issingle": 0}]
    out = w0.gate()
    assert out["pass"] is False, "gate passed a site still holding a Building"
    assert not out.get("missing"), \
        "gate cried ruin over a site whose foundation is intact"
    assert "Building" in out["residue"], \
        "gate missed the Building still on the site"

    # Foundation gone. A different failure, and it must read differently.
    S.DB["Company"] = []
    out = w0.gate()
    assert out["pass"] is False
    assert "Company" in (out.get("missing") or []), \
        "gate did not notice the Company was gone"
    reset()

def t_wipe_orders_for_the_guards():
    """The first Stage 0 run failed three ways, all ordering.

    Unit.on_trash throws on Occupied and deleting a tenancy does not clear
    that flag. guard_cost_center_delete throws while GL Entry rows exist. And
    cancelling a voucher writes reversals rather than removing rows, so the
    ledger has to be swept after the vouchers and before the buildings.

    This pins that order in place so a later edit cannot quietly undo it.
    """
    import inspect
    from darkbrown.load import stage_00_wipe as w0
    src = inspect.getsource(w0.run)

    occ = src.index("set status = 'Vacant'")
    units = src.index('d != "Building"')
    ledger = src.index("delete from `tab%s`")
    bldg = src.index('for name in frappe.get_all("Building"')

    assert occ < units, "units are deleted before occupancy is cleared"
    assert ledger < bldg, "buildings are deleted before the ledger is cleared"
    assert src.index("_force_submitted") < ledger, \
        "the ledger is swept before stubborn vouchers are forced"

def t_wipe_will_not_orphan_the_ledger():
    """Sweeping GL rows while a voucher still points at them would leave the
    ledger inconsistent rather than empty. The sweep has to be guarded."""
    import inspect
    from darkbrown.load import stage_00_wipe as w0
    src = inspect.getsource(w0.run)
    assert "survivors" in src and "leaving the ledger intact" in src, \
        "the GL sweep is not guarded on the vouchers being gone"

check("wipe covers every doctype the module owns", t_wipe_covers_every_doctype)
def t_wipe_error_handler_cannot_throw():
    """The handler that reports a failure must not become one.

    DocumentLockedError carries no message. str(e).splitlines()[0] on an
    empty string raises IndexError, which is how a report about ten journal
    entries took down a run that had already cleared thousands of records.
    """
    from darkbrown.load import stage_00_wipe as w0

    class Silent(Exception):
        pass

    for e in (Silent(), Silent(""), Silent("\n"), ValueError(""),
              Exception("first line\nsecond line")):
        out = w0._why(e)
        assert isinstance(out, str) and out, "_why returned %r for %r" % (out, e)
        assert "\n" not in out, "_why returned more than one line"

def t_wipe_does_not_cancel_before_deleting():
    """Cancelling writes reversing GL entries. On the first attempt that took
    the ledger from 9,958 rows to 17,303 — all of which were about to be
    deleted anyway. Forcing the docstatus skips that."""
    import ast, inspect, textwrap
    from darkbrown.load import stage_00_wipe as w0

    def calls(fn):
        """Method calls actually made, read from the syntax tree.

        A first version of this test searched the source text and failed on
        the docstring, which mentions doc.cancel() while explaining why it is
        not used. Prose is not code.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        return {n.func.attr for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

    for fn in (w0._force_one, w0._drop_submittable):
        assert "cancel" not in calls(fn), \
            "%s calls cancel(), which writes reversing GL entries" % fn.__name__
    assert "delete_doc" in calls(w0._force_one)
    assert "_force_one" in inspect.getsource(w0._drop_submittable), \
        "the submittable path no longer forces"

def t_wipe_drop_result_read_correctly():
    """_drop returns None on success and the reason on failure.

    An earlier version returned True/False, and changing it left one caller
    with `if _drop(...)` — which then counted every success as a failure and
    every failure as a success. Nothing in the output would have looked wrong.
    """
    import ast, inspect, textwrap
    from darkbrown.load import stage_00_wipe as w0
    tree = ast.parse(textwrap.dedent(inspect.getsource(w0.run)))
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Call):
            f = n.test.func
            if isinstance(f, ast.Name) and f.id == "_drop":
                assert False, ("_drop used as a bare truth value at line %d; "
                               "it returns a reason string, so a failure "
                               "reads as success" % n.lineno)

def t_wipe_takes_cost_centres_before_buildings():
    """Building.on_trash deletes the cost centre with force=False, which
    ERPNext refuses. Doing it ourselves first, with force=True, is what makes
    the building deletable."""
    import inspect
    from darkbrown.load import stage_00_wipe as w0
    src = inspect.getsource(w0.run)
    cc = src.index('_drop("Cost Center", cc)')
    clear = src.index("set cost_center = NULL")
    bldg = src.index('frappe.get_all("Building", pluck="name")')
    assert cc < clear < bldg, \
        "cost centres must go, then be unpointed, before buildings are deleted"

check("wipe orders its passes around the guards", t_wipe_orders_for_the_guards)
check("wipe reads its own delete result correctly", t_wipe_drop_result_read_correctly)
check("wipe clears cost centres before buildings", t_wipe_takes_cost_centres_before_buildings)
check("wipe error handler cannot itself throw", t_wipe_error_handler_cannot_throw)
check("wipe forces rather than cancelling", t_wipe_does_not_cancel_before_deleting)
check("wipe will not orphan ledger rows", t_wipe_will_not_orphan_the_ledger)
check("wipe refuses without the exact phrase", t_wipe_refuses_without_phrase)
check("wipe gate refuses to pass blind or on residue", t_wipe_gate_tells_residue_from_ruin)

# ---- L. the load pipeline

def t_load_data_matches_its_manifest():
    """A file and its manifest must not drift apart.

    opening_arrears.csv shipped as a header row and nothing else last time.
    The loader read it, found no rows, and reported a clean run. The site went
    live with no opening arrears and nothing said so.
    """
    import csv as _csv, json as _json, os as _os
    from darkbrown.load import common as LC
    d = REPO + '/darkbrown/load/data'
    man = _json.load(open(_os.path.join(d, 'manifest.json'), encoding='utf-8'))
    for name, m in man.items():
        if name.startswith('_'):
            continue
        path = _os.path.join(d, name)
        assert _os.path.exists(path), 'manifest names a missing file: %s' % name
        raw = open(path, 'rb').read()
        got = LC.digest(raw)   # the same function the loader uses, not a copy
        assert got == m['sha256'], '%s checksum %s, manifest says %s' % (name, got, m['sha256'])
        rows = list(_csv.DictReader(raw.decode('utf-8-sig').splitlines()))
        assert len(rows) == m['rows'], '%s has %d rows, manifest says %d' % (name, len(rows), m['rows'])
        assert rows, '%s is empty' % name
    # every CSV present must also be *named* in the manifest. Twice now a
    # stale manifest has been copied over a corrected one, and a file the
    # manifest does not mention would load with no checksum at all.
    on_disk = {f for f in _os.listdir(d) if f.endswith('.csv')}
    named = {k for k in man if not k.startswith('_')}
    assert on_disk == named, \
        'manifest and directory disagree: only on disk %s, only in manifest %s' \
        % (sorted(on_disk - named), sorted(named - on_disk))
    print('        (%d data files match the manifest)' % len(named))

def t_load_select_values_are_legal():
    """Every Select value in the data must exist in the doctype.

    FREQ was written from memory as 'Annually'. The doctype says 'Annual'.
    Nothing in today's data uses it, so nothing would have failed until the
    first annual lease arrived months from now.
    """
    import csv as _csv, glob as _glob, json as _json
    opts = {}
    for f in _glob.glob(REPO + '/darkbrown/darkbrown/doctype/*/*.json'):
        d = _json.load(open(f, encoding='utf-8'))
        if d.get('doctype') != 'DocType':
            continue
        for fld in d.get('fields', []):
            if fld.get('fieldtype') == 'Select':
                opts[(d['name'], fld['fieldname'])] = set(
                    (fld.get('options') or '').split('\n'))
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/buildings.csv', encoding='utf-8-sig')))
    for r in rows:
        assert r['status'] in opts[('Building', 'status')], \
            'Building.status %r is not a valid option' % r['status']
    leases = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/head_leases.csv', encoding='utf-8-sig')))
    for r in leases:
        assert r['payment_frequency'] in opts[('Head Lease', 'payment_frequency')], \
            'Head Lease.payment_frequency %r is not a valid option' % r['payment_frequency']
        assert r['status'] in opts[('Head Lease', 'status')], \
            'Head Lease.status %r is not a valid option' % r['status']
    from darkbrown.load import stage_02_buildings as s2
    for f in s2.FREQ:
        assert f in opts[('Head Lease', 'payment_frequency')], \
            'the loader would accept %r, which the doctype rejects' % f
    print('        (%d buildings, %d leases, every Select value legal)'
          % (len(rows), len(leases)))

def t_load_stages_expose_check_run_gate():
    from darkbrown.load import stage_01_landlords as s1
    from darkbrown.load import stage_02_buildings as s2
    from darkbrown.load import stage_00_wipe as s0
    for mod in (s0, s1, s2):
        for fn in ('check', 'run', 'gate'):
            assert callable(getattr(mod, fn, None)), \
                '%s has no %s()' % (mod.__name__, fn)

def t_load_normalise_folds_the_case_variants():
    """488 tenant names in the revenue worksheet fold to 435. The 53 that
    collapse are the same person typed twice, which is how the previous load
    produced 547 customers against 441 tenancies."""
    from darkbrown.load import common as LC
    assert LC.norm('HAMED HRAIZ') == LC.norm('Hamed Hraiz')
    assert LC.norm('Al Adekhar Real Estate Company WLL') == \
           LC.norm('AL ADEKHAR REAL ESTATE COMPANY  W.L.L.').replace('w l l', 'wll')
    assert LC.norm('  Spaced   Out  ') == 'spaced out'
    assert LC.norm(None) == ''

def t_load_data_lives_outside_patches():
    """patches/ is schema only. This is the rule that stops a loader creeping
    back in beside the migrations."""
    import glob as _glob, os as _os
    stray = [_os.path.basename(f) for f in _glob.glob(REPO + '/darkbrown/patches/*')
             if _os.path.splitext(f)[1].lower() in ('.csv', '.json', '.xlsx')]
    assert not stray, 'data files in patches/: %s' % stray
    assert _os.path.isdir(REPO + '/darkbrown/load/data'), 'load/data is missing'

def t_load_digest_survives_line_endings():
    """A checksum must guard the data, not the encoding.

    Git on Windows commits CRLF as LF, and the Linux server checks it out as
    LF. The first version hashed the raw bytes, so landlords.csv left here as
    fd01d278 and arrived as 070c3584 without one character changing. The guard
    blocked a load that was entirely correct.
    """
    from darkbrown.load import common as LC
    lf = b'a,b\n1,2\n3,4\n'
    crlf = b'a,b\r\n1,2\r\n3,4\r\n'
    cr = b'a,b\r1,2\r3,4\r'
    assert LC.digest(lf) == LC.digest(crlf) == LC.digest(cr), \
        'the checksum still depends on how the lines end'
    assert LC.digest(lf) != LC.digest(b'a,b\n1,2\n3,5\n'), \
        'the checksum no longer notices a changed figure'
    assert LC.digest(lf) != LC.digest(b'a,b\n1,2\n'), \
        'the checksum no longer notices a dropped row'

def t_units_never_load_not_ready():
    """Every unit must load Vacant.

    _sync_unit_occupancy returns early when the unit reads "Not Ready", so a
    unit left at the doctype default can never be marked Occupied however many
    live tenancies point at it. The portfolio would read empty with 296 flats
    let, and nothing would look broken.
    """
    import csv as _csv
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/units.csv', encoding='utf-8-sig')))
    bad = [r for r in rows if r['status'] != 'Vacant']
    assert not bad, "%d unit rows are not Vacant, e.g. %s" % (
        len(bad), bad[0])
    from darkbrown.load import stage_03_units as s3
    import inspect
    src = inspect.getsource(s3.run)
    assert 'u.status = "Vacant"' in src, \
        "the loader no longer forces Vacant"
    print('        (%d units, all Vacant)' % len(rows))

def t_unit_list_covers_synthetic_buildings():
    """The tracked fixture covers both synthetic scope-test buildings."""
    import csv as _csv
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/units.csv', encoding='utf-8-sig')))
    assert len(rows) == 4, 'expected 4 synthetic units, found %d' % len(rows)
    per = {}
    for r in rows:
        per[r['building']] = per.get(r['building'], 0) + 1
    assert per == {'SYN-A': 2, 'SYN-B': 2}, per

def t_tenants_are_people_not_placeholders():
    """VACANT and EMPTY mean the flat stood empty, not that someone rented it.

    125 revenue rows carry one or the other in the tenant column. Loaded
    literally they become two customers who between them rented 125
    flat-months, and every occupancy figure built on top is wrong.
    """
    import csv as _csv, re as _re
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/tenants.csv', encoding='utf-8-sig')))
    bad = [r['customer_name'] for r in rows
           if _re.match(r'^(vacant|empty|n/?a|unoccupied|not let|-+)$',
                        r['customer_name'].strip(), _re.I)]
    assert not bad, 'placeholders loaded as tenants: %s' % bad
    print('        (%d tenants, no placeholders)' % len(rows))

def t_tenant_folding_is_recorded_and_sane():
    """Synthetic match keys are unique and contain no hidden merges."""
    import csv as _csv
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/tenants.csv', encoding='utf-8-sig')))
    assert len(rows) == 2, 'expected 2 synthetic tenants, found %d' % len(rows)

    keys = [r['match_key'] for r in rows]
    assert len(keys) == len(set(keys)), 'the folded list still holds duplicates'

    assert all(r['customer_name'].startswith('Synthetic Tenant ') for r in rows)
    assert not any(r['name_variants'] for r in rows)
    print('        (%d synthetic tenants, unique match keys)' % len(rows))

check("load data matches its manifest", t_load_data_matches_its_manifest)
def t_contact_details_never_lose_a_tenant():
    """A phone number must not cost you a person.

    A joint lease carries two people, so the worksheet holds
    "55728528 / 66097515", and one cell reads "77101848 (handwritten
    correction; printed 77652938)". Frappe validates the field and rejects the
    lot — 33 tenants failed to load on the first run, each one lost to a
    contact number nobody needed.
    """
    import csv as _csv, re as _re
    from darkbrown.load import stage_04_tenants as s4

    assert s4._numbers('55728528 / 66097515') == ['55728528', '66097515']
    assert s4._numbers('77101848 (handwritten correction; printed 77652938)') \
        == ['77101848', '77652938']
    assert s4._numbers('') == [] and s4._numbers(None) == []
    assert s4._first_id('29335651868 / 29435649449') == '29335651868'

    # every number the worksheet holds must survive extraction cleanly
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/tenants.csv', encoding='utf-8-sig')))
    n = 0
    for r in rows:
        for phone in s4._numbers(r['mobile']):
            assert _re.match(r'^\+?[0-9][0-9 -]{5,19}$', phone), \
                'extracted %r, which Frappe would still reject' % phone
            n += 1
    assert n == 2, 'expected 2 synthetic phone values, found %d' % n

    # and the loader must fall back rather than drop the record
    import inspect
    src = inspect.getsource(s4.run)
    assert 'stripped.append' in src, \
        'a field-level failure no longer falls back to identity only'
    print('        (%d phone numbers, all clean)' % n)

check("tenants are people, not placeholders", t_tenants_are_people_not_placeholders)
check("a bad phone number never loses a tenant", t_contact_details_never_lose_a_tenant)
check("tenant folding is recorded and sane", t_tenant_folding_is_recorded_and_sane)
def t_unit_key_folds_narrowly():
    """The unit fold must join what is the same and never join what is not.

    The Tenancy Master writes 23 flats as F01 where Revenue writes F-01. An
    earlier fold stripped every separator to catch that, which also turned
    F-03/1 into F-31 — two different flats in TWR-20 collapsed into one, with
    nothing in the output to show it had happened.
    """
    from darkbrown.load import common as LC
    assert LC.unit_key('F01') == LC.unit_key('F-01') == 'F-01'
    assert LC.unit_key('F-1') == 'F-01'
    assert LC.unit_key('F-03/1') != LC.unit_key('F-31'), \
        'the fold merges two different flats'
    for verbatim in ('F-03/1', 'F-O/1', 'G-01A', 'G-01/GF', 'CABIN', 'VILLA'):
        assert LC.unit_key(verbatim) == verbatim, \
            '%s should be left alone' % verbatim

    import csv as _csv
    from collections import defaultdict
    rows = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/units.csv', encoding='utf-8-sig')))
    seen = defaultdict(list)
    for r in rows:
        seen[(r['building'], LC.unit_key(r['unit_no']))].append(r['unit_no'])
    clash = {k: v for k, v in seen.items() if len(v) > 1}
    assert not clash, 'the fold collides on real units: %s' % list(clash.items())[:3]
    print('        (%d units, no collisions)' % len(rows))

check("units all load Vacant, never Not Ready", t_units_never_load_not_ready)
check("unit-number fold joins only what is the same", t_unit_key_folds_narrowly)
def t_superseded_units_are_mapped_not_dropped():
    """A retired unit label must still resolve, or its history is orphaned.

    14 flats were renumbered — UG-169's F-01/S became F-01/FB with the same
    tenant on the same rent, TWR-20's F-12 became F-O/1. Loading both labels
    would show 14 phantom empty flats and put occupancy at 90.2% instead of
    94.7%. Dropping the old label without a map would strand the revenue
    booked against it.
    """
    import csv as _csv
    d = REPO + '/darkbrown/load/data/'
    units = list(_csv.DictReader(open(d + 'units.csv', encoding='utf-8-sig')))
    alias = list(_csv.DictReader(open(d + 'unit_aliases.csv', encoding='utf-8-sig')))
    live = {(u['building'], u['unit_no']) for u in units}

    for a in alias:
        assert (a['building'], a['old_unit_no']) not in live, \
            '%s %s is both a live unit and a superseded label' % (
                a['building'], a['old_unit_no'])
        assert (a['building'], a['unit_no']) in live, \
            '%s %s points at a unit that was not loaded' % (
                a['building'], a['unit_no'])
        assert a['evidence'], 'no evidence recorded for %s %s' % (
            a['building'], a['old_unit_no'])

    targets = [(a['building'], a['unit_no']) for a in alias]
    assert len(targets) == len(set(targets)), \
        'two old labels map to the same unit: %s' % [
            t for t in targets if targets.count(t) > 1][:2]
    print('        (%d live units, %d superseded labels mapped)'
          % (len(units), len(alias)))

check("unit list covers both synthetic buildings", t_unit_list_covers_synthetic_buildings)
check("superseded unit labels are mapped, not dropped", t_superseded_units_are_mapped_not_dropped)
check("checksum guards the data, not the line endings", t_load_digest_survives_line_endings)
def t_one_active_lease_per_building():
    """Two active leases on one building doubles its monthly cost.

    DAJ-21 now carries two periods — 28,000 for Sep-Oct 2025 when only 8 flats
    were under agreement, and 78,000 from November when the whole building was
    taken on. Only the second is Active. If both were, the portfolio cost would
    read 557,000 a month instead of 529,000 and nothing would look wrong.
    """
    import csv as _csv
    from collections import Counter
    leases = list(_csv.DictReader(
        open(REPO + '/darkbrown/load/data/head_leases.csv', encoding='utf-8-sig')))
    active = Counter(r['building_code'] for r in leases if r['status'] == 'Active')
    doubled = [b for b, n in active.items() if n > 1]
    assert not doubled, 'more than one active lease on %s' % doubled

    buildings = {r['building_code'] for r in _csv.DictReader(
        open(REPO + '/darkbrown/load/data/buildings.csv', encoding='utf-8-sig'))}
    unleased = sorted(buildings - set(active))
    assert not unleased, 'no active lease for %s' % unleased

    total = sum(int(float(r['annual_rent'])) for r in leases
                if r['status'] == 'Active')
    assert total == 264000, \
        'active annual rent is %d, expected synthetic total 264,000' % total
    print('        (%d leases, %d buildings, QAR %s a month)'
          % (len(leases), len(buildings), format(total // 12, ',')))

def t_fixture_has_one_lease_per_scope_building():
    """Both synthetic scope buildings have exactly one lease."""
    import csv as _csv
    leases = [r for r in _csv.DictReader(
        open(REPO + '/darkbrown/load/data/head_leases.csv', encoding='utf-8-sig'))
        if r['building_code'] in ('SYN-A', 'SYN-B')]
    assert len(leases) == 2, leases
    assert {r['building_code'] for r in leases} == {'SYN-A', 'SYN-B'}
    assert all(r['status'] == 'Active' for r in leases)

check("every Select value in the data is legal", t_load_select_values_are_legal)
check("one active head lease per building", t_one_active_lease_per_building)
check("synthetic fixture has one lease per scope building", t_fixture_has_one_lease_per_scope_building)
check("each stage exposes check, run and gate", t_load_stages_expose_check_run_gate)
check("name folding merges the case variants", t_load_normalise_folds_the_case_variants)
check("data lives outside patches/", t_load_data_lives_outside_patches)

# ---- P. patches.txt registers nothing that writes business records
def t_patches_safe():
    import re
    named = [l.strip() for l in open(REPO + '/darkbrown/patches.txt')
             if l.strip() and not l.startswith(('#', '['))]
    for m in named:
        path = REPO + '/' + m.replace('.', '/') + '.py'
        assert os.path.exists(path), "patches.txt names a missing module: %s" % m
        assert re.search(r'^def execute\(', open(path).read(), re.M), "%s has no execute()" % m

    # Structural rule, replacing the old denylist: patches/ holds schema only.
    # A data file here means a loader has crept back in alongside it.
    stray = [os.path.basename(f)
             for f in glob.glob(REPO + '/darkbrown/patches/*')
             if os.path.splitext(f)[1].lower() in ('.csv', '.json', '.xlsx')]
    assert not stray, "data files in darkbrown/patches/: %s" % stray
    print("        (%d schema patches registered, no data files alongside)" % len(named))
check("patches.txt registers no ledger-writing patch", t_patches_safe)

# ---- Q. finance deployment repairs
def t_billrun_count_is_posted_count():
    import inspect
    from darkbrown.api import app
    src = inspect.getsource(app.billruns)
    assert '"count": issued,' in src
    assert 'issued or drawn' not in src
    assert '"charge_snapshot"' in src
    assert 'kind == "Utility Recovery"' in src
    assert '"util": "util" in included.get' in src
check("invoice-run count reports issued invoices only", t_billrun_count_is_posted_count)

def t_cancelled_invoice_reopens_run():
    reset()
    S.DB['Invoice Run'] = [{
        'name': 'INV-RUN-1', 'status': 'Issued',
        'approved_by': 'gm@example.com', 'issued_on': '2026-09-21',
    }]
    S.DB['Invoice Run Line'] = [{
        'name': 'INV-RUN-LINE-1', 'parent': 'INV-RUN-1',
        'parenttype': 'Invoice Run', 'sales_invoice': 'SINV-1',
    }]
    from darkbrown.utils.invoice_run import on_sales_invoice_cancel
    on_sales_invoice_cancel(S.Doc('Sales Invoice', {'name': 'SINV-1'}))
    line = S.DB['Invoice Run Line'][0]
    run = S.DB['Invoice Run'][0]
    assert line['sales_invoice'] is None
    assert run['status'] == 'Pending GM'
    assert run['approved_by'] is None and run['issued_on'] is None
check("cancelling a Sales Invoice reopens its run for GM", t_cancelled_invoice_reopens_run)

def t_finance_ui_and_label_patch_are_wired():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    hooks = open(REPO + '/darkbrown/hooks.py').read()
    patches = open(REPO + '/darkbrown/patches.txt').read()
    label_patch = open(
        REPO + '/darkbrown/patches/normalize_invoice_reference_labels.py').read()
    assert 'Draft landlord accrual' in shell
    assert "finance.build_head_lease_payable" in shell
    assert "'head-lease-accrual'" in shell
    assert 'period_start:d.period' in shell
    assert "t:'date'" in shell
    assert 'utils.invoice_run.on_sales_invoice_cancel' in hooks
    assert 'darkbrown.patches.normalize_invoice_reference_labels' in patches
    assert '"Tenancy Agreement", "Tenancy Agreement"' in label_patch
check("finance UI, cancellation hook and label patch are wired",
      t_finance_ui_and_label_patch_are_wired)

def t_cancelled_run_recovery_is_explicit_and_scoped():
    import inspect
    from darkbrown.api import finance
    src = inspect.getsource(finance.reopen_cancelled_invoice_run)
    assert 'guard(MD, GM)' in src
    assert 'doc.status != "Issued"' in src
    assert '"docstatus") == 2' in src
    assert 'line.db_set("sales_invoice", None' in src
    assert 'doc.status = "Pending GM"' in src
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "finance.reopen_cancelled_invoice_run" in shell
    assert 'Reopen ${GEN.repairable} cancelled invoice' in shell
check("cancelled legacy invoice runs have a controlled recovery action",
      t_cancelled_run_recovery_is_explicit_and_scoped)

def t_existing_accrual_returns_truthful_summary():
    import inspect
    from darkbrown.api import finance
    src = inspect.getsource(finance.build_head_lease_payable)
    assert '["name", "grand_total"], as_dict=True' in src
    assert '"amount": _kk(existing.grand_total)' in src
    assert '"head_lease": lease.name' in src
check("duplicate Head Lease accrual returns its amount and source",
      t_existing_accrual_returns_truthful_summary)

def t_deposit_batch_rejects_untrusted_cheque_lines():
    from darkbrown.api import finance
    reset()
    mkcheque(name='CHQ-OUT', direction='Outgoing', status='Issued')
    try:
        finance.create_deposit_batch({
            'bank_account': 'QNB Main',
            'lines': [{'type': 'Cheque', 'cheque': 'CHQ-OUT',
                       'amount': 5000}],
        })
        assert False, 'outgoing cheque was accepted into a deposit batch'
    except S.ValidationError as exc:
        assert 'incoming cheque on hand' in str(exc)

    reset()
    mkcheque(name='CHQ-IN', amount=5000)
    try:
        finance.create_deposit_batch({
            'bank_account': 'QNB Main',
            'lines': [{'type': 'Cheque', 'cheque': 'CHQ-IN',
                       'amount': 4999}],
        })
        assert False, 'caller-controlled cheque amount was accepted'
    except S.ValidationError as exc:
        assert 'amount must match' in str(exc)
check("deposit batches reject outgoing and amount-tampered cheques",
      t_deposit_batch_rejects_untrusted_cheque_lines)

def t_deposit_batch_picker_only_shows_incoming_cheques():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "CHQ.filter(c=>c.dir==='in'&&c.st==='On hand')" in shell
check("deposit batch picker excludes outgoing cheques",
      t_deposit_batch_picker_only_shows_incoming_cheques)

def t_deposit_batch_enforces_same_user_override():
    from darkbrown.api import finance
    reset()
    S.DB['Deposit Batch'] = [{
        'name': 'DEP-1', 'status': 'Draft', 'prepared_by': S.SESSION['user'],
        'bank_account': 'QNB Main', 'lines': [], 'override_reason': None,
    }]
    try:
        finance.deposit_batch('DEP-1')
        assert False, 'same-user deposit succeeded without an override reason'
    except S.ValidationError as exc:
        assert 'override reason' in str(exc)
check("same-user deposit requires an auditable override reason",
      t_deposit_batch_enforces_same_user_override)

def t_deposit_batch_links_presented_cheque():
    from darkbrown.api import finance
    reset()
    mkcheque(name='CHQ-IN', amount=5000)
    line = S.Doc('Deposit Batch Line', {
        'name': 'DEP-LINE-1', 'payment_type': 'Cheque',
        'cheque': 'CHQ-IN', 'tenant': 'CUST-001', 'unit': None,
        'amount': 5000,
    })
    S.DB['Deposit Batch'] = [{
        'name': 'DEP-1', 'status': 'Draft', 'prepared_by': S.SESSION['user'],
        'bank_account': 'QNB Main', 'lines': [line], 'override_reason': None,
    }]
    result = finance.deposit_batch(
        'DEP-1', on='2026-09-21', reason='Synthetic single-operator test')
    cheque = S.DB['Cheque'][0]
    batch = S.DB['Deposit Batch'][0]
    actual = (result['status'], cheque['status'], cheque['presented_on'],
              cheque['deposit_batch'], batch['override_reason'])
    assert actual == ('Deposited', 'Deposited', '2026-09-21', 'DEP-1',
                      'Synthetic single-operator test'), actual
check("depositing a batch validates and links each presented cheque",
      t_deposit_batch_links_presented_cheque)

def t_statement_import_rejects_bad_scope_and_duplicates():
    from darkbrown.api import cashdesk
    base = {
        'bank_account': 'QNB Main', 'from_date': '2026-09-01',
        'to_date': '2026-09-30',
        'lines': [{'date': '2026-09-21', 'ref': 'SYN-1',
                   'narrative': 'Synthetic', 'amount': 100,
                   'direction': 'Credit'}],
    }
    cases = [
        dict(base, bank_account='NOT-A-BANK'),
        dict(base, from_date='2026-10-01', to_date='2026-09-01'),
        dict(base, lines=[dict(base['lines'][0], amount=-100)]),
        dict(base, lines=[dict(base['lines'][0], date='2026-10-01')]),
        dict(base, lines=base['lines'] + base['lines']),
    ]
    for payload in cases:
        reset()
        try:
            cashdesk.import_statement(payload)
            assert False, 'invalid statement import was accepted: %s' % payload
        except S.ValidationError:
            pass
check("statement imports reject invalid banks, periods, amounts and duplicates",
      t_statement_import_rejects_bad_scope_and_duplicates)

def t_statement_matching_is_bank_and_state_scoped():
    import inspect
    from darkbrown.api import cashdesk
    src = inspect.getsource(cashdesk.import_statement)
    assert "status in ('Deposited', 'Reconciled')" in src
    assert src.count('bank_account = %s') >= 3
    assert "deposit_batch is null or deposit_batch = ''" in src
    assert 'coalesce(presented_on, cheque_date)' in src
    assert "hp.status = 'Cleared'" in src
    assert 'coalesce(c.cleared_on, c.presented_on' in src
    assert 'if len(candidates) != 1' in src
check("statement matcher uses the correct bank and completed money state",
      t_statement_matching_is_bank_and_state_scoped)

def t_weekly_close_is_recomputed_and_snapshotted_server_side():
    from darkbrown.api import cashdesk
    reset()
    result = cashdesk.record_close({
        'period_end': '2026-09-17', 'status': 'Closed',
        'discrepancies': 0, 'manual_confirmed': [],
        'assigned_to': 'forged@example.com',
    })
    row = S.DB['Weekly Closing'][0]
    assert result['discrepancies'] == 4, result
    assert row['discrepancies'] == 4
    assert row['assigned_to'] == S.SESSION['user']
    assert 'Not confirmed: Landlord cheque schedule confirmed' in row['notes']
    snapshot = json.loads(row['check_snapshot'])
    assert snapshot['closed_by'] == S.SESSION['user']
    assert len(snapshot['checks']) == 8
check("weekly close recomputes discrepancies and stores its audit snapshot",
      t_weekly_close_is_recomputed_and_snapshotted_server_side)

def t_weekly_close_rejects_bad_periods_and_manual_keys():
    from datetime import date, timedelta
    from darkbrown.api import cashdesk
    now = date.today()
    future_thursday = now + timedelta(days=((3 - now.weekday()) % 7 or 7))
    for payload in (
        {'period_end': '2026-09-16', 'status': 'Closed'},
        {'period_end': future_thursday.isoformat(), 'status': 'Closed'},
        {'period_end': '2026-09-17', 'status': 'Closed',
         'manual_confirmed': ['invented-check']},
    ):
        reset()
        try:
            cashdesk.record_close(payload)
            assert False, 'invalid weekly close was accepted: %s' % payload
        except S.ValidationError:
            pass
check("weekly close rejects non-Thursday, future and forged confirmations",
      t_weekly_close_rejects_bad_periods_and_manual_keys)

def t_weekly_statement_check_requires_date_overlap():
    from darkbrown.api import cashdesk
    reset()
    S.DB['Bank Statement Import'] = [{
        'name': 'BSI-LATER', 'from_date': '2026-09-21',
        'to_date': '2026-09-21',
    }]
    checks = cashdesk._checks('2026-09-11', '2026-09-17')
    stmt = next(c for c in checks if c['k'] == 'stmt')
    assert not stmt['ok'] and stmt['count'] == 0, stmt
    S.DB['Bank Statement Import'].append({
        'name': 'BSI-OVERLAP', 'from_date': '2026-09-10',
        'to_date': '2026-09-12',
    })
    checks = cashdesk._checks('2026-09-11', '2026-09-17')
    stmt = next(c for c in checks if c['k'] == 'stmt')
    assert stmt['ok'] and stmt['count'] == 1, stmt
check("weekly close counts only statements overlapping its period",
      t_weekly_statement_check_requires_date_overlap)

def t_weekly_close_ui_sends_confirmed_keys_not_counts():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    action = shell[shell.index("'start-close':{\n m:'cashdesk.record_close'"):
                   shell.index("/* ---------------- money ---------------- */")]
    assert 'manual_confirmed:' in action
    assert 'discrepancies:open' not in action
check("weekly close UI sends attestations and leaves counting to the server",
      t_weekly_close_ui_sends_confirmed_keys_not_counts)

def t_weekly_close_returns_and_renders_the_recorded_snapshot():
    from darkbrown.api import cashdesk
    reset()
    cashdesk.record_close({
        'period_end': '2026-09-17', 'status': 'Closed',
        'manual_confirmed': [],
    })
    saved = json.loads(S.DB['Weekly Closing'][0]['check_snapshot'])['checks']
    assert len(saved) == 8, saved
    manual = [c for c in saved if c['kind'] == 'manual']
    assert len(manual) == 3 and all(not c['ok'] for c in manual), manual
    import inspect
    api = inspect.getsource(cashdesk.closing)
    assert 'frappe.parse_json(d.check_snapshot)' in api
    assert '"checks": recorded_checks' in api

    shell = open(REPO + '/darkbrown/shell/index.html').read()
    route = shell[shell.index('ROUTES.closing=()=>{'):
                  shell.index('/* ---------------- Approvals (2E) ---------------- */')]
    assert "Array.isArray(cur.checks)" in route
    assert "chip('Not confirmed','a')" in route
    form = shell[shell.index("'start-close':{t:'Weekly close'"):
                 shell.index("'record-inspection':")]
    assert 'const totalOpen=open.length+manualOpen.length' in form
check("weekly close renders its immutable snapshot and honest manual status",
      t_weekly_close_returns_and_renders_the_recorded_snapshot)

def _statement_node(acc, label, cls='Expense', parent=None, group=False,
                    account_type='', dr=0, cr=0):
    return {'acc': acc, 'code': label, 'label': label, 'cls': cls,
            'nat': 'Dr' if cls in ('Asset', 'Expense') else 'Cr',
            'type': account_type, 'group': group, 'parent': parent,
            'lft': 0, 'kids': [], 'dr': dr, 'cr': cr}

def t_profit_and_loss_honours_mapped_heads_on_legacy_chart():
    from darkbrown.api import statements
    root = _statement_node('EXP', 'Expenses', group=True)
    nodes = {'EXP': root}
    for acc, label, amount in (
        ('HL', 'Head Lease Rent', 100),
        ('SAL', 'Salary', 30),
        ('DEP', 'Depreciation', 10),
        ('ODD', 'Unmapped legacy expense', 5),
    ):
        nodes[acc] = _statement_node(acc, label, parent='EXP', dr=amount)
        root['kids'].append(nodes[acc])
    groups = {g['key']: g for g in statements._expense_groups(nodes)}
    assert groups['Cost of Sales']['total'] == 100, groups
    assert groups['Staff Cost']['total'] == 30, groups
    assert groups['Depreciation and Amortisation']['total'] == 10, groups
    assert groups['Other']['total'] == 5, groups
    assert sum(g['total'] for g in groups.values()) == 145
check("P&L mapping survives legacy account parentage without changing the ledger",
      t_profit_and_loss_honours_mapped_heads_on_legacy_chart)

def t_cash_flow_excludes_the_historical_cutover_control():
    from darkbrown.api import statements
    nodes = {
        'BANK': _statement_node('BANK', 'Qatar National Bank', cls='Asset',
                                account_type='Bank'),
        'CONTROL': _statement_node('CONTROL', 'Historical Cutover Control',
                                   cls='Asset', account_type='Cash'),
    }
    cash = statements._cash_accounts(nodes)
    assert list(cash) == ['BANK'], cash
    assert statements._excluded_cash_controls(nodes) == [
        'Historical Cutover Control']
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'legacy cutover clearing account, not money at bank' in shell
check("cash flow excludes the non-cash historical cutover control",
      t_cash_flow_excludes_the_historical_cutover_control)

def t_cash_flow_ignores_same_side_noncash_reclassification():
    from darkbrown.api import statements
    rows = [
        types.SimpleNamespace(account='DEPOSIT', debit=100, credit=0),
        types.SimpleNamespace(account='INCOME', debit=0, credit=20),
    ]
    outflow = statements._cash_counterparts(rows, -80)
    assert [r.account for r in outflow] == ['DEPOSIT'], outflow

    receipt = [
        types.SimpleNamespace(account='DEPOSIT', debit=0, credit=100),
        types.SimpleNamespace(account='FEE', debit=5, credit=0),
    ]
    inflow = statements._cash_counterparts(receipt, 95)
    assert [r.account for r in inflow] == ['DEPOSIT'], inflow
check("cash flow excludes same-side non-cash voucher legs",
      t_cash_flow_ignores_same_side_noncash_reclassification)

def t_receipts_reject_untyped_bank_account_mappings():
    from darkbrown.api import finance
    reset()
    assert finance._paid_to('QNB Main', 'DarkBrown RealEstate') == \
        'QNB Main - DB'
    S.DB['Account'].append({
        'name':'QNB Current Account - DB',
        'account_name':'QNB Current Account', 'root_type':'Asset',
        'account_type':'', 'is_group':0, 'disabled':0,
        'company':'DarkBrown RealEstate'})
    S.DB['Bank Account'].append({
        'name':'QNB Untyped', 'account':'QNB Current Account - DB'})
    assert finance._paid_to('QNB Untyped', 'DarkBrown RealEstate') is None
    assert finance._paid_to('Historical Cutover Control - DB',
                            'DarkBrown RealEstate') is None
check("receipts reject bank mappings that cash flow cannot recognise",
      t_receipts_reject_untyped_bank_account_mappings)

def t_voucher_detail_uses_source_document_cancellation():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    start = shell.index('function journalDetail(id)')
    detail = shell[start:shell.index(
        '/* ================================================================', start)]
    assert "actbtn('Reverse entry')" not in detail
    assert "'Sales Invoice':'Cancel the source Sales Invoice" in detail
    assert "'Payment Entry':'Cancel the source Payment Entry" in detail
    assert "['Correction path',correction]" in detail
    assert 'creates a mirror entry' not in detail
check("voucher detail directs corrections through the source document",
      t_voucher_detail_uses_source_document_cancellation)

def t_expense_register_totals_are_not_limited_with_rows():
    import inspect
    from darkbrown.api import expenses
    src = inspect.getsource(expenses.register)
    assert 'group by expense_head, basis, payment_mode' in src
    assert '"returned": len(out)' in src
    assert '"capped": total_count > len(out)' in src
    assert 'total = sum(flt(r.amount) for r in summary)' in src
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'The summary totals and common-cost pool include the full selected' in shell
check("expense totals cover the full period when register rows are capped",
      t_expense_register_totals_are_not_limited_with_rows)

def t_account_window_is_labelled_as_movement_not_balance():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    coa = shell[shell.index('ROUTES.coa=()=>{'):
                shell.index('/* ---------- Journal entries list ---------- */')]
    ledger = shell[shell.index('ROUTES.ledger=()=>{'):
                   shell.index('/* The paperwork step attaches',
                               shell.index('ROUTES.ledger=()=>{'))]
    assert "movement '+periodSpan()" in coa
    assert "<th class=\"r\">Net movement</th>" in coa
    assert "Liability:'Liabilities'" in coa
    assert 'Account movement <span class="plabel">${periodSpan()}' in ledger
    assert "['Bank movement'" in ledger
    assert "['Net movement'" in ledger
    assert 'window movement ${money(Math.abs(b.bal))}' in ledger
    assert "function movementSide(b)" in shell
    assert "return b.bal<0?(b.nat==='Dr'?'Cr':'Dr'):b.nat" in shell
    assert "money(Math.abs(b.bal))+' '+movementSide(b)" in ledger
    assert '${movementSide({bal:r.bal,nat:a[3]})}' in ledger
    assert '${money(Math.abs(b.bal))} ${movementSide(b)}' in coa
check("account screens describe selected-window movement accurately",
      t_account_window_is_labelled_as_movement_not_balance)

def t_statement_match_closes_the_deposit_batch_lifecycle():
    import inspect
    from darkbrown.api import app, cashdesk
    importer = inspect.getsource(cashdesk.import_statement)
    assert 'line.matched_type == "Deposit Batch"' in importer
    assert '"status": "Reconciled"' in importer
    assert '"bank_statement_import": doc.name' in importer
    assert '"reconciled_by": frappe.session.user' in importer
    feed = inspect.getsource(app.batches)
    assert 'legacy_recon' in feed
    assert 'effective_status = "Reconciled" if recon_import' in feed
    batch_schema = json.load(open(
        REPO + '/darkbrown/darkbrown/doctype/deposit_batch/deposit_batch.json'))
    fields = {f['fieldname'] for f in batch_schema['fields']}
    assert {'bank_statement_import', 'reconciled_by',
            'reconciled_on'} <= fields
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "['Reconciled by',b.reconciled_by]" in shell
check("a matched statement line closes and audits its deposit batch",
      t_statement_match_closes_the_deposit_batch_lifecycle)

def t_reconciled_batch_posting_is_explicit_and_idempotent():
    import inspect
    from darkbrown.api import cashdesk
    src = inspect.getsource(cashdesk.post_reconciled_batch)
    assert '"matched_type": "Deposit Batch"' in src
    assert 'from darkbrown.api.finance import clear_cheque' in src
    assert 'before = frappe.db.get_value("Cheque", line.cheque, "payment_entry")' in src
    assert '(existing if before else posted).append(item)' in src
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "fbtn('Post cleared cheques','post-reconciled-batch'" in shell
    assert "m:'cashdesk.post_reconciled_batch'" in shell
check("reconciled batch posting is reviewed, explicit and idempotent",
      t_reconciled_batch_posting_is_explicit_and_idempotent)

def t_receipts_link_back_to_their_cleared_cheques():
    import inspect
    from darkbrown.api import finance
    listing = inspect.getsource(finance.receipts)
    detail = inspect.getsource(finance.receipt)
    assert 'cheque_refs = set(frappe.get_all(' in listing
    assert '_receipt_row(r, names, cheque_refs)' in listing
    assert '{"name": pe.reference_no} if named_cheque' in detail
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "!RCPT.some(r=>r.chq===c.id)" in shell
check("cleared-cheque receipts are linked and not offered for duplicate issue",
      t_receipts_link_back_to_their_cleared_cheques)

def t_reconciled_batch_does_not_roll_cheques_back_to_received():
    import inspect
    from darkbrown.darkbrown.doctype.deposit_batch.deposit_batch import DepositBatch
    src = inspect.getsource(DepositBatch.on_update)
    assert 'if self.status == "Draft"' in src
    assert 'elif self.status == "Deposited"' in src
    assert 'elif self.status == "Cancelled"' in src
    assert 'Reconciled deliberately changes no cheque status' in src
    assert '"Deposited" if self.status == "Deposited" else "Received"' not in src
check("saving a reconciled batch preserves its cleared cheque state",
      t_reconciled_batch_does_not_roll_cheques_back_to_received)

def t_ledger_headlines_use_full_window_not_capped_vouchers():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    route = shell[shell.index('ROUTES.ledger=()=>{'):
                  shell.index('window.openAcct=', shell.index('ROUTES.ledger=()=>{'))]
    assert 'const totDr=COA.reduce((s,a)=>s+(a[4]||0),0)' in route
    assert 'const totCr=COA.reduce((s,a)=>s+(a[5]||0),0)' in route
    assert 'const totDr=JRN.reduce' not in route
check("ledger headline totals do not change when the voucher list is capped",
      t_ledger_headlines_use_full_window_not_capped_vouchers)

def t_moveout_settlement_syncs_deposit_deductions():
    from darkbrown.api import operations
    reset()
    S.DB['Security Deposit'].append({
        'name':'SD-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'company':'DarkBrown RealEstate', 'amount':1000, 'deductions':0,
        'status':'Held', 'receipt_method':'Transfer'})
    S.DB['Move Out Case'].append({
        'name':'MO-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'unit':None, 'building':'Al Sadd', 'security_deposit':'SD-1',
        'status':'Settlement Pending', 'deposit_held':1000,
        'outstanding_rent':0, 'utilities_due':40, 'damages_charged':0})
    result = operations.advance_moveout('MO-1', {
        'step':'settle', 'outstanding_rent':100, 'damages_charged':60})
    sd = S.DB['Security Deposit'][0]
    assert result['status'] == 'Refund Pending', result
    assert sd['deductions'] == 200, sd
    assert sd['move_out_case'] == 'MO-1', sd
    assert 'Outstanding rent: QAR 100.00' in sd['deduction_reason']
    assert 'Utilities: QAR 40.00' in sd['deduction_reason']
    assert 'Damages: QAR 60.00' in sd['deduction_reason']
check("move-out settlement carries itemised deductions to the deposit approval",
      t_moveout_settlement_syncs_deposit_deductions)

def t_moveout_pending_release_is_not_rendered_closed():
    from darkbrown.api import app
    assert app.MO_STEP['Refund Pending'] == 3, app.MO_STEP
    assert app.MO_STEP['Closed'] == 4, app.MO_STEP
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert shell.count("'Deposit release pending','Closed'") >= 2
    assert "'Deposit release approved','Closed'" not in shell
check("pending deposit release is not displayed as a closed move-out",
      t_moveout_pending_release_is_not_rendered_closed)

def t_moveout_inspection_preserves_damage_and_utility_categories():
    from darkbrown.api import operations
    reset()
    S.DB['Move Out Case'].append({
        'name':'MO-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'unit':None, 'building':'Al Sadd', 'security_deposit':'SD-1',
        'status':'Notice Received', 'deposit_held':100,
        'outstanding_rent':0, 'utilities_due':0, 'damages_amount':0,
        'damages_charged':0})
    result = operations.advance_moveout('MO-1', {
        'step':'inspection', 'inspection_on':'2026-09-23',
        'notes':'Controlled inspection', 'damages':10, 'utilities_due':10})
    case = S.DB['Move Out Case'][0]
    assert result['status'] == 'Inspection Done', result
    assert case['damages_amount'] == 10, case
    assert case['damages_charged'] == 10, case
    assert case['utilities_due'] == 10, case
check("move-out inspection keeps damage and utility deductions distinct",
      t_moveout_inspection_preserves_damage_and_utility_categories)

def t_moveout_shell_uses_live_case_values_for_release():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    inspection = shell[shell.index("'record-inspection':{t:"):
                       shell.index("'deposit-release':{t:")]
    release = shell[shell.index("'deposit-release':{t:"):
                    shell.index("'record-contact':{t:")]
    binding = shell[shell.rindex("'record-inspection':{"):
                    shell.index("/* ---------------- the rest", shell.rindex("'record-inspection':{"))]
    assert 'n0(11200)' not in inspection
    assert 'n0(11200)' not in release
    assert "const m=MO(d.__ctx&&d.__ctx.id)||{}" in inspection
    assert "const m=MO(d.__ctx&&d.__ctx.id)||{}" in release
    assert "method==='Transfer'" in release
    assert "utilities_due:+wNum(d.d4).toFixed(2)" in binding
    assert "damages_charged:amount('Damages')" in binding
check("move-out modals and bindings use live deposit and deduction values",
      t_moveout_shell_uses_live_case_values_for_release)

def t_deposit_release_posts_balanced_refund_journal():
    from darkbrown.api import approvals
    reset()
    S.DB['Security Deposit'].append({
        'name':'SD-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'company':'DarkBrown RealEstate', 'amount':1000, 'deductions':200,
        'deduction_reason':'Rent 100; utilities and damage 100',
        'status':'Held', 'receipt_method':'Cash',
        'move_out_case':'MO-1', 'refund_journal_entry':None})
    S.DB['Move Out Case'].append({
        'name':'MO-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'unit':None, 'building':'Al Sadd', 'security_deposit':'SD-1',
        'status':'Refund Pending', 'deposit_held':1000,
        'outstanding_rent':100, 'utilities_due':40, 'damages_charged':60})
    result = approvals._deposit('SD-1', 'approve', 'Controlled test')
    inserted = [c for c in S.CALLS
                if c[0] == 'insert' and c[1] == 'Journal Entry']
    assert inserted, 'deposit release did not create a Journal Entry'
    accounts = inserted[-1][2]['accounts']
    debit = sum(float(a.get('debit_in_account_currency') or 0)
                for a in accounts)
    credit = sum(float(a.get('credit_in_account_currency') or 0)
                 for a in accounts)
    assert (debit, credit) == (1000, 1000), accounts
    cash_lines = [a for a in accounts
                  if float(a.get('credit_in_account_currency') or 0) == 800]
    assert cash_lines and cash_lines[0]['account'] == 'Cash - DB', accounts
    assert result['refund'] == 800, result
    assert result['journal_entry'], result
    assert S.DB['Security Deposit'][0]['refund_journal_entry'] == result['journal_entry']
    assert S.DB['Move Out Case'][0]['status'] == 'Closed'
    assert any(c[0] == 'submit' and c[1] == 'Journal Entry' for c in S.CALLS), \
        'refund journal was left in draft'
check("MD deposit approval posts and links a balanced refund journal",
      t_deposit_release_posts_balanced_refund_journal)

def t_deposit_release_correction_reopens_complete_chain():
    from darkbrown.api import approvals
    reset()
    S.frappe.session.user = 'Administrator'
    S.DB['Security Deposit'].append({
        'name':'SD-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'company':'DarkBrown RealEstate', 'amount':1000, 'deductions':200,
        'deduction_reason':'Damage 200', 'status':'Partially Refunded',
        'receipt_method':'Cash', 'move_out_case':'MO-1',
        'refunded_on':'2026-09-23', 'refund_journal_entry':'JV-1'})
    S.DB['Move Out Case'].append({
        'name':'MO-1', 'tenancy_agreement':'TA-1', 'tenant':'CUST-001',
        'unit':'UNIT-1', 'building':'Al Sadd', 'security_deposit':'SD-1',
        'status':'Closed', 'deposit_held':1000, 'outstanding_rent':0,
        'utilities_due':100, 'damages_charged':100,
        'refund_paid_on':'2026-09-23', 'refund_method':'Cash'})
    S.DB['Tenancy Agreement'].append({'name':'TA-1','status':'Terminated'})
    S.DB['Unit'].append({'name':'UNIT-1','status':'Not Ready'})
    S.DB['Journal Entry'].append({
        'name':'JV-1', 'docstatus':1,
        'user_remark':'Security deposit settlement SD-1 for move-out MO-1'})
    result = approvals.reopen_deposit_release(
        'SD-1', 'JV-1', 'Wrong cash account selected')
    assert result['status'] == 'Held', result
    assert result['move_out_status'] == 'Refund Pending', result
    assert any(c[0] == 'cancel' and c[2]['name'] == 'JV-1' for c in S.CALLS)
    assert S.DB['Security Deposit'][0]['refund_journal_entry'] is None
    assert S.DB['Move Out Case'][0]['refund_paid_on'] is None
    assert S.DB['Tenancy Agreement'][0]['status'] == 'Active'
    assert S.DB['Unit'][0]['status'] == 'Occupied'
check("deposit correction cancels the journal and reopens the complete chain",
      t_deposit_release_correction_reopens_complete_chain)

def t_shell_wires_guarded_deposit_correction():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "fbtn('Correct deposit settlement','reopen-deposit-release'" in shell
    assert "m:'approvals.reopen_deposit_release'" in shell
    assert 'This reverses a posted financial transaction.' in shell
check("journal detail exposes the guarded deposit correction workflow",
      t_shell_wires_guarded_deposit_correction)

def _maintenance_fixture():
    reset()
    S.DB['DBR Settings'][0]['emergency_maintenance_ceiling'] = 2000
    S.DB['Maintenance Request'] = []
    S.DB['Unit'] = [
        {'name':'UNIT-1', 'building':'Al Sadd', 'status':'Occupied'},
        {'name':'UNIT-2', 'building':'Other Building', 'status':'Occupied'},
    ]
    S.DB['Building'].append({'name':'Other Building'})
    S.DB['Tenancy Agreement'] = [{
        'name':'TA-MNT-1', 'building':'Al Sadd', 'unit':'UNIT-1',
        'tenant':'CUST-001', 'status':'Active', 'monthly_rent':5000,
        'start_date':'2026-01-01', 'end_date':'2026-12-31',
        'payment_frequency':'Monthly'}]

def t_maintenance_creation_persists_cost_assignment_and_recharge_scope():
    _maintenance_fixture()
    old_user, old_roles = S.frappe.session.user, list(S.SESSION['roles'])
    try:
        S.frappe.session.user = 'Administrator'
        S.SESSION['roles'] = ['Managing Director']
        from darkbrown.api import operations
        result = operations.raise_job({
            'building':'Al Sadd', 'unit':'UNIT-1', 'category':'Plumbing',
            'priority':'Medium', 'issue':'Leaking sink',
            'estimated_cost':1250, 'assigned_to':'maintenance@darkbrown.qa',
            'rechargeable':1})
        row = next(r for r in S.DB['Maintenance Request']
                   if r['name'] == result['case'])
        assert row['status'] == 'Assigned', row
        assert row['assigned_to'] == 'maintenance@darkbrown.qa', row
        assert row['cost'] == 1250, row
        assert row['cost_lines'][0]['amount'] == 1250, row
        assert row['recharge_to'] == 'CUST-001', row
        assert row['recharge_tenancy'] == 'TA-MNT-1', row
        assert row['recharge_amount'] == 1250, row
        assert row['recharge_status'] == 'Pending', row
    finally:
        S.frappe.session.user, S.SESSION['roles'] = old_user, old_roles
check("maintenance creation persists assignment, cost and tenancy recharge scope",
      t_maintenance_creation_persists_cost_assignment_and_recharge_scope)

def t_maintenance_refuses_a_unit_from_another_building():
    _maintenance_fixture()
    old_user, old_roles = S.frappe.session.user, list(S.SESSION['roles'])
    try:
        S.frappe.session.user = 'Administrator'
        S.SESSION['roles'] = ['Managing Director']
        from darkbrown.api import operations
        try:
            operations.raise_job({
                'building':'Al Sadd', 'unit':'UNIT-2', 'category':'Electrical',
                'priority':'High', 'issue':'Test', 'estimated_cost':500})
            assert False, 'cross-building unit was accepted'
        except S.ValidationError:
            assert 'does not belong to Al Sadd' in S.THROWN[-1], S.THROWN[-1]
        assert not S.DB['Maintenance Request']
    finally:
        S.frappe.session.user, S.SESSION['roles'] = old_user, old_roles
check("maintenance creation rejects a unit from another building",
      t_maintenance_refuses_a_unit_from_another_building)

def t_emergency_maintenance_approval_cannot_be_bypassed_by_cost_change():
    _maintenance_fixture()
    old_user, old_roles = S.frappe.session.user, list(S.SESSION['roles'])
    try:
        S.frappe.session.user = 'Administrator'
        S.SESSION['roles'] = ['Managing Director']
        from darkbrown.api import operations, approvals
        raised = operations.raise_job({
            'building':'Al Sadd', 'unit':'UNIT-1', 'category':'Electrical',
            'priority':'Emergency', 'issue':'Main breaker failure',
            'estimated_cost':3000, 'assigned_to':'maintenance@darkbrown.qa'})
        job = raised['case']
        assert raised['over_ceiling'] is True, raised
        try:
            operations.advance_job(job, 'In Progress', cost=3000)
            assert False, 'unapproved emergency work started'
        except S.ValidationError:
            assert 'needs MD approval' in S.THROWN[-1], S.THROWN[-1]

        approved = approvals.decide(
            'Emergency maint.', job, 'approve', 'Restore essential power')
        assert approved['status'] == 'Assigned', approved
        stored = next(r for r in S.DB['Maintenance Request']
                      if r['name'] == job)
        assert stored['ceiling_approved_by'] == 'Administrator', stored
        assert stored['over_ceiling'] == 0, stored

        try:
            operations.advance_job(job, 'In Progress', cost=3500)
            assert False, 'a higher cost reused the old approval'
        except S.ValidationError:
            assert 'needs MD approval' in S.THROWN[-1], S.THROWN[-1]
        stored = next(r for r in S.DB['Maintenance Request']
                      if r['name'] == job)
        assert stored['status'] == 'Assigned', stored
        assert stored['cost'] == 3000, stored
        assert stored['ceiling_approved_by'] == 'Administrator', stored

        moved = operations.advance_job(job, 'In Progress', cost=3000)
        assert moved['status'] == 'In Progress', moved
        done = operations.advance_job(
            job, 'Resolved', cost=3000,
            notes='Breaker and damaged cable replaced; supply tested.')
        assert done['status'] == 'Resolved', done
    finally:
        S.frappe.session.user, S.SESSION['roles'] = old_user, old_roles
check("emergency maintenance approval is required again after a cost change",
      t_emergency_maintenance_approval_cannot_be_bypassed_by_cost_change)

def t_maintenance_status_rules_and_recharge_handoff_are_wired():
    import inspect
    from darkbrown.api import finance, operations, app
    from darkbrown.utils import invoice_run
    advance = inspect.getsource(operations.advance_job)
    billing = inspect.getsource(finance.build_invoice_run)
    cancellation = inspect.getsource(invoice_run.on_sales_invoice_cancel)
    feed = inspect.getsource(app.jobs)
    assert 'status == "Scheduled" and not effective_schedule' in advance
    assert 'status == "Resolved" and not (notes or doc.resolution_notes)' in advance
    assert 'doc.recharge_status == "Invoiced"' in advance
    assert '"recharge_status": "Queued"' in billing
    assert '"source_doctype": "Maintenance Request"' in billing
    assert '"recharge_status": "Queued"' in cancellation
    invoice_cancel = inspect.getsource(finance.cancel_run_invoice)
    assert 'only a wholly unpaid invoice can be cancelled here' in invoice_cancel
    assert 'si.cancel()' in invoice_cancel
    assert 'parenttype": "Invoice Run"' in invoice_cancel
    assert '"ceiling_approved_by"' in feed
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'assigned_to:d.assigned||null' in shell
    assert "['Resolved','Cancelled'].includes(j.raw_status)?''" in shell
    assert 'before work starts.' in shell
    assert "m:'finance.cancel_run_invoice'" in shell
    assert "d.kind==='Cancel the invoice entirely'" in shell
    assert "fbtn('Cancel this invoice','amend-invoice'" in shell
    assert "window.DB_LIVE?'Cancel an issued invoice'" in shell
    assert "window.DB_LIVE?'Cancel invoice':'Send to the General Manager'" in shell
    assert "Only a wholly unpaid invoice raised by an Invoice Run" in shell
    assert "window.DB_LIVE?'Ledger reversal':'Credit note'" in shell
check("maintenance status, audit and tenant-recharge lifecycle are wired",
      t_maintenance_status_rules_and_recharge_handoff_are_wired)

def _utility_fixture():
    reset()
    S.DB['Unit'] = [
        {'name':'UNIT-1','building':'Al Sadd','status':'Occupied','area_sqm':60},
        {'name':'UNIT-2','building':'Al Sadd','status':'Occupied','area_sqm':40},
    ]
    S.DB['Tenancy Agreement'] = [
        {'name':'TA-U1','building':'Al Sadd','unit':'UNIT-1','tenant':'CUST-001',
         'status':'Active','start_date':'2026-01-01','end_date':'2026-12-31',
         'monthly_rent':5000,'payment_frequency':'Monthly'},
        {'name':'TA-U2','building':'Al Sadd','unit':'UNIT-2','tenant':'CUST-002',
         'status':'Active','start_date':'2026-01-01','end_date':'2026-12-31',
         'monthly_rent':4500,'payment_frequency':'Monthly'},
    ]
    S.DB['Utility Bill'] = []
    S.DB['Utility Bill Allocation'] = []

def t_utility_bill_capture_allocates_without_posting_income():
    _utility_fixture()
    from darkbrown.api import utilities
    result = utilities.record_bill(json.dumps({
        'building':'Al Sadd','utility_type':'Kahramaa',
        'bill_no':'KM-TEST-001','period_start':'2026-09-01',
        'period_end':'2026-09-23','amount':1000,
        'consumption':2500,'allocation_basis':'Area'}))
    assert result['status'] == 'Allocated', result
    assert result['allocated'] == 1000, result
    bill = S.DB['Utility Bill'][0]
    assert [r['amount'] for r in bill['allocations']] == [600, 400], bill
    assert [r['tenant'] for r in bill['allocations']] == ['CUST-001','CUST-002']
    assert not [c for c in S.CALLS if c[1:2] in (('Sales Invoice',),
                                                  ('Journal Entry',))]
check("utility capture validates and allocates without touching the ledger",
      t_utility_bill_capture_allocates_without_posting_income)

def t_manual_utility_allocation_refuses_cross_building_units():
    _utility_fixture()
    S.DB['Unit'].append({'name':'OTHER-1','building':'Other','status':'Occupied'})
    from darkbrown.api import utilities
    try:
        utilities.record_bill(json.dumps({
            'building':'Al Sadd','utility_type':'Water','bill_no':'W-TEST-001',
            'period_start':'2026-09-01','period_end':'2026-09-23','amount':500,
            'allocation_basis':'Manual',
            'allocations':[{'unit':'OTHER-1','amount':500}]}))
        assert False, 'cross-building utility allocation was accepted'
    except S.ValidationError:
        assert 'no live tenancy in this building' in S.THROWN[-1], S.THROWN[-1]
check("manual utility allocations cannot cross the building boundary",
      t_manual_utility_allocation_refuses_cross_building_units)

def t_utility_recovery_is_reserved_for_the_governed_invoice_run():
    _utility_fixture()
    # September is not a rent month for the quarterly agreement that began in
    # January. Its monthly utility recovery must still get its own run line.
    S.DB['Tenancy Agreement'][1]['payment_frequency'] = 'Quarterly'
    S.DB['Utility Bill'].append({
        'name':'UB-1','building':'Al Sadd','utility_type':'Kahramaa',
        'bill_no':'KM-TEST-002','status':'Allocated',
        'period_end':'2026-09-23','amount':1000})
    S.DB['Utility Bill Allocation'].extend([
        {'name':'UBA-1','parent':'UB-1','unit':'UNIT-1','tenant':'CUST-001',
         'amount':600,'invoice_run':None,'sales_invoice':None},
        {'name':'UBA-2','parent':'UB-1','unit':'UNIT-2','tenant':'CUST-002',
         'amount':400,'invoice_run':None,'sales_invoice':None},
    ])
    from darkbrown.api import finance
    made = finance.build_invoice_run('Al Sadd','2026-09-01')
    run = S.DB['Invoice Run'][0]
    assert len(run['lines']) == 2, run['lines']
    charges = json.loads(run['lines'][0]['charge_snapshot'])
    utility = next(c for c in charges
                   if c.get('source_doctype') == 'Utility Bill Allocation')
    assert utility['source_name'] == 'UBA-1', utility
    assert utility['amount'] == 600, utility
    quarterly = run['lines'][1]
    assert quarterly['agreement_amount'] == 0, quarterly
    assert quarterly['invoice_amount'] == 400, quarterly
    assert quarterly['reason'] == 'Utility recovery for this period', quarterly
    assert all(a['invoice_run'] == made['run']
               for a in S.DB['Utility Bill Allocation'])
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "m:'utilities.record_bill'" in shell
    assert "fbtn('Record utility bill','record-utility')" in shell
    from darkbrown.utils import invoice_run
    import inspect
    cancellation = inspect.getsource(invoice_run.on_sales_invoice_cancel)
    assert 'source == "Utility Bill Allocation"' in cancellation
    assert '"status", "Allocated"' in cancellation
    cancelled = finance.cancel_invoice_run(
        made['run'], 'Rebuild monthly utility recovery scope')
    assert cancelled['status'] == 'Cancelled', cancelled
    assert cancelled['utility_released'] == 2, cancelled
    assert all(not a['invoice_run'] for a in S.DB['Utility Bill Allocation'])
    rebuilt = finance.build_invoice_run('Al Sadd', '2026-09-01')
    assert rebuilt['run'] == made['run'] + '-2', rebuilt
    assert len(S.DB['Invoice Run']) == 2
check("utility recovery is reserved for an approved invoice run and reversible",
      t_utility_recovery_is_reserved_for_the_governed_invoice_run)

def t_utility_recovery_is_part_of_the_accounting_foundation():
    import inspect
    from darkbrown.api import finance
    from darkbrown.utils import accounting_foundation, accounting_setup
    requirements = {role: labels for role, labels, _root, _parents
                    in accounting_setup.ACCOUNT_REQUIREMENTS}
    assert requirements["utility_recovery"] == ("Utility Recovery",)
    assert accounting_foundation.ACCOUNT_ROLES["utility_recovery"] == (
        "Income", ("Utility Recovery",))
    fallback = inspect.getsource(finance._utility_recovery_account)
    assert "ensure_utility_recovery_account" in fallback
    helper = inspect.getsource(accounting_setup.ensure_utility_recovery_account)
    assert '("Utility Recovery",), "Income"' in helper
    assert "GL Entry" in helper
check("utility recovery account is installed and audited",
      t_utility_recovery_is_part_of_the_accounting_foundation)

def t_invoice_run_validation_uses_document_safe_child_assignment():
    import inspect
    from darkbrown.darkbrown.doctype.invoice_run import invoice_run
    validation = inspect.getsource(invoice_run.InvoiceRun.validate)
    assert 'if hasattr(line, "set")' in validation
    assert 'line.set("variance", variance)' in validation
    assert 'elif isinstance(line, dict)' in validation
check("invoice run validation writes child fields through the document API",
      t_invoice_run_validation_uses_document_safe_child_assignment)

def t_unissued_invoice_run_can_be_cancelled_from_the_live_review():
    import inspect
    from darkbrown.api import finance
    endpoint = inspect.getsource(finance.cancel_invoice_run)
    assert 'doc.status not in ("Draft", "Pending GM")' in endpoint
    assert '"recharge_invoice_run": None' in endpoint
    assert '"invoice_run", None' in endpoint
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "openForm('cancel-invoice-run',{run:" in shell
    assert "m:'finance.cancel_invoice_run'" in shell
    assert 'Unissued draft' in shell
    landing = shell[shell.index('function genLanding(){'):
                    shell.index('/* ================================================================\n   Cheques',
                                shell.index('function genLanding(){'))]
    assert "&&x.st!=='Cancelled'" in landing
    assert "BILLRUNS.filter(r=>r.st==='Issued').length" in landing
    assert '<h3>Run history</h3>' in landing
check("unissued invoice runs have an audited cancellation path",
      t_unissued_invoice_run_can_be_cancelled_from_the_live_review)

def t_cancelled_invoice_run_can_be_rebuilt_without_overwriting_audit():
    import inspect
    from darkbrown.api import finance
    naming = inspect.getsource(finance._invoice_run_name)
    builder = inspect.getsource(finance.build_invoice_run)
    assert 'base = "INV-{0}-{1}"' in naming
    assert 'while frappe.db.exists("Invoice Run", name)' in naming
    assert 'name = "{0}-{1}".format(base, suffix)' in naming
    assert 'run.name = _invoice_run_name(building, start)' in builder
    assert 'run.flags.name_set = True' in builder
check("cancelled invoice run rebuilds receive an audit-safe suffix",
      t_cancelled_invoice_run_can_be_rebuilt_without_overwriting_audit)

def t_cancelled_invoice_and_replacement_audit_is_visible():
    import inspect
    from darkbrown.api import app
    feed = inspect.getsource(app.invoices)
    assert '"docstatus": ["in", [0, 1, 2]]' in feed
    assert 'custom_rental_agreement' in feed
    assert 'custom_billing_period' in feed
    assert 'cancel_reason' in feed
    assert '"replaces": replaces.get(si.name)' in feed
    assert '"replaced_by": replaced_by.get(si.name)' in feed
    assert '"balance": 0 if si.docstatus == 2' in feed
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "const invBal=i=>" in shell
    assert "['Cancelled',INV.filter(i=>i.st==='Cancelled').length" in shell
    assert "active and cancelled invoices share one audit register" in shell
    assert "Open cancelled original" in shell
    assert "<h3>Invoice history</h3>" in shell
    assert "i.st!=='Cancelled'&&invBal(i)>0.005" in shell
check("cancelled invoices and their replacements remain visible and non-payable",
      t_cancelled_invoice_and_replacement_audit_is_visible)

def t_invoice_detail_uses_the_posted_income_account():
    import inspect
    from darkbrown.api import app
    lines = inspect.getsource(app._invoice_lines)
    assert '"income_account"' in lines
    assert 'i.income_account or "—"' in lines
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "v:r=>r[2]||(/recharge/i.test(r[0])" in shell
check("invoice detail shows the submitted line income account",
      t_invoice_detail_uses_the_posted_income_account)

def t_petty_cash_movements_post_to_the_ledger():
    import inspect
    from darkbrown.api import pettycash
    from darkbrown.utils import accounting_foundation, accounting_setup
    endpoint = inspect.getsource(pettycash.record_entry)
    poster = inspect.getsource(pettycash._post_movement)
    count = inspect.getsource(pettycash.record_count)
    assert 'doc.adjustment_effect = p.get("effect")' in endpoint
    assert '_assert_non_negative_after(entry_date, delta)' in endpoint
    assert 'journal = _post_movement(doc)' in endpoint
    assert 'doc.db_set("journal_entry", journal' in endpoint
    assert '"doctype": "Journal Entry"' in poster
    assert '"debit_in_account_currency": amount' in poster
    assert '"credit_in_account_currency": amount' in poster
    assert '_bank_gl_account(doc.funded_from, company)' in poster
    assert 'journal = _post_movement(doc)' in count
    roles = accounting_foundation.ACCOUNT_ROLES
    assert roles['petty_cash_asset'] == ('Asset', ('Petty Cash',))
    assert roles['petty_cash_expense'] == ('Expense', ('Petty Cash Expenses',))
    requirements = {role: labels for role, labels, _root, _parents
                    in accounting_setup.ACCOUNT_REQUIREMENTS}
    assert requirements['petty_cash_asset'] == ('Petty Cash',)
    assert requirements['petty_cash_expense'] == ('Petty Cash Expenses',)
    setup = inspect.getsource(accounting_setup.ensure_petty_cash_accounts)
    assert 'account_type="Cash"' in setup
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'o:BANKS().map(x=>x.label)' in shell
    assert 'from:bankName(d.from)' in shell
    assert "{h:'Ledger',v:e=>e.je||'\\u2014'}" in shell
    assert 'batches:BATCHES,staff:PEOPLE,petty:PETTY' in shell
    assert 'e.__bal=liveBalances?(+e.balance||0):run' in shell
    assert "a.e.date.localeCompare(b.e.date)||a.i-b.i" in shell
check("petty cash movements are validated and ledger-backed",
      t_petty_cash_movements_post_to_the_ledger)

def t_staff_register_retains_leavers_and_rejects_invalid_pay():
    import inspect
    from darkbrown.api import app, people
    from darkbrown.darkbrown.doctype.staff_member import staff_member
    seed = inspect.getsource(app._staff_seed)
    endpoint = inspect.getsource(people.save_staff)
    validate = inspect.getsource(staff_member.StaffMember.validate)
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "staff_list(include_left=1)" in seed
    assert 'flt(p.get("basic")) <= 0' in endpoint
    assert 'flt(p.get("allow")) < 0' in endpoint
    assert 'p.get("status") == "Left" and not p.get("left")' in endpoint
    assert "flt(self.basic_salary) <= 0" in validate
    assert "flt(self.allowances) < 0" in validate
    assert 'self.status == "Left" and not self.left_on' in validate
    assert "if((+d.allow||0)<0) return 'Allowances cannot be negative.'" in shell
check("staff register retains leavers and rejects invalid pay",
      t_staff_register_retains_leavers_and_rejects_invalid_pay)

def t_approval_rejection_uses_controlled_run_cancellation_and_keeps_conditions():
    import inspect
    from darkbrown.api import approvals
    reject = inspect.getsource(approvals._invoice_run)
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "cancel_invoice_run, issue_invoice_run" in reject
    assert 'cancel_invoice_run(reference, "Approval rejected: {0}".format(note))' in reject
    assert 'maintenance_released' in reject and 'utility_released' in reject
    wire = shell[shell.index("'approve-decision':{\n m:'approvals.decide'"):
                 shell.index("'reopen-deposit-release':{", shell.index(
                     "'approve-decision':{\n m:'approvals.decide'"))]
    assert "?'\\nCondition: '+d.cond:''" in wire
    assert "note:String(d.why||'').trim()+condition" in wire
    assert "s:'Approval decision · reasoning is mandatory'" in shell
check("approval rejection releases reservations and keeps conditions",
      t_approval_rejection_uses_controlled_run_cancellation_and_keeps_conditions)

def t_building_pl_withholds_margin_when_head_lease_cost_is_missing():
    import inspect
    from darkbrown.api import reports
    pack = inspect.getsource(reports._pl_by_building)
    assert 'a.account_name == "Head Lease Rent"' in pack
    assert 'def expects_head_lease_cost(building_name, month)' in pack
    assert 'and abs(v["head_lease"]) < 0.005' in pack
    assert '"Missing head-lease cost" if missing_cost' in pack
    assert '"No chargeable head lease" if missing_lease' in pack
    assert '_col("cost_status", "Cost status")' in pack
    assert '"net": None if incomplete' in pack
    assert '"margin": (None if incomplete or not inc' in pack
    assert 'are withheld rather than presenting' in pack
check("building P&L withholds false margin when lease cost is missing",
      t_building_pl_withholds_margin_when_head_lease_cost_is_missing)

def t_spread_withholds_profit_until_accrued_lease_cost_is_posted():
    import inspect
    from darkbrown.api import reports
    pack = inspect.getsource(reports._spread)
    assert '_head_lease_accrual_window, _prorated_monthly' in pack
    assert '"account_name": "Rental Income"' in pack
    assert 'flt(gle.credit) - flt(gle.debit)' in pack
    assert '"custom_landlord_contract":' in pack
    assert '["is", "set"]' in pack
    assert 'monthly_rent or flt(lease.annual_rent) / 12.0' in pack
    assert 'missing_lease = rent > 0 and accrued_cost <= 0.005' in pack
    assert 'missing_posting = rent > 0 and accrued_cost > 0.005' in pack
    assert '"spread": (None if incomplete' in pack
    assert '"margin": (None if incomplete or not rent' in pack
    assert '"per_unit": (None if incomplete or not units' in pack
    assert '"cost_status": "Incomplete" if incomplete else "Complete"' in pack
check("spread withholds profit until accrued lease cost is fully posted",
      t_spread_withholds_profit_until_accrued_lease_cost_is_posted)

def t_collection_case_history_uses_recorded_events():
    import inspect
    from darkbrown.api import app
    feed = inspect.getsource(app.cases)
    assert '"Collection Case Action"' in feed
    assert '"activity": actions_by_case.get(c.name, [])' in feed
    assert '"manual": c.trigger == "Manual"' in feed
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "...(c.activity||[]).map" in shell
    assert "Case opened automatically — invoice 30 days overdue" not in shell
    assert "Tenant contacted by phone — promised payment" not in shell
    assert "same tenancy, it escalates instead" in shell
check("collection detail shows recorded history without invented future events",
      t_collection_case_history_uses_recorded_events)

def t_collection_escalation_and_bounce_rules_are_enforced():
    import inspect
    from darkbrown.api import finance, operations
    from darkbrown.utils import collections_case
    bounce = inspect.getsource(finance._case_for_bounce)
    opening = inspect.getsource(collections_case.open_case)
    legal = inspect.getsource(operations.escalate)
    assert 'from darkbrown.utils.collections_case import open_case' in bounce
    assert 'invoice_exposure' in bounce and 'max(invoice_exposure' in bounce
    assert 'filters={"tenant": cheque.party' not in bounce
    assert 'trigger == "Returned Cheque"' in opening
    assert 'doc.status = "Broken Promise"' in opening
    assert 'trigger == "Two Months Arrears"' in opening
    assert 'doc.status = "Escalated"' in opening
    assert 'doc.append("actions"' not in opening
    assert 'guard(MD)' in legal and 'guard(MD, GM, ACC)' not in legal
    assert 'doc.status = "Legal"' in legal
    assert 'A legal notice needs the grounds for escalation.' in legal
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert "['Arrears detected','Reminder sent','Promise to pay','Promise broken','Escalated','Legal notice']" in shell
    assert "ROLEV==='MD'&&c.stage!=='Legal notice'" in shell
    assert "Reserved Managing Director action" in shell
    assert "Legal counsel: '+d.firm" in shell
check("collection triggers and legal escalation follow the guarded stage model",
      t_collection_escalation_and_bounce_rules_are_enforced)

def t_collection_contact_and_promise_inputs_are_auditable():
    import inspect
    from darkbrown.api import operations
    contact = inspect.getsource(operations.log_contact)
    assert 'contact_on=None' in contact
    assert 'A contact date cannot be in the future.' in contact
    assert 'A contact log needs notes.' in contact
    assert 'A new promise date cannot be in the past.' in contact
    assert 'A promise needs a positive amount.' in contact
    assert 'A promise cannot exceed the case outstanding amount.' in contact
    assert '"{0} 12:00:00".format(action_date)' in contact
    assert 'doc.security_deposit' not in contact
    assert 'return {"case": doc.name, "status": doc.status}' in contact
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    form = shell[shell.index("'record-contact':{t:"):
                 shell.index("'record-promise':{t:")]
    wire = shell[shell.index("'record-contact':{\n m:"):
                 shell.index("'escalate-legal':{\n m:")]
    assert "l:'Contact date',t:'date',d:ISO(TODAY)" in form
    assert "2026-07-26" not in form
    assert "contact_on:d.date" in wire
    assert "d.method?'To pay by '+d.method" in wire
check("collection contacts and promises preserve valid dates and amounts",
      t_collection_contact_and_promise_inputs_are_auditable)

def t_manual_collection_case_has_truthful_inputs_and_server_guards():
    import inspect
    from darkbrown.api import operations
    from darkbrown.utils import collections_case
    endpoint = inspect.getsource(operations.open_case)
    manual = inspect.getsource(collections_case.open_manual)
    assert "outstanding_amount=None" in endpoint
    assert "open_manual(tenancy_agreement, reason, outstanding_amount)" in endpoint
    assert "amount = flt(outstanding_amount)" in manual
    assert "A case opened by hand needs a positive amount at stake." in manual
    assert '"outstanding_amount": amount' in manual
    assert '"status": "Open"' in manual
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    form = shell[shell.index("'open-case':{t:"):
                 shell.index("'record-handover':{t:")]
    wire = shell[shell.index("'open-case':{\n m:"):
                 shell.index("'record-handover':{\n m:")]
    assert "A manual case always starts at Reminder sent" in form
    assert "l:'Opening stage'" not in form
    assert "l:'Assign to'" not in form
    assert "outstanding_amount:wNum(d.amt)" in wire
check("manual collection cases persist amount without bypassing stage controls",
      t_manual_collection_case_has_truthful_inputs_and_server_guards)

def t_vault_entity_filter_follows_live_register_values():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    vault = shell[shell.index('ROUTES.vault=()=>'):
                  shell.index('window.openVDoc=', shell.index('ROUTES.vault=()=>'))]
    assert "new Set(VDOCS.map(d=>d.ent).filter(Boolean))" in vault
    assert "${sel('ty',types)} ${sel('ent',entities)}" in vault
    assert "['All records','Tenant','Building','Agreement','Batch','Move-out']" not in vault
    assert "filed against operational records" in vault
check("vault entity filter is derived from the live document register",
      t_vault_entity_filter_follows_live_register_values)

def t_ocr_is_deferred_and_manual_document_review_is_wired():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'data-r="intake" data-feature="ocr" hidden' in shell
    assert "const ocrDeferred=r=>r==='intake'&&window.DB_OCR_ENABLED!==true;" in shell
    router = shell[shell.index('function router(){'):
                   shell.index('window.toggleNav=', shell.index('function router(){'))]
    assert 'if(ocrDeferred(r)){' in router
    assert "history.replaceState(null,'','#/vault')" in router
    roles = shell[shell.index('function roleCan(r){'):
                  shell.index('/* ---------- owner and reserve data ---------- */')]
    assert 'if(ocrDeferred(r))return false;' in roles
    assert "n.dataset.feature==='ocr'&&window.DB_OCR_ENABLED!==true" in roles
    upload = shell[shell.index("'upload-docs':{t:"):
                   shell.index("'review-document':{t:")]
    assert "t:'Upload for review'" in upload
    assert "init:()=>({type:'Other'})" in upload
    assert "l:'Link to'" not in upload
    assert '/doc-intake' not in upload
    assert 'does not send the file to an extraction service' in upload
    assert "window.openDoc=id=>openForm('review-document',{id});" in shell
    review_form = shell[shell.index("'review-document':{t:"):
                        shell.index("'add-files':{t:")]
    assert "VDOCS.find(d=>d.id===id)" in review_form
    assert "onclick=\"openFileDoc('${escA(d.id||'')}')\"" in review_form
    vault_open = shell[shell.index('window.openVDoc=id=>'):
                       shell.index('/* ---------- Approval with notes ---------- */')]
    assert "d.st==='Needs review'&&['MD','GM','DOC'].includes(ROLEV)" in vault_open
    assert "return openForm('review-document',{id});" in vault_open
    wire = shell[shell.index("'review-document':{\n guard:"):
                 shell.index("'add-files':{\n pre:")]
    assert "m:'documents.review'" in wire
    assert "decision:d.decision==='Reject'?'reject':'confirm'" in wire
    assert "{reason:String(d.reason||'').trim()}" in wire
    assert "{document_type:d.type||'Other'}" in wire
check("OCR stays hidden while manual upload and document review remain usable",
      t_ocr_is_deferred_and_manual_document_review_is_wired)

def t_planning_module_is_deferred_everywhere():
    shell = open(REPO + '/darkbrown/shell/index.html').read()
    assert 'const PLANNING_ENABLED=false;' in shell
    for route in ('planning', 'capacity', 'forecast', 'scenarios', 'scenario',
                  'model', 'portfolioplan', 'targets', 'risks', 'pactions',
                  'cfo', 'fva', 'compare', 'unitplan', 'solver', 'optimise',
                  'pconfig'):
        assert "'%s'" % route in shell[shell.index(
            'const DEFERRED_PLANNING_ROUTES='):shell.index(
            'const DEFERRED_PLANNING_FORMS=')], route
    for route in ('planning', 'capacity', 'forecast', 'scenarios', 'model',
                  'portfolioplan', 'targets', 'risks', 'pactions', 'cfo'):
        assert 'data-r="%s" data-feature="planning" hidden' % route in shell
    router = shell[shell.index('function router(){'):
                   shell.index('window.toggleNav=', shell.index('function router(){'))]
    assert 'if(planningDeferred(r)){' in router
    assert "history.replaceState(null,'',dflt)" in router
    opener = shell[shell.index('window.openForm=(key,ctx)=>{'):
                   shell.index('window.startFresh=', shell.index('window.openForm=(key,ctx)=>{'))]
    assert 'DEFERRED_PLANNING_FORMS.includes(key)' in opener
    admin = shell[shell.index('ROUTES.admin=()=>_admin()'):
                  shell.index('Stage-by-stage workflow build')]
    assert '(PLANNING_ENABLED?' in admin
    owners = shell[shell.index('ROUTES.owners=()=>'):
                   shell.index('window.openRun=', shell.index('ROUTES.owners=()=>'))]
    assert '${PLANNING_ENABLED?`<div class="card"><h3>Distribution capacity' in owners
check("Planning navigation, direct routes, forms and cross-links stay hidden",
      t_planning_module_is_deferred_everywhere)

# =====================================================================
print()
for n in PASS: print("  PASS  %s" % n)
for n, e in FAIL: print("  FAIL  %s\n          %s" % (n, e))
print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
