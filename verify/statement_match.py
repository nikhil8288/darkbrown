"""Read-only candidate planner: unique, ambiguous, reused and OCR checks."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from darkbrown.api.statement_match import plan_links


def row(index, **extra):
    return {"index": index, "date": "2026-10-02", "page": 1,
            "amount": "100.00", "direction": "Credit", "ref": "SYN",
            "narrative": "Synthetic", **extra}


rows = [row(1), row(2), row(3), row(4), row(5, ocr_review=True),
        row(6, date="2026-09-30")]
found = {1: [("Deposit Batch", "SYN-1")],
         2: [("Cheque", "SYN-2"), ("Deposit Batch", "SYN-2")],
         3: [("Cheque", "SYN-3")], 4: [("Cheque", "SYN-3")]}
called = []
def lookup(r, bank):
    called.append(r["index"])
    return found.get(r["index"], [])

review = plan_links(rows, "BANK-SYN", lookup)
assert [r["status"] for r in review] == [
    "Proposed", "Exception", "Exception", "Exception", "Exception", "Historical"]
assert called == [1, 2, 3, 4]
assert review[0]["candidate"] == {"doctype": "Deposit Batch", "name": "SYN-1"}
assert not any("candidate" in r for r in review[1:])
assert plan_links([row(1)], "BANK-SYN", lookup,
                  used={("Deposit Batch", "SYN-1")})[0]["status"] == "Exception"
assert plan_links([row(1)], "BANK-SYN", lookup,
                  overlaps={1})[0]["status"] == "Exception"
assert plan_links([row(1)], None, lookup)[0]["status"] == "Exception"
assert "derived" in plan_links([row(1, ocr_inferred=True)], "BANK-SYN", lookup)[0]["reason"]
print("PASS unique, ambiguous, reused, overlap, mapping and OCR review")
