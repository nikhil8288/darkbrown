"""Dashboard history derived from native income and expense ledger entries."""
from collections import defaultdict
from datetime import date
from calendar import monthrange
from decimal import Decimal


def summarize(rows):
    months, buildings = {}, defaultdict(lambda: {'income': Decimal(0), 'owner': Decimal(0), 'profit': Decimal(0)})
    for r in rows:
        year, month = map(int, r['period'].split('-'))
        end = date(year, month, monthrange(year, month)[1])
        key = r['period']
        if key not in months:
            months[key] = {'label': end.strftime('%b %y'), 'end': str(end), 'lump': 0,
                           'income': Decimal(0), 'owner': Decimal(0), 'profit': Decimal(0)}
        debit, credit = Decimal(str(r['debit'] or 0)), Decimal(str(r['credit'] or 0))
        for target in (months[key], buildings[r.get('building') or 'Unallocated']):
            if r['root_type'] == 'Income':
                target['income'] += credit - debit
                target['profit'] += credit - debit
            elif r['root_type'] == 'Expense':
                target['profit'] -= debit - credit
                if r.get('owner_rent'): target['owner'] += debit - credit
            else:
                raise ValueError('History accepts income/expense accounts only')
    return {'live': bool(rows), 'source': 'native_general_ledger',
            'months': [{k: float(v) if isinstance(v, Decimal) else v for k,v in months[p].items()} for p in sorted(months)],
            'by_building': sorted([[name, round(float(v['income']) / 1000, 1),
                                    round(float(v['owner']) / 1000, 1), round(float(v['profit']) / 1000, 1)]
                                   for name,v in buildings.items()], key=lambda r: -r[3])}


def load(frappe, company, as_on):
    rows = frappe.db.sql("""
        SELECT DATE_FORMAT(g.posting_date, '%%Y-%%m') AS period,
               COALESCE(b.name, c.cost_center_name, 'Unallocated') AS building,
               a.root_type, a.account_name = 'Head Lease Rent' AS owner_rent,
               SUM(g.debit) AS debit, SUM(g.credit) AS credit
        FROM `tabGL Entry` g JOIN `tabAccount` a ON a.name = g.account
        LEFT JOIN `tabCost Center` c ON c.name = g.cost_center
        LEFT JOIN (SELECT cost_center, company, MIN(name) AS name FROM `tabBuilding` GROUP BY cost_center, company) b
          ON b.cost_center = g.cost_center AND b.company = g.company
        WHERE g.company = %s AND g.is_cancelled = 0 AND g.posting_date <= %s
          AND g.voucher_type != 'Period Closing Voucher'
          AND a.root_type IN ('Income', 'Expense')
        GROUP BY period, building, a.root_type, owner_rent
    """, (company, as_on), as_dict=True)
    return summarize(rows)
