"""Explicit add-only historical corrections; never called by deployment hooks."""
import json
from collections import defaultdict
from decimal import Decimal

import frappe
from frappe.utils import cint
from darkbrown.migration.evidence import digest
from darkbrown.migration.native_import import (
    validate_batch, post_event, same_master_value, document_name,
)
from darkbrown.migration.plan import money
from darkbrown.migration.reconcile import expected_accounts


def validate_scope(batch):
    validate_batch(batch)
    if not 0 < len(batch['events']) <= 100:
        raise ValueError('A supplement must contain 1 to 100 events')
    if any(m['doctype'] != 'Customer' for m in batch.get('masters', [])):
        raise ValueError('Only missing customer masters may be added')
    if any(e['kind'] not in {'rent_invoice', 'collection', 'journal'} for e in batch['events']):
        raise ValueError('Unsupported supplemental document')


@frappe.whitelist()
def apply(file_name, checksum, confirmation, dry_run=1):
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    if confirmation != 'ADD REVIEWED HISTORICAL CORRECTIONS':
        raise ValueError('Explicit correction approval required')
    source = frappe.get_doc('File', file_name)
    if not source.is_private or source.is_folder:
        raise ValueError('Private correction file required')
    raw = source.get_content()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Correction file too large')
    batch = json.loads(raw)
    validate_scope(batch)
    if batch['batch_checksum'] != checksum:
        raise ValueError('Reviewed correction checksum changed')
    if batch['site'] != str(frappe.local.site):
        raise ValueError('Wrong site')
    if frappe.db.get_value('Company', batch['company'], 'default_currency') != 'QAR':
        raise ValueError('Wrong company currency')
    from frappe.utils.background_jobs import get_redis_conn
    lock = get_redis_conn().lock(str(frappe.local.site) + ':darkbrown-migration', timeout=300, blocking_timeout=1)
    with lock:
        frappe.db.savepoint('historical_supplement')
        old_mute = frappe.flags.get('mute_emails')
        frappe.flags.mute_emails = True
        try:
            created = 0
            for master in batch.get('masters', []):
                if frappe.db.exists('Customer', master['name']):
                    doc = frappe.get_doc('Customer', master['name'])
                    if any(not same_master_value(doc.meta, k, doc.get(k), v) for k, v in master['values'].items()):
                        raise ValueError('Existing customer differs')
                else:
                    doc = frappe.get_doc({'doctype': 'Customer', **master['values']})
                    doc.insert(set_name=master['name'])
                    if doc.name != master['name']:
                        raise ValueError('Customer identity changed')
                    created += 1
            records = [post_event(frappe, batch, e) for e in batch['events']]
            names = [document_name(e['kind'], e['key']) for e in batch['events']]
            actual = defaultdict(Decimal)
            vouchers = defaultdict(lambda: [Decimal(0), Decimal(0)])
            for row in frappe.get_all('GL Entry', filters={'company': batch['company'], 'voucher_no': ['in', names], 'is_cancelled': 0}, fields=['voucher_no', 'account', 'debit', 'credit'], limit_page_length=0):
                d, c = money(row.debit), money(row.credit)
                actual[row.account] += d - c
                vouchers[row.voucher_no][0] += d
                vouchers[row.voucher_no][1] += c
            for event in batch['events']:
                amount = (sum((money(r.get('debit', 0)) for r in event['lines']), Decimal(0)) if event['kind'] == 'journal' else money(event['amount']))
                if vouchers[document_name(event['kind'], event['key'])] != [amount, amount]:
                    raise ValueError('Voucher ledger does not match correction')
            expected = expected_accounts(batch)
            if {k: v for k, v in actual.items() if v} != {k: v for k, v in expected.items() if v}:
                raise ValueError('Ledger does not match reviewed correction')
            result = {'dry_run': bool(cint(dry_run)), 'masters_created': created, 'events_created': sum(r['created'] for r in records), 'documents': records, 'ledger_verified': True}
            if cint(dry_run):
                frappe.db.rollback(save_point='historical_supplement')
            return result
        except Exception:
            frappe.db.rollback(save_point='historical_supplement')
            raise
        finally:
            frappe.flags.mute_emails = old_mute
