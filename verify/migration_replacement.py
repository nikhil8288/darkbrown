"""Atomic commit/failure and explicit unresolved-scope acceptance tests."""
import importlib.util
from pathlib import Path
from contextlib import nullcontext
import sys
import types
import unittest
from unittest.mock import patch
from darkbrown.migration.evidence import digest
from darkbrown.migration.native_import import approved_provisional_scope

class ReplacementTests(unittest.TestCase):
    def test_exception_approval_binds_exact_batch(self):
        b={'batch_checksum':'source', 'exceptions':['unmatched'], 'contract_review':[], 'blocking_items':['bank']}
        approval={'batch_checksum':'source','exception_checksum':digest([b['exceptions'],[],b['blocking_items']]),
                  'confirmation':'IMPORT SUPPORTED HISTORY AS PROVISIONAL'}
        self.assertTrue(approved_provisional_scope(b,approval))
        b['exceptions'].append('new unresolved fact')
        self.assertFalse(approved_provisional_scope(b,approval))
        self.assertFalse(approved_provisional_scope(b,None))

    def exercise(self, failed_check=False, existing=False):
        state={'business':False,'marker':False,'commits':0,'rollbacks':0}
        f=types.ModuleType('frappe'); f.local=types.SimpleNamespace(site='test.invalid')
        f.PermissionError=PermissionError; f.clear_cache=lambda:None
        def commit():
            assert state['business'] and state['marker']
            state['commits']+=1
        def rollback():
            state.update(business=False,marker=False);state['rollbacks']+=1
        f.db=types.SimpleNamespace(commit=commit,rollback=rollback)
        f.get_all=lambda *a,**k:['existing'] if existing else []
        class Report:
            name='report'
            def insert(self): state['marker']=True
            def get_content(self):return '{"source_bundle_checksum":"source","status":"COMPLETED_PROVISIONAL_REPLACEMENT"}'
        f.get_doc=lambda *a,**k:Report()
        j=types.ModuleType('frappe.utils.background_jobs');j.get_redis_conn=lambda:types.SimpleNamespace(lock=lambda *a,**k:nullcontext())
        rq=types.ModuleType('rq');rq.get_current_job=lambda:types.SimpleNamespace(kwargs={'site':'test.invalid','user':'Administrator','method':'darkbrown.migration.replacement.run'})
        rehearsal=types.ModuleType('darkbrown.migration.rehearsal');rehearsal.load_private=lambda *a:None;rehearsal.maintenance_window=nullcontext
        with patch.dict(sys.modules,{'frappe':f,'frappe.utils.background_jobs':j,'rq':rq,'darkbrown.migration.rehearsal':rehearsal}):
            spec=importlib.util.spec_from_file_location('replacement_test_target',Path(__file__).parents[1]/'darkbrown/migration/replacement.py')
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            plan={'rows':[],'orphan_exceptions':[],'business_population_checksum':'x','protected_setup_checksum':'y','reset_checksum':'z'}
            m.load_approved=lambda *a:({'batch':{'site':'test.invalid','company':'Example'}},{'scope':{},'backup_id':'b'},plan)
            m.verify_idle_site=lambda *a:None;m.inspect=lambda *a:{'passed':True};m.capture=lambda **k:{};m.reset_plan=lambda *a:plan
            def reset(*a):state['business']=True;return {}
            m.execute=reset;m.import_batch=lambda *a,**k:{'events_created':0,'masters_created':0}
            def reconcile(*a):
                if failed_check:raise ValueError('Ledger mismatch')
                return {'balanced':True}
            m.verify=reconcile
            if failed_check:
                with self.assertRaisesRegex(ValueError,'Ledger mismatch'):m.run('private','source',{})
            else:m.run('private','source',{})
        return state
    def test_ledger_failure_rolls_back_and_never_commits(self):
        s=self.exercise(True);self.assertEqual(s['commits'],0);self.assertEqual(s['rollbacks'],1);self.assertFalse(s['business'])
    def test_success_commits_marker_and_business_together(self):
        s=self.exercise();self.assertEqual(s['commits'],1);self.assertTrue(s['marker'])
    def test_repeat_never_resets_completed_replacement(self):
        s=self.exercise(existing=True);self.assertEqual(s['commits'],0);self.assertFalse(s['business'])

if __name__=='__main__':unittest.main()
