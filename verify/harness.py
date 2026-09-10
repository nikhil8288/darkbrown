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
    import csv as _csv, hashlib, json as _json, os as _os
    d = REPO + '/darkbrown/load/data'
    man = _json.load(open(_os.path.join(d, 'manifest.json'), encoding='utf-8'))
    for name, m in man.items():
        if name.startswith('_'):
            continue
        path = _os.path.join(d, name)
        assert _os.path.exists(path), 'manifest names a missing file: %s' % name
        raw = open(path, 'rb').read()
        got = hashlib.sha256(raw).hexdigest()[:16]
        assert got == m['sha256'], '%s checksum %s, manifest says %s' % (name, got, m['sha256'])
        rows = list(_csv.DictReader(raw.decode('utf-8-sig').splitlines()))
        assert len(rows) == m['rows'], '%s has %d rows, manifest says %d' % (name, len(rows), m['rows'])
        assert rows, '%s is empty' % name
    print('        (%d data files match the manifest)'
          % len([k for k in man if not k.startswith('_')]))

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
        assert r['payment_frequency'] in opts[('Head Lease', 'payment_frequency')], \
            'Head Lease.payment_frequency %r is not a valid option' % r['payment_frequency']
    from darkbrown.load import stage_02_buildings as s2
    for f in s2.FREQ:
        assert f in opts[('Head Lease', 'payment_frequency')], \
            'the loader would accept %r, which the doctype rejects' % f
    print('        (%d rows, every Select value legal)' % len(rows))

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

check("load data matches its manifest", t_load_data_matches_its_manifest)
check("every Select value in the data is legal", t_load_select_values_are_legal)
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

# =====================================================================
print()
for n in PASS: print("  PASS  %s" % n)
for n, e in FAIL: print("  FAIL  %s\n          %s" % (n, e))
print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
