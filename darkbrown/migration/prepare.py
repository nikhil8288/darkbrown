"""Build a private, non-posting reconstruction preview from verified evidence.

No source row is silently converted into a submitted ERP document. The preview
keeps bank matching, party/account mapping and ambiguous evidence as gates.
"""
import argparse
import calendar
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from darkbrown.migration.evidence import digest, file_hash, outside_repo, verify_pack
from darkbrown.migration.plan import event_key, money, change_plan


def columns(row):
    return {re.sub(r"\d", "", c["cell"]): c for c in row["cells"]}


def values(row):
    return {k: c["value"] for k, c in columns(row).items()}


def amount(row, column):
    cell = columns(row).get(column)
    if not cell or cell["type"] == "e":
        raise ValueError("Blank or error financial input")
    return money(cell["value"])


def period(value):
    if value and str(value).isdigit():
        day = date(1899, 12, 30) + timedelta(days=int(value))
        if date(2000, 1, 1) <= day <= date(2100, 1, 1):
            return day.strftime("%Y-%m")
    if value:
        found = re.fullmatch(r"([A-Za-z]{3})[' -]?(\d{2}|\d{4})", value.strip())
        if found:
            month = list(calendar.month_abbr).index(found[1].title())
            year = int(found[2]) + (2000 if len(found[2]) == 2 else 0)
            return f"{year:04d}-{month:02d}"
    raise ValueError("Period requires explicit interpretation: " + str(value))


def normalized(value):
    return " ".join((value or "").upper().split())


def building(value):
    key = normalized(value)
    return {"UG-180": "UG-169", "UG-169/180": "UG-169", "THUMAMA-20": "TV-20"}.get(key, key)


def lineage(row):
    return {k: row[k] for k in ("source_file", "source_sha256", "worksheet", "row", "evidence_id")}


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def prepare(pack, extracted):
    root, output = outside_repo(pack), outside_repo(extracted)
    manifest = verify_pack(root)
    summary = json.loads((output / "extraction-summary.json").read_text(encoding="utf-8"))
    if summary["pack_checksum"] != digest(manifest):
        raise ValueError("Extracted evidence belongs to a different data pack")
    if summary.get("evidence_rows_sha256") != file_hash(output / "evidence-rows.jsonl"):
        raise ValueError("Extracted evidence changed; rerun extraction into a fresh directory")
    rows = [json.loads(line) for line in (output / "evidence-rows.jsonl").open(encoding="utf-8")]
    hashes = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    if any(hashes.get(r["source_file"]) != r["source_sha256"] for r in rows):
        raise ValueError("Evidence lineage hash mismatch")
    by_sheet = defaultdict(list)
    for row in rows:
        by_sheet[(Path(row["source_file"]).name, row["worksheet"])].append(row)
    rent = by_sheet[("REVENUE  RECEIVABLES 22 SEP 2026.xlsx", "Revenue ")]
    overlap = by_sheet[("REVENUE  RECEIVABLES 30 SEP 2026.xlsx", "Revenue ")]
    if not rent or not overlap:
        raise ValueError("Authoritative trailing-space Revenue worksheet missing")
    header = values(rent[0])
    if header.get("F") != "RENT" or header.get("G") != "RECEIVED" or header.get("M", "").strip() != "Month":
        raise ValueError("Revenue schema changed; explicit mapping review required")
    rent_rows = [r for r in rent[1:] if values(r).get("B")]
    overlap_rows = [r for r in overlap[1:] if values(r).get("B")]
    # Compare economic cells, not cached worksheet summary formulas or row numbers.
    def economic_signature(row):
        return digest({k: v for k, v in values(row).items() if k != "A"})
    left = Counter(economic_signature(r) for r in rent_rows)
    right = Counter(economic_signature(r) for r in overlap_rows)
    supersession = {"authority": "explicit user instruction: 22 SEP / Revenue with trailing space",
                   "authoritative_rows": len(rent_rows), "comparison_rows": len(overlap_rows),
                   "identical_economic_rows": sum((left & right).values()),
                   "only_authority": sum((left - right).values()),
                   "only_comparison": sum((right - left).values()),
                   "comparison_imported": False}
    master_rows = by_sheet[("DarkBrown_Tenancy_Master_300_v28(1).xlsx", "Tenancy Master")][1:]
    masters = defaultdict(list)
    for row in master_rows:
        v = values(row)
        if v.get("B") and v.get("C") and v.get("D"):
            masters[(building(v["B"]), normalized(v["C"]), normalized(v["D"]))].append(row)
    events, coverage, totals, missing, issue_counts = [], Counter(), defaultdict(Decimal), Counter(), Counter()
    for row in rent_rows:
        v = values(row)
        for column in ("F", "G", "H", "I", "J", "K", "L"):
            try:
                totals[column] += amount(row, column)
            except ValueError:
                missing[column] += 1
        original = v.get("M")
        issues = []
        try:
            month = period(original)
            coverage[month] += 1
        except ValueError:
            month = None
            issues.append("unresolved_service_period")
        ident = (building(v.get("B")), normalized(v.get("C")), normalized(v.get("E")))
        candidates = masters.get(ident, [])
        contract = values(candidates[0]).get("I") if len(candidates) == 1 else None
        if not all(ident):
            issues.append("missing_party_or_unit")
        if not contract:
            issues.append("missing_or_ambiguous_exact_contract_join")
        if candidates and len(candidates) == 1 and month:
            cv = values(candidates[0])
            try:
                if not (period(cv.get("K")) <= month <= period(cv.get("L"))):
                    issues.append("service_outside_supplied_contract_dates")
            except ValueError:
                issues.append("contract_dates_unverified")
        try:
            rent_amount = amount(row, "F")
        except ValueError:
            rent_amount = None
            issues.append("missing_or_invalid_rent")
        if rent_amount is not None and rent_amount < 0:
            issues.append("negative_rent_requires_credit_note_review")
        # These fields are explicit source evidence, never rent-minus-due receipts.
        source_amounts = {}
        for col, name in {"G": "recorded_received", "H": "advance_applied", "J": "previous_due_received_adjustment", "K": "net_due", "L": "security"}.items():
            try:
                source_amounts[name] = str(amount(row, col))
            except ValueError:
                source_amounts[name] = None
        key = event_key("rent", ident, month or original or "unknown", "rent")
        event = {"economic_event_key": key, "content_checksum": digest(v),
                 "source": lineage(row), "evidence_type": "rent_schedule",
                 "identity": {"building": ident[0], "unit": ident[1], "tenant_name": v.get("E"), "contract_reference": contract},
                 "original_period": original, "service_period": month,
                 "proposed_posting_date": month + "-01" if month else None,
                 "actual_receipt_date": None, "receipt_posting_date": None,
                 "receipt_treatment": "aggregate evidence; allocation/date and duplicate review required",
                 "reconstructed": True, "internal_only": True,
                 "rent_amount": str(rent_amount) if rent_amount is not None else None,
                 "source_amounts": source_amounts, "mapping_issues": issues,
                 "posting_status": "blocked_site_accounts_and_identity_verification",
                 "planned_doctype": "Sales Invoice" if rent_amount and rent_amount > 0 else None,
                 "planned_series": "MIG-INV-.YYYY.-.#####",
                 "accounting_effect_template": "Dr mapped receivable / Cr mapped rent income; existing tax settings require validation"}
        events.append(event)
        issue_counts.update(issues)
    collisions = Counter(e["economic_event_key"] for e in events)
    for event in events:
        if collisions[event["economic_event_key"]] > 1:
            event["mapping_issues"].append("duplicate_economic_identity_requires_review")
            issue_counts["duplicate_economic_identity_requires_review"] += 1
    # Group identities with all constituent evidence, never silently drop rows.
    groups = defaultdict(list)
    for event in events:
        groups[event["economic_event_key"]].append(event)
    canonical = [{"economic_event_key": key, "evidence": group,
                  "aggregation": "none" if len(group) == 1 else "blocked_collision"}
                 for key, group in sorted(groups.items())]
    old_path = output / "normalized-preview.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else []
    changes = change_plan(old, canonical)
    write_json(output / "change-plan.json", changes)
    write_json(old_path, canonical)
    controls = []
    total_row = rent[-1]
    for col, label in {"F": "rent", "G": "recorded_receipts", "H": "advances_applied", "I": "rent_due", "J": "previous_due_adjustment", "K": "net_due"}.items():
        control = amount(total_row, col)
        controls.append({"control": label, "independent_row_sum": str(totals[col]),
                         "source_summary": str(control), "variance": str(totals[col] - control),
                         "blank_or_error_cells_excluded_not_zeroed": missing[col], "source": lineage(total_row)})
    # Bank review arithmetic is a comparison, not a second import source.
    bank_checks, bank_totals = [], defaultdict(lambda: defaultdict(Decimal))
    for row in by_sheet[("DarkBrown_Bank_and_Balance_Intake.xlsx", "Bank transactions")]:
        v = values(row)
        if not v.get("A", "").startswith(("QNB-", "DOHA-")):
            continue
        debit, credit, closing, previous = (amount(row, c) for c in ("G", "H", "I", "J"))
        variance = previous + credit - debit - closing
        bank_checks.append({"source": lineage(row), "bank": v["B"], "record_id": v["A"],
                            "variance": str(variance), "match_status": "unmatched"})
        bank_totals[v["B"]]["debits"] += debit
        bank_totals[v["B"]]["credits"] += credit
    review_selection = [r for r in rows if (
        Path(r["source_file"]).name == "DarkBrown_Consolidated_Current_PL.xlsx" and
        r["worksheet"] in {"Approved decisions", "Current exceptions", "Source register", "Timing bridge", "ERP checklist"}) or (
        Path(r["source_file"]).name == "DarkBrown_Bank_and_Balance_Intake.xlsx" and
        r["worksheet"] in {"Payroll review", "Supplier payables", "Payables", "Bank accounts"})]
    write_json(output / "mapping-and-supersession.json", {"revenue": supersession,
               "source_decisions_and_exceptions": review_selection,
               "rule": "Reviews, summaries, liability snapshots and superseded workbooks are not additive events"})
    write_json(output / "bank-comparison.json", {"checks": bank_checks, "totals": bank_totals,
               "bank_reconciliation_performed": False, "review_rows_are_not_new_transactions": True})
    write_json(output / "controls.json", controls)
    report = {"pack_checksum": summary["pack_checksum"], "manifest_sha256": summary["manifest_sha256"],
              "source_files_verified": len(manifest["files"]), "revenue_rows": len(events),
              "revenue_coverage": dict(sorted(coverage.items())), "earliest_rent_period": min(coverage),
              "coverage_warning": "Key money includes July-October and owner rent August-October aggregates; do not infer October as earliest economic activity",
              "rent_invoice_candidates": sum(bool(e["planned_doctype"]) for e in events),
              "ready_to_post_documents": 0, "production_documents_created": 0,
              "mapping_issue_counts": issue_counts, "duplicate_identity_groups": sum(n > 1 for n in collisions.values()),
              "formula_error_cells": len(summary["errors"]), "supersession": supersession,
              "bank_comparison_rows": len(bank_checks), "bank_arithmetic_exceptions": sum(money(r["variance"]) != 0 for r in bank_checks),
              "cleanup_counts": None, "installed_versions": None, "company": None,
              "site": "erp.darkbrown.qa", "backup_restore_verified": False,
              "disposable_erp_integration_tests": "not run: no confirmed environment",
              "financial_signoff": "provisional; not complete",
              "remaining_implementation": ["owner/expense/payroll/asset canonical event mapping", "approved account/party mapping",
                  "installed-version cleanup executor and import checkpoint/resume", "historical linked clearing vouchers",
                  "agreement billing recognition/deferral validation", "authorized correction register",
                  "GL/party-ledger/report reconciliation and disposable ERP integration tests"]}
    write_json(output / "dry-run-report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack")
    parser.add_argument("extracted")
    args = parser.parse_args()
    report = prepare(args.pack, args.extracted)
    print(json.dumps({k: report[k] for k in ("source_files_verified", "revenue_rows", "earliest_rent_period", "rent_invoice_candidates", "ready_to_post_documents", "bank_comparison_rows", "bank_arithmetic_exceptions", "mapping_issue_counts")}))
