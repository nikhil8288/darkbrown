"""Rollback-only native replacement rehearsal in an isolated maintenance window.

There is deliberately no commit mode. The only persistent result is a private
report written after rollback. Real execution needs a separately reviewed route.
"""
import copy
import json
from contextlib import contextmanager

import frappe
from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import capture
from darkbrown.migration.preflight import inspect
from darkbrown.migration.native_import import import_batch, validate_batch
from darkbrown.migration.scoped_reset import reset_plan, execute
from darkbrown.migration.runtime_queue import verify_idle_site


METHOD = 'darkbrown.migration.rehearsal.run'


def load_private(file_name, checksum):
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    document = frappe.get_doc('File', file_name)
    if not document.is_private or document.is_folder:
        raise ValueError('Private bundle required')
    raw = document.get_content()
    if len(raw) > 50 * 1024 * 1024:
        raise ValueError('Bundle too large')
    bundle = json.loads(raw)
    if digest(bundle) != checksum:
        raise ValueError('Bundle changed')
    batch_file = frappe.get_doc('File', bundle['batch_file'])
    if not batch_file.is_private or batch_file.is_folder:
        raise ValueError('Private batch required')
    batch_raw = batch_file.get_content()
    if len(batch_raw) > 50 * 1024 * 1024:
        raise ValueError('Batch too large')
    batch = json.loads(batch_raw)
    validate_batch(batch)
    if batch['batch_checksum'] != bundle['batch_checksum']:
        raise ValueError('Referenced batch changed')
    bundle['batch'] = batch
    if str(frappe.local.site) != bundle['batch']['site']:
        raise ValueError('Wrong target site')
    if not bundle.get('backup_id'):
        raise ValueError('Completed backup reference required')
    return bundle


@contextmanager
def maintenance_window():
    from frappe.installer import update_site_config
    switches = ('maintenance_mode', 'pause_scheduler', 'mute_emails')
    original = {key: frappe.conf.get(key) for key in switches}
    previous_mute = frappe.flags.get('mute_emails')
    try:
        for key in switches:
            update_site_config(key, 1)
        frappe.flags.mute_emails = True
        yield
    finally:
        frappe.flags.mute_emails = previous_mute
        for key in reversed(switches):
            update_site_config(key, original[key] if original[key] is not None else 'None')


def run(file_name, checksum):
    """Background-worker entry, not an HTTP endpoint and never an import commit."""
    from frappe.utils.background_jobs import get_redis_conn
    from rq import get_current_job
    job = get_current_job()
    if (not job or job.kwargs.get('method') != METHOD
            or job.kwargs.get('site') != str(frappe.local.site)
            or job.kwargs.get('user') != 'Administrator'):
        raise frappe.PermissionError('Authorised migration worker required')
    bundle = load_private(file_name, checksum)
    result = {'status': 'FAILED', 'committed_business_data': False,
              'source_bundle_checksum': checksum, 'phase': 'preflight'}
    lock = get_redis_conn().lock(str(frappe.local.site) + ':darkbrown-migration',
                               timeout=7500, blocking_timeout=1)
    with lock:
        with maintenance_window():
            try:
                verify_idle_site(frappe)
                report = inspect(frappe, bundle['batch'])
                if not report['passed']:
                    result['preflight'] = report
                    raise ValueError('Native preflight failed')
                original = capture(company=bundle['batch']['company'], expected_site=bundle['batch']['site'])
                old_plan = bundle['reset_plan']
                current_rows = {(dt, r['name']): r for dt, data in original['records'].items() for r in data['rows']}
                for row in old_plan['rows']:
                    current = current_rows.get((row['doctype'], row['name']))
                    if not current or current['content_checksum'] != row['source_record_checksum']:
                        raise ValueError('Reviewed dummy record changed')
                plan = reset_plan(original, [(r['doctype'], r['name']) for r in old_plan['rows']], old_plan['orphan_exceptions'])
                result['reset_plan'] = plan
                result['phase'] = 'rollback_only_reset'
                result['reset'] = execute(frappe, plan, {
                    'reset_checksum': plan['reset_checksum'],
                    'confirmation': 'REMOVE EXACT REVIEWED DUMMY RECORDS',
                    'backup_id': bundle['backup_id'], 'replacement_import_preflight_passed': True,
                    'queue_drain_verified': True})
                # Exercise the complete supplied test fixture. This flag exists
                # only on this private in-memory copy and NEVER authorises a
                # persistent import. The finally block always rolls it back.
                fixture = copy.deepcopy(bundle['batch'])
                fixture['complete_replacement'] = True
                fixture['batch_checksum'] = digest({k: v for k, v in fixture.items() if k != 'batch_checksum'})
                result['phase'] = 'rollback_only_native_import'
                result['import'] = import_batch(frappe, fixture)
                result['phase'] = 'rollback_only_idempotency'
                repeat = import_batch(frappe, fixture)
                if repeat['events_created'] or repeat['masters_created']:
                    raise ValueError('Identical rerun added records')
                result['rerun'] = {k: v for k, v in repeat.items() if k != 'documents'}
            except Exception as exc:
                result['error_type'] = type(exc).__name__
                result['error'] = str(exc)
            finally:
                frappe.db.rollback()
                frappe.clear_cache()
            if 'original' in locals():
                restored = capture(company=bundle['batch']['company'], expected_site=bundle['batch']['site'])
                result['rollback_verified'] = digest(original['records']) == digest(restored['records'])
                if not result['rollback_verified']:
                    result['error'] = 'Inventory changed across rollback; investigate before any execution'
                elif 'error' not in result:
                    result['status'] = 'PASSED_ROLLBACK_REHEARSAL'
            frappe.db.rollback()
    # Store evidence only after the business transaction has been rolled back.
    report_name = 'darkbrown-rollback-rehearsal-' + checksum[:12] + '-' + job.id[-12:] + '.json'
    doc = frappe.get_doc({'doctype': 'File', 'file_name': report_name,
                          'is_private': 1, 'content': json.dumps(result, default=str)})
    doc.insert()
    return {'status': result['status'], 'report_file': doc.name,
            'committed_business_data': False}
