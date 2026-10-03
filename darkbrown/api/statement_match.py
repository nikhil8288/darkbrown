"""Conservative, read-only statement-to-ERP candidate planner.

This never changes a document or treats amount/date proximity as settled cash.
Only a unique, unused ERP candidate is proposed; conflicts become exceptions.
"""

from collections import Counter


def plan_links(rows, bank_account, lookup, used=None, overlaps=None, cutoff="2026-10-01"):
    """lookup(row, bank_account) returns distinct (doctype, name) candidates."""
    used = used or set()
    overlaps = overlaps or set()
    candidates = []
    for row in rows:
        if (row["date"] < cutoff or not bank_account or row["index"] in overlaps
                or row.get("ocr_review")):
            candidates.append([])
        else:
            candidates.append(sorted(set(lookup(row, bank_account)) - used))
    frequency = Counter(candidate for group in candidates for candidate in group)
    review = []
    for row, group in zip(rows, candidates):
        if row["date"] < cutoff:
            status, reason = "Historical", "Before the 1 October 2026 cutover"
        elif not bank_account:
            status, reason = "Exception", "Bank account needs a unique ERP mapping"
        elif row["index"] in overlaps:
            status, reason = "Exception", "May already exist in an earlier import"
        elif row.get("ocr_inferred"):
            status, reason = "Exception", "OCR amount derived from running balance; verify printed row"
        elif row.get("ocr_review"):
            status, reason = "Exception", "OCR page needs visual text review"
        elif not group:
            status, reason = "Exception", "No eligible ERP record found"
        elif len(group) > 1 or frequency[group[0]] > 1:
            status, reason = "Exception", "Ambiguous or reused ERP candidate"
        else:
            status, reason = "Proposed", "Unique ERP candidate; no financial action taken"
        item = {"index": row["index"], "date": row["date"], "page": row.get("page"),
                "amount": row["amount"], "direction": row["direction"],
                "ref": row.get("ref") or "", "narrative": row.get("narrative") or "",
                "status": status, "reason": reason}
        if status == "Proposed":
            item["candidate"] = {"doctype": group[0][0], "name": group[0][1]}
        elif status == "Exception" and group:
            item["candidate_count"] = len(group)
        review.append(item)
    return review
