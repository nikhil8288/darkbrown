"""Synthetic proposal tests, not installed lifecycle integration."""
import unittest
from cleanup_sequence import snapshot, link, run
from darkbrown.migration.inventory import snapshot_checksum
from darkbrown.migration.lifecycle_review import propose, REVIEWED_HEADS


def reviewed(s):
    s['versions']={app:{'head':head} for app,head in REVIEWED_HEADS.items()}
    s['snapshot_checksum']=snapshot_checksum(s)
    return s


def customer(shared=False, user=None):
    items=[dict(name='L',parenttype='Contact',parent='C',parentfield='links',link_doctype='Customer',link_name='A')]
    if shared:items.append(dict(name='L2',parenttype='Contact',parent='C',parentfield='links',link_doctype='Customer',link_name='B'))
    s=snapshot({'Customer':[dict(name='A',customer_primary_contact='C'),dict(name='B')],
        'Contact':[dict(name='C',user=user)],'Dynamic Link':items},
        [link('Customer','customer_primary_contact','Contact'),link('Dynamic Link','link_name','link_doctype','Dynamic Link'),link('Contact','links','Dynamic Link','Table')])
    s['records']['Dynamic Link']['istable']=True
    return reviewed(s)


class Proposals(unittest.TestCase):
    def test_exclusive_contact_native(self):
        s=customer();p=propose(s,run(s));self.assertEqual(len(p['proposals']),1)
        self.assertFalse(p['proposals'][0]['manual_unlink']);self.assertFalse(p['execution_enabled'])
    def test_shared_contact_held(self):
        s=customer(shared=True);p=propose(s,run(s));self.assertEqual(p['proposals'],[])
    def test_user_contact_held(self):
        s=customer(user='staff@example.invalid');self.assertEqual(propose(s,run(s))['proposals'],[])
    def test_backlink_exact(self):
        s=reviewed(snapshot({'Cheque':[dict(name='C',docstatus=0,deposit_batch='D')],
            'Deposit Batch':[dict(name='D',cheque='C')]},[link('Cheque','deposit_batch','Deposit Batch'),link('Deposit Batch','cheque','Cheque')]))
        p=propose(s,run(s));self.assertEqual(p['proposals'][0]['expected_value'],'D')
        self.assertIsNone(p['proposals'][0]['proposed_value'])
    def test_submitted_backlink_held(self):
        s=reviewed(snapshot({'Cheque':[dict(name='C',docstatus=1,deposit_batch='D')],
            'Deposit Batch':[dict(name='D',cheque='C')]},[link('Cheque','deposit_batch','Deposit Batch'),link('Deposit Batch','cheque','Cheque')]))
        self.assertEqual(propose(s,run(s))['proposals'],[])
    def test_version_changed(self):
        s=customer();s['versions']['frappe']['head']='different';s['snapshot_checksum']=snapshot_checksum(s)
        self.assertEqual(propose(s,run(s))['proposals'],[])
    def test_rehearsal_tamper(self):
        s=customer();r=run(s);r['cyclic_groups']=[]
        with self.assertRaises(ValueError):propose(s,r)
    def test_native_status_holds(self):
        s=reviewed(snapshot({'Tenancy Agreement':[dict(name='T',status='Active')],
            'Head Lease':[dict(name='H',status='Active')],'Building':[dict(name='B',cost_center='CC')]}))
        self.assertEqual(len(propose(s,run(s))['holds']),3)

if __name__=='__main__':unittest.main()
