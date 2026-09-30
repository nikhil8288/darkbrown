import unittest
from darkbrown.utils.ledger_history import summarize

class LedgerHistoryTests(unittest.TestCase):
    def test_reversals_and_non_rent_expenses_change_profit(self):
        base={'period':'2026-01','building':'Example','owner_rent':0}
        rows=[dict(base,root_type='Income',debit=10,credit=100),
              dict(base,root_type='Expense',debit=30,credit=5,owner_rent=1),
              dict(base,root_type='Expense',debit=20,credit=0)]
        h=summarize(rows)
        self.assertEqual(h['source'],'native_general_ledger')
        self.assertEqual(h['months'][0]['income'],90)
        self.assertEqual(h['months'][0]['owner'],25)
        self.assertEqual(h['months'][0]['profit'],45)
    def test_balance_sheet_lines_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize([dict(period='2026-01',root_type='Asset',debit=100,credit=0)])
    def test_empty_does_not_invent_history(self):
        self.assertEqual(summarize([])['months'],[])
if __name__=='__main__':unittest.main()
