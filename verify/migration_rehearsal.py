"""Synthetic failure-injection checks of the rollback-only orchestration."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import patch


class Flags(dict):
    def __setattr__(self, key, value):
        self[key] = value


class RehearsalTests(unittest.TestCase):
    def exercise(self, fail_import):
        state = {'work': False, 'report': None, 'rollback_count': 0}
        def rollback():
            state['work'] = False
            state['rollback_count'] += 1
        frappe = types.ModuleType('frappe')
        frappe.local = types.SimpleNamespace(site='test.invalid')
        frappe.session = types.SimpleNamespace(user='Administrator')
        frappe.conf = {}; frappe.flags = Flags(); frappe.PermissionError = PermissionError
        frappe.db = types.SimpleNamespace(rollback=rollback)
        class Report:
            name = 'private-report'
            def __init__(self, values): self.values = values
            def insert(self):
                assert not state['work'], 'Report must follow rollback'
                state['report'] = json.loads(self.values['content'])
        frappe.get_doc = lambda values: Report(values)
        installer = types.ModuleType('frappe.installer')
        def config(key, value):
            if value == 'None': frappe.conf.pop(key, None)
            else: frappe.conf[key] = value
        installer.update_site_config = config
        jobs = types.ModuleType('frappe.utils.background_jobs')
        jobs.get_redis_conn = lambda: types.SimpleNamespace(lock=lambda *a, **k: nullcontext())
        rq = types.ModuleType('rq')
        rq.get_current_job = lambda: types.SimpleNamespace(kwargs={
            'site': 'test.invalid', 'user': 'Administrator', 'method': 'darkbrown.migration.rehearsal.run'})
        with patch.dict(sys.modules, {'frappe': frappe, 'frappe.installer': installer,
                                     'frappe.utils.background_jobs': jobs, 'rq': rq}):
            spec = importlib.util.spec_from_file_location('rehearsal_test_target',
                Path(__file__).parents[1] / 'darkbrown/migration/rehearsal.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            module.load_private = lambda *a: {'batch': {'site': 'test.invalid', 'company': 'Synthetic'},
                'reset_plan': {'rows': [], 'orphan_exceptions': []}, 'backup_id': 'synthetic-backup'}
            module.verify_idle_site = lambda *a: None
            module.inspect = lambda *a: {'passed': True}
            module.capture = lambda **kw: {'records': {'Example': {'rows': [{'name': 'synthetic-row', 'changed': state['work']}]}}}
            module.reset_plan = lambda *a: {'reset_checksum': 'synthetic'}
            def reset(*args): state['work'] = True; return {'committed': False}
            module.execute = reset
            calls = []
            def posting(*args):
                calls.append(True)
                if fail_import: raise ValueError('Synthetic posting failure')
                return {'events_created': 1 if len(calls) == 1 else 0, 'masters_created': 0}
            module.import_batch = posting
            result = module.run('private-input', 'checksum')
        self.assertFalse(state['work'])
        self.assertEqual(frappe.conf, {})
        self.assertGreaterEqual(state['rollback_count'], 2)
        self.assertFalse(result['committed_business_data'])
        return result, state['report']

    def test_posting_failure_restores_data_and_site_switches(self):
        result, report = self.exercise(True)
        self.assertEqual(result['status'], 'FAILED')
        self.assertTrue(report['rollback_verified'])
        self.assertEqual(report['error'], 'Synthetic posting failure')

    def test_success_also_rolls_back(self):
        result, report = self.exercise(False)
        self.assertEqual(result['status'], 'PASSED_ROLLBACK_REHEARSAL')
        self.assertTrue(report['rollback_verified'])


if __name__ == '__main__': unittest.main()
