"""Synthetic regression: complete invoice register and scoped totals."""
import os,sys
sys.path.insert(0,os.path.dirname(__file__))
import stub_frappe as S
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from darkbrown.api import app
S.DB.clear()
S.DB['Customer']=[{'name':'TEN','customer_name':'Synthetic tenant'}]
S.DB['Building']=[{'name':'A','building_name':'A'},{'name':'B','building_name':'B'}]
S.DB['Sales Invoice']=[dict(name=f'INV-{i:04}',customer='TEN',grand_total=10,
 outstanding_amount=1,due_date='2026-09-30',docstatus=1,
 db_migration_building='A' if i%2 else 'B',db_migration_unit_label='U') for i in range(2313)]
S.DB['Sales Invoice Item']=[dict(parent=r['name'],item_name='Rent',amount=10,income_account='Rent - SYN') for r in S.DB['Sales Invoice']]
app._has=lambda dt,fields:fields
rows=app.invoices()
assert len(rows)==2313
assert sum(r['balance'] for r in rows)==2313
assert all(r['lines']==[['Rent',10,'Rent - SYN']] for r in rows)
app.allowed_buildings=lambda user=None:{'A'}
scoped=app._scope_section('invoices',rows)
assert len(scoped)==1156 and all(r['b']=='A' for r in scoped)
assert sum(r['balance'] for r in scoped)==1156
print('PASS: 2313 invoices, complete balances/items, building scope preserved')
