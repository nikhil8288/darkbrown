# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Party Document helpers for the Document Intake system.

Called from doc_intake.confirm_and_push() when a confirmed document is an
identity document (QID / Passport) or any doc that should hang off a party.

Rules:
  - Never silently overwrite: if the party already has a different QID /
    passport number on file, the row is added with verification_status
    "Conflict" and the flat field is left untouched.
  - If the flat field is empty, it is filled from the confirmed extraction.
  - De-dupe: same party + same document_type + same id_number = update the
    existing row (refresh archive link / expiry) instead of adding another.
"""

import frappe
from frappe.utils import getdate


def append_party_document(
	party_doctype,          # "Customer" or "Supplier"
	party_name,             # docname
	document_type,          # value from Party Document.document_type Select
	id_number=None,
	holder_name=None,
	nationality=None,
	issue_date=None,
	expiry_date=None,
	document_archive=None,  # Document Archive docname
	source_register=None,   # Document Register docname
	file_url=None,
	id_check_verified=False,  # result of the two-check QID/name validation
):
	"""Append (or update) a Party Document row on the given party.

	Returns a dict: {"row": <row name>, "status": "added|updated",
	                 "flat_field": "filled|conflict|unchanged"}
	"""
	party = frappe.get_doc(party_doctype, party_name)

	clean_id = (id_number or "").replace(" ", "").strip()

	# --- de-dupe: update existing row if same type + id ---
	existing = None
	for row in party.get("dbr_party_documents") or []:
		if (
			row.document_type == document_type
			and (row.id_number or "").replace(" ", "").strip() == clean_id
			and clean_id
		):
			existing = row
			break

	if existing:
		existing.document_archive = document_archive or existing.document_archive
		existing.source_register = source_register or existing.source_register
		existing.file = file_url or existing.file
		existing.expiry_date = expiry_date or existing.expiry_date
		existing.issue_date = issue_date or existing.issue_date
		if id_check_verified and existing.verification_status != "Conflict":
			existing.verification_status = "Verified"
		row_ref, status = existing, "updated"
	else:
		row_ref = party.append(
			"dbr_party_documents",
			{
				"document_type": document_type,
				"id_number": clean_id,
				"holder_name": holder_name,
				"nationality": nationality,
				"issue_date": issue_date,
				"expiry_date": expiry_date,
				"document_archive": document_archive,
				"source_register": source_register,
				"file": file_url,
				"verification_status": "Verified" if id_check_verified else "Unverified",
			},
		)
		status = "added"

	# --- flat field handling (QID / Passport only) ---
	flat_result = "unchanged"
	flat_field = None
	if document_type == "QID / National ID":
		flat_field = "custom_qid" if party.meta.has_field("custom_qid") else None
	elif document_type == "Passport":
		flat_field = "custom_passport_no" if party.meta.has_field("custom_passport_no") else None

	if flat_field and clean_id:
		current = (party.get(flat_field) or "").replace(" ", "").strip()
		if not current:
			party.set(flat_field, clean_id)
			flat_result = "filled"
		elif current != clean_id:
			row_ref.verification_status = "Conflict"
			row_ref.remarks = (
				f"ID on file ({current}) differs from extracted ({clean_id}). "
				"Flat field NOT changed — resolve manually."
			)
			flat_result = "conflict"

	party.flags.ignore_permissions = True
	party.save()
	return {"row": row_ref.name, "status": status, "flat_field": flat_result}


def get_expiring_ids(days=60):
	"""All party ID documents expiring within N days — for a future
	attention alert on the MD dashboard."""
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), days)
	rows = frappe.get_all(
		"Party Document",
		filters={
			"document_type": ["in", ["QID / National ID", "Passport"]],
			"expiry_date": ["<=", cutoff],
		},
		# Party Document carries document_no; id_number and holder_name are
		# V1 names and this query returned an Unknown column error, not rows.
		fields=[
			"parent", "parenttype", "document_type",
			"document_no", "expiry_date",
		],
		order_by="expiry_date asc",
	)
	return rows
