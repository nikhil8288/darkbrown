"""Synthetic checks of the real read-only consolidated P&L endpoints."""
import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stub_frappe as S
from darkbrown.api import consolidated_pl as C, accounts_home as H

def date(v):
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))

nodes = {}
for acc, label, cls, parent, group in [
    ('I','Rent Income','Income',None,False), ('H','Head Lease Rent - SYN','Expense',None,False),
    ('C','Building Maintenance','Expense',None,False), ('S','Salary','Expense',None,False),
    ('O','Audit Fees','Expense',None,False), ('D','Depreciation','Expense',None,False),
    ('B','Bank Charges','Expense',None,False), ('X','Unmapped','Expense',None,False),
    ('P','Operating Expenses','Expense',None,True), ('L','Custom leaf','Expense','P',False),
    ('A','Cash','Asset',None,False)]:
    nodes[acc] = dict(acc=acc,label=label,cls=cls,parent=parent,group=group)
assert C._column(nodes['H'], nodes) == 'head_lease'
assert C._column(nodes['L'], nodes) == 'operating'
assert C._column(nodes['X'], nodes) == 'other'
assert C._column(nodes['P'], nodes) is None

register = {'Cost Center':[Row(name='CC',parent_cost_center='ROOT'),
    Row(name='CHILD',parent_cost_center='CC'),Row(name='ROOT',parent_cost_center=None),
    Row(name='OVERHEAD',parent_cost_center='ROOT')],
    'Building':[Row(name='SYN-B',cost_center='CC'),Row(name='SYN-ZERO',cost_center=None),
                Row(name='OTHER-CO',cost_center='EXTERNAL')]}
with patch.object(C.frappe,'get_all',side_effect=lambda d,**k:register[d]):
    owners, buildings = C._cost_centres('SYN')
    assert owners == {'CC':'SYN-B','CHILD':'SYN-B'}
    assert buildings == ['SYN-B','SYN-ZERO']
    register['Building'].append(Row(name='DUPLICATE',cost_center='CC'))
    try: C._cost_centres('SYN')
    except S.ValidationError: pass
    else: raise AssertionError('duplicate building cost centres must fail')
    register['Building'].pop()

rows = [Row(account=a,cost_center=cc,posting_date=m+'-15',dr=dr,cr=cr)
    for a,cc,m,dr,cr in [('I','CC','2026-08',0,100),('H','CC','2026-08',70,0),
    ('C','CHILD','2026-08',40,0),('C','CC','2026-08',0,5),
    ('I','CC','2026-09',100,0),('H','CC','2026-09',0,70),
    ('S','OVERHEAD','2026-08',8,0),('O',None,'2026-08',3,0),
    ('D','OVERHEAD','2026-08',2,0),('B','OVERHEAD','2026-08',1,0),
    ('X',None,'2026-08',4,0),('L','CC','2026-08',6,0),
    ('A','CC','2026-08',999,0)]]
expected = dict(income=0,expense=59,gross=-35,net=-59,cost_of_sales=35,
    groups=[dict(key=k,total=v) for k,v in [('Cost of Sales',35),('Staff Cost',8),
        ('Operating Expenses',9),('Depreciation and Amortisation',2),
        ('Bank and Finance Charges',1),('Other',4)]],notes=['Provisional source costs'])
calls=[]
def read(d, **kw):
    calls.append(kw)
    return rows
with patch.object(C,'guard'),patch.object(C,'_access'),patch.object(H,'today',return_value='2026-10-02'), \
     patch.object(H,'getdate',side_effect=date),patch.object(C,'getdate',side_effect=date), \
     patch.object(C.statements,'_company',return_value='SYN'),patch.object(C.statements,'_tree',return_value=nodes), \
     patch.object(C,'_cost_centres',return_value=(owners,buildings)), \
     patch.object(C.statements,'profit_and_loss',return_value=expected) as pl, \
     patch.object(C.frappe,'get_all',side_effect=read):
    result=C.report('2026-08','2026-10')
    assert result['reconciled'] and result['total']['net']==-59
    assert [m['total']['net'] for m in result['months']]==[-29,-30,0]
    assert result['months'][0]['rows'][0]['head_lease']==70
    assert result['months'][0]['rows'][0]['cos']==35
    assert result['months'][0]['rows'][-1]['net']==-18
    assert result['months'][0]['rows'][1]['net']==0
    assert result['total']['income']==0  # Offset across months must not erase monthly revenue.
    assert result['notes']==expected['notes']
    assert calls[0]['filters']['posting_date']==['between',['2026-08-01','2026-10-02']]
    assert calls[0]['filters']['voucher_type']==['!=','Period Closing Voucher']
    assert calls[0]['filters']['is_cancelled']==0
    pl.return_value={**expected,'net':-58}
    try: C.report('2026-08','2026-09')
    except S.ValidationError: pass
    else: raise AssertionError('mismatched independent P&L must fail')

cell_calls=[]
def cell_read(d, **kw):
    cell_calls.append(kw)
    if kw.get('group_by'):
        return [Row(account='I',dr=0,cr=100,entries=450),Row(account='H',dr=130,cr=0,entries=10)]
    return [dict(name='SYN-GL-'+str(i),account='I',posting_date='2026-08-15',
        voucher_type='Journal Entry',voucher_no='SYN-EXACT-'+str(i),debit=0,credit=1) for i in range(101)]
with patch.object(C,'guard'),patch.object(C,'_access'),patch.object(H,'today',return_value='2026-10-02'), \
     patch.object(H,'getdate',side_effect=date),patch.object(C.statements,'_company',return_value='SYN'), \
     patch.object(C.statements,'_tree',return_value=nodes),patch.object(C,'_cost_centres',return_value=(owners,buildings)), \
     patch.object(C.statements,'reporting_status',return_value={'notes':[]}), \
     patch.object(C.frappe,'get_all',side_effect=cell_read):
    r=C.cell('2026-08','SYN-B','net',page=4)
    assert (r['total'],r['entries'],len(r['rows']),r['has_more'])==(-30,460,100,True)
    assert r['accounts'][0]['amount']==-130
    assert cell_calls[-1]['limit_start']==400
    assert cell_calls[-1]['filters']['cost_center']==['in',['CC','CHILD']]
    assert cell_calls[-1]['filters']['posting_date']==['between',['2026-08-01','2026-08-31']]
    assert r['rows'][0]['voucher_no']=='SYN-EXACT-0'
    _,filters,ors=C._selection('SYN',nodes,C.COMPANY_ROW,'operating','2026-08-01','2026-08-31')
    assert set(filters['account'][1])=={'O','L'}
    assert ors==[['cost_center','not in',['CC','CHILD']],['cost_center','is','not set']]
    _,filters,ors=C._selection('SYN',nodes,'__all__','gross','2026-08-01','2026-08-31')
    assert set(filters['account'][1])=={'I','H','C'} and ors is None and 'cost_center' not in filters
    for args in [('bad','net'),('SYN-B','bad')]:
        try: C._selection('SYN',nodes,*args,'2026-08-01','2026-08-31')
        except S.ValidationError: pass
        else: raise AssertionError('invalid selection')
    for page in [-1,'bad']:
        try: C.cell('2026-08','SYN-B','net',page=page)
        except S.ValidationError: pass
        else: raise AssertionError('invalid page')

# Real role and portfolio scope guards execute before ledger reads.
S.SESSION['roles']=['Maintenance']
try: C.report('2026-08','2026-09')
except S.PermissionError_: pass
else: raise AssertionError('nonfinance role allowed')
S.SESSION['roles']=['Accounts']
with patch.object(H,'allowed_buildings',return_value={'SYN-B'}):
    try: C.cell('2026-08','SYN-B','net')
    except S.PermissionError_: pass
    else: raise AssertionError('scoped login allowed company reports')
assert not S.CALLS, S.CALLS
print('PASS monthly contra entries, loss signs, head rent split, CC inheritance, company NULL costs, independent reconciliation, exact pagination, guards and read-only endpoints')
