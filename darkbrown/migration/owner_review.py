"""Continue owner reconstruction from cached evidence; never create vouchers.

Payable snapshots are controls, not an additional bill or payment source.
Unresolved combined periods and blank amounts remain explicit review gates.
"""
import argparse
import json
from pathlib import Path

from darkbrown.migration.evidence import digest, file_hash, outside_repo
from darkbrown.migration.prepare import amount, building, lineage, period, values, write_json

CURRENT = "OWNER RENT - PAYABLE  Sep 2026 v1.xlsx"
OLD = "OWNER RENT - PAYABLE  Sep 2026.xlsx"
HISTORY = "V4 Owners Rent Payment Balance 31 July 2026.xlsx"


def review(rows):
    history, controls = [], []
    versions = {CURRENT: {}, OLD: {}}
    for row in rows:
        source = Path(row["source_file"]).name
        v = values(row)
        if source == HISTORY and row["worksheet"] == "Owners Rent" and row["row"] > 1 and v.get("A", "").isdigit() and v.get("B"):
            issues = ["agreement/supplier mapping and service-period validation required",
                      "paid total is not dated settlement evidence"]
            try:
                original_period = period(v.get("F"))
            except ValueError:
                original_period = None
                issues.append("combined or non-calendar period requires interpretation")
            amounts = {}
            for label, col in (("billed", "C"), ("paid_control", "D"), ("balance_control", "E")):
                try:
                    amounts[label] = str(amount(row, col))
                except ValueError:
                    amounts[label] = None
                    issues.append(label + ": blank/error is not zero")
            history.append({"lineage": lineage(row), "building_source": v["B"],
                            "building_candidate": building(v["B"]), "period_source": v.get("F"),
                            "original_period": original_period, "posting_period": None,
                            "amounts": amounts, "comments": v.get("G"),
                            "evidence_type": "historical owner charge evidence awaiting agreement join",
                            "economic_event_key": None, "reconstruction": True,
                            "execution_enabled": False, "blockers": issues})
        elif source in versions and row["row"] > 2 and v.get("D"):
            # Row coordinates match these workbook revisions. They establish
            # comparison identity only; never pretend they are economic keys.
            key = (row["worksheet"], row["row"])
            versions[source][key] = row
            if source == CURRENT:
                controls.append({"lineage": lineage(row), "raw_values": v,
                                 "evidence_type": "payable control snapshot",
                                 "postable": False, "supersedes": OLD,
                                 "warning": "dates/banks on payable schedules do not prove settlement"})
    differences = []
    for key in sorted(versions[CURRENT].keys() | versions[OLD].keys()):
        current, old = versions[CURRENT].get(key), versions[OLD].get(key)
        if digest(values(current) if current else None) != digest(values(old) if old else None):
            differences.append({"worksheet": key[0], "row": key[1],
                                "current": lineage(current) if current else None,
                                "previous": lineage(old) if old else None,
                                "current_values": values(current) if current else None,
                                "previous_values": values(old) if old else None,
                                "action": "current supersedes comparison; never append both"})
    return {"historical_owner_candidates": history, "current_payable_controls": controls,
            "supersession_differences": differences, "ready_to_post": 0,
            "execution_enabled": False,
            "remaining": ["join source property to exact Head Lease and supplier",
                          "resolve combined service periods and rent-free evidence",
                          "separate settlement facts from payable controls",
                          "apply approved recognition/accrual corrections before final economic keys"]}


def continue_review(directory):
    output = outside_repo(directory)
    summary = json.loads((output / "extraction-summary.json").read_text(encoding="utf-8"))
    cached = output / "evidence-rows.jsonl"
    if file_hash(cached) != summary["evidence_rows_sha256"]:
        raise ValueError("Cached extraction changed")
    with cached.open(encoding="utf-8") as stream:
        result = review(json.loads(line) for line in stream)
    result["pack_checksum"] = summary["pack_checksum"]
    write_json(output / "owner-reconstruction-review.json", result)
    return {"historical_owner_candidates": len(result["historical_owner_candidates"]),
            "payable_controls": len(result["current_payable_controls"]),
            "supersession_differences": len(result["supersession_differences"]),
            "ready_to_post": 0, "execution_enabled": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cached_evidence_directory")
    print(json.dumps(continue_review(parser.parse_args().cached_evidence_directory)))
