# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Document Intake API for DarkBrown Real Estate.

Flow:
  1. Legal & Documentation user uploads a file on the /doc-intake page.
  2. A Document Register record is created (status = Draft) holding the file.
  3. extract_document() rasterises the PDF pages, sends them to the Claude
     vision API, parses the JSON, writes it back (status = Needs Review).
  4. The human reviews side-by-side with the source and edits (save_edits).
  5. confirm_and_push() archives the document (Document Archive, renamed per
     Building_Unit_DocType convention), links identity documents to the
     matched Customer/Supplier via the Party Document child table (with the
     two-check QID validation), and creates PDC Cheque records for confirmed
     cheque rows. Status -> Pushed.

Security:
  - The Anthropic API key is read server-side only, from site_config
    ("anthropic_api_key") or DBR Settings. It is NEVER exposed to the client.
  - All entry points are @frappe.whitelist() and permission-checked.
"""

import base64
import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from darkbrown.api.doc_intake_prompts import (
	SYSTEM_PROMPT,
	USER_INSTRUCTION,
)
from darkbrown.api import id_validation
from darkbrown.api.party_documents import append_party_document

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ESCALATION_MODEL = "claude-sonnet-5"
RENDER_DPI = 150
MAX_PAGES = 15  # safety cap; a huge PDF should be split before intake

# Register document_type -> Party Document document_type
PARTY_DOC_TYPE_MAP = {
	"QID / National ID": "QID / National ID",
	"Passport": "Passport",
	"Tenant Agreement": "Tenant Contract",
	"Landlord Contract": "Landlord Contract",
	"Owner Contract": "Owner Contract",
	"Cheque Batch": "Cheque Batch",
	"Utility / Other": "Utility / Other",
}

# Candidate fieldnames on PDC Cheque (created via Desk UI, so mapped
# defensively at runtime). First existing candidate wins.
PDC_FIELD_CANDIDATES = {
	"cheque_number": ["cheque_number", "cheque_no", "chq_no"],
	"cheque_date": ["cheque_date", "date", "due_date"],
	"amount": ["amount", "cheque_amount"],
	"bank_name": ["bank_name", "bank"],
	"direction": ["direction", "cheque_type", "type"],
	"payee": ["payee", "party_name", "in_favour_of"],
	"party_account_no": ["party_account_no", "account_no"],
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_api_key():
	"""Read the Anthropic key from site_config first, then DBR Settings.
	Never logged, never returned to the client."""
	key = frappe.conf.get("anthropic_api_key")
	if not key:
		try:
			key = frappe.db.get_single_value("DBR Settings", "anthropic_api_key")
			if key:
				key = frappe.utils.password.get_decrypted_password(
					"DBR Settings", "DBR Settings", "anthropic_api_key"
				)
		except Exception:
			key = None
	if not key:
		frappe.throw(
			_("Anthropic API key is not configured. Set 'anthropic_api_key' in "
			  "site_config.json or in DBR Settings.")
		)
	return key


def _get_model(escalate=False):
	return ESCALATION_MODEL if escalate else DEFAULT_MODEL


# ---------------------------------------------------------------------------
# PDF / image rendering
# ---------------------------------------------------------------------------

def _file_to_page_images(file_url):
	"""Return a list of (media_type, base64_data) for each page/image of the
	source file. PDFs are rasterised page-by-page; images are passed through."""
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()  # bytes
	fname = (file_doc.file_name or "").lower()

	images = []

	if fname.endswith(".pdf"):
		import fitz  # PyMuPDF

		pdf = fitz.open(stream=content, filetype="pdf")
		page_total = min(pdf.page_count, MAX_PAGES)
		for i in range(page_total):
			pix = pdf[i].get_pixmap(dpi=RENDER_DPI)
			png = pix.tobytes("png")
			images.append(("image/png", base64.standard_b64encode(png).decode()))
		pdf.close()
	else:
		# jpg / png / etc. -> send as-is
		media = "image/png"
		if fname.endswith((".jpg", ".jpeg")):
			media = "image/jpeg"
		images.append((media, base64.standard_b64encode(content).decode()))

	if not images:
		frappe.throw(_("Could not render any pages from the uploaded file."))
	return images


# ---------------------------------------------------------------------------
# Anthropic call
# ---------------------------------------------------------------------------

def _call_claude(images, model):
	"""Send the page images to Claude and return the parsed JSON dict."""
	import requests

	content = []
	for media_type, data in images:
		content.append({
			"type": "image",
			"source": {"type": "base64", "media_type": media_type, "data": data},
		})
	content.append({"type": "text", "text": USER_INSTRUCTION})

	payload = {
		"model": model,
		"max_tokens": 4096,
		"system": SYSTEM_PROMPT,
		"messages": [{"role": "user", "content": content}],
	}

	headers = {
		"x-api-key": _get_api_key(),
		"anthropic-version": ANTHROPIC_VERSION,
		"content-type": "application/json",
	}

	resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=120)
	if resp.status_code != 200:
		# Surface a clean error; do not leak the key or full payload
		frappe.log_error(
			title="Doc Intake: Anthropic API error",
			message=f"HTTP {resp.status_code}: {resp.text[:2000]}",
		)
		frappe.throw(_("Extraction service returned an error (HTTP {0}). "
		               "See error log.").format(resp.status_code))

	data = resp.json()
	# Concatenate all text blocks from the response
	text = "".join(
		block.get("text", "")
		for block in data.get("content", [])
		if block.get("type") == "text"
	).strip()

	return _parse_json(text)


def _parse_json(text):
	"""Parse the model's JSON output, tolerating stray code fences."""
	cleaned = text.strip()
	if cleaned.startswith("```"):
		# strip ```json ... ``` fences if the model added them
		cleaned = cleaned.split("```", 2)
		cleaned = cleaned[1] if len(cleaned) > 1 else text
		if cleaned.lstrip().lower().startswith("json"):
			cleaned = cleaned.lstrip()[4:]
	try:
		return json.loads(cleaned)
	except Exception:
		# last resort: grab the outermost {...}
		start = cleaned.find("{")
		end = cleaned.rfind("}")
		if start != -1 and end != -1:
			return json.loads(cleaned[start:end + 1])
		raise


# ---------------------------------------------------------------------------
# Writing results back to Document Register
# ---------------------------------------------------------------------------

def _apply_extraction(reg, result):
	"""Populate a Document Register doc from the parsed extraction dict."""
	dtype = result.get("document_type") or "Unknown"
	reg.document_type = dtype
	reg.detected_type = dtype
	reg.extraction_confidence = result.get("overall_confidence")
	reg.raw_json = json.dumps(result, indent=2, ensure_ascii=False)
	notes = result.get("notes") or []
	reg.extraction_notes = "\n".join(str(n) for n in notes) if notes else None

	# Contract-style fields (id_document block reuses the same flat fields)
	contract = result.get("contract") or result.get("id_document") or {}
	if contract:
		mapping = [
			"party_name", "party_name_ar", "id_number", "nationality",
			"cr_number", "counterparty_name", "counterparty_id",
			"contract_ref_no", "building_no", "zone", "street", "area_name",
			"unit_no", "electricity_no", "water_no", "monthly_rent",
			"security_deposit", "start_date", "end_date", "cheques_per_year",
		]
		for f in mapping:
			if contract.get(f) is not None:
				reg.set(f, contract.get(f))
		# id_document extras land in flat fields too
		if contract.get("expiry_date") and not reg.end_date:
			reg.end_date = contract.get("expiry_date")

	# Cheque batches: the drawer (account holder) is the party
	drawer = result.get("drawer") or {}
	if drawer.get("name") and not reg.party_name:
		reg.party_name = drawer.get("name")
	if drawer.get("name_ar") and not reg.party_name_ar:
		reg.party_name_ar = drawer.get("name_ar")

	# Cheque rows
	reg.set("cheques", [])
	for chq in (result.get("cheques") or []):
		reg.append("cheques", {
			"direction": chq.get("direction") or "Incoming (from Tenant)",
			"cheque_number": chq.get("cheque_number"),
			"cheque_date": chq.get("cheque_date"),
			"amount": chq.get("amount"),
			"amount_in_words": chq.get("amount_in_words"),
			"payee": chq.get("payee"),
			"party_account_no": chq.get("party_account_no"),
			"bank_name": chq.get("bank_name"),
			"branch": chq.get("branch"),
			"row_confidence": chq.get("confidence"),
			"row_notes": chq.get("notes"),
		})


# ---------------------------------------------------------------------------
# Whitelisted entry points — extraction
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_intake(file_url):
	"""Create a Document Register record for an uploaded file (status Draft)."""
	if not frappe.has_permission("Document Register", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	reg = frappe.new_doc("Document Register")
	reg.source_file = file_url
	reg.status = "Draft"
	reg.insert()
	return reg.name


@frappe.whitelist()
def extract_document(docname, escalate=0):
	"""Run extraction on a Document Register record and save the result.
	Returns the updated doc as a dict for the UI to render."""
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not reg.source_file:
		frappe.throw(_("No source file attached."))

	reg.db_set("status", "Extracting", commit=True)

	try:
		images = _file_to_page_images(reg.source_file)
		reg.page_count = len(images)
		model = _get_model(escalate=int(escalate or 0))
		result = _call_claude(images, model)

		_apply_extraction(reg, result)
		reg.extractor_model = model
		reg.extracted_on = now_datetime()
		reg.status = "Needs Review"
		reg.save()
		frappe.db.commit()
	except Exception as e:
		reg.db_set("status", "Draft", commit=True)
		frappe.log_error(title="Doc Intake extraction failed", message=frappe.get_traceback())
		frappe.throw(_("Extraction failed: {0}").format(str(e)))

	return reg.as_dict()


@frappe.whitelist()
def extract_from_upload(file_url, escalate=0):
	"""Convenience: create the register record AND extract in one call."""
	docname = create_intake(file_url)
	return extract_document(docname, escalate=escalate)


@frappe.whitelist()
def reject_document(docname, reason=None):
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	reg.status = "Rejected"
	if reason:
		reg.extraction_notes = (reg.extraction_notes or "") + f"\n[Rejected] {reason}"
	reg.save()
	frappe.db.commit()
	return reg.name


# ---------------------------------------------------------------------------
# Whitelisted entry points — review & push
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_document(docname):
	"""Fetch one register record for the review UI."""
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return reg.as_dict()


@frappe.whitelist()
def list_queue(limit=30):
	"""Register records awaiting action, newest first."""
	if not frappe.has_permission("Document Register", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_all(
		"Document Register",
		filters={"status": ["in", ["Draft", "Needs Review"]]},
		fields=["name", "status", "document_type", "party_name", "id_number",
		        "extraction_confidence", "source_file", "modified"],
		order_by="modified desc",
		limit_page_length=int(limit),
	)


@frappe.whitelist()
def save_edits(docname, updates):
	"""Apply reviewer edits. `updates` is a JSON dict of flat fields, plus an
	optional 'cheques' list that replaces the child rows wholesale."""
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	data = json.loads(updates) if isinstance(updates, str) else (updates or {})

	editable = {
		"document_type", "party_name", "party_name_ar", "id_number",
		"nationality", "cr_number", "counterparty_name", "counterparty_id",
		"contract_ref_no", "building_no", "zone", "street", "area_name",
		"unit_no", "electricity_no", "water_no", "monthly_rent",
		"security_deposit", "start_date", "end_date", "cheques_per_year",
		"extraction_notes",
	}
	for field, value in data.items():
		if field in editable:
			reg.set(field, value if value not in ("", "null") else None)

	if isinstance(data.get("cheques"), list):
		reg.set("cheques", [])
		for chq in data["cheques"]:
			reg.append("cheques", {
				"row_confirmed": 1 if chq.get("row_confirmed") else 0,
				"direction": chq.get("direction") or "Incoming (from Tenant)",
				"cheque_number": chq.get("cheque_number"),
				"cheque_date": chq.get("cheque_date") or None,
				"amount": chq.get("amount") or None,
				"amount_in_words": chq.get("amount_in_words"),
				"payee": chq.get("payee"),
				"party_account_no": chq.get("party_account_no"),
				"bank_name": chq.get("bank_name"),
				"branch": chq.get("branch"),
				"row_confidence": chq.get("row_confidence"),
				"row_notes": chq.get("row_notes"),
			})

	reg.save()
	frappe.db.commit()
	return reg.as_dict()


@frappe.whitelist()
def validate_id(docname):
	"""Run the two-check identity validation for the review UI."""
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	is_qid = reg.document_type != "Passport"
	return id_validation.validate_identity(
		reg.id_number, holder_name=reg.party_name,
		nationality=reg.nationality, doc_is_qid=is_qid,
	)


def _sanitize(part):
	part = re.sub(r"[^\w\- ]", "", str(part or "")).strip().replace(" ", "")
	return part or "NA"


def _archive_title(reg):
	"""Building_Unit_DocType per the locked filename convention; when the
	document has no property context (e.g. cheque batches, IDs), fall back
	to PartyName_DocType instead of NA_NA."""
	building = reg.area_name or reg.building_no
	unit = reg.unit_no
	dtype = (reg.document_type or "Doc").replace(" / ", "").replace(" ", "")
	if not building and not unit and reg.party_name:
		return f"{_sanitize(reg.party_name)[:40]}_{_sanitize(dtype)}"
	return f"{_sanitize(building or 'NA')}_{_sanitize(unit or 'NA')}_{_sanitize(dtype)}"


def _resolve_building(reg):
	"""Best-effort Building link from extracted fields; never throws."""
	try:
		meta = frappe.get_meta("Building")
		for field, value in (("building_no", reg.building_no), ("building_name", reg.area_name)):
			if value and meta.has_field(field):
				hit = frappe.db.get_value("Building", {field: value})
				if hit:
					return hit
	except Exception:
		pass
	return None


def _push_cheques(reg, refs):
	"""Create PDC Cheque records for confirmed rows. Fieldnames are resolved
	defensively since PDC Cheque was created via the Desk UI."""
	if not frappe.db.exists("DocType", "PDC Cheque"):
		refs.append("PDC Cheque DocType not found - cheque rows skipped")
		return

	meta = frappe.get_meta("PDC Cheque")
	fieldmap = {}
	for logical, candidates in PDC_FIELD_CANDIDATES.items():
		for c in candidates:
			if meta.has_field(c):
				fieldmap[logical] = c
				break

	if "cheque_number" not in fieldmap or "amount" not in fieldmap:
		refs.append("PDC Cheque fieldnames unrecognised - cheque rows skipped")
		return

	created = 0
	for row in reg.cheques or []:
		if not row.row_confirmed:
			continue
		if row.cheque_number and frappe.db.exists(
			"PDC Cheque", {fieldmap["cheque_number"]: row.cheque_number}
		):
			refs.append(f"Cheque {row.cheque_number}: already exists, skipped")
			continue
		pdc = frappe.new_doc("PDC Cheque")
		values = {
			"cheque_number": row.cheque_number,
			"cheque_date": row.cheque_date,
			"amount": row.amount,
			"bank_name": row.bank_name,
			"direction": row.direction,
			"payee": row.payee,
			"party_account_no": row.party_account_no,
		}
		for logical, value in values.items():
			if logical in fieldmap and value is not None:
				pdc.set(fieldmap[logical], value)
		pdc.flags.ignore_permissions = True
		pdc.insert()
		refs.append(f"PDC Cheque {pdc.name}")
		created += 1
	if not created:
		refs.append("No confirmed cheque rows to push")


@frappe.whitelist()
def confirm_and_push(docname):
	"""Reviewer confirmation: archive the document, link identity docs to the
	matched party, push confirmed cheques. Status -> Pushed."""
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if reg.status not in ("Needs Review", "Confirmed"):
		frappe.throw(_("Only records in Needs Review can be pushed."))

	refs = []
	warnings = []

	# 1) Identity validation + party linkage
	validation = None
	party_type = party = None
	if reg.id_number:
		is_qid = reg.document_type != "Passport"
		validation = id_validation.validate_identity(
			reg.id_number, holder_name=reg.party_name,
			nationality=reg.nationality, doc_is_qid=is_qid,
		)
		warnings.extend(validation.get("flags") or [])
		if validation.get("db_match"):
			party_type = validation["db_match"]["party_type"]
			party = validation["db_match"]["party"]

	# No ID (or no ID hit) but we have a name (e.g. cheque drawer):
	# conservative fuzzy match. Incoming cheques -> tenants, outgoing -> landlords.
	name_match = None
	if not party and reg.party_name:
		preferred = None
		if reg.document_type == "Cheque Batch" and reg.cheques:
			preferred = (
				"Supplier"
				if "Outgoing" in (reg.cheques[0].direction or "")
				else "Customer"
			)
		name_match = id_validation.find_party_by_name(reg.party_name, party_type=preferred)
		if name_match:
			party_type = name_match["party_type"]
			party = name_match["party"]
			refs.append(
				f"Matched {party_type} '{name_match['party_name']}' by name "
				f"(score {name_match['score']})"
			)
		else:
			warnings.append(
				f"No party matched the name '{reg.party_name}' - "
				"archived without link"
			)

	# 2) Archive (always)
	title = _archive_title(reg)
	archive = frappe.new_doc("Document Archive")
	archive.archive_title = title
	archive.document_type = reg.document_type if reg.document_type in PARTY_DOC_TYPE_MAP else "Utility / Other"
	archive.file = reg.source_file
	archive.id_number = reg.id_number
	archive.party_type = party_type
	archive.party = party
	archive.building = _resolve_building(reg)
	archive.source_register = reg.name
	try:
		fdoc = frappe.get_doc("File", {"file_url": reg.source_file})
		archive.original_filename = fdoc.file_name
		ext = (fdoc.file_name or "").rsplit(".", 1)
		if len(ext) == 2:
			fdoc.db_set("file_name", f"{title}.{ext[1]}")
	except Exception:
		pass
	archive.flags.ignore_permissions = True
	archive.insert()
	refs.append(f"Document Archive {archive.name} ({title})")

	# 3) Party Document row on the matched Customer/Supplier
	if party and reg.document_type in PARTY_DOC_TYPE_MAP:
		result = append_party_document(
			party_doctype=party_type,
			party_name=party,
			document_type=PARTY_DOC_TYPE_MAP[reg.document_type],
			id_number=reg.id_number,
			holder_name=reg.party_name,
			nationality=reg.nationality,
			expiry_date=reg.end_date,
			document_archive=archive.name,
			source_register=reg.name,
			file_url=reg.source_file,
			id_check_verified=bool(validation and validation.get("verified")),
		)
		refs.append(
			f"Party Document {result['status']} on {party_type} {party} "
			f"(flat field: {result['flat_field']})"
		)
		if result["flat_field"] == "conflict":
			warnings.append("ID conflict on party - flagged, flat field NOT changed")
	elif reg.id_number and not party:
		warnings.append("No matching party - document archived but not linked")

	# 4) Cheques
	if reg.document_type == "Cheque Batch":
		_push_cheques(reg, refs)

	# 5) Close out
	reg.status = "Pushed"
	reg.reviewed_by = frappe.session.user
	reg.reviewed_on = now_datetime()
	reg.pushed_refs = "\n".join(refs)
	reg.save()
	frappe.db.commit()

	return {"refs": refs, "warnings": warnings, "validation": validation, "archive": archive.name}
