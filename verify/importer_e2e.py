"""End-to-end: drive the real importer over a real CSV against the stub, and
check what it actually created."""
import sys, os, csv, tempfile, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stub_frappe as S
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')+'/darkbrown/darkbrown/doctype/*/*.json'):
    d = json.load(open(f))
    if d.get('doctype') == 'DocType':
        S.SCHEMA[d['name']] = {x['fieldname']: (x['fieldtype'], x.get('options'),
                               x.get('default')) for x in d.get('fields', [])}
S.SCHEMA['Customer'] = {'name': ('Data', None, None), 'customer_name': ('Data', None, None)}
S.SCHEMA['Company'] = {'name': ('Data', None, None)}

from darkbrown.patches import import_tenancies as it

TMP = tempfile.mkdtemp()
it.CSV = os.path.join(TMP, 'tenancies.csv')
it.NAME_MAP = os.path.join(TMP, 'map.csv')
it.CHARGES_CSV = os.path.join(TMP, 'charges.csv')

S.DB.update({
    'Company': [{'name': 'DarkBrown RealEstate'}],
    'DBR Settings': [{'default_company': 'DarkBrown RealEstate',
                      'default_tenancy_notice_days': 60}],
    'Building': [{'name': 'Al Sadd'}, {'name': 'Najma Tower'}],
    'Unit': [{'name': 'Al Sadd-101', 'building': 'Al Sadd', 'unit_no': '101', 'status': 'Vacant'},
             {'name': 'Al Sadd-102', 'building': 'Al Sadd', 'unit_no': '102', 'status': 'Vacant'},
             {'name': 'Najma Tower-501', 'building': 'Najma Tower', 'unit_no': '501', 'status': 'Not Ready'}],
    'Customer': [{'name': 'CUST-001', 'customer_name': 'Rashid Al Kuwari'},
                 {'name': 'CUST-002', 'customer_name': 'Anita George'},
                 {'name': 'CUST-003', 'customer_name': 'Thasmeer Shamnadh'}],
    'Tenancy Agreement': [], 'Account': [], 'Cost Center': [],
})

ROWS = [
  # unit name contains a space, tenant matched exactly, no QID (no pack either)
  dict(tenant_name='Rashid Al Kuwari', building='Najma Tower', unit_no='501',
       start_date='2026-01-01', end_date='2026-12-31', monthly_rent='9000',
       security_deposit='9000', payment_mode='Cheque', payment_frequency='Monthly',
       cheques_held='12', status='Active', qid_number='', notes='no pack scanned'),
  # QID present -> should self-approve
  dict(tenant_name='Anita George', building='Al Sadd', unit_no='101',
       start_date='2026-02-01', end_date='2027-01-31', monthly_rent='6500',
       cheques_held='12', status='Active', qid_number='28912345678'),
  # historical, expired - must not empty a unit
  dict(tenant_name='Thasmeer Shamnadh', building='Al Sadd', unit_no='102',
       start_date='2024-01-01', end_date='2024-12-31', monthly_rent='5000',
       status='Expired'),
]
COLS = [c for c, _ in it.COLUMNS]
with open(it.CSV, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
    for r in ROWS: w.writerow({c: r.get(c, '') for c in COLS})
with open(it.CHARGES_CSV, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=[c for c, _ in it.CHARGE_COLUMNS]); w.writeheader()
    w.writerow(dict(building='Al Sadd', unit_no='101', start_date='2026-02-01',
                    charge_type='Parking', amount='300', frequency='Monthly', remarks='1 bay'))

fails = []
def ck(label, cond, detail=''):
    print(("  PASS  " if cond else "  FAIL  ") + label + ('' if cond else '\n          ' + str(detail)))
    if not cond: fails.append(label)

print("=" * 72); print("IMPORTER END-TO-END"); print("=" * 72)
d = it.dry_run()
ck("dry_run finds 3 clean rows, 0 problems", d['clean'] == 3 and d['problems'] == 0, d)
ck("dry_run creates nothing", len(S.DB['Tenancy Agreement']) == 0)

r = it.run()
ck("run created 3 agreements", r['created'] == 3, r)
ck("charge row attached", r['charges'] == 1, r)

made = {a['unit']: a for a in S.DB['Tenancy Agreement']}
ck("unit with a space in its name resolved", 'Najma Tower-501' in made, list(made))
ck("status kept as Active, not downgraded",
   made['Najma Tower-501']['status'] == 'Active', made['Najma Tower-501']['status'])
ck("company stamped", made['Al Sadd-101']['company'] == 'DarkBrown RealEstate')
ck("building derived from unit", made['Al Sadd-101']['building'] == 'Al Sadd')
ck("notice_days defaulted from settings", made['Al Sadd-102']['notice_days'] == 60)
ck("expired historical row imported as Expired",
   made['Al Sadd-102']['status'] == 'Expired')

units = {u['name']: u['status'] for u in S.DB['Unit']}
ck("Not Ready unit not overwritten by tenancy", units['Najma Tower-501'] == 'Not Ready', units)
ck("active tenancy marks its unit Occupied", units['Al Sadd-101'] == 'Occupied', units)
ck("expired-only history left the unit Vacant", units['Al Sadd-102'] == 'Vacant', units)

before = len(S.DB['Tenancy Agreement'])
r2 = it.run()
ck("re-run is idempotent: creates 0, skips 3", r2['created'] == 0 and r2['skipped'] == 3, r2)
ck("re-run added no rows", len(S.DB['Tenancy Agreement']) == before)

# now make it dirty and prove it refuses
with open(it.CSV, 'a', newline='') as f:
    csv.DictWriter(f, fieldnames=COLS).writerow(
        {c: dict(tenant_name='Someone Not In The System', building='Al Sadd',
                 unit_no='101', start_date='2027-01-01', end_date='2027-12-31',
                 monthly_rent='7000', status='Active').get(c, '') for c in COLS})
r3 = it.run()
ck("an unmatched tenant aborts the whole run", r3.get('aborted') is True, r3)
ck("nothing was created by the aborted run", len(S.DB['Tenancy Agreement']) == before)

print()
print("%d passed, %d failed" % (16 - len(fails), len(fails)))
sys.exit(1 if fails else 0)
