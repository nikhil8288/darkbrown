"""Explicit Administrator replacement launch; not called from UI/deploy hooks."""
import json
import frappe
from darkbrown.migration.replacement import load_approved, METHOD

@frappe.whitelist(methods=['POST'])
def start(file_name, checksum, approval):
    bundle, approval, plan = load_approved(file_name, checksum, approval)
    job_id = 'darkbrown-replacement-' + frappe.generate_hash(length=12)
    frappe.enqueue(METHOD, queue='long', timeout=7200, job_id=job_id,
                   file_name=file_name, checksum=checksum, approval=approval,
                   enqueue_after_commit=True)
    return {'queued': True, 'commit_mode': True, 'job_id': job_id}

@frappe.whitelist(methods=['POST'])
def status(job_id):
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    from frappe.utils.background_jobs import get_job
    job = get_job(job_id)
    if not job or job.kwargs.get('method') != METHOD or job.kwargs.get('site') != str(frappe.local.site):
        raise ValueError('Unknown replacement job')
    result = {'job_status': job.get_status()}
    if job.is_finished and isinstance(job.result, dict):
        result.update(job.result)
        doc = frappe.get_doc('File', result['report_file'])
        if not doc.is_private: raise ValueError('Private report required')
        report = json.loads(doc.get_content())
        result['import_counts'] = {k: v for k, v in report['import'].items() if k != 'documents'}
        result['reconciliation'] = report['reconciliation']
        result['rerun'] = report['rerun']
    return result
