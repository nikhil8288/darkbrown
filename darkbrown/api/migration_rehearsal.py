"""Administrator-only launch of a rollback-only native rehearsal."""
import frappe
from darkbrown.migration.rehearsal import load_private, METHOD


@frappe.whitelist(methods=['POST'])
def start(file_name, checksum):
    load_private(file_name, checksum)
    job = frappe.enqueue(METHOD, queue='long', timeout=7200,
                         file_name=file_name, checksum=checksum,
                         enqueue_after_commit=True)
    return {'queued': True, 'commit_mode': False}
