"""Local posting-contract tests; native ERP integration still required."""
import pathlib,sys,types,unittest,copy
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from unittest.mock import Mock
from darkbrown.migration.evidence import digest
from darkbrown.migration.native_import import validate_batch,post_event,document_name
from cleanup_sequence import snapshot,link
from darkbrown.migration.scoped_reset import reset_plan


def batch(events):
    b={'schema_version':1,'company':'Example','site':'test.invalid','masters':[],'events':events}
    b['batch_checksum']=digest(b);return b

def event(kind='rent_invoice'):
    return {'kind':kind,'key':'unit/period/rent','source':{'row':2,'sha256':'synthetic'},'description':'Historical synthetic rent',
            'posting_date':'2026-09-01','due_date':'2026-09-01','service_period':'2026-09','party':'Tenant',
            'amount':'100.00','party_account':'AR','account':'Rent income','item':'Rent','cost_center':'Example CC'}

class Importer(unittest.TestCase):
    def test_valid_batch(self):self.assertTrue(validate_batch(batch([event()])))
    def test_duplicate_event(self):
        with self.assertRaises(ValueError):validate_batch(batch([event(),event()]))
    def test_cutover(self):
        e=event();e['posting_date']='2026-10-01'
        with self.assertRaises(ValueError):validate_batch(batch([e]))
    def test_unbalanced_journal(self):
        e=event('journal');e['lines']=[{'account':'A','debit':'100','credit':'0'}]
        with self.assertRaises(ValueError):validate_batch(batch([e]))
    def test_changed_source(self):
        b=batch([event()]);b['events'][0]['amount']='101'
        with self.assertRaises(ValueError):validate_batch(b)
    def test_invoice_native_submit_and_rerun(self):
        e=event();b=batch([e]);saved={};frappe=types.SimpleNamespace()
        def get_value(dt,name,fields,as_dict=False):
            return types.SimpleNamespace(company='Example',is_group=0,disabled=0,account_currency='QAR',account_type='Receivable' if name=='AR' else '',root_type='Income' if name=='Rent income' else 'Asset')
        frappe.db=types.SimpleNamespace(exists=lambda dt,n:dt=='Customer' or (dt,n) in saved,get_value=get_value)
        class Flags(dict):
            def __setattr__(self,k,v):self[k]=v
        frappe.flags=Flags()
        frappe.get_meta=lambda dt:types.SimpleNamespace(has_field=lambda f:True)
        class Doc:
            def __init__(self,v):self.v=v;self.name=None;self.docstatus=0;self.grand_total='100.00'
            def get(self,k):return self.v.get(k)
            def insert(self,set_name):self.name=set_name;saved[(self.v['doctype'],set_name)]=self
            def submit(self):self.docstatus=1
        frappe.get_doc=lambda value,name=None:saved[(value,name)] if name else Doc(value)
        r=post_event(frappe,b,e);self.assertTrue(r['created'])
        self.assertEqual(r['doctype'],'Sales Invoice');self.assertTrue(r['name'].startswith('MIG-INV-'))
        self.assertFalse(post_event(frappe,b,e)['created']);self.assertEqual(len(saved),1)
        changed=copy.deepcopy(e);changed['amount']='101'
        with self.assertRaises(ValueError):post_event(frappe,b,changed)
    def test_no_receipt_derived_from_due(self):
        self.assertNotEqual(document_name('collection','x'),document_name('rent_invoice','x'))
    def test_reset_protected(self):
        s=snapshot({'Account':[{'name':'A'}]})
        with self.assertRaises(ValueError):reset_plan(s,[('Account','A')])
    def test_reset_incoming_permission(self):
        s=snapshot({'Building':[{'name':'B'}],'User Permission':[{'name':'P','allow':'Building','for_value':'B'}]},[link('User Permission','for_value','allow','Dynamic Link')])
        with self.assertRaises(ValueError):reset_plan(s,[('Building','B')])
    def test_reset_exact_scope(self):
        s=snapshot({'Sales Invoice':[{'name':'I'}]});p=reset_plan(s,[('Sales Invoice','I')])
        self.assertEqual(len(p['rows']),1);self.assertEqual(p['method'],'exact_record_low_level_dummy_reset')

if __name__=='__main__':unittest.main()
