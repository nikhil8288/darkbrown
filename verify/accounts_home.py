"""Synthetic overview adapter checks; native ERP runtime is checked after deploy."""
import datetime as dt
import importlib
import sys
import types
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stub_frappe as S
from darkbrown.api import accounts_home as H

def date(v):
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))

with patch.object(H, 'today', return_value='2026-10-01'), patch.object(H, 'getdate', side_effect=date):
    assert H._window('2026-08','2026-09') == ('2026-08-01','2026-09-30')
    assert H._window('2026-10','2026-10') == ('2026-10-01','2026-10-01')
    assert H._window('2024-02','2024-02') == ('2024-02-01','2024-02-29')
    for args in [('2026-09','2026-08'),('2026-10','2026-11'),('2026-13','2026-13'),('2000-01','2026-01')]:
        try: H._window(*args)
        except Exception: pass
        else: raise AssertionError(args)

seen = []
class NativeReport:
    def __init__(self, filters): self.filters=filters; seen.append(filters)
    def run(self, args):
        seen.append(args)
        return [], [dict(voucher_no='SYN-A',voucher_type='Sales Invoice',party='C',
            posting_date='2026-07-01',due_date='2026-07-31',outstanding=100),
            dict(voucher_no='SYN-B',voucher_type='Sales Invoice',party='C',
            posting_date='2026-09-01',due_date='2026-10-01',outstanding=25),
            dict(voucher_no='SYN-ADV',voucher_type='Payment Entry',party='C',
            posting_date='2026-09-01',outstanding=-20)], None
module=types.ModuleType('erpnext.accounts.report.accounts_receivable.accounts_receivable')
module.ReceivablePayableReport=NativeReport
with patch.dict(sys.modules, {module.__name__:module}), patch.object(H,'getdate',side_effect=date):
    d=H._ageing('Receivable','2026-09-30','SYN',cost_center='CC')
    assert d['buckets']==dict(current=25,b30=0,b60=0,b90=100,b90p=0)
    assert (d['gross'],d['credits'],d['net'])==(125,-20,105)
    assert seen[0]['report_date']=='2026-09-30' and seen[0]['age_as_on']=='Report Date'
    assert seen[0]['in_party_currency']==0 and seen[0]['show_future_payments']==0
    assert seen[0]['cost_center']==['CC'] and seen[1]['account_type']=='Receivable'

rows=[types.SimpleNamespace(account='INC',cost_center='CC',posting_date='2026-08-15',dr=0,cr=100),
      types.SimpleNamespace(account='EXP',cost_center='CC',posting_date='2026-08-16',dr=130,cr=0),
      types.SimpleNamespace(account='EXP',cost_center='',posting_date='2026-09-01',dr=10,cr=0)]
calls=[]
def get_all(doctype, **kw):
    calls.append((doctype,kw))
    return rows if doctype=='GL Entry' else [types.SimpleNamespace(cost_center='CC',name='Building A')]
with patch.object(H.frappe,'get_all',side_effect=get_all),patch.object(H,'getdate',side_effect=date):
    d=H._performance('SYN','2026-08-01','2026-09-30',{'INC':{'cls':'Income'},'EXP':{'cls':'Expense'}})
    assert [r['net'] for r in d['monthly']]==[-30,-10]
    assert sum(r['net'] for r in d['buildings'])==-40
    assert any(r['building']=='Unassigned / company costs' for r in d['buildings'])
    assert calls[0][1]['filters']['voucher_type']==['!=','Period Closing Voucher']
with patch.object(H,'guard'),patch.object(H,'allowed_buildings',return_value={'Building A'}):
    try: H._access()
    except Exception: pass
    else: raise AssertionError('scoped login must not read company bank totals')
with patch.object(H,'today',return_value='2026-10-01'):
    d=H._occupancy_position({'A':{'status':'Occupied'},'B':{'status':'Unknown'},'C':{'status':'Vacant'}},'2026-09-30')
    assert (d['units'],d['occupied'],d['unknown'],d['pct'])==(3,1,1,33.3)
    assert d['source_as_of']=='2026-09-30' and 'not assumed vacant' in d['note']
print('PASS month boundaries, invalid ranges, dated/native ageing adapter, credits, signed losses, unassigned costs and scope denial')
