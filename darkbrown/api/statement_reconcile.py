"""Record complete bank PDFs against posted bank ledger vouchers only.

This path never calls the legacy statement importer or cheque clearing. A
matched line is evidence of an existing GL movement, not a new posting.
"""

import hashlib
from collections import Counter
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate

from darkbrown.api.statement_pdf import StatementError, parse_statement
from darkbrown.guards import ACC, MD, guard
from darkbrown.permissions import require_file_access


def _key(date, ref, amount, direction):
    return (str(date), (ref or "").strip(),
            Decimal(str(amount)).quantize(Decimal("0.01")), direction)


def _statement(file_url):
    source = require_file_access(file_url)
    if not source.is_private or not (source.file_name or "").lower().endswith(".pdf"):
        frappe.throw("Upload the complete statement as a private PDF.")
    data = source.get_content()
    data = data.encode("utf-8") if isinstance(data, str) else data
    try:
        parsed = parse_statement(data)
    except StatementError as exc:
        frappe.throw("Bank statement needs review: {0}".format(exc))
    company = frappe.get_single("DBR Settings").default_company
    normalized = "".join(c for c in parsed["account_number"] if c.isalnum()).upper()
    accounts = frappe.get_all("Bank Account", filters={
        "company": company, "is_company_account": 1},
        fields=["name", "bank_account_no", "account"], limit_page_length=0)
    matches = [a for a in accounts if a.bank_account_no and
               "".join(c for c in a.bank_account_no if c.isalnum()).upper() == normalized]
    if len(matches) != 1 or not matches[0].account:
        frappe.throw("Statement account needs one company Bank Account with a bank GL account.")
    return source, parsed, matches[0], company, hashlib.sha256(data).hexdigest()


def _review(parsed, account, company, digest):
    rows = parsed["rows"]
    prior = frappe.get_all("Bank Statement Import", filters={"bank_account": account.name},
                           fields=["name", "source_sha256"], limit_page_length=0)
    if any(p.source_sha256 == digest for p in prior):
        frappe.throw("This exact PDF was already recorded as a statement.")
    prior_keys = set()
    if prior:
        old = frappe.get_all("Bank Statement Line", filters={
            "parent": ["in", [p.name for p in prior]],
            "txn_date": ["between", [rows[0]["date"], rows[-1]["date"]]]},
            fields=["txn_date", "bank_ref", "amount", "direction"],
            limit_page_length=0)
        prior_keys = {_key(x.txn_date, x.bank_ref, x.amount, x.direction) for x in old}

    start = getdate(rows[0]["date"]) - timedelta(days=5)
    end = getdate(rows[-1]["date"]) + timedelta(days=5)
    gl = frappe.db.sql("""select posting_date, voucher_type, voucher_no,
                sum(debit_in_account_currency-credit_in_account_currency) signed
            from `tabGL Entry`
            where company=%s and account=%s and is_cancelled=0
              and posting_date between %s and %s
              and voucher_type in ('Payment Entry','Journal Entry')
            group by posting_date, voucher_type, voucher_no""",
                       (company, account.account, start, end), as_dict=True)
    refs = {}
    for kind, field in (("Payment Entry", "reference_no"),
                        ("Journal Entry", "cheque_no")):
        names = [g.voucher_no for g in gl if g.voucher_type == kind]
        if names:
            for item in frappe.get_all(kind, filters={"name": ["in", names], "docstatus": 1},
                                       fields=["name", field], limit_page_length=0):
                refs[(kind, item.name)] = str(item.get(field) or "").strip()
    used = set()
    if prior:
        old_links = frappe.get_all("Bank Statement Line", filters={
            "parent": ["in", [p.name for p in prior]], "status": "Matched"},
            fields=["matched_type", "matched_ref"], limit_page_length=0)
        used = {(x.matched_type, x.matched_ref) for x in old_links}

    groups = []
    for row in rows:
        signed = Decimal(row["amount"]) * (1 if row["direction"] == "Credit" else -1)
        reference = (row.get("ref") or "").strip().upper()
        candidates = set()
        if reference and row["page"] not in parsed["ocr_pages"]:
            for entry in gl:
                key = (entry.voucher_type, entry.voucher_no)
                if key in used or key not in refs:
                    continue
                erp_ref = refs[key].upper()
                if (erp_ref and erp_ref == reference and
                        Decimal(str(entry.signed)).quantize(Decimal("0.01")) == signed and
                        abs((getdate(entry.posting_date) - getdate(row["date"])).days) <= 5):
                    candidates.add(key)
        groups.append(candidates)
    frequency = Counter(candidate for group in groups for candidate in group)
    review = []
    for index, (row, group) in enumerate(zip(rows, groups), 1):
        duplicate = _key(row["date"], row["ref"], row["amount"], row["direction"]) in prior_keys
        if duplicate:
            reason = "This bank line may already be in an earlier import"
        elif row["page"] in parsed["ocr_pages"] or row.get("ocr_inferred"):
            reason = "OCR row needs visual verification"
        elif len(group) != 1 or (group and frequency[next(iter(group))] != 1):
            reason = "No unique posted bank voucher with this reference, amount and date"
        else:
            reason = "Exact reference and amount on a submitted bank GL voucher"
        match = next(iter(group)) if reason.startswith("Exact") else None
        review.append({"index": index, "page": row["page"], "date": row["date"],
                       "value_date": row["value_date"], "ref": row["ref"],
                       "narrative": row["narrative"], "amount": row["amount"],
                       "direction": row["direction"], "balance": row["balance"],
                       "status": "Matched" if match else "Unmatched", "reason": reason,
                       "match": {"doctype": match[0], "name": match[1]} if match else None,
                       "overlap": duplicate})
    return review


@frappe.whitelist()
def preview_real_statement(file_url):
    guard(MD, ACC)
    _, parsed, account, company, digest = _statement(file_url)
    review = _review(parsed, account, company, digest)
    return {"bank": parsed["bank"], "pages": parsed["pages"],
            "ocr_pages": parsed["ocr_pages"], "bank_account": account.name,
            "account_suffix": parsed["account_number"][-4:],
            "opening": parsed["opening"], "closing": parsed["closing"],
            "total_debit": parsed["total_debit"], "total_credit": parsed["total_credit"],
            "source_file": file_url, "digest": digest, "rows": review,
            "matched": sum(r["status"] == "Matched" for r in review),
            "unmatched": sum(r["status"] == "Unmatched" for r in review),
            "overlaps": sum(r["overlap"] for r in review)}


@frappe.whitelist()
def record_real_statement(file_url, digest):
    """Reparse the private source and recompute links at the point of saving."""
    guard(MD, ACC)
    source, parsed, account, company, actual_digest = _statement(file_url)
    if digest != actual_digest:
        frappe.throw("The PDF changed since preview. Validate it again.")
    review = _review(parsed, account, company, actual_digest)
    if any(r["overlap"] for r in review):
        frappe.throw("Some lines overlap an earlier import. Review that import before recording this PDF.")
    doc = frappe.get_doc({"doctype": "Bank Statement Import", "bank_account": account.name,
        "from_date": parsed["rows"][0]["date"], "to_date": parsed["rows"][-1]["date"],
        "source": "Validated {0} PDF".format(parsed["bank"].upper()),
        "status": "Reviewed", "source_sha256": actual_digest, "source_file": file_url,
        "opening_balance": parsed["opening"], "closing_balance": parsed["closing"]})
    for row in review:
        doc.append("lines", {"txn_date": row["date"], "value_date": row["value_date"],
            "row_number": row["index"], "page_number": row["page"],
            "bank_ref": row["ref"], "narrative": row["narrative"],
            "amount": row["amount"], "direction": row["direction"],
            "running_balance": row["balance"], "status": row["status"],
            "review_reason": row["reason"],
            "matched_type": row["match"]["doctype"] if row["match"] else None,
            "matched_ref": row["match"]["name"] if row["match"] else None})
    doc.insert()
    # Keep the private source with the import for audit and future review.
    source.db_set("attached_to_doctype", doc.doctype, update_modified=False)
    source.db_set("attached_to_name", doc.name, update_modified=False)
    return {"name": doc.name, "total": doc.total_lines,
            "matched": doc.matched, "unmatched": doc.unmatched}


@frappe.whitelist()
def statement_detail(name):
    guard(MD, ACC)
    doc = frappe.get_doc("Bank Statement Import", name)
    doc.check_permission("read")
    return {"name": doc.name, "bank_account": doc.bank_account,
            "from_date": str(doc.from_date), "to_date": str(doc.to_date),
            "source_file": doc.source_file, "opening": doc.opening_balance,
            "closing": doc.closing_balance, "status": doc.status,
            "lines": [{"index": l.row_number, "page": l.page_number,
                "date": str(l.txn_date), "value_date": str(l.value_date or ""),
                "ref": l.bank_ref, "narrative": l.narrative,
                "amount": l.amount, "direction": l.direction,
                "balance": l.running_balance, "status": l.status,
                "reason": l.review_reason, "match":
                {"doctype": l.matched_type, "name": l.matched_ref}
                if l.matched_ref else None} for l in doc.lines]}
