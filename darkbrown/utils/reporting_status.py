"""Read-only reporting qualifications; no balances or contract states are changed."""
import frappe
from frappe.utils import flt


def status(company):
    key = '_dbr_reporting_status'
    cached = getattr(frappe.local, key, None)
    if cached and cached.get('company') == company:
        return cached
    pending = frappe.db.sql("""SELECT a.account_name, SUM(g.debit-g.credit) balance
        FROM `tabGL Entry` g JOIN `tabAccount` a ON a.name=g.account
        WHERE g.company=%s AND g.is_cancelled=0 AND a.account_name LIKE 'Historical%%'
        GROUP BY g.account HAVING ABS(balance)>0.005""", (company,), as_dict=True)
    result = {'company':company, 'reconstruction_pending':bool(pending),
              'draft_leases':frappe.db.count('Head Lease', {'company':company,'status':'Draft'}),
              'draft_tenancies':frappe.db.count('Tenancy Agreement', {'company':company,'status':'Draft'})}
    result['notes'] = (["Imported history is provisional. Missing source expenses are not confirmed zero; opening balances and historical settlements remain under reconciliation."] if pending else [])
    setattr(frappe.local, key, result)
    return result
