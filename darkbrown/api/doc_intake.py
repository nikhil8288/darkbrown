# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Document Intake API for DarkBrown Real Estate.

Flow:
  1. Legal & Documentation user uploads a file on the /doc-intake page.
  2. A Document Register record is created (status = Draft) holding the file.
  3. extract_document() is called (server-side): it rasterises the PDF pages,
     sends them to the Claude vision API with a strict extraction prompt, parses
     the returned JSON, and writes the result back onto the Document Register
     record (status = Needs Review).
  4. The human reviews side-by-side with the source image and confirms.
  5. confirm_and_push() fans the confirmed data out to the live DocTypes
     (PDC Cheque / Landlord Contract / Tenant Rental Agreement).

Security:
  - The Anthropic API key is read server-side only, from site_config
    ("anthropic_api_key") or DBR Settings. It is NEVER exposed to the client.
  - All entry points are @frappe.whitelist() and permission-checked.
"""

import base64
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from darkbrown.api.doc_intake_prompts import (
	SYSTEM_PROMPT,
	USER_INSTRUCTION,
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ESCALATION_MODEL = "claude-sonnet-5"
RENDER_DPI = 150
MAX_PAGES = 15  # safety cap; a huge PDF should be split before intake


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

	# Contract-style fields
	contract = result.get("contract") or {}
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
# Whitelisted entry points
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
