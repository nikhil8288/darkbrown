"""Synthetic controller tests: no Frappe database or restore proof."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Retention(unittest.TestCase):
    def load(self, has_active_gl):
        fake = types.ModuleType('frappe')
        fake._ = lambda text: text
        fake.db = types.SimpleNamespace(exists=Mock(return_value=has_active_gl))
        fake.delete_doc = Mock(side_effect=AssertionError('Cost centre deletion forbidden'))
        def throw(message):
            raise ValueError(message)
        fake.throw = throw
        source = pathlib.Path(__file__).resolve().parents[1] / 'darkbrown/utils/cost_center.py'
        spec = importlib.util.spec_from_file_location('tested_cost_center', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': fake}):
            spec.loader.exec_module(module)
        return module, fake

    def test_active_ledger_blocks_building_deletion(self):
        module, fake = self.load(True)
        with self.assertRaises(ValueError):
            module.guard_cost_center_delete(types.SimpleNamespace(cost_center='Test - EX'))
        fake.db.exists.assert_called_once_with('GL Entry', {'cost_center':'Test - EX','is_cancelled':0})
        fake.delete_doc.assert_not_called()

    def test_empty_or_cancelled_ledger_retains_dimension(self):
        module, fake = self.load(False)
        module.guard_cost_center_delete(types.SimpleNamespace(cost_center='Test - EX'))
        fake.delete_doc.assert_not_called()

    def test_missing_dimension_no_write(self):
        module, fake = self.load(False)
        module.guard_cost_center_delete(types.SimpleNamespace(cost_center=None))
        fake.db.exists.assert_not_called()
        fake.delete_doc.assert_not_called()

if __name__ == '__main__':
    unittest.main()
