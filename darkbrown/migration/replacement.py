"""Explicit, checksum-bound provisional replacement; never a deployment hook."""
import json
import frappe
from darkbrown.migration.evidence import digest
from darkbrown.migration.rehearsal import load_private, maintenance_window
from darkbrown.migration.inventory import capture
from darkbrown.migration.preflight import inspect
from darkbrown.migration.native_import import import_batch, approved_provisional_scope
from darkbrown.migration.reconcile import verify
from darkbrown.migration.scoped_reset import reset_plan, execute
from darkbrown.migration.runtime_queue import verify_idle_site

METHOD = 'darkbrown.migration.replacement.run'
CONFIRMATION = 'REPLACE EXACT REVIEWED DUMMY DATA WITH APPROVED PROVISIONAL HISTORY'


def load_approved(file_name, checksum, approval):
    bundle = load_private(file_name, checksum)
    if isinstance(approval, str):
        approval = json.loads(approval)
    if not isinstance(approval, dict) or approval.get('confirmation') != CONFIRMATION:
        raise ValueError('Explicit replacement confirmation required')
    if approval.get('bundle_checksum') != checksum or not approved_provisional_scope(bundle['batch'], approval.get('scope')):
        raise ValueError('Source/exception approval changed')
    doc = frappe.get_doc('File', approval['rehearsal_report'])
    if not doc.is_private:
        raise ValueError('Private rehearsal report required')
    report = json.loads(doc.get_content())
    if report.get('source_bundle_checksum') != checksum or report.get('committed_business_data') is not False:
        raise ValueError('Matching non-committing rehearsal required')
    if report.get('status') != 'PASSED_ROLLBACK_REHEARSAL' or report.get('rollback_verified') is not True:
        from darkbrown.migration.recovery import verify as verify_recovery
        recovery = verify_recovery(frappe, approval['rehearsal_report'], bundle, checksum)
        if approval.get('recovery_checksum') != digest(recovery):
            raise ValueError('Independent exact business recovery must be reviewed')
    plan = report['reset_plan']
    if approval.get('reset_checksum') != plan['reset_checksum']:
        raise ValueError('Exact reviewed deletion scope changed')
    if not approval.get('backup_id'):
        raise ValueError('Completed backup reference required')
    if report.get('import', {}).get('events_created') != len(bundle['batch']['events']):
        raise ValueError('Rehearsal did not exercise every source event')
    return bundle, approval, plan


def run(file_name, checksum, approval):
    from frappe.utils.background_jobs import get_redis_conn
    from rq import get_current_job
    job = get_current_job()
    if (not job or job.kwargs.get('method') != METHOD
            or job.kwargs.get('site') != str(frappe.local.site)
            or job.kwargs.get('user') != 'Administrator'):
        raise frappe.PermissionError('Authorised replacement worker required')
    bundle, approval, reviewed = load_approved(file_name, checksum, approval)
    batch = bundle['batch']
    marker_name = 'darkbrown-completed-replacement-' + checksum[:24] + '.json'
    previous = frappe.get_all('File', filters={'file_name': marker_name, 'is_private': 1}, pluck='name')
    if previous:
        # Never delete a second time after a successful replacement.
        if len(previous) != 1:
            raise ValueError('Ambiguous completion evidence')
        stored = json.loads(frappe.get_doc('File', previous[0]).get_content())
        if stored.get('source_bundle_checksum') != checksum or stored.get('status') != 'COMPLETED_PROVISIONAL_REPLACEMENT':
            raise ValueError('Invalid completion marker')
        return {'status': stored['status'], 'report_file': previous[0], 'already_completed': True}
    result = {'status': 'FAILED', 'committed_business_data': False,
              'source_bundle_checksum': checksum, 'approval_checksum': digest(approval)}
    lock = get_redis_conn().lock(str(frappe.local.site) + ':darkbrown-migration', timeout=7500, blocking_timeout=1)
    with lock:
        with maintenance_window():
            try:
                verify_idle_site(frappe)
                if not inspect(frappe, batch)['passed']:
                    raise ValueError('Native preflight failed')
                current = capture(company=batch['company'], expected_site=batch['site'])
                plan = reset_plan(current, [(r['doctype'], r['name']) for r in reviewed['rows']], reviewed['orphan_exceptions'])
                for key in ('rows', 'business_population_checksum', 'protected_setup_checksum'):
                    if plan[key] != reviewed[key]:
                        raise ValueError('Site changed since successful rehearsal and approval')
                result['reset'] = execute(frappe, plan, {
                    'reset_checksum': plan['reset_checksum'], 'confirmation': 'REMOVE EXACT REVIEWED DUMMY RECORDS',
                    'backup_id': approval['backup_id'], 'replacement_import_preflight_passed': True,
                    'queue_drain_verified': True})
                result['import'] = import_batch(frappe, batch, approved_scope=approval['scope'])
                result['reconciliation'] = verify(frappe, batch)
                repeated = import_batch(frappe, batch, approved_scope=approval['scope'])
                if repeated['events_created'] or repeated['masters_created']:
                    raise ValueError('Identical rerun added records')
                result['rerun'] = {k: v for k, v in repeated.items() if k != 'documents'}
                result['status'] = 'COMPLETED_PROVISIONAL_REPLACEMENT'
                result['committed_business_data'] = True
                result['accepted_unresolved_scope'] = approval['scope']
                report = frappe.get_doc({'doctype': 'File', 'file_name': marker_name,
                    'is_private': 1, 'content': json.dumps(result, default=str)})
                report.insert()
                # Business data and completion marker persist in ONE transaction.
                frappe.db.commit()
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                frappe.clear_cache()
    return {'status': result['status'], 'report_file': report.name,
            'committed_business_data': True}
