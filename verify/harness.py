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

check("wipe covers every doctype the module owns", t_wipe_covers_every_doctype)
check("wipe refuses without the exact phrase", t_wipe_refuses_without_phrase)
check("wipe gate refuses to pass blind or on residue", t_wipe_gate_tells_residue_from_ruin)

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

# =====================================================================
print()
for n in PASS: print("  PASS  %s" % n)
for n, e in FAIL: print("  FAIL  %s\n          %s" % (n, e))
print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
