# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
Identity document validation for the Document Intake pipeline.

Two-check model:
  Check 1 - QID format validation + exact database match against
            Customer/Supplier (flat custom fields and Party Document rows).
  Check 2 - fuzzy name agreement between the name on the document and the
            matched party's name.

Bonus check (free signal discovered from real samples): the Qatari QID embeds
an ISO 3166-1 numeric country code in digits 4-6 which must agree with the
nationality printed on the document (e.g. QID 282-144-09024 -> 144 = Sri Lanka).

Nothing here blocks a push on its own; results feed verification_status
(Verified / Unverified / Conflict) so the human reviewer stays in charge.
"""

import re
from difflib import SequenceMatcher

import frappe

# ISO 3166-1 numeric -> country name (subset relevant to Qatar's workforce;
# extend as new nationalities appear in intake).
ISO_NUMERIC = {
	"004": "Afghanistan", "050": "Bangladesh", "064": "Bhutan",
	"076": "Brazil", "108": "Burundi", "120": "Cameroon", "144": "Sri Lanka",
	"156": "China", "180": "Congo", "218": "Ecuador", "231": "Ethiopia",
	"232": "Eritrea", "262": "Djibouti", "275": "Palestine", "276": "Germany",
	"288": "Ghana", "324": "Guinea", "356": "India", "360": "Indonesia",
	"364": "Iran", "368": "Iraq", "400": "Jordan", "404": "Kenya",
	"408": "North Korea", "410": "South Korea", "414": "Kuwait",
	"422": "Lebanon", "430": "Liberia", "434": "Libya", "458": "Malaysia",
	"462": "Maldives", "466": "Mali", "478": "Mauritania", "504": "Morocco",
	"512": "Oman", "524": "Nepal", "554": "New Zealand", "566": "Nigeria",
	"586": "Pakistan", "608": "Philippines", "634": "Qatar", "642": "Romania",
	"646": "Rwanda", "682": "Saudi Arabia", "686": "Senegal", "690": "Seychelles",
	"694": "Sierra Leone", "706": "Somalia", "710": "South Africa",
	"728": "South Sudan", "729": "Sudan", "760": "Syria", "764": "Thailand",
	"788": "Tunisia", "792": "Turkey", "800": "Uganda", "818": "Egypt",
	"826": "United Kingdom", "834": "Tanzania", "840": "United States",
	"854": "Burkina Faso", "860": "Uzbekistan", "887": "Yemen",
}

QID_RE = re.compile(r"^[23]\d{10}$")


def clean_id(id_number):
	return re.sub(r"[\s\-]", "", str(id_number or "")).strip()


def qid_format_check(qid):
	"""Structural QID check. 11 digits; first digit 2 (born 19xx) or 3 (born
	20xx); digits 2-3 = birth year; digits 4-6 = ISO nationality code.
	Returns dict with ok, birth_year, country_code, country."""
	q = clean_id(qid)
	if not QID_RE.match(q):
		return {"ok": False, "reason": "Not an 11-digit QID starting with 2 or 3"}
	century = "19" if q[0] == "2" else "20"
	birth_year = int(century + q[1:3])
	code = q[3:6]
	return {
		"ok": True,
		"birth_year": birth_year,
		"country_code": code,
		"country": ISO_NUMERIC.get(code),
	}


def nationality_check(qid, stated_nationality):
	"""Bonus check: QID-embedded country code vs the nationality printed on
	the document. Returns 'match', 'mismatch', or 'unknown'."""
	fmt = qid_format_check(qid)
	if not fmt.get("ok") or not stated_nationality:
		return {"result": "unknown", **fmt}
	country = fmt.get("country")
	if not country:
		return {"result": "unknown", **fmt}
	a = country.lower().strip()
	b = str(stated_nationality).lower().strip()
	# tolerate demonyms: "Sri Lankan" vs "Sri Lanka", "Indian" vs "India"
	match = a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.75
	return {"result": "match" if match else "mismatch", **fmt}


def name_similarity(a, b):
	"""Fuzzy name agreement (Check 2). Token-set based so order and missing
	middle names don't fail the match. Returns 0..1."""
	if not a or not b:
		return 0.0
	ta = set(re.sub(r"[^a-z ]", "", a.lower()).split())
	tb = set(re.sub(r"[^a-z ]", "", b.lower()).split())
	if not ta or not tb:
		return 0.0
	overlap = len(ta & tb) / min(len(ta), len(tb))
	ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
	return round(max(overlap, ratio), 3)


def find_party_by_id(id_number):
	"""Check 1b: exact DB match. Looks in Customer/Supplier flat custom
	fields, then Party Document rows. Returns
	{party_type, party, party_name, via} or None."""
	q = clean_id(id_number)
	if not q:
		return None

	for doctype, name_field in (("Customer", "customer_name"), ("Supplier", "supplier_name")):
		meta = frappe.get_meta(doctype)
		for field in ("custom_qid", "custom_passport_no", "custom_id_number"):
			if not meta.has_field(field):
				continue
			hit = frappe.db.get_value(
				doctype, {field: ["like", f"%{q}%"]}, ["name", name_field], as_dict=True
			)
			if hit:
				return {
					"party_type": doctype, "party": hit.name,
					"party_name": hit.get(name_field), "via": f"{doctype}.{field}",
				}

	if frappe.db.exists("DocType", "Party Document"):
		row = frappe.db.get_value(
			"Party Document", {"id_number": q},
			["parent", "parenttype", "holder_name"], as_dict=True,
		)
		if row:
			name_field = "customer_name" if row.parenttype == "Customer" else "supplier_name"
			return {
				"party_type": row.parenttype, "party": row.parent,
				"party_name": frappe.db.get_value(row.parenttype, row.parent, name_field),
				"via": "Party Document",
			}
	return None


def find_party_by_name(name, party_type=None, threshold=0.72):
	"""Fuzzy name match against Customer/Supplier for documents that carry a
	name but no ID number (e.g. cheque batches: the drawer). Returns the best
	{party_type, party, party_name, score, via} above threshold, else None.
	Deliberately conservative: a wrong link is worse than no link."""
	if not name:
		return None
	doctypes = (
		[(party_type, "customer_name" if party_type == "Customer" else "supplier_name")]
		if party_type
		else [("Customer", "customer_name"), ("Supplier", "supplier_name")]
	)
	best = None
	for doctype, name_field in doctypes:
		for row in frappe.get_all(doctype, fields=["name", name_field]):
			candidate = row.get(name_field) or row.name
			score = name_similarity(name, candidate)
			if score >= threshold and (not best or score > best["score"]):
				best = {
					"party_type": doctype, "party": row.name,
					"party_name": candidate, "score": score, "via": "name match",
				}
	return best


def validate_identity(id_number, holder_name=None, nationality=None, doc_is_qid=True):
	"""Full two-check run. Returns a dict the UI can render and
	confirm_and_push can act on:
	{
	  "format": {...}, "nationality": {...},
	  "db_match": {...} | None,
	  "name_score": 0..1,
	  "verified": bool,     # both checks green
	  "flags": ["..."],     # human-readable warnings
	}
	"""
	flags = []
	fmt = qid_format_check(id_number) if doc_is_qid else {"ok": None}
	if doc_is_qid and not fmt.get("ok"):
		flags.append(f"QID format: {fmt.get('reason')}")

	nat = nationality_check(id_number, nationality) if doc_is_qid else {"result": "unknown"}
	if nat.get("result") == "mismatch":
		flags.append(
			f"QID country code {nat.get('country_code')} = {nat.get('country')} "
			f"does not match stated nationality '{nationality}'"
		)

	match = find_party_by_id(id_number)
	if not match:
		flags.append("No party in ERP with this ID number")

	score = name_similarity(holder_name, match["party_name"]) if match else 0.0
	if match and score < 0.6:
		flags.append(
			f"Name on document ('{holder_name}') is a weak match for "
			f"{match['party_type']} '{match['party_name']}' (score {score})"
		)

	verified = bool(
		match
		and score >= 0.6
		and (not doc_is_qid or fmt.get("ok"))
		and nat.get("result") != "mismatch"
	)

	return {
		"format": fmt,
		"nationality": nat,
		"db_match": match,
		"name_score": score,
		"verified": verified,
		"flags": flags,
	}
