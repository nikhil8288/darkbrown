"""Read-only Administrator check; caller may retain its private result."""
import frappe
from darkbrown.migration.rehearsal import load_private
from darkbrown.migration.recovery import verify

@frappe.whitelist(methods=['POST'])
def inspect(file_name, checksum, rehearsal_report):
    bundle = load_private(file_name, checksum)
    return verify(frappe, rehearsal_report, bundle, checksum)
