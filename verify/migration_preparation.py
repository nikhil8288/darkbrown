"""Synthetic pure-Python and source/stub tests; NOT ERP accounting integration."""
import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from darkbrown.migration.evidence import digest, file_hash, outside_repo, verify_pack, workbook_rows
from darkbrown.migration.plan import cleanup_plan, event_key, change_plan, money, validate_approval
from darkbrown.migration.prepare import period, building, amount
from darkbrown.migration.inventory import snapshot_checksum


class EvidenceTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for value in (None, "", "#REF!", "NaN", "Infinity", True):
            with self.assertRaises(ValueError):
                money(value)
        self.assertEqual(str(money("0")), "0.00")

    def test_error_cell_is_rejected_even_with_numeric_value(self):
        with self.assertRaises(ValueError):
            amount({"cells": [{"cell": "F2", "type": "e", "value": "12"}]}, "F")

    def test_economic_key_independent_of_lineage(self):
        key = event_key("rent", ["SYN-A", "SYN-U", "SYN-T"], "2026-09", "rent")
        old = {"economic_event_key": key, "amount": "100", "source": "old"}
        new = {**old, "source": "revised"}
        self.assertEqual(change_plan([old], [old])["new"], [])
        result = change_plan([old], [new])
        self.assertEqual(result["changed_review_only"], [key])
        self.assertEqual(result["new"], [])
        with self.assertRaises(ValueError):
            change_plan([], [old, old])

    def test_removed_is_review_only(self):
        old = {"economic_event_key": "synthetic"}
        self.assertEqual(change_plan([old], [])["removed_review_only"], ["synthetic"])

    def test_period_and_alias(self):
        self.assertEqual(period("Sep'26"), "2026-09")
        with self.assertRaises(ValueError):
            period("July to October 2025")
        self.assertEqual(building("UG-180"), "UG-169")
        self.assertNotEqual(building("TWR-16"), building("TWR-39"))

    def test_output_not_in_repo(self):
        with self.assertRaises(ValueError):
            outside_repo(Path(__file__).resolve().parents[1] / "private.json")

    def test_manifest_changed_or_escaping(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "source.txt"
            p.write_text("synthetic")
            entry = {"path": "source.txt", "sha256": file_hash(p), "bytes": p.stat().st_size}
            (root / "manifest.json").write_text(json.dumps({"files": [entry]}))
            verify_pack(root)
            p.write_text("revised")
            with self.assertRaises(ValueError):
                verify_pack(root)
            entry["path"] = "../escape"
            (root / "manifest.json").write_text(json.dumps({"files": [entry]}))
            with self.assertRaises(ValueError):
                verify_pack(root)

    def test_sparse_cells_trailing_space_and_formula_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "synthetic.xlsx"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue " sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:XFD1048576"/><sheetData><row r="2"><c r="F2"><v>100</v></c><c r="G2" t="e"><f>1/0</f><v>#DIV/0!</v></c><c r="H2"/></row></sheetData></worksheet>')
            rows = list(workbook_rows(p))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "Revenue ")
            self.assertEqual(len(rows[0][2]), 2)
            self.assertEqual(rows[0][2][1]["financial_input_status"], "reject_error")


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"schema_version": 2, "site": "synthetic.invalid", "company": "SYN", "errors": [],
                         "snapshot_checksum": "synthetic-snapshot", "relationships": [],
                         "records": {"Sales Invoice": {"rows": [{"name": "SYN-INV", "company": "SYN", "posting_date": "2026-09-01"}]},
                                     "Account": {"rows": [{"name": "SYN-AR", "company": "SYN"}]}}}
        self.decisions = [{"doctype": "Sales Invoice", "name": "SYN-INV", "action": "delete", "reason": "Synthetic dummy fixture"}]

    def plan(self):
        self.snapshot["snapshot_checksum"] = snapshot_checksum(self.snapshot)
        return cleanup_plan(self.snapshot, self.decisions, "synthetic.invalid", "SYN", "synthetic-pack")

    def test_preserve_setup_and_exact_counts(self):
        plan = self.plan()
        self.assertEqual(plan["deletion_counts"], {"Sales Invoice": 1})
        self.assertEqual(plan["preserved_total"], 1)
        self.assertFalse(plan["execution_enabled"])

    def test_protected_record_denied(self):
        self.decisions[0].update(doctype="Account", name="SYN-AR")
        with self.assertRaises(ValueError):
            self.plan()

    def test_post_live_denied(self):
        self.snapshot["records"]["Sales Invoice"]["rows"][0]["posting_date"] = "2026-10-01"
        with self.assertRaises(ValueError):
            self.plan()

    def test_cross_company_denied(self):
        self.snapshot["records"]["Sales Invoice"]["rows"][0]["company"] = "OTHER"
        with self.assertRaises(ValueError):
            self.plan()

    def test_incomplete_inventory_denied(self):
        self.snapshot["errors"].append({"doctype": "File"})
        with self.assertRaises(ValueError):
            self.plan()

    def test_retained_dynamic_reference_blocks(self):
        self.snapshot["records"]["File"] = {"rows": [{"name": "SYN-F", "attached_to_doctype": "Sales Invoice", "attached_to_name": "SYN-INV"}]}
        self.snapshot["relationships"].append({"doctype": "File", "type": "Dynamic Link", "target": "attached_to_doctype", "field": "attached_to_name"})
        self.assertEqual(len(self.plan()["blockers"]), 1)

    def test_retained_child_blocks(self):
        self.snapshot["records"]["Sales Invoice Item"] = {"rows": [{"name": "SYN-L", "parenttype": "Sales Invoice", "parent": "SYN-INV"}]}
        self.assertEqual(len(self.plan()["blockers"]), 1)

    def test_wrong_site_denied(self):
        self.snapshot["site"] = "other.invalid"
        with self.assertRaises(ValueError):
            self.plan()

    def test_binding_and_scope_changes(self):
        plan = self.plan()
        approval = {k: plan[k] for k in ("site", "company", "pack_checksum", "snapshot_checksum", "plan_checksum")}
        approval["backup_restore_verified"] = True
        self.assertFalse(validate_approval(plan, approval, self.snapshot)["execution_enabled"])
        with self.assertRaises(ValueError):
            validate_approval(plan, {}, self.snapshot)
        with self.assertRaises(ValueError):
            validate_approval(plan, approval, {**self.snapshot, "snapshot_checksum": "new-write"})
        altered = copy.deepcopy(plan)
        altered["delete"] = []
        with self.assertRaises(ValueError):
            validate_approval(altered, approval, self.snapshot)


class SourceSafetyTests(unittest.TestCase):
    def test_legacy_write_actions_denied_before_queue(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import stub_frappe as S
        from darkbrown.api import admin
        for action in ("seed", "purge", "rebuild", "stage0_run", "stage11_run", "stage4_reload"):
            with self.assertRaises(Exception):
                admin._require_read_only_action(action)
        admin._require_read_only_action("stage0_check")

    def test_no_migrate_posting(self):
        from ast import parse, walk, Call, Name
        source = Path("darkbrown/install.py").read_text()
        function = next(n for n in parse(source).body if getattr(n, "name", None) == "after_migrate")
        self.assertFalse(any(isinstance(n, Call) and isinstance(n.func, Name) and n.func.id == "generate_head_lease_bills" for n in walk(function)))

    def test_inventory_is_not_public_endpoint(self):
        source = Path("darkbrown/migration/inventory.py").read_text()
        self.assertNotIn("@frappe.whitelist", source)
        self.assertNotIn("frappe.db.commit", source)
        self.assertNotIn("frappe.db.set_value", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
