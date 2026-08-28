"""Loads the REAL doctype JSON into the stub's schema, imports the REAL
darkbrown modules, and exercises the paths the audit flagged."""
import sys, json, glob, os, traceback
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
        'Account':[{'name':'Bank Charges - DB','account_name':'Bank Charges',
                    'account_type':'Expense Account','is_group':0},
                   {'name':'QNB Main - DB','account_name':'QNB Main',
                    'account_type':'Bank','is_group':0},
                   {'name':'Security Deposits Held - DB',
                    'account_name':'Security Deposits Held','is_group':0,
                    'company':'DarkBrown RealEstate'}],
        'Bank Account':[{'name':'QNB Main','account':'QNB Main - DB'}],
        'Cost Center':[{'name':'Al Sadd - DB','cost_center_name':'Al Sadd','is_group':0}],
        'Customer':[{'name':'CUST-001','customer_name':'Mohammed Abdul Rahman'},
                    {'name':'CUST-002','customer_name':'Mohammed Abdul Kareem'}],
        'Supplier':[{'name':'SUP-001','supplier_name':'Al Adekhar Real Estate LLC'}],
        'Unit':[], 'Building':[{'name':'Al Sadd'}],
        'Cheque':[], 'Security Deposit':[], 'Head Lease Payment':[],
        'Collection Case':[], 'Sales Invoice':[], 'Payment Entry':[],
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
                      party='SUP-001', head_lease='HL-001')
    S.DB['Head Lease Payment'].append({'name':'HLP-1','cheque':'CHQ-001','status':'Due'})
    from darkbrown.api import finance
    finance.clear_cheque('CHQ-001')
    assert S.DB['Head Lease Payment'][0]['status'] == 'Cleared', S.DB['Head Lease Payment']
check("clearing an outgoing cheque marks its Head Lease Payment", t_headlease_marked)

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
def t_arrears_tags_unique():
    from darkbrown.patches import seed_opening_arrears as sa
    tags = [sa._tag(i) for i in range(200)]
    assert len(set(tags)) == 200
    bad = [(a,b) for a in tags for b in tags if a != b and a.strip('[]') in b]
    assert not bad, "tag is a substring of another: %s" % bad[:3]
def t_arrears_no_fuzzy():
    reset()
    from darkbrown.patches import seed_opening_arrears as sa
    idx = sa._customer_index()
    c, how = sa._match_customer('Mohammed Abdul Rahman', idx, {})
    assert (c, how) == ('CUST-001', 'exact'), (c, how)
    c, how = sa._match_customer('Mohammed Abdul Hameed', idx, {})
    assert c is None, "fuzzy matcher still cross-posts: matched %s" % c
def t_arrears_no_autocreate():
    import inspect
    from darkbrown.patches import seed_opening_arrears as sa
    src = inspect.getsource(sa)
    assert 'TEST_MODE' not in src, "TEST_MODE still present"
    assert 'def execute(' not in src, "still a migrate patch entrypoint"
    assert '"doctype": "Customer"' not in src, "still auto-creates Customers"
def t_pdc_multiplicity():
    import inspect
    from darkbrown.patches import seed_pdc_outgoing as sp
    src = inspect.getsource(sp)
    assert 'TEST_MODE' not in src and 'def execute(' not in src
    assert 'PDC-SEED-%03d' in src, "cheque numbering still restarts per run"
    assert 'consumed[k] < counts[k]' in src, "multiplicity dedupe missing"
check("arrears seed tags cannot prefix-collide", t_arrears_tags_unique)
check("arrears matcher no longer cross-posts between similar names", t_arrears_no_fuzzy)
check("arrears seeder cannot auto-create parties or run on migrate", t_arrears_no_autocreate)
check("PDC seeder dedupes by multiplicity with stable numbering", t_pdc_multiplicity)

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

def t_importer_exact_only():
    reset()
    from darkbrown.patches import import_tenancies as it
    idx = it._customer_index()
    assert it._match_tenant({'tenant_name': 'Mohammed Abdul Rahman'}, idx, {})[0] == 'CUST-001'
    t, _ = it._match_tenant({'tenant_name': 'Mohammed Abdul Hameed'}, idx, {})
    assert t is None, "importer fuzzy-matched a different tenant: %s" % t
    S.DB['Customer'].append({'name': 'CUST-009', 'customer_name': 'Mohammed Abdul Rahman'})
    t, how = it._match_tenant({'tenant_name': 'Mohammed Abdul Rahman'}, it._customer_index(), {})
    assert t is None and 'ambiguous' in how, (t, how)

def t_importer_validates():
    reset()
    S.DB['Unit'].append({'name':'Al Sadd-101','building':'Al Sadd','unit_no':'101','status':'Vacant'})
    from darkbrown.patches import import_tenancies as it
    idx = it._customer_index()
    base = {'tenant_name':'Mohammed Abdul Rahman','building':'Al Sadd','unit_no':'101',
            'start_date':'2026-01-01','end_date':'2026-12-31','monthly_rent':'6500'}
    rows = [dict(base, status='Active'),
            dict(base, start_date='2026-06-01', end_date='2026-01-01'),
            dict(base),
            dict(base, unit_no='999'),
            dict(base, start_date='2026-03-01', monthly_rent='0')]
    resolved, problems = it._resolve(rows, idx, {})
    assert len(resolved) == 1, "expected 1 clean row, got %d" % len(resolved)
    kinds = " | ".join(";".join(e) for _, e in problems)
    for expect in ('not after', 'duplicate of CSV line', 'no unit', 'monthly_rent must be > 0'):
        assert expect in kinds, "%r not detected in: %s" % (expect, kinds)

def t_importer_live_conflict():
    reset()
    S.DB['Unit'].append({'name':'Al Sadd-101','building':'Al Sadd','unit_no':'101','status':'Occupied'})
    S.DB['Tenancy Agreement'].append({'name':'TA-OLD','unit':'Al Sadd-101','status':'Active',
                                      'start_date':'2025-01-01'})
    from darkbrown.patches import import_tenancies as it
    rows = [{'tenant_name':'Mohammed Abdul Rahman','building':'Al Sadd','unit_no':'101',
             'start_date':'2026-01-01','end_date':'2026-12-31','monthly_rent':'6500',
             'status':'Active'}]
    resolved, problems = it._resolve(rows, it._customer_index(), {})
    assert not problems
    conflicts = it._live_conflicts(resolved, it._existing_keys())
    assert conflicts, "a second live tenancy on one unit was allowed"

def t_importer_active_survives_controller():
    reset()
    from darkbrown.darkbrown.doctype.tenancy_agreement import tenancy_agreement as ta
    inst = _mkinst(ta.TenancyAgreement, doctype='Tenancy Agreement',
                   name='TA-1', unit='Al Sadd-101', status='Active',
                   qid_number=None, signed_pack=None)
    inst._set_activation_route()

    # and the ordinary path is unchanged: a Draft with nothing attached still
    # routes rather than going live
    draft = _mkinst(ta.TenancyAgreement, doctype='Tenancy Agreement',
                    name='TA-2', unit='Al Sadd-102', status='Draft',
                    qid_number=None, signed_pack=None)
    draft._set_activation_route()
    assert draft.status == 'Pending Approval', draft.status
    assert inst.status == 'Active', "explicit Active was downgraded to %s" % inst.status
    assert inst.activation_route == 'Routed for Approval'
    assert 'signed agreement pack' in inst.missing_items

def t_importer_not_a_patch():
    import inspect
    from darkbrown.patches import import_tenancies as it
    src = inspect.getsource(it)
    assert 'def execute(' not in src, "importer is a migrate patch entrypoint"
    assert '"doctype": "Customer"' not in src, "importer auto-creates Customers"
check("tenancy importer matches exactly and refuses ambiguity", t_importer_exact_only)
check("tenancy importer rejects bad dates, dupes, unknown units, zero rent", t_importer_validates)
check("tenancy importer refuses a second live tenancy on one unit", t_importer_live_conflict)
check("an explicitly Active imported agreement is not downgraded", t_importer_active_survives_controller)
check("tenancy importer cannot run on migrate or invent parties", t_importer_not_a_patch)

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
    from darkbrown.patches import run_july_billing
    try:
        run_july_billing.execute(); assert False, "run_july_billing still bills"
    except S.ValidationError:
        pass
check("rent_invoicing no longer duplicates the invoice builder", t_one_invoice_builder)
check("no code suppresses ERPNext due-date validation", t_no_validation_suppression)

# ---- P. patches.txt registers nothing that writes business records
def t_patches_safe():
    import re
    named = [l.strip() for l in open(REPO + '/darkbrown/patches.txt')
             if l.strip() and not l.startswith(('#', '['))]
    WRITERS = {'seed_opening_arrears','seed_pdc_outgoing','import_tenancies',
               'import_history','run_july_billing'}
    for m in named:
        assert m.split('.')[-1] not in WRITERS, \
            "%s writes business records and must not run on migrate" % m
        path = REPO + '/' + m.replace('.', '/') + '.py'
        assert os.path.exists(path), "patches.txt names a missing module: %s" % m
        assert re.search(r'^def execute\(', open(path).read(), re.M), "%s has no execute()" % m
    print("        (%d patches registered, none writes to the ledger)" % len(named))
check("patches.txt registers no ledger-writing patch", t_patches_safe)

# =====================================================================
print()
for n in PASS: print("  PASS  %s" % n)
for n, e in FAIL: print("  FAIL  %s\n          %s" % (n, e))
print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
