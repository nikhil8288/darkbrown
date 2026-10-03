"""Synthetic boundary tests: private durable reviews never write financial docs."""
import copy
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stub_frappe
from darkbrown.api import statement_review as api, cashdesk

class Reviews(unittest.TestCase):
    def setUp(self):
        self.docs = {}
        self.source = NS(is_private=1, file_name='synthetic.pdf', get_content=lambda: b'sample')
        self.review = dict(bank='synthetic', account_suffix='1234', bank_account='SYN',
            historical=2, closing='20.00', exceptions=[], rows=[
            dict(date='2026-09-30', ref='repeat', amount='10.00', direction='Credit', balance='10.00'),
            dict(date='2026-09-30', ref='repeat', amount='10.00', direction='Credit', balance='20.00')])
        def get_doc(dt, name=None):
            if isinstance(dt, dict):
                self.assertEqual(dt['doctype'], 'File')
                self.assertEqual(dt['is_private'], 1)
                def insert(set_name):
                    self.assertNotIn(set_name, self.docs)
                    self.docs[set_name] = NS(owner=api.frappe.session.user, is_private=1,
                        file_url='/private/files/'+set_name, get_content=lambda: dt['content'])
                return NS(insert=insert)
            self.assertEqual(dt, 'File')
            return self.docs[name]
        def listing(dt, **kw):
            self.assertEqual(dt, 'File')
            prefix=kw['filters']['name'][1][:-1]
            values=[NS(name=n) for n,d in self.docs.items() if n.startswith(prefix) and d.owner==api.frappe.session.user]
            return values[kw['start']:kw['start']+kw['page_length']]
        patches = [patch.object(api,'guard'), patch.object(api,'require_file_access', return_value=self.source),
            patch.object(api.frappe,'get_single',return_value=NS(default_company='SYN')),
            patch.object(api.frappe,'get_doc',side_effect=get_doc),
            patch.object(api.frappe,'get_list',side_effect=listing,create=True),
            patch.object(api.frappe,'cache',NS(lock=lambda *a,**k:nullcontext()),create=True),
            patch.object(api.frappe.db,'exists',side_effect=lambda dt,n:n in self.docs),
            patch.object(cashdesk,'preview_statement_file',side_effect=lambda u:copy.deepcopy(self.review))]
        for p in patches: p.start(); self.addCleanup(p.stop)
    def test_save_reload_and_repeat(self):
        result=api.save_review('source')
        self.assertEqual(len(result['rows']),2)
        self.assertNotEqual(result['rows'][0]['source_row_id'],result['rows'][1]['source_row_id'])
        self.assertEqual(api.load_review(result['saved_id'])['rows'],result['rows'])
        self.assertTrue(api.save_review('renamed')['duplicate_file'])
        self.assertEqual(len(self.docs),1)
        self.assertEqual(api.list_reviews()[0]['rows'],2)
    def test_reexport_overlap_preserves_rows(self):
        api.save_review('source')
        self.source.get_content=lambda:b'reexport'
        result=api.save_review('other')
        self.assertEqual(result['saved_overlap_rows'],[1,2])
        self.assertEqual(len(result['rows']),2)
    def test_no_mapping_no_save(self):
        self.review['bank_account']=None
        with self.assertRaises(Exception):api.save_review('source')
        self.assertFalse(self.docs)
    def test_public_rejected(self):
        self.source.is_private=0
        with self.assertRaises(Exception):api.save_review('source')
        cashdesk.preview_statement_file.assert_not_called()
    def test_cross_user_read_rejected(self):
        result=api.save_review('source')
        with patch.object(api.frappe,'session',NS(user='other')):
            with self.assertRaises(Exception):api.load_review(result['saved_id'])
            self.assertEqual(api.list_reviews(),[])
    def test_guard_before_access(self):
        with patch.object(api,'guard',side_effect=PermissionError):
            with self.assertRaises(PermissionError):api.save_review('source')
        api.require_file_access.assert_not_called()
    def test_changed_source_rejected(self):
        self.source.get_content=iter([b'first',b'changed']).__next__
        with self.assertRaises(Exception):api.save_review('source')
        self.assertFalse(self.docs)
    def test_legacy_endpoint_denied_before_payload(self):
        with patch.object(cashdesk,'guard'), patch.object(cashdesk,'_payload') as parse:
            with self.assertRaisesRegex(Exception,'Legacy statement posting is disabled'):
                cashdesk.import_statement({})
            parse.assert_not_called()

if __name__=='__main__':unittest.main()
