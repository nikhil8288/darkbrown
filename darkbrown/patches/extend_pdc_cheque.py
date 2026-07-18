# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Phase 1 of PDC accounting: turn PDC Cheque (Desk-created DocType) into a
real accounting object.

- Ensures the status Select carries the full lifecycle:
  In Hand / Deposited / Cleared / Bounced / Replaced / Cancelled
  (existing options are preserved; missing ones appended)
- Adds: cheque_type, payment_entry, journal_entry, source_register,
  bounce_date custom fields
- Creates a Client Script adding "Mark Cleared" / "Mark Bounced" buttons
  to the PDC Cheque form, wired to darkbrown.utils.pdc_accounting

Idempotent: safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

LIFECYCLE = ["In Hand", "Deposited", "Cleared", "Bounced", "Replaced", "Cancelled"]

CLIENT_SCRIPT_NAME = "PDC Cheque Accounting Buttons"
CLIENT_SCRIPT = r"""
frappe.ui.form.on('PDC Cheque', {
    refresh(frm) {
        if (frm.is_new()) return;
        const st = frm.doc.status;
        if (!['Cleared', 'Cancelled', 'Replaced'].includes(st)) {
            frm.add_custom_button(__('Mark Cleared'), () => {
                frappe.prompt(
                    [{fieldname: 'clearance_date', fieldtype: 'Date',
                      label: 'Clearance date (from bank statement)',
                      default: frappe.datetime.get_today(), reqd: 1}],
                    (v) => {
                        frappe.call({
                            method: 'darkbrown.utils.pdc_accounting.mark_cleared',
                            args: {pdc: frm.doc.name, clearance_date: v.clearance_date},
                            freeze: true, freeze_message: __('Creating payment entry...'),
                            callback: (r) => {
                                frappe.msgprint(r.message && r.message.msg || 'Done');
                                frm.reload_doc();
                            }
                        });
                    }, __('Mark Cleared'), __('Confirm'));
            }, __('Accounting'));
        }
        if (!['Bounced', 'Cancelled'].includes(st)) {
            frm.add_custom_button(__('Mark Bounced'), () => {
                frappe.confirm(
                    __('Mark this cheque as bounced? Any linked Payment Entry will be cancelled.'),
                    () => {
                        frappe.call({
                            method: 'darkbrown.utils.pdc_accounting.mark_bounced',
                            args: {pdc: frm.doc.name},
                            freeze: true,
                            callback: (r) => {
                                frappe.msgprint(r.message && r.message.msg || 'Done');
                                frm.reload_doc();
                            }
                        });
                    });
            }, __('Accounting'));
        }
    }
});
"""


def _extend_status_options():
	"""Append missing lifecycle options to the existing status Select of the
	Desk-created PDC Cheque DocType, preserving whatever is already there."""
	if not frappe.db.exists("DocType", "PDC Cheque"):
		return
	dt = frappe.get_doc("DocType", "PDC Cheque")
	for f in dt.fields:
		if f.fieldname == "status" and f.fieldtype == "Select":
			existing = [o.strip() for o in (f.options or "").split("\n") if o.strip()]
			merged = existing + [o for o in LIFECYCLE if o not in existing]
			if merged != existing:
				f.options = "\n".join(merged)
				dt.flags.ignore_permissions = True
				dt.save()
			break


def execute():
	_extend_status_options()

	create_custom_fields({
		"PDC Cheque": [
			{
				"fieldname": "cheque_type",
				"fieldtype": "Select",
				"label": "Cheque Type",
				"options": "Rent\nSecurity Deposit\nOther",
				"default": "Rent",
				"insert_after": "amount",
			},
			{
				"fieldname": "payment_entry",
				"fieldtype": "Link",
				"label": "Payment Entry",
				"options": "Payment Entry",
				"read_only": 1,
				"insert_after": "cleared_date",
			},
			{
				"fieldname": "journal_entry",
				"fieldtype": "Link",
				"label": "Journal Entry",
				"options": "Journal Entry",
				"read_only": 1,
				"insert_after": "payment_entry",
			},
			{
				"fieldname": "source_register",
				"fieldtype": "Link",
				"label": "Source Register Entry",
				"options": "Document Register",
				"read_only": 1,
				"insert_after": "journal_entry",
			},
			{
				"fieldname": "bounce_date",
				"fieldtype": "Date",
				"label": "Bounce Date",
				"read_only": 1,
				"insert_after": "source_register",
			},
		],
	}, ignore_validate=True)

	# Desk form buttons via Client Script
	if frappe.db.exists("Client Script", CLIENT_SCRIPT_NAME):
		cs = frappe.get_doc("Client Script", CLIENT_SCRIPT_NAME)
		cs.script = CLIENT_SCRIPT
		cs.enabled = 1
		cs.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "Client Script",
			"name": CLIENT_SCRIPT_NAME,
			"dt": "PDC Cheque",
			"view": "Form",
			"enabled": 1,
			"script": CLIENT_SCRIPT,
		}).insert(ignore_permissions=True)

	frappe.db.commit()
