"""Focused synthetic checks for reporting dates and the shared ledger bridge."""
import ast
import datetime as dt
from pathlib import Path
import sys, types
root=Path(__file__).resolve().parents[1]
source=(root/'darkbrown/api/command.py').read_text()
tree=ast.parse(source)
def load(name, env):
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(root/'darkbrown/api/command.py'),'exec'),env)
    return env[name]
for month in range(1,13):
    env={'getdate':lambda d:d,'today':lambda:dt.date(2030,month,15)}
    assert load('_quarter_months',env)()==list(range(-((month-1)%3),1))
seen=[]
pl={'income':100,'expense':135,'net':-35,'groups':[{'total':135}], 'frm':'2030-01-01','to':'2030-01-15','notes':['provisional']}
m=types.ModuleType('darkbrown.api.statements')
m.profit_and_loss=lambda **kw:(seen.append(kw) or pl)
sys.modules['darkbrown.api.statements']=m
f=load('_waterfall',{})
r=f('2030-01-01','2030-01-15')
assert seen==[{'frm':'2030-01-01','to':'2030-01-15'}]
assert (r['gross'],r['expense'],r['spread'])==(100,135,-35)
assert r['groups']==pl['groups'] and r['notes']==pl['notes']
print('PASS all twelve quarter boundaries and shared P&L bridge, including loss')
