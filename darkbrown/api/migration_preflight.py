"""Administrator-only read-only inspection of a private migration batch."""
import json
import frappe
from darkbrown.migration.preflight import inspect


@frappe.whitelist(methods=['POST'])
def inspect_private_batch(file_name, expected_checksum):
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    if not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
        raise ValueError('Exact batch checksum required')
    doc = frappe.get_doc('File', file_name)
    if not doc.is_private or doc.is_folder:
        raise ValueError('A private uploaded batch file is required')
    content = doc.get_content()
    if len(content) > 50 * 1024 * 1024:
        raise ValueError('Batch exceeds reviewed size limit')
    batch = json.loads(content)
    if batch.get('batch_checksum') != expected_checksum:
        raise ValueError('Uploaded batch checksum differs')
    return inspect(frappe, batch)
