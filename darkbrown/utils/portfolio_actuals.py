"""Read-only source occupancy and posted money, independent of contract activation."""
import json
import frappe
from frappe.utils import getdate, today, get_first_day, get_last_day, flt

SNAPSHOT_FILE = 'darkbrown-occupancy-2026-09.json'


def company():
    return (frappe.db.get_single_value('DBR Settings', 'default_company')
            or frappe.defaults.get_user_default('Company'))


def snapshot():
    cached = getattr(frappe.local, '_dbr_occupancy_snapshot', None)
    if cached is not None:
        return cached
    name = frappe.db.get_value('File', {'file_name': SNAPSHOT_FILE, 'is_private': 1}, 'name')
    result = json.loads(frappe.get_doc('File', name).get_content()) if name else {}
    if result and result.get('company') != company():
        raise ValueError('Occupancy snapshot company mismatch')
    frappe.local._dbr_occupancy_snapshot = result
    return result


def occupancy():
    """Latest supplied observation; newer operational changes take precedence.

    Missing source rooms are Unknown, never assumed vacant. This is a display
    projection only: it cannot activate agreements or generate invoices.
    """
    cached = getattr(frappe.local, '_dbr_occupancy', None)
    if cached is not None:return cached
    snap = snapshot()
    observed = snap.get('units', {})
    result = {}
    for u in frappe.get_all('Unit', fields=['name', 'building', 'status', 'modified']):
        row = observed.get(u.name)
        if row:
            result[u.name] = dict(row, basis='Reported '+snap['as_of'])
        else:
            result[u.name] = {'building':u.building, 'status':'Unknown', 'tenant':'', 'rent':None,
                              'basis':'No current occupancy evidence'}
        # Migration starts all rooms Not Ready. Never interpret that default
        # as vacancy. Subsequent operational status changes are explicit facts.
        if u.status != 'Not Ready':
            result[u.name].update(status=u.status, basis='Operational status')
    names = {c.name:c.customer_name for c in frappe.get_all('Customer', fields=['name','customer_name'])}
    for a in frappe.get_all('Tenancy Agreement', filters={'company':company(),
            'status':['in',['Active','Expiring']], 'start_date':['<=',today()], 'end_date':['>=',today()]},
            fields=['unit','tenant','monthly_rent']):
        if a.unit in result:
            result[a.unit].update(status='Occupied', tenant=names.get(a.tenant,a.tenant),
                                  rent=flt(a.monthly_rent), basis='Active agreement')
    frappe.local._dbr_occupancy = result
    return result


def amounts(period_start=None):
    """Billed, recorded receipts and open AR; advances applied are not receipts.

    Migration receipt dates are reconstructed service-month dates, not verified
    bank dates. The UI identifies that basis explicitly.
    """
    start=get_first_day(period_start or today());end=get_last_day(start)
    cache=getattr(frappe.local,'_dbr_actuals',None)
    if cache is None:
        cache={};frappe.local._dbr_actuals=cache
    key=str(start)
    if key in cache:return cache[key]
    co=company(); bs={};us={}
    def add(b,u,field,value):
        if not b:return
        bs.setdefault(b,{});bs[b][field]=bs[b].get(field,0)+flt(value)
        if u:
            uid=u if str(u).startswith(b+'-') else b+'-'+u
            us.setdefault(uid,{});us[uid][field]=us[uid].get(field,0)+flt(value)
    invoices=frappe.db.sql('''SELECT si.name, si.posting_date, si.grand_total, si.outstanding_amount,
        COALESCE(NULLIF(si.db_migration_building,''),ta.building) AS building,
        COALESCE(NULLIF(si.db_migration_unit_label,''),ta.unit) AS unit
        FROM `tabSales Invoice` si LEFT JOIN `tabTenancy Agreement` ta ON ta.name=si.custom_rental_agreement
        WHERE si.docstatus=1 AND si.company=%s AND si.posting_date<=%s''',(co,today()),as_dict=True)
    by_invoice={r.name:r for r in invoices}
    for r in invoices:
        add(r.building,r.unit,'arrears',r.outstanding_amount)
        if start<=getdate(r.posting_date)<=end:add(r.building,r.unit,'billed',r.grand_total)
    for r in frappe.get_all('Journal Entry',filters={'company':co,'docstatus':1,
            'db_migration_kind':'collection','posting_date':['between',[start,end]]},
            fields=['db_migration_building','db_migration_unit_label','total_debit']):
        add(r.db_migration_building,r.db_migration_unit_label,'collected',r.total_debit)
    # Only allocations from actually submitted receipts. Unallocated money has
    # no building/unit attribution and is deliberately not spread among rooms.
    for r in frappe.db.sql('''SELECT ref.reference_name, ref.allocated_amount
        FROM `tabPayment Entry Reference` ref JOIN `tabPayment Entry` pe ON pe.name=ref.parent
        WHERE pe.docstatus=1 AND pe.company=%s AND pe.payment_type='Receive'
          AND pe.posting_date BETWEEN %s AND %s AND ref.reference_doctype='Sales Invoice' ''',
          (co,start,end),as_dict=True):
        inv=by_invoice.get(r.reference_name)
        if inv:add(inv.building,inv.unit,'collected',r.allocated_amount)
    # Posted landlord expense, including history without an active head lease.
    for r in frappe.db.sql('''SELECT b.name AS building,SUM(g.debit-g.credit) AS amount
        FROM `tabGL Entry` g JOIN `tabAccount` a ON a.name=g.account
        JOIN `tabBuilding` b ON b.cost_center=g.cost_center AND b.company=g.company
        WHERE g.company=%s AND g.is_cancelled=0 AND a.account_name='Head Lease Rent'
          AND g.posting_date BETWEEN %s AND %s AND g.voucher_type!='Period Closing Voucher'
        GROUP BY b.name''',(co,start,end),as_dict=True):add(r.building,None,'owner_cost',r.amount)
    result={'buildings':bs,'units':us,'period':str(start)[:7]}
    cache[key]=result
    return result
