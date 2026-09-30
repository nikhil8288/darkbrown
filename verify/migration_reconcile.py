"""Ledger failures must stop replacement even if all documents submitted."""
from types import SimpleNamespace as NS
import unittest
from darkbrown.migration.reconcile import verify, expected_accounts
from darkbrown.migration.native_import import document_name

class ReconcileTests(unittest.TestCase):
    def fixture(self):
        batch={'company':'Example','events':[
            {'kind':'rent_invoice','key':'invoice','amount':'100','party_account':'AR','account':'Rent'},
            {'kind':'collection','key':'receipt','amount':'60','party_account':'AR','clearing_account':'Clearing'}],
            'controls':{'rent':{'planned_rent_due':'40'}}}
        rows=[]
        for kind,key,entries in [('rent_invoice','invoice',[('AR',100,0),('Rent',0,100)]),
                                 ('collection','receipt',[('Clearing',60,0),('AR',0,60)])]:
            rows.extend(NS(voucher_no=document_name(kind,key),account=a,debit=d,credit=c) for a,d,c in entries)
        invoice=NS(name=document_name('rent_invoice','invoice'),outstanding_amount=40)
        f=NS(db=NS(count=lambda *a:len(rows)),get_all=lambda dt,**kw: rows if dt=='GL Entry' else [invoice])
        return f,batch,rows,invoice
    def test_balanced_source_backed_posting(self):
        f,b,r,i=self.fixture()
        self.assertTrue(verify(f,b)['balanced'])
    def test_balanced_but_wrong_account_fails(self):
        f,b,r,i=self.fixture(); r[1].account='Wrong Income'
        with self.assertRaisesRegex(ValueError,'Account balances'): verify(f,b)
    def test_missing_voucher_fails(self):
        f,b,r,i=self.fixture(); del r[2:]
        with self.assertRaisesRegex(ValueError,'voucher ledger'): verify(f,b)
    def test_unapplied_receipt_fails(self):
        f,b,r,i=self.fixture(); i.outstanding_amount=100
        with self.assertRaisesRegex(ValueError,'outstanding'): verify(f,b)
    def test_leftover_dummy_ledger_fails(self):
        f,b,r,i=self.fixture(); f.db.count=lambda *a: len(r)+1
        with self.assertRaisesRegex(ValueError,'Unexpected company'): verify(f,b)

if __name__=='__main__': unittest.main()
