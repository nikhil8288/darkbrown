"""Administrator-only launch of a rollback-only native rehearsal."""
import json
import frappe
from darkbrown.migration.rehearsal import load_private, METHOD


@frappe.whitelist(methods=['POST'])
def start(file_name, checksum):
    load_private(file_name, checksum)
    job_id = 'darkbrown-rehearsal-' + frappe.generate_hash(length=12)
    frappe.enqueue(METHOD, queue='long', timeout=7200, job_id=job_id,
                         file_name=file_name, checksum=checksum,
                         enqueue_after_commit=True)
    return {'queued': True, 'commit_mode': False, 'job_id': job_id}


@frappe.whitelist(methods=['POST'])
def status(job_id):
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    from frappe.utils.background_jobs import get_job
    job = get_job(job_id)
    if not job or job.kwargs.get('method') != METHOD or job.kwargs.get('site') != str(frappe.local.site):
        raise ValueError('Unknown site rehearsal job')
    result = {'job_status': job.get_status(), 'commit_mode': False}
    if job.is_finished and isinstance(job.result, dict):
        result.update(job.result)
        if result.get('report_file'):
            doc = frappe.get_doc('File', result['report_file'])
            if not doc.is_private:
                raise ValueError('Rehearsal report must be private')
            report = json.loads(doc.get_content())
            result['summary'] = {k: report.get(k) for k in
                ('status', 'phase', 'error', 'error_type', 'rollback_verified', 'committed_business_data')}
            result['import_counts'] = {k: v for k, v in report.get('import', {}).items() if k != 'documents'}
            result['rerun'] = report.get('rerun')
    return result
