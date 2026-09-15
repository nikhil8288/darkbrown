"""Regenerate the tracked loader fixtures with obviously synthetic records."""

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "darkbrown" / "load" / "data"

DATA = {
    "landlords.csv": (["supplier_name", "ident", "nationality", "contact", "email"], [
        ["Synthetic Landlord Alpha LLC", "SYN-CR-0001", "Testland", "+00000000001", "alpha@example.invalid"],
        ["Synthetic Landlord Beta LLC", "SYN-CR-0002", "Testland", "+00000000002", "beta@example.invalid"],
    ]),
    "buildings.csv": (["building_code", "building_name", "landlord", "status", "area_name", "municipality", "zone_no", "street_no", "building_no", "kahramaa_account_no", "source_file"], [
        ["SYN-A", "Synthetic Building A", "Synthetic Landlord Alpha LLC", "Active", "Test District A", "Test Municipality", "900", "9001", "A-01", "SYN-KM-A", "synthetic-fixture"],
        ["SYN-B", "Synthetic Building B", "Synthetic Landlord Beta LLC", "Active", "Test District B", "Test Municipality", "901", "9002", "B-01", "SYN-KM-B", "synthetic-fixture"],
    ]),
    "head_leases.csv": (["building_code", "landlord", "seq", "status", "hl_start", "hl_end", "annual_rent", "payment_frequency", "security_deposit", "rent_free_days", "notice_period_days", "auto_renew", "note"], [
        ["SYN-A", "Synthetic Landlord Alpha LLC", "1", "Active", "2026-01-01", "2027-12-31", "120000", "Quarterly", "10000", "0", "60", "0", "synthetic only"],
        ["SYN-B", "Synthetic Landlord Beta LLC", "1", "Active", "2026-01-01", "2027-12-31", "144000", "Quarterly", "12000", "0", "60", "0", "synthetic only"],
    ]),
    "units.csv": (["building", "unit_no", "status", "unit_type", "market_rent"], [
        ["SYN-A", "A-01", "Vacant", "1BR", "1500"], ["SYN-A", "A-02", "Vacant", "1BR", "1550"],
        ["SYN-B", "B-01", "Vacant", "2BR", "2100"], ["SYN-B", "B-02", "Vacant", "2BR", "2200"],
    ]),
    "unit_aliases.csv": (["building", "old_unit_no", "unit_no", "evidence"], [
        ["SYN-A", "A01", "A-01", "synthetic alias fixture"],
    ]),
    "tenants.csv": (["customer_name", "match_key", "tenant_category", "qid", "nationality", "mobile", "email", "has_agreement", "name_variants"], [
        ["Synthetic Tenant One", "synthetic tenant one", "Individual", "00000000001", "Testland", "+00000000101", "tenant1@example.invalid", "1", ""],
        ["Synthetic Tenant Two", "synthetic tenant two", "Individual", "00000000002", "Testland", "+00000000102", "tenant2@example.invalid", "1", ""],
    ]),
    "tenancies.csv": (["tenancy_key", "match_key", "building", "unit_no", "start_date", "end_date", "status", "monthly_rent", "security_deposit", "payment_mode", "payment_frequency", "rent_free", "has_agreement", "activation_route", "missing_items", "qid_number", "mobile_no", "notes"], [
        ["SYN-TA-001", "synthetic tenant one", "SYN-A", "A-01", "2026-01-01", "2027-12-31", "Active", "1500", "1500", "Cheque", "Monthly", "0", "1", "Self Approved", "", "00000000001", "+00000000101", "synthetic only"],
        ["SYN-TA-002", "synthetic tenant two", "SYN-B", "B-01", "2026-01-01", "2027-12-31", "Active", "2100", "2100", "Transfer", "Monthly", "0", "1", "Self Approved", "", "00000000002", "+00000000102", "synthetic only"],
    ]),
    "arrears.csv": (["building", "unit_no", "match_key", "tenancy_start", "outstanding_amount", "oldest_due_date", "days_past_due", "months_in_arrears", "status", "trigger", "opened_on", "reference", "manual_reason"], [
        ["SYN-A", "A-01", "synthetic tenant one", "2026-01-01", "150", "2026-08-01", "15", "1", "Open", "Past Due", "2026-08-16", "SYN-AR-001", "synthetic only"],
    ]),
    "owner_cheques.csv": (["cheque_no", "building", "covers", "landlord", "cheque_date", "amount", "bank", "account_name", "payee", "period_label", "status", "is_security", "undated_reason", "source_period"], [
        ["SYN-CHQ-001", "SYN-A", "head lease", "Synthetic Landlord Alpha LLC", "2026-10-01", "30000", "Synthetic Bank", "SYN-ACCOUNT-A", "Synthetic Landlord Alpha LLC", "2026-Q4", "Received", "0", "", "synthetic-fixture"],
    ]),
    "owner_transfers.csv": (["building", "period_label", "period_end", "landlord", "amount", "derived", "note"], [
        ["SYN-B", "2026-08", "2026-08-31", "Synthetic Landlord Beta LLC", "12000", "0", "synthetic only"],
    ]),
    "portfolio_history.csv": (["building", "period_label", "period_end", "is_lump_period", "rent_charged", "rent_received", "owner_rent", "kahrama", "wifi", "profit", "rent_free"], [
        ["SYN-A", "2026-08", "2026-08-31", "0", "1500", "1350", "10000", "100", "50", "-8800", "0"],
        ["SYN-B", "2026-08", "2026-08-31", "0", "2100", "2100", "12000", "120", "60", "-10080", "0"],
    ]),
    "opex.csv": (["expense_date", "expense_head", "basis", "building", "amount", "description"], [
        ["2026-08-15", "Synthetic Maintenance", "Direct", "SYN-A", "100", "synthetic fixture; no real payment"],
    ]),
    "key_money.csv": (["expense_date", "period_label", "is_lump_period", "expense_head", "basis", "building", "amount", "description"], [
        ["2026-01-01", "2026", "0", "Synthetic Setup", "Direct", "SYN-B", "250", "synthetic fixture; no real payment"],
    ]),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"_note": "SYNTHETIC TEST FIXTURES ONLY", "_source": "verify/generate_synthetic_loader_data.py"}
    for filename, (header, rows) in DATA.items():
        path = OUT / filename
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
        raw = path.read_bytes()
        manifest[filename] = {"rows": len(rows), "sha256": hashlib.sha256(raw).hexdigest()[:16]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
