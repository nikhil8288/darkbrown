"""Daily refresh of Document Register statuses.

HISTORY: this originally rolled forward Expiring Soon / Expired statuses on
the old building-documents register (fields `file` + `expiry_date`, with a
compute_status() helper on the controller). That schema was replaced by the
Document Intake staging register (statuses Draft / Extracting / Needs Review /
Confirmed / Pushed / Rejected), whose status is driven entirely by the intake
workflow — so there is nothing to roll forward daily anymore.

The old import of compute_status crashed this job on every scheduler run.
The function is kept (hooks.py still references it) but is now a guarded
no-op: if a future register ever reintroduces expiry_date, wire the new
logic here. Expiry tracking now lives on Party Document rows
(darkbrown.api.party_documents.get_expiring_ids).
"""

import frappe


def refresh_statuses():
	if not frappe.db.exists("DocType", "Document Register"):
		return
	meta = frappe.get_meta("Document Register")
	if not meta.has_field("expiry_date"):
		# Intake-era register: status is workflow-driven; nothing to refresh.
		return
	# (Legacy path, only if an expiry_date field exists again.)
	from frappe.utils import getdate, nowdate, add_days

	today = getdate(nowdate())
	soon = getdate(add_days(nowdate(), 30))
	for r in frappe.get_all(
		"Document Register",
		fields=["name", "expiry_date", "status"],
		filters={"expiry_date": ["is", "set"]},
	):
		exp = getdate(r.expiry_date)
		new = "Expired" if exp < today else ("Expiring Soon" if exp <= soon else None)
		if new and new != r.status:
			frappe.db.set_value(
				"Document Register", r.name, "status", new, update_modified=False
			)
	frappe.db.commit()
