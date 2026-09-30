import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from darkbrown.migration import recovery

class RecoveryTests(unittest.TestCase):
    def fixture(self):
        plan={'rows':[{'doctype':'Building','name':'Example'}], 'orphan_exceptions':[],
              'business_population_checksum':'business','protected_setup_checksum':'setup','reset_checksum':'reset'}
        report={'source_bundle_checksum':'bundle','committed_business_data':False,
                'error_type':None,'error':'Inventory changed across rollback; investigate before any execution',
                'import':{'events_created':1,'masters_created':1},
                'rerun':{'events_created':0,'masters_created':0,'events_reused':1},
                'reset_plan':plan,'rollback_verified':False}
        f=NS(get_doc=lambda *a:NS(is_private=1,get_content=lambda:json.dumps(report)),
             db=NS(count=lambda *a:0),get_meta=lambda dt:NS(get_table_fields=lambda:[NS(options='Child')]))
        bundle={'batch':{'company':'Example','site':'test.invalid', 'masters':[{}], 'events':[{'kind':'rent_invoice','key':'example'}]}}
        return f,bundle,report,plan
    def invoke(self,f,b,plan):
        with patch.object(recovery,'capture',return_value={'errors':[]}),patch.object(recovery,'reset_plan',return_value=plan):
            return recovery.verify(f,'report',b,'bundle')
    def test_runtime_mismatch_never_relabels_full_rollback(self):
        f,b,r,p=self.fixture(); result=self.invoke(f,b,p)
        self.assertEqual(result['status'],'VERIFIED_SCOPED_BUSINESS_RECOVERY')
        self.assertFalse(result['full_inventory_rollback_verified'])
    def test_changed_business_population_blocks(self):
        f,b,r,p=self.fixture(); fresh={**p,'business_population_checksum':'changed'}
        with self.assertRaisesRegex(ValueError,'business_population'):self.invoke(f,b,fresh)
    def test_changed_protected_setup_blocks(self):
        f,b,r,p=self.fixture(); fresh={**p,'protected_setup_checksum':'changed'}
        with self.assertRaisesRegex(ValueError,'protected_setup'):self.invoke(f,b,fresh)
    def test_leftover_child_blocks(self):
        f,b,r,p=self.fixture();f.db.count=lambda dt,*a:1 if dt=='Child' else 0
        with self.assertRaisesRegex(ValueError,'child rows'):self.invoke(f,b,p)
    def test_posting_failure_cannot_be_waived(self):
        f,b,r,p=self.fixture();r['error_type']='ValidationError'
        with self.assertRaisesRegex(ValueError,'another unresolved'):self.invoke(f,b,p)

if __name__=='__main__':unittest.main()
