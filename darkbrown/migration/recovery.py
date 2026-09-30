"""Independent read-only verification of the exact rehearsed business scope.

Runtime error/access logs may be added by maintenance-page requests. Preserve
that original full-inventory mismatch; certify business recovery separately.
"""
import json
from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import capture
from darkbrown.migration.scoped_reset import reset_plan
from darkbrown.migration.native_import import document_name


def verify(frappe, report_file, bundle, bundle_checksum):
    doc = frappe.get_doc('File', report_file)
    if not doc.is_private: raise ValueError('Private rehearsal evidence required')
    report = json.loads(doc.get_content())
    if (report.get('source_bundle_checksum') != bundle_checksum
            or report.get('committed_business_data') is not False
            or report.get('error_type') is not None
            or report.get('error') not in (None, 'Inventory changed across rollback; investigate before any execution')):
        raise ValueError('Rehearsal has another unresolved error')
    batch = bundle['batch']
    if (report.get('import', {}).get('events_created') != len(batch['events'])
            or report.get('import', {}).get('masters_created') != len(batch['masters'])
            or report.get('rerun', {}).get('events_created') != 0
            or report.get('rerun', {}).get('masters_created') != 0
            or report.get('rerun', {}).get('events_reused') != len(batch['events'])):
        raise ValueError('Native import/idempotency was not fully exercised')
    snapshot = capture(company=batch['company'], expected_site=batch['site'])
    unexpected = [e for e in snapshot['errors'] if e.get('doctype') not in {'RQ Job', 'RQ Worker'}]
    if unexpected: raise ValueError('Current inventory is incomplete')
    old = report['reset_plan']
    fresh = reset_plan(snapshot, [(r['doctype'], r['name']) for r in old['rows']], old['orphan_exceptions'])
    for key in ('rows', 'business_population_checksum', 'protected_setup_checksum'):
        if fresh[key] != old[key]: raise ValueError('Business/setup rollback mismatch: ' + key)
    names = [document_name(e['kind'], e['key']) for e in batch['events']]
    financial_types = ('Sales Invoice', 'Purchase Invoice', 'Journal Entry')
    for start in range(0, len(names), 300):
        chunk = names[start:start + 300]
        for dt in financial_types:
            if frappe.db.count(dt, {'name': ['in', chunk]}):
                raise ValueError('A rehearsed financial document survived rollback')
            for field in frappe.get_meta(dt).get_table_fields():
                if frappe.db.count(field.options, {'parenttype': dt, 'parent': ['in', chunk]}):
                    raise ValueError('Rehearsed financial child rows survived rollback')
        for dt in ('GL Entry', 'Payment Ledger Entry'):
            if frappe.db.count(dt, {'voucher_no': ['in', chunk]}):
                raise ValueError('Rehearsed ledger rows survived rollback')
    return {'status': 'VERIFIED_SCOPED_BUSINESS_RECOVERY',
            'rehearsal_report': report_file, 'rehearsal_report_checksum': digest(report),
            'source_bundle_checksum': bundle_checksum, 'reset_checksum': old['reset_checksum'],
            'reviewed_rows_restored': len(old['rows']), 'protected_setup_unchanged': True,
            'business_population_unchanged': True, 'imported_financial_documents_and_children_absent': True,
            'writes_performed': False,
            'full_inventory_rollback_verified': report.get('rollback_verified'),
            'scope_note': 'Verifies reviewed dummy rows, complete business-parent population, protected setup and absence of imported financial/ledger rows. Does not claim runtime log inventory is unchanged.'}
