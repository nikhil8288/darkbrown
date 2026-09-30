"""Synthetic offline tests; not Frappe integration or restore evidence."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import snapshot_checksum
from darkbrown.migration.sequence import rehearse, cyclic_components


def snapshot(records, links=(), errors=()):
    s = dict(schema_version=2, site='test.invalid', company='Example', errors=list(errors), relationships=list(links), records={})
    for dt, items in records.items():
        rows = [dict(r, content_checksum=digest(r)) for r in items]
        s['records'][dt] = dict(rows=rows,count=len(rows),istable=dt=='Child',issingle=False)
    s['snapshot_checksum']=snapshot_checksum(s)
    return s


def select(s, keys=None):
    return [dict(doctype=dt,name=r['name'],reason='Synthetic review',source_record_checksum=r['content_checksum'])
        for dt,d in s['records'].items() for r in d['rows'] if keys is None or (dt,r['name']) in keys]


def run(s, selection=None):
    return rehearse(s,select(s) if selection is None else selection,'test.invalid','Example')


def link(dt, field, target, kind='Link'):
    return dict(doctype=dt,field=field,target=target,type=kind)


class Sequence(unittest.TestCase):
    def test_source_before_target(self):
        s=snapshot({'Invoice':[dict(name='I',customer='C')],'Customer':[dict(name='C')]},[link('Invoice','customer','Customer')])
        self.assertEqual(run(s)['dependency_order_prefix'],[('Invoice','I'),('Customer','C')])
        self.assertFalse(run(s)['execution_enabled'])
    def test_child_and_ledger_group(self):
        s=snapshot({'Invoice':[dict(name='I',docstatus=1)],'Child':[dict(name='C',parent='I',parenttype='Invoice',parentfield='items')], 'GL Entry':[dict(name='G',voucher_type='Invoice',voucher_no='I')]},[link('Invoice','items','Child','Table')])
        r=run(s); self.assertEqual(len(r['lifecycle_groups']),1);self.assertEqual(len(r['lifecycle_groups'][0]['members']),3)
        self.assertEqual(r['lifecycle_groups'][0]['proposed_route'],'native_cancel_then_delete_rehearsal')
    def test_missing_parent(self):
        r=run(snapshot({'Child':[dict(name='C',parent='missing',parenttype='Invoice')]}))
        self.assertIn('missing_parent',r['blocker_counts']);self.assertEqual(r['lifecycle_groups'],[])
    def test_missing_voucher(self):
        r=run(snapshot({'GL Entry':[dict(name='G',voucher_type='Invoice',voucher_no='missing')]}))
        self.assertIn('missing_native_voucher',r['blocker_counts']);self.assertEqual(r['lifecycle_groups'],[])
    def test_retained_incoming(self):
        s=snapshot({'Invoice':[dict(name='I',customer='C')],'Customer':[dict(name='C')]},[link('Invoice','customer','Customer')])
        self.assertIn('retained_incoming_link',run(s,select(s,{('Customer','C')}))['blocker_counts'])
    def test_unselected_ledger(self):
        s=snapshot({'Invoice':[dict(name='I')],'GL Entry':[dict(name='G',voucher_type='Invoice',voucher_no='I')]})
        self.assertIn('unselected_lifecycle_member',run(s,select(s,{('Invoice','I')}))['blocker_counts'])
    def test_protected_and_cutover(self):
        r=run(snapshot({'Account':[dict(name='A')],'Invoice':[dict(name='I',posting_date='2026-10-01',company='Other')]}))
        for code in ['protected_setup','post_cutover_exact_exception_required','cross_company']: self.assertIn(code,r['blocker_counts'])
    def test_cycle(self):
        s=snapshot({'Thing':[dict(name='A',other='B'),dict(name='B',other='A')]},[link('Thing','other','Thing')])
        self.assertFalse(run(s)['order_complete']);self.assertIn('cyclic_or_cycle_dependent_groups',run(s)['blocker_counts'])
    def test_inventory_errors_preserved(self):
        r=run(snapshot({},errors=[dict(doctype='RQ Job',error='queue evidence required')]))
        self.assertEqual(r['blocker_counts']['inventory_error'],1)
    def test_tampering(self):
        s=snapshot({'Thing':[dict(name='A')]});s['company']='wrong'
        with self.assertRaises(ValueError):run(s)
    def test_stale_selection(self):
        s=snapshot({'Thing':[dict(name='A')]});d=select(s);d[0]['source_record_checksum']='bad'
        with self.assertRaises(ValueError):run(s,d)
    def test_row_checksum(self):
        s=snapshot({'Thing':[dict(name='A')]});s['records']['Thing']['rows'][0]['extra']='x';s['snapshot_checksum']=snapshot_checksum(s)
        with self.assertRaises(ValueError):run(s)
    def test_invalid_parentfield(self):
        s=snapshot({'Invoice':[dict(name='I')],'Child':[dict(name='C',parent='I',parenttype='Invoice',parentfield='wrong')]})
        self.assertIn('invalid_parentfield',run(s)['blocker_counts'])
    def test_deterministic(self):
        s=snapshot({'Thing':[dict(name='B'),dict(name='A')]});before=copy.deepcopy(s)
        self.assertEqual(run(s),run(s,list(reversed(select(s)))));self.assertEqual(s,before)
    def test_cycle_excludes_downstream(self):
        self.assertEqual(cyclic_components(["A","B","C"],[("A","B"),("B","A"),("B","C")]),[["A","B"]])
    def test_dynamic_missing_target(self):
        s=snapshot({'History':[dict(name='H',kind='Invoice',ref='missing')]},[link('History','ref','kind','Dynamic Link')])
        self.assertIn('missing_link_target',run(s)['blocker_counts'])

if __name__=='__main__':unittest.main()
