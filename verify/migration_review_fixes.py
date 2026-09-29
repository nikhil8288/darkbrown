"""Focused synthetic regressions for the three preparation review findings."""
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from darkbrown.migration.inventory import capture, snapshot_checksum
from darkbrown.migration.plan import cleanup_plan


def fixture():
    return {"schema_version": 2, "site": "test.invalid", "company": "A", "errors": [], "snapshot_checksum": "test",
            "records": {
                "Sales Invoice": {"rows": [{"name": "INV", "company": "A", "posting_date": "2026-09-01"}]},
                "Sales Invoice Item": {"istable": 1, "rows": [{"name": "ITEM", "parent": "INV", "parenttype": "Sales Invoice", "parentfield": "items"}]}},
            "relationships": [{"doctype": "Sales Invoice", "field": "items", "type": "Table", "target": "Sales Invoice Item"}]}


def decision(dt, name, action="delete"):
    return {"doctype": dt, "name": name, "action": action, "reason": "Synthetic reviewed fixture"}


def plan(s, decisions):
    s["snapshot_checksum"] = snapshot_checksum(s)
    return cleanup_plan(s, decisions, "test.invalid", "A", "synthetic-pack")


class Ownership(unittest.TestCase):
    def test_old_inventory_requires_recapture(self):
        s = fixture()
        s["schema_version"] = 1
        with self.assertRaisesRegex(ValueError, "singleton"):
            plan(s, [])

    def test_reported_other_company_post_cutover_child(self):
        s = fixture()
        s["records"]["Sales Invoice"]["rows"][0].update(company="B", posting_date="2026-10-02")
        result = plan(s, [decision("Sales Invoice Item", "ITEM")])
        reasons = [b["reason"] for b in result["blockers"]]
        self.assertTrue(any("another company" in r for r in reasons))
        self.assertTrue(any("post-cutover" in r for r in reasons))
        self.assertTrue(any("parent retained" in r for r in reasons))
        self.assertFalse(result["execution_enabled"])

    def test_explicit_retained_parent(self):
        s = fixture()
        result = plan(s, [decision("Sales Invoice", "INV", "preserve"), decision("Sales Invoice Item", "ITEM")])
        self.assertTrue(result["blockers"])

    def test_valid_parent_and_child_selection(self):
        result = plan(fixture(), [decision("Sales Invoice", "INV"), decision("Sales Invoice Item", "ITEM")])
        self.assertEqual(result["blockers"], [])

    def test_missing_parent(self):
        s = fixture()
        s["records"]["Sales Invoice"]["rows"] = []
        self.assertTrue(plan(s, [decision("Sales Invoice Item", "ITEM")])["blockers"])

    def test_wrong_parentfield(self):
        s = fixture()
        s["records"]["Sales Invoice Item"]["rows"][0]["parentfield"] = "invented"
        self.assertTrue(plan(s, [decision("Sales Invoice", "INV"), decision("Sales Invoice Item", "ITEM")])["blockers"])

    def test_protected_parent(self):
        s = fixture()
        s["records"]["Company"] = {"rows": [{"name": "A"}]}
        s["records"]["Sales Invoice Item"]["rows"][0].update(parent="A", parenttype="Company")
        s["relationships"].append({"doctype": "Company", "type": "Table", "field": "items", "target": "Sales Invoice Item"})
        reasons = [b["reason"] for b in plan(s, [decision("Sales Invoice Item", "ITEM")])["blockers"]]
        self.assertIn("child of protected parent", reasons)

    def test_linked_document_cutover(self):
        s = fixture()
        s["records"]["File"] = {"rows": [{"name": "FILE", "attached_to_doctype": "Sales Invoice", "attached_to_name": "INV"}]}
        s["records"]["Sales Invoice"]["rows"][0]["posting_date"] = "2026-10-02"
        s["relationships"].append({"doctype": "File", "type": "Dynamic Link", "field": "attached_to_name", "target": "attached_to_doctype"})
        reasons = [b["reason"] for b in plan(s, [decision("File", "FILE")])["blockers"]]
        self.assertIn("linked or parent record is post-cutover", reasons)


class SingletonCapture(unittest.TestCase):
    def capture_fixture(self, invoice="INV", setting=1):
        Field = lambda name, typ, options=None: types.SimpleNamespace(fieldname=name, fieldtype=typ, options=options)
        fields = [Field("default_invoice", "Link", "Sales Invoice"), Field("enabled", "Check"),
                  Field("credential", "Data"), Field("opaque", "Password"), Field("api_secret", "Data"),
                  Field("opaque_data", "Data")]
        class Meta:
            is_virtual = False
            def __init__(self, fs): self.fields = fs
            def get_field(self, n): return next((f for f in self.fields if f.fieldname == n), None)
            def has_field(self, n): return self.get_field(n) is not None
        dt = types.SimpleNamespace(name="Synthetic Settings", module="Darkbrown", istable=0, issingle=1)
        reads = []
        def read_single(doctype, field):
            reads.append(field)
            return {"default_invoice": invoice, "enabled": setting}.get(field)
        frappe = types.ModuleType("frappe")
        frappe.session = types.SimpleNamespace(user="Administrator")
        frappe.local = types.SimpleNamespace(site="test.invalid")
        frappe.conf = {}
        frappe.db = types.SimpleNamespace(get_single_value=read_single)
        frappe.get_installed_apps = lambda: []
        frappe.get_meta = lambda name: Meta(fields if name == dt.name else [])
        frappe.get_all = lambda name, **kw: ([dt] if name == "DocType" else [types.SimpleNamespace(name="A", default_currency="QAR")] if name == "Company" else [])
        utils = types.ModuleType("frappe.utils")
        utils.get_bench_path = lambda: "/synthetic"
        utils.now_datetime = lambda: "2026-09-30"
        frappe.utils = utils
        with patch.dict(sys.modules, {"frappe": frappe, "frappe.utils": utils}):
            result = capture(company="A", expected_site="test.invalid")
        return result, reads

    def test_singleton_reference_is_retained_and_blocks(self):
        captured, reads = self.capture_fixture()
        row = captured["records"]["Synthetic Settings"]["rows"][0]
        self.assertEqual(row["default_invoice"], "INV")
        self.assertEqual(captured["errors"], [])
        s = fixture()
        s["records"].update(captured["records"])
        s["relationships"] += captured["relationships"]
        result = plan(s, [decision("Sales Invoice", "INV"), decision("Sales Invoice Item", "ITEM")])
        self.assertTrue(any(b["reason"] == "retained incoming link" for b in result["blockers"]))
        for name in ("credential", "opaque", "api_secret", "opaque_data"):
            self.assertNotIn(name, reads)
            self.assertNotIn(name, row)

    def test_reference_and_setting_changes_invalidate_checksum(self):
        original, _ = self.capture_fixture()
        for changed in (self.capture_fixture(invoice="OTHER")[0], self.capture_fixture(setting=0)[0]):
            self.assertNotEqual(original["snapshot_checksum"], changed["snapshot_checksum"])
        self.assertEqual(snapshot_checksum(original), original["snapshot_checksum"])

    def test_singleton_cannot_be_deleted(self):
        s, _ = self.capture_fixture()
        with self.assertRaises(ValueError):
            plan(s, [decision("Synthetic Settings", "Synthetic Settings")])

    def test_changed_singleton_cannot_reuse_old_fingerprint(self):
        s, _ = self.capture_fixture()
        s["records"]["Synthetic Settings"]["rows"][0]["enabled"] = 0
        with self.assertRaisesRegex(ValueError, "content changed"):
            cleanup_plan(s, [], "test.invalid", "A", "synthetic-pack")


class ReadOnlyWorker(unittest.TestCase):
    def test_missing_overhead_does_not_create_configuration(self):
        import stub_frappe as S
        from darkbrown.api import admin
        S.DB.clear()
        S.DB.update({"Company": [{"name": "A"}], "Cost Center": [{"name": "Root - A", "company": "A", "is_group": 1}]})
        S.SESSION["roles"] = ["System Manager"]
        before = copy.deepcopy(S.DB)
        S.CALLS.clear()
        # Test both entry points, including already queued actions. The entire
        # legacy catalogue except the audited count function must fail closed.
        for action in admin.ACTIONS:
            if action == "stage0_check":
                continue
            with self.assertRaises(S.ValidationError): admin.start(action)
            with self.assertRaises(S.ValidationError): admin.execute(action)
        self.assertEqual(S.DB, before)
        self.assertEqual(S.CALLS, [])


class DeploymentAndOperations(unittest.TestCase):
    def test_migrate_keeps_configuration_helpers_without_posting(self):
        import stub_frappe as S
        from darkbrown import install
        from contextlib import ExitStack
        helpers = ("reconcile_custom_fields", "seed_document_requirements",
                   "seed_expense_chart", "seed_accounting_foundation")
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch.object(install, name)) for name in helpers]
            posting = stack.enter_context(patch("darkbrown.api.finance.generate_head_lease_bills"))
            commit = stack.enter_context(patch.object(S.frappe.db, "commit"))
            install.after_migrate()
            for helper in mocks:
                helper.assert_called_once_with()
            posting.assert_not_called()
            commit.assert_called_once_with()

    def test_existing_owner_nightly_remains_registered_and_calls_billing(self):
        import stub_frappe as S
        from darkbrown import hooks
        from darkbrown.api import finance
        self.assertIn("darkbrown.api.finance.nightly", hooks.scheduler_events["daily_long"])
        with patch.object(finance, "generate_head_lease_bills") as billing, \
             patch.object(finance, "_settings", return_value=types.SimpleNamespace(presentation_notice_days=14)), \
             patch.object(S.frappe, "get_all", return_value=[]), \
             patch.object(S.frappe.db, "commit"):
            self.assertEqual(finance.nightly(), 0)
            billing.assert_called_once_with()

    def test_supported_count_worker_has_no_business_or_config_writes(self):
        import stub_frappe as S
        from darkbrown.api import admin
        S.DB.clear()
        S.DB.update({"Company": [{"name": "A"}], "Cost Center": [{"name": "Root - A", "company": "A", "is_group": 1}]})
        before = copy.deepcopy(S.DB)
        S.CALLS.clear()
        with patch.object(S.frappe, "set_user", create=True) as user, \
             patch.object(admin, "_append"), patch.object(admin, "_finish"), \
             patch.object(S.frappe.db, "rollback", create=True) as rollback, \
             patch.object(S.frappe.db, "commit") as commit:
            admin.execute("stage0_check")
            commit.assert_not_called()
            rollback.assert_called_once()
        self.assertEqual(S.DB, before)
        self.assertEqual(S.CALLS, [])


class OwnerEvidenceContinuation(unittest.TestCase):
    def row(self, source, sheet, data):
        return {"source_file": source, "source_sha256": "synthetic", "worksheet": sheet,
                "row": 3, "evidence_id": source + sheet,
                "cells": [{"cell": col + "3", "type": "n" if value.isdigit() else "s", "value": value}
                          for col, value in data.items()]}

    def test_combined_period_and_blank_charge_never_become_postable(self):
        from darkbrown.migration.owner_review import HISTORY, review
        result = review([self.row(HISTORY, "Owners Rent", {"A": "1", "B": "SYN", "D": "0", "F": "Aug to Oct 2025"})])
        row = result["historical_owner_candidates"][0]
        self.assertIsNone(row["amounts"]["billed"])
        self.assertIsNone(row["original_period"])
        self.assertIsNone(row["economic_event_key"])
        self.assertFalse(row["execution_enabled"])

    def test_revised_payable_is_control_not_an_additional_bill(self):
        from darkbrown.migration.owner_review import CURRENT, OLD, review
        result = review([self.row(OLD, "Sheet1", {"D": "SYN", "E": "100"}),
                         self.row(CURRENT, "Sheet1", {"D": "SYN", "E": "120"})])
        self.assertEqual(len(result["current_payable_controls"]), 1)
        self.assertEqual(len(result["supersession_differences"]), 1)
        self.assertEqual(result["historical_owner_candidates"], [])
        self.assertEqual(result["ready_to_post"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
