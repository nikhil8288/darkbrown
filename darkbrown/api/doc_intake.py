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
     two-check QID validation), and creates Cheque records for confirmed
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
from frappe.utils import now_datetime, flt, getdate

from darkbrown.api.doc_intake_prompts import (
	SYSTEM_PROMPT,
	USER_INSTRUCTION,
)
from darkbrown.api import id_validation
from darkbrown.api.party_documents import append_party_document
from darkbrown.guards import guard, ACC, DOC, MD

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
	"Head Lease": "Head Lease",
	"Owner Contract": "Owner Contract",
	"Cheque Batch": "Cheque Batch",
	"Utility / Other": "Utility / Other",
}

# Candidate fieldnames on Cheque (created via Desk UI, so mapped
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

#: The model's document_type vocabulary and the Document Register's Select
#: options are two different lists, written at different times. Four of the
#: nine labels the model can return are not options on the field, and writing
#: one of them is a validation error rather than a bad classification. The
#: translation happens here, once, on the way in.
REG_TYPE = {
	"Head Lease": "Head Lease",
	"Owner Contract": "Head Lease",          # the same paper, seen from our side
	"Tenant Agreement": "Tenancy Agreement",
	"Tenancy Agreement": "Tenancy Agreement",
	"QID / National ID": "QID",
	"QID": "QID",
	"Passport": "Passport",
	"Commercial Registration": "Commercial Registration",
	"Cheque Batch": "Cheque Batch",
	"Utility / Other": "Utility Bill",
	"Utility Bill": "Utility Bill",
	"Bank Statement": "Bank Statement",
	"Maintenance Invoice": "Maintenance Invoice",
	"Other": "Other",
	"Unknown": "Unknown",
}


def _reg_type(raw):
	"""Model label -> a value the Select will actually accept."""
	return REG_TYPE.get((raw or "").strip(), "Unknown")


#: Everything the extractor produces that the V2 Document Register has no
#: column for. It is kept in `extracted_json` and put back on the in-memory
#: doc by _rehydrate(), so code written against the old flat schema still
#: reads the right values without the doctype growing fifty columns.
FLAT_FIELDS = (
	"party_name", "party_name_ar", "id_number", "nationality", "cr_number",
	"counterparty_name", "counterparty_id", "contract_ref_no", "building_no",
	"zone", "street", "area_name", "unit_no", "electricity_no", "water_no",
	"monthly_rent", "annual_rent", "security_deposit", "start_date",
	"end_date", "cheques_per_year", "building_name", "floors", "total_units",
	"detected_type", "extraction_notes",
)


def _setf(reg, fieldname, value):
	"""Write only if the doctype actually has the column.

	Assigning an unknown fieldname on a Frappe doc is silent — it sets a
	Python attribute that never reaches the database — so a whole extraction
	could appear to save and persist nothing. This makes the distinction
	explicit: real fields are written, the rest are the caller's problem.
	"""
	if value is None or value == "":
		return False
	if not reg.meta.has_field(fieldname):
		return False
	reg.set(fieldname, value)
	return True


def _rehydrate(reg):
	"""Put the flat extraction values back on a freshly loaded register doc.

	`extracted_json` is the record; these attributes are a convenience view of
	it. Call this before any code that reads reg.party_name, reg.cheques and
	the rest.
	"""
	try:
		data = json.loads(reg.extracted_json) if reg.extracted_json else {}
	except Exception:
		data = {}
	flat = dict(data.get("contract") or {})
	flat.update({k: v for k, v in (data.get("id_document") or {}).items()
	             if v is not None})
	for f in FLAT_FIELDS:
		if getattr(reg, f, None) in (None, ""):
			setattr(reg, f, flat.get(f))
	if not getattr(reg, "detected_type", None):
		reg.detected_type = data.get("document_type")
	drawer = data.get("drawer") or {}
	if drawer.get("name") and not getattr(reg, "party_name", None):
		reg.party_name = drawer.get("name")
	if not getattr(reg, "cheques", None):
		reg.cheques = [frappe._dict(c) for c in (data.get("cheques") or [])]
	stmt = data.get("statement") or {}
	if stmt and not getattr(reg, "statement_lines", None):
		reg.statement_bank = stmt.get("bank")
		reg.statement_account_no = stmt.get("account_no")
		reg.opening_balance = stmt.get("opening_balance")
		reg.closing_balance = stmt.get("closing_balance")
		reg.statement_lines = [frappe._dict(l) for l in (stmt.get("lines") or [])]
	return reg


def _apply_extraction(reg, result):
	"""Populate a Document Register doc from the parsed extraction dict.

	The register keeps the whole reading in `extracted_json`. Only the handful
	of things the doctype has real columns for are also written flat, and each
	of those is guarded, because a field the doctype does not have absorbs the
	value silently and loses it.
	"""
	raw_type = result.get("document_type") or "Unknown"
	reg.document_type = _reg_type(raw_type)
	reg.detected_type = raw_type          # in-memory only; the model's own word
	reg.extraction_confidence = flt(result.get("overall_confidence") or 0)

	# The record of what was read. Everything else on this doc is a view of it.
	reg.extracted_json = json.dumps(result, indent=2, ensure_ascii=False)
	_setf(reg, "raw_json", reg.extracted_json)   # only if an older site has it

	notes = result.get("notes") or []
	reg.extraction_notes = "\n".join(str(n) for n in notes) if notes else None
	_setf(reg, "extraction_notes", reg.extraction_notes)

	# Contract-style fields. The id_document block reuses the same flat names.
	contract = dict(result.get("contract") or {})
	for k, v in (result.get("id_document") or {}).items():
		if v is not None and contract.get(k) is None:
			contract[k] = v

	if contract:
		for f in FLAT_FIELDS:
			if contract.get(f) is not None:
				setattr(reg, f, contract.get(f))
				_setf(reg, f, contract.get(f))

		# What the V2 register does have columns for.
		_setf(reg, "document_no", contract.get("id_number")
		      or contract.get("cr_number") or contract.get("contract_ref_no"))
		_setf(reg, "issue_date", contract.get("start_date"))
		_setf(reg, "expiry_date", contract.get("end_date")
		      or contract.get("expiry_date"))
		_setf(reg, "unit", None)      # a Link; matched on review, never guessed

	# Cheque batches: the drawer (account holder) is the party
	drawer = result.get("drawer") or {}
	if drawer.get("name") and not getattr(reg, "party_name", None):
		reg.party_name = drawer.get("name")
	if drawer.get("name_ar") and not getattr(reg, "party_name_ar", None):
		reg.party_name_ar = drawer.get("name_ar")

	# Cheque rows. Kept in the JSON always; written to the child table only
	# where that table exists.
	cheques = result.get("cheques") or []
	reg.cheques = [frappe._dict(c) for c in cheques]
	if cheques and reg.meta.has_field("cheques"):
		reg.set("cheques", [])
		for chq in cheques:
			reg.append("cheques", {
				"direction": chq.get("direction") or "Incoming (from Tenant)",
				"cheque_type": chq.get("cheque_type") or "Rent",
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

	# Bank statement, same rule.
	stmt = result.get("statement") or {}
	if stmt:
		reg.statement_bank = stmt.get("bank")
		reg.statement_account_no = stmt.get("account_no")
		reg.opening_balance = stmt.get("opening_balance")
		reg.closing_balance = stmt.get("closing_balance")
		reg.statement_lines = [frappe._dict(l) for l in (stmt.get("lines") or [])]
		if reg.meta.has_field("statement_lines"):
			_setf(reg, "statement_bank", stmt.get("bank"))
			_setf(reg, "statement_account_no", stmt.get("account_no"))
			_setf(reg, "statement_from", stmt.get("period_from"))
			_setf(reg, "statement_to", stmt.get("period_to"))
			_setf(reg, "opening_balance", stmt.get("opening_balance"))
			_setf(reg, "closing_balance", stmt.get("closing_balance"))
			reg.set("statement_lines", [])
			for ln in (stmt.get("lines") or []):
				reg.append("statement_lines", {
					"txn_date": ln.get("date"),
					"description": ln.get("description"),
					"ref_no": ln.get("ref_no"),
					"debit": ln.get("debit"),
					"credit": ln.get("credit"),
					"balance": ln.get("balance"),
					"line_status": "Unmatched",
				})


# ---------------------------------------------------------------------------
# Whitelisted entry points — extraction
# ---------------------------------------------------------------------------

def _find_duplicate(file_url):
	"""Return the name of an existing non-rejected Document Register entry
	whose source file has the same content hash (true duplicate even if the
	filename differs), else None."""
	try:
		this_hash = frappe.db.get_value("File", {"file_url": file_url}, "content_hash")
		if not this_hash:
			return None
		twin_urls = frappe.get_all(
			"File",
			filters={"content_hash": this_hash, "file_url": ["!=", file_url]},
			pluck="file_url",
		)
		if not twin_urls:
			return None
		return frappe.db.get_value(
			"Document Register",
			{"source_file": ["in", twin_urls], "status": ["!=", "Rejected"]},
			"name",
		)
	except Exception:
		return None


@frappe.whitelist()
def create_intake(file_url):
	"""Create a Document Register record for an uploaded file (status Draft)."""
	guard(MD, DOC)
	if not frappe.has_permission("Document Register", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	reg = frappe.new_doc("Document Register")
	reg.source_file = file_url
	reg.status = "Draft"
	# document_type is mandatory and carries a default, but the default is not
	# reaching this path — five files in a row failed insert on it. Set it.
	# The real classification lands in _apply_extraction a moment later.
	reg.document_type = "Unknown"
	reg.insert()
	return reg.name


@frappe.whitelist()
def extract_document(docname, escalate=0):
	"""Run extraction on a Document Register record and save the result.
	Returns the updated doc as a dict for the UI to render."""
	guard(MD, DOC)
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
def extract_from_upload(file_url, escalate=0, skip_duplicate_check=0):
	"""Convenience: create the register record AND extract in one call.
	Duplicate files (same content hash as an existing non-rejected register
	entry) are skipped BEFORE any API spend, unless explicitly overridden."""
	guard(MD, DOC)
	if not int(skip_duplicate_check or 0):
		twin = _find_duplicate(file_url)
		if twin:
			return {"duplicate": twin, "file_url": file_url}
	docname = create_intake(file_url)
	return extract_document(docname, escalate=escalate)


@frappe.whitelist()
def reject_document(docname, reason=None):
	guard(MD, DOC)
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
	guard(MD, DOC, ACC)
	reg = _rehydrate(frappe.get_doc("Document Register", docname))
	if not reg.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return reg.as_dict()


@frappe.whitelist()
def list_queue(limit=30):
	"""Register records awaiting action, newest first."""
	guard(MD, DOC, ACC)
	if not frappe.has_permission("Document Register", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_all(
		"Document Register",
		filters={"status": ["in", ["Draft", "Needs Review"]]},
		fields=["name", "status", "document_type", "party", "document_no",
		        "extraction_confidence", "source_file", "modified"],
		order_by="modified desc",
		limit_page_length=int(limit),
	)


@frappe.whitelist()
def save_edits(docname, updates):
	"""Apply reviewer edits. `updates` is a JSON dict of flat fields, plus an
	optional 'cheques' list that replaces the child rows wholesale."""
	guard(MD, DOC)
	reg = _rehydrate(frappe.get_doc("Document Register", docname))
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
				"cheque_type": chq.get("cheque_type") or "Rent",
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
	guard(MD, DOC)
	reg = _rehydrate(frappe.get_doc("Document Register", docname))
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


def _agreement_for(party_type, party):
	"""Active agreement for the linked party (Phase 1 linkage)."""
	try:
		if party_type == "Customer":
			return ("tenant_rental_agreement", frappe.db.get_value(
				"Tenancy Agreement",
				{"tenant": party, "status": "Active"}, "name"))
		if party_type == "Supplier":
			return ("landlord_contract", frappe.db.get_value(
				"Head Lease",
				{"landlord": party, "status": "Active"}, "name"))
	except Exception:
		pass
	return (None, None)


def _push_cheques(reg, refs, party_type=None, party=None):
	"""Create Cheque records for confirmed rows. Fieldnames are resolved
	defensively since Cheque was created via the Desk UI. Phase 1: each
	PDC is linked to its party and active agreement, typed, and starts its
	lifecycle at 'In Hand'."""
	if not frappe.db.exists("DocType", "Cheque"):
		refs.append("Cheque DocType not found - cheque rows skipped")
		return

	meta = frappe.get_meta("Cheque")
	fieldmap = {}
	for logical, candidates in PDC_FIELD_CANDIDATES.items():
		for c in candidates:
			if meta.has_field(c):
				fieldmap[logical] = c
				break

	if "cheque_number" not in fieldmap or "amount" not in fieldmap:
		refs.append("Cheque fieldnames unrecognised - cheque rows skipped")
		return

	# The live PDC schema: 'party' is a role Select (Tenant/Landlord);
	# the actual party lives in separate link fields. Handle all variants.
	party_value = None
	party_role = None
	party_link_field = None
	if party:
		pf = meta.get_field("party")
		if pf and pf.fieldtype == "Link":
			party_value = party
		elif pf and pf.fieldtype == "Select":
			opts = [o.strip() for o in (pf.options or "").split("\n")]
			party_role = ("Tenant" if party_type == "Customer" else "Landlord")
			if party_role not in opts:
				party_role = None
		elif pf:  # Data
			name_field = "customer_name" if party_type == "Customer" else "supplier_name"
			party_value = frappe.db.get_value(party_type, party, name_field) or party
		# the real party link field, whatever it's called
		candidates = (["tenant", "customer"] if party_type == "Customer"
		              else ["landlord", "supplier"])
		for c in candidates:
			f = meta.get_field(c)
			if f and f.fieldtype == "Link":
				party_link_field = c
				break
	agr_field, agr_name = _agreement_for(party_type, party) if party else (None, None)

	status_opts = [o.strip() for o in (meta.get_field("status").options or "").split("\n")] \
		if meta.has_field("status") else []
	initial_status = "In Hand" if "In Hand" in status_opts else None

	created = 0
	for row in reg.cheques or []:
		if not row.row_confirmed:
			continue
		if row.cheque_number and frappe.db.exists(
			"Cheque", {fieldmap["cheque_number"]: row.cheque_number}
		):
			refs.append(f"Cheque {row.cheque_number}: already exists, skipped")
			continue
		pdc = frappe.new_doc("Cheque")
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
		if meta.has_field("party"):
			if party_value:
				pdc.set("party", party_value)
			elif party_role:
				pdc.set("party", party_role)
		if party and party_link_field:
			pdc.set(party_link_field, party)
		if agr_field and agr_name and meta.has_field(agr_field):
			pdc.set(agr_field, agr_name)
		if initial_status:
			pdc.set("status", initial_status)
		if meta.has_field("cheque_type"):
			pdc.set("cheque_type", row.get("cheque_type") or "Rent")
		if meta.has_field("source_register"):
			pdc.set("source_register", reg.name)
		pdc.flags.ignore_permissions = True
		pdc.insert()
		refs.append(f"Cheque {pdc.name}"
		            + (f" [{row.get('cheque_type')}]" if row.get("cheque_type") and row.get("cheque_type") != "Rent" else ""))
		created += 1
	if not created:
		refs.append("No confirmed cheque rows to push")


@frappe.whitelist()
def confirm_and_push(docname):
	"""Reviewer confirmation: archive the document, link identity docs to the
	matched party, push confirmed cheques. Status -> Pushed."""
	guard(MD, DOC)
	reg = _rehydrate(frappe.get_doc("Document Register", docname))
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if reg.status not in ("Needs Review", "Confirmed"):
		frappe.throw(_("Only records in Needs Review can be pushed."))
	if reg.document_type == "Cheque Batch" and not any(
		r.row_confirmed for r in (reg.cheques or [])
	):
		frappe.throw(
			_("No cheque rows are ticked. Tick each cheque you have verified "
			  "against the scan (or use Tick all), then push.")
		)

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

	# No ID (or no ID hit) but we have a name (e.g. cheque batches):
	# conservative fuzzy match. The counterparty depends on direction -
	# incoming: the DRAWER (tenant paying us); outgoing: the PAYEE
	# (landlord we pay). Our own name is never a link candidate.
	name_match = None
	match_name = reg.party_name
	if not party and reg.document_type == "Cheque Batch" and reg.cheques:
		outgoing = "Outgoing" in (reg.cheques[0].direction or "")
		if outgoing:
			match_name = None
			for r in reg.cheques:
				if r.payee and "dark brown" not in r.payee.lower():
					match_name = r.payee
					break
		preferred = "Supplier" if outgoing else "Customer"
	else:
		preferred = None
	if match_name and "dark brown" in match_name.lower():
		match_name = None  # that's us, not a counterparty
	if not party and match_name:
		name_match = id_validation.find_party_by_name(match_name, party_type=preferred)
		if name_match:
			party_type = name_match["party_type"]
			party = name_match["party"]
			refs.append(
				f"Matched {party_type} '{name_match['party_name']}' by name "
				f"(score {name_match['score']})"
			)
		else:
			warnings.append(
				f"No party matched the name '{match_name}' - "
				"archived without link"
			)

	# 2) Archive (always) - titled by the true counterparty where known
	title_name = (name_match and name_match["party_name"]) or match_name or reg.party_name
	if title_name and "dark brown" in title_name.lower():
		title_name = None
	if title_name and not (reg.area_name or reg.building_no or reg.unit_no):
		title = f"{_sanitize(title_name)[:40]}_{_sanitize((reg.document_type or 'Doc').replace(' / ', '').replace(' ', ''))}"
	else:
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

	# 4) Cheques - now party- and agreement-linked
	if reg.document_type == "Cheque Batch":
		_push_cheques(reg, refs, party_type=party_type, party=party)

	# 4b) Agreements: cross-check the scan against the live agreement (Phase 4)
	if reg.document_type in ("Tenant Agreement", "Head Lease", "Owner Contract"):
		_diff_agreement(reg, party_type, party, refs, warnings)

	# 4c) Bank statement: report reconciliation state (lines are applied
	# individually from the review UI before or after pushing)
	if reg.document_type == "Bank Statement" and reg.meta.has_field("statement_lines"):
		lines = reg.statement_lines or []
		unresolved = [l for l in lines if l.line_status in ("Unmatched", "Suggested")]
		applied = [l for l in lines if l.line_status == "Applied"]
		refs.append(f"Statement archived: {len(applied)} lines applied, "
		            f"{len(unresolved)} unresolved, "
		            f"{len(lines) - len(applied) - len(unresolved)} ignored")
		if unresolved:
			warnings.append(
				f"{len(unresolved)} statement lines are still unmatched - "
				"they were archived but have NOT touched the accounts")
		net = sum(flt(l.credit) for l in lines) - sum(flt(l.debit) for l in lines)
		if reg.opening_balance is not None and reg.closing_balance is not None:
			expected = flt(reg.opening_balance) + net
			if abs(expected - flt(reg.closing_balance)) > 0.01:
				warnings.append(
					f"Balance check FAILED: opening {flt(reg.opening_balance):,.2f} "
					f"+ net movement {net:,.2f} = {expected:,.2f}, but statement "
					f"closing is {flt(reg.closing_balance):,.2f} - a line is "
					"missing or misread")
			else:
				refs.append("Balance check passed: opening + movements = closing")

	# 5) Close out
	reg.status = "Pushed"
	reg.reviewed_by = frappe.session.user
	reg.reviewed_on = now_datetime()
	reg.pushed_refs = "\n".join(refs)
	reg.save()
	frappe.db.commit()

	return {"refs": refs, "warnings": warnings, "validation": validation, "archive": archive.name}


# ---------------------------------------------------------------------------
# Phase 4: agreement cross-check
# ---------------------------------------------------------------------------

def _diff_agreement(reg, party_type, party, refs, warnings):
	"""Compare the scanned agreement against the live ERP agreement for the
	matched party. Mismatches become warnings; a missing agreement is flagged
	for Legal to create through the normal approval workflow."""
	def _d(x):
		try:
			return getdate(x) if x else None
		except Exception:
			return None

	if reg.document_type == "Tenant Agreement":
		if party_type != "Customer" or not party:
			warnings.append("Agreement cross-check skipped: no tenant matched")
			return
		agr = frappe.db.get_value(
			"Tenancy Agreement", {"tenant": party, "status": "Active"},
			["name", "monthly_rent", "start_date", "end_date", "security_deposit"],
			as_dict=True)
		if not agr:
			warnings.append(
				f"No ACTIVE Tenancy Agreement for {party} in ERP - "
				"if this scan is a new lease, create it via the Legal approval workflow")
			return
		checks = [
			("monthly rent", flt(reg.monthly_rent), flt(agr.monthly_rent)),
			("security deposit", flt(reg.security_deposit), flt(agr.security_deposit)),
		]
		date_checks = [
			("start date", _d(reg.start_date), _d(agr.start_date)),
			("end date", _d(reg.end_date), _d(agr.end_date)),
		]
		mismatch = False
		for label, scanned, live in checks:
			if scanned and live and abs(scanned - live) > 0.01:
				warnings.append(
					f"MISMATCH vs {agr.name}: {label} on scan is {scanned:,.0f} "
					f"but ERP has {live:,.0f}")
				mismatch = True
		for label, scanned, live in date_checks:
			if scanned and live and scanned != live:
				warnings.append(
					f"MISMATCH vs {agr.name}: {label} on scan is {scanned} "
					f"but ERP has {live}")
				mismatch = True
		if not mismatch:
			refs.append(f"Cross-checked against {agr.name}: rent, deposit and dates all agree")

	else:  # Head Lease / Owner Contract
		if party_type != "Supplier" or not party:
			warnings.append("Contract cross-check skipped: no landlord matched")
			return
		agr = frappe.db.get_value(
			"Head Lease", {"landlord": party, "status": "Active"},
			["name", "monthly_rent", "start_date", "end_date"],
			as_dict=True)
		if not agr:
			warnings.append(
				f"No ACTIVE Head Lease for {party} in ERP - "
				"create it via the normal workflow if this is a new head-lease")
			return
		mismatch = False
		if reg.monthly_rent and agr.monthly_rent and \
				abs(flt(reg.monthly_rent) - flt(agr.monthly_rent)) > 0.01:
			warnings.append(
				f"MISMATCH vs {agr.name}: rent on scan is {flt(reg.monthly_rent):,.0f} "
				f"but ERP has {flt(agr.monthly_rent):,.0f}")
			mismatch = True
		for label, scanned, live in [
			("start date", _d(reg.start_date), _d(agr.start_date)),
			("end date", _d(reg.end_date), _d(agr.end_date)),
		]:
			if scanned and live and scanned != live:
				warnings.append(
					f"MISMATCH vs {agr.name}: {label} on scan is {scanned} "
					f"but ERP has {live}")
				mismatch = True
		if not mismatch:
			refs.append(f"Cross-checked against {agr.name}: rent and dates agree")


# ---------------------------------------------------------------------------
# Phase 3: bank statement matching
# ---------------------------------------------------------------------------

@frappe.whitelist()
def match_statement(docname):
	"""Suggest a Cheque for every unmatched statement line. Matching:
	exact cheque-number hit (strong), else amount+direction within a small
	date window (weak). Suggestions are saved onto the lines."""
	guard(MD, DOC, ACC)
	reg = _rehydrate(frappe.get_doc("Document Register", docname))
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not reg.meta.has_field("statement_lines"):
		frappe.throw(_("Statement fields not deployed yet (run the Phase-3 migrate)."))
	if not frappe.db.exists("DocType", "Cheque"):
		frappe.throw(_("Cheque DocType not found."))

	meta = frappe.get_meta("Cheque")
	pdc_fields = ["name", "cheque_number", "amount", "direction", "status", "cheque_date"]
	pdc_fields = [f for f in pdc_fields if meta.has_field(f) or f == "name"]
	pdcs = frappe.get_all("Cheque",
		filters={"status": ["not in", ["Cleared", "Cancelled", "Replaced"]]},
		fields=pdc_fields)
	by_number = {}
	for p in pdcs:
		n = re.sub(r"\D", "", str(p.get("cheque_number") or ""))
		if n:
			by_number.setdefault(n.lstrip("0") or "0", []).append(p)

	suggested = 0
	for line in reg.statement_lines or []:
		if line.line_status in ("Applied", "Ignored"):
			continue
		amount = flt(line.credit) or flt(line.debit)
		incoming_line = flt(line.credit) > 0
		hit, note = None, None

		refno = re.sub(r"\D", "", str(line.ref_no or ""))
		candidates = by_number.get(refno.lstrip("0") or "0", []) if refno else []
		for p in candidates:
			if abs(flt(p.get("amount")) - amount) <= 0.01:
				hit, note = p, f"cheque number {line.ref_no} + exact amount"
				break
		if not hit and candidates:
			hit, note = candidates[0], (
				f"cheque number {line.ref_no} matched but amount differs "
				f"({flt(candidates[0].get('amount')):,.2f} vs {amount:,.2f}) - VERIFY")

		if not hit and amount:
			window = []
			for p in pdcs:
				p_in = "Incoming" in (p.get("direction") or "")
				if p_in != incoming_line:
					continue
				if abs(flt(p.get("amount")) - amount) > 0.01:
					continue
				try:
					dd = abs((getdate(line.txn_date) - getdate(p.get("cheque_date"))).days) \
						if line.txn_date and p.get("cheque_date") else 999
				except Exception:
					dd = 999
				window.append((dd, p))
			window.sort(key=lambda t: t[0])
			if window and window[0][0] <= 10:
				hit, note = window[0][1], (
					f"amount match, cheque dated {window[0][0]} day(s) away - VERIFY number")

		if hit:
			line.match_pdc = hit.name
			line.match_note = note
			line.line_status = "Suggested"
			suggested += 1

	reg.flags.ignore_permissions = True
	reg.save()
	frappe.db.commit()
	return {"suggested": suggested, "doc": reg.as_dict()}


@frappe.whitelist()
def apply_statement_line(docname, line_name, pdc=None):
	"""Reviewer accepted a match: clear the cheque as of the line's date and
	mark the line. Clearing goes through api.finance, which is the only engine
	that posts a receipt - the Phase-2 engine this used to call was written
	against fields the Cheque doctype does not have."""
	guard(MD, DOC, ACC)
	from darkbrown.api import finance
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	line = next((l for l in reg.statement_lines or [] if l.name == line_name), None)
	if not line:
		frappe.throw(_("Statement line not found."))
	target = pdc or line.match_pdc
	if not target:
		frappe.throw(_("No PDC selected for this line."))

	cleared = finance.clear_cheque(target, on=line.txn_date)
	pe = cleared.get("payment_entry")
	msg = (f"Cheque {cleared['cheque']} cleared {line.txn_date}"
	       + (f"; Payment Entry {pe}." if pe else "."))
	result = {"msg": msg}
	line.match_pdc = target
	line.line_status = "Applied"
	line.match_note = ((line.match_note or "") + f" | {msg}").strip(" |")
	reg.flags.ignore_permissions = True
	reg.save()
	frappe.db.commit()
	return {"msg": result.get("msg"), "doc": reg.as_dict()}


@frappe.whitelist()
def ignore_statement_line(docname, line_name, note=None):
	"""Line is not a cheque event we track (bank charges, transfers, etc.)."""
	guard(MD, DOC, ACC)
	reg = frappe.get_doc("Document Register", docname)
	if not reg.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	line = next((l for l in reg.statement_lines or [] if l.name == line_name), None)
	if not line:
		frappe.throw(_("Statement line not found."))
	line.line_status = "Ignored"
	if note:
		line.match_note = note
	reg.flags.ignore_permissions = True
	reg.save()
	frappe.db.commit()
	return {"doc": reg.as_dict()}


# ---------------------------------------------------------------------------
# Wizard extraction
#
# The onboarding wizards hold their files client-side and upload them on save.
# That is the right order for filing, but it means nothing can be read off the
# paperwork before the form is filled in — which is exactly what the Documents
# step at the top of each wizard is for.
#
# extract_for_wizard() takes the files the user has just chosen, runs each one
# through the same extractor the intake queue uses, and folds the results into
# one flat map of wizard field keys. A head lease fills the property and the
# lease; the landlord's QID or CR fills the landlord; a cheque register fills
# the first cheque number. Every value carries its confidence and the file it
# came from, so the screen can show the user what it read and where.
#
# Nothing here writes a Building. The wizard's own submit still does that,
# against values a human has looked at.
# ---------------------------------------------------------------------------

#: Below this, a value is offered but marked as needing confirmation rather
#: than accepted. Matches the review threshold used by the intake queue.
WIZARD_CONFIRM_BELOW = 0.75

#: Instalment counts the Payment step's select actually offers. Anything else
#: is surfaced as a note instead of being forced into the field.
_NCHQ_ALLOWED = {1, 2, 4, 12}


def _num(v):
	try:
		if v is None or v == "":
			return None
		return flt(v)
	except Exception:
		return None


def _put(fields, key, value, conf, src, note=None):
	"""First non-empty value wins, unless a later one is more confident.

	Five files can each carry the landlord's name. Taking the highest
	confidence rather than the first file in the list means a clean QID card
	beats a smudged signature block.
	"""
	if value is None or value == "":
		return
	prev = fields.get(key)
	if prev and flt(prev.get("conf") or 0) >= flt(conf or 0):
		return
	fields[key] = {
		"value": value,
		"conf": round(flt(conf or 0), 2),
		"source": src,
		"confirm": flt(conf or 0) < WIZARD_CONFIRM_BELOW,
		"note": note,
	}


def _fold_building(data, src, fields, notes):
	"""Map one extracted document onto onboard-building's field keys."""
	dt = (data.get("document_type") or "").strip()
	oc = flt(data.get("overall_confidence") or 0)

	c = data.get("contract") or {}
	if c and dt in ("Head Lease", "Owner Contract"):
		_put(fields, "name", c.get("building_name"), oc, src)
		_put(fields, "area", c.get("area_name"), oc, src)
		_put(fields, "floors", _num(c.get("floors")), oc, src)
		_put(fields, "units", _num(c.get("total_units")), oc, src)

		# The wizard works in annual money. Prefer what the document states.
		annual = _num(c.get("annual_rent"))
		monthly = _num(c.get("monthly_rent"))
		if annual:
			_put(fields, "annual", annual, oc, src)
		elif monthly:
			_put(fields, "annual", monthly * 12, oc, src,
			     "the lease states %s a month; multiplied by 12" % monthly)

		_put(fields, "depll", _num(c.get("security_deposit")), oc, src)
		_put(fields, "start", c.get("start_date"), oc, src)
		_put(fields, "end", c.get("end_date"), oc, src)
		_put(fields, "first", c.get("start_date"), oc, src)

		n = _num(c.get("cheques_per_year"))
		if n:
			n = int(n)
			if n in _NCHQ_ALLOWED:
				_put(fields, "nchq", str(n), oc, src)
			else:
				notes.append(
					"%s states %d payments a year. The Payment step offers 1, 2, 4 "
					"or 12, so it has been left for you to set." % (src, n)
				)

		# Landlord, from the lease itself
		if c.get("cr_number"):
			_put(fields, "lltype", "Company", oc, src)
			_put(fields, "llid", c.get("cr_number"), oc, src)
		elif c.get("id_number"):
			_put(fields, "lltype", "Individual", oc, src)
			_put(fields, "llid", c.get("id_number"), oc, src)
		_put(fields, "ll", c.get("party_name"), oc, src)

		addr = " ".join(
			str(x) for x in (
				("Building " + str(c["building_no"])) if c.get("building_no") else None,
				("Street " + str(c["street"])) if c.get("street") else None,
				("Zone " + str(c["zone"])) if c.get("zone") else None,
			) if x
		)
		if addr:
			_put(fields, "addr", addr, oc, src)

	# A QID card or CR certificate identifies the landlord and nothing else.
	idd = data.get("id_document") or {}
	if idd and dt in ("QID / National ID", "Passport", "Utility / Other"):
		_put(fields, "ll", idd.get("party_name"), oc, src)
		if idd.get("id_number"):
			_put(fields, "llid", idd.get("id_number"), oc, src)
			_put(fields, "lltype", "Individual", oc, src)

	# A cheque register gives the first cheque number and the bank.
	chqs = data.get("cheques") or []
	if chqs and dt == "Cheque Batch":
		out = [q for q in chqs if "Landlord" in (q.get("direction") or "")] or chqs
		numbered = [q for q in out if (q.get("cheque_number") or "").strip()]
		numbered.sort(key=lambda q: str(q.get("cheque_date") or ""))
		if numbered:
			first = numbered[0]
			_put(fields, "chqfrom", str(first.get("cheque_number")).strip(),
			     flt(first.get("confidence") or oc), src)
		notes.append("%s carries %d cheque%s. They are logged from the Cheques "
		             "screen, not from here." % (src, len(out), "" if len(out) == 1 else "s"))

	drawer = data.get("drawer") or {}
	if drawer.get("name") and dt == "Cheque Batch":
		notes.append("%s is drawn by %s." % (src, drawer.get("name")))


_WIZARD_FOLD = {
	"building": _fold_building,
}


@frappe.whitelist()
def extract_for_wizard(file_urls, kind="building", escalate=0):
	"""Read a set of just-uploaded files and return wizard field values.

	`file_urls` is a JSON list or a comma-separated string of File URLs that
	the client has already uploaded. Each is run through the normal extractor,
	so each also lands in the Document Register and is reviewable later — the
	wizard is not a side channel that skips the register.

	Returns:
	  fields  {wizard_key: {value, conf, source, confirm, note}}
	  docs    one row per file: name, type, confidence, register id, error
	  notes   things worth telling the user that are not field values
	"""
	guard(MD, DOC)

	fold = _WIZARD_FOLD.get(kind)
	if not fold:
		frappe.throw(_("Unknown wizard: {0}").format(kind))

	if isinstance(file_urls, str):
		try:
			file_urls = json.loads(file_urls)
		except Exception:
			file_urls = [u.strip() for u in file_urls.split(",") if u.strip()]
	file_urls = [u for u in (file_urls or []) if u]
	if not file_urls:
		frappe.throw(_("No files to read."))
	if len(file_urls) > 12:
		frappe.throw(_("Twelve files at a time is the limit. Split the batch."))

	# Fail on the key before spending anything, and say so plainly.
	_get_api_key()

	fields, docs, notes = {}, [], []
	for url in file_urls:
		label = url.rsplit("/", 1)[-1]
		try:
			res = extract_from_upload(url, escalate=escalate)
			# A second click on Read must not spend a second time. The
			# duplicate check returns the register entry that already holds
			# this file's content; its extraction is reused as-is.
			if res.get("duplicate"):
				res = frappe.get_doc("Document Register",
				                     res["duplicate"]).as_dict()
				if not res.get("extracted_json"):
					res = extract_document(res["name"], escalate=escalate)
			raw = res.get("extracted_json")
			data = json.loads(raw) if isinstance(raw, str) else (raw or {})
			fold(data, label, fields, notes)
			docs.append({
				"file": label,
				"register": res.get("name"),
				"type": data.get("document_type") or res.get("document_type") or "Unknown",
				"conf": round(flt(data.get("overall_confidence") or 0), 2),
				"pages": res.get("page_count"),
			})
			for n in (data.get("notes") or [])[:3]:
				notes.append("%s: %s" % (label, n))
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), "extract_for_wizard")
			docs.append({"file": label, "type": "—", "conf": 0,
			             "error": str(e).split("\n")[0][:200]})

	return {"fields": fields, "docs": docs, "notes": notes,
	        "threshold": WIZARD_CONFIRM_BELOW}
