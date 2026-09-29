"""Synthetic regressions for live-export coverage failures; no ERP writes."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from darkbrown.migration.inventory import record_inventory, safe_field, reviewed_virtual, stored_field

class Meta:
    def __init__(self, name, fields): self.name,self.fields=name,fields
    def get_field(self,n): return next((f for f in self.fields if f.fieldname==n),None)
    def has_field(self,n): return self.get_field(n) is not None

def field(name,kind,options=None,virtual=False):
    return types.SimpleNamespace(fieldname=name,fieldtype=kind,options=options,is_virtual=virtual)

class CoverageTests(unittest.TestCase):
    def selected(self,name,fields):
        meta=Meta(name,fields)
        f=types.SimpleNamespace(get_all=Mock(return_value=[]))
        dt=types.SimpleNamespace(name=name,module='Accounts',issingle=0,istable=0)
        record_inventory(f,dt,meta,[x for x in fields if x.fieldtype in {'Link','Dynamic Link','Table','Table MultiSelect'}])
        return f.get_all.call_args.kwargs['fields']

    def test_customer_group_section_not_column(self):
        fields=self.selected('Customer Group',[field('default_receivable_account','Section Break'),field('parent_customer_group','Link','Customer Group')])
        self.assertNotIn('default_receivable_account',fields)
        self.assertIn('parent_customer_group',fields)

    def test_supplier_group_section_not_column(self):
        self.assertNotIn('default_payable_account',self.selected('Supplier Group',[field('default_payable_account','Section Break')]))

    def test_promotional_multiselect_not_column(self):
        fields=self.selected('Promotional Scheme',[field('customer','Table MultiSelect','Customer Item'),field('supplier','Table MultiSelect','Supplier Item'),field('company','Link','Company')])
        self.assertNotIn('customer',fields);self.assertNotIn('supplier',fields);self.assertIn('company',fields)

    def test_statement_multiselect_not_column(self):
        self.assertNotIn('cost_center',self.selected('Process Statement Of Accounts',[field('cost_center','Table MultiSelect','PSOA Cost Center')]))

    def test_virtual_field_not_queried(self):
        self.assertFalse(stored_field('company',Meta('Synthetic',[field('company','Link','Company',True)])))

    def test_email_template_reference_is_safe(self):
        self.assertTrue(safe_field('reset_password_template',Meta('System Settings',[field('reset_password_template','Link','Email Template')])))

    def test_exception_does_not_allow_secrets_or_other_doctypes(self):
        for name,typ,target in [('System Settings','Password','Email Template'),('System Settings','Link','User'),('Other','Link','Email Template')]:
            self.assertFalse(safe_field('reset_password_template',Meta(name,[field('reset_password_template',typ,target)])))
        self.assertFalse(safe_field('api_key',Meta('System Settings',[field('api_key','Data')])))

    def test_reviewed_virtual_is_not_zero_rows(self):
        dt=types.SimpleNamespace(name='Bulk Transaction Log')
        versions={'erpnext':{'head':'4aee12e16c664897571457c007aaa95b8364bbbb'}}
        result=reviewed_virtual(dt,[],versions)
        self.assertIsNone(result['record_count']);self.assertFalse(result['controller_invoked'])

    def test_version_change_requires_review(self):
        self.assertIsNone(reviewed_virtual(types.SimpleNamespace(name='Bulk Transaction Log'),[],{'erpnext':{'head':'new'}}))

    def test_relationship_change_requires_review(self):
        self.assertIsNone(reviewed_virtual(types.SimpleNamespace(name='Bulk Transaction Log'),[{'field':'added'}],{'erpnext':{'head':'4aee12e16c664897571457c007aaa95b8364bbbb'}}))

    def test_unknown_and_runtime_virtuals_stay_blocked(self):
        for name in ['RQ Job','RQ Worker','Custom Virtual']:
            self.assertIsNone(reviewed_virtual(types.SimpleNamespace(name=name),[],{}))

if __name__=='__main__': unittest.main()
