"""Synthetic API/boot checks. Does not claim installed Frappe integration."""
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
frappe = types.ModuleType('frappe')
registered = {}
def whitelist(**kwargs):
    def decorate(fn):
        registered[fn.__name__] = kwargs
        return fn
    return decorate
frappe.whitelist = whitelist
frappe.PermissionError = PermissionError
frappe.session = types.SimpleNamespace(user='Administrator')
frappe.local = types.SimpleNamespace(site='synthetic.invalid')
frappe.get_all = Mock(return_value=['Synthetic Company'])
sys.modules['frappe'] = frappe
api = importlib.import_module('darkbrown.api.migration_inventory')

class DownloadTests(unittest.TestCase):
    def setUp(self):
        frappe.session.user = 'Administrator'
        frappe.get_all.reset_mock()

    def test_non_admin_denied_before_any_read(self):
        for user in ['Guest', 'manager@example.invalid', 'accounts@example.invalid']:
            frappe.session.user = user
            with patch.object(api, 'capture') as capture:
                for fn in [api.context, api.download]:
                    with self.assertRaises(PermissionError): fn()
                capture.assert_not_called()
        frappe.get_all.assert_not_called()

    def test_post_only_no_guest(self):
        for args in registered.values():
            self.assertEqual(args['methods'], ['POST'])
            self.assertFalse(args.get('allow_guest', False))

    def test_context_private_and_actual_company_choices(self):
        response = api.context()
        self.assertEqual(json.loads(response.data)['message'], {
            'site': 'synthetic.invalid', 'companies': ['Synthetic Company']})
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertNotIn('Content-Disposition', response.headers)

    def test_company_required(self):
        for value in [None, '', ' ', [], {'name': 'Synthetic Company'}]:
            with patch.object(api, 'capture') as capture:
                with self.assertRaises(ValueError): api.download(company=value)
                capture.assert_not_called()

    def test_private_attachment_preserves_snapshot_and_errors(self):
        snapshot = {'schema_version': 2, 'snapshot_checksum': 'fixture',
                    'cleanup_executable': False, 'errors': [{'doctype':'Virtual','error':'manual review'}]}
        with patch.object(api, 'capture', return_value=snapshot) as capture:
            response = api.download(company='Synthetic Company', expected_site='synthetic.invalid')
            capture.assert_called_once_with(company='Synthetic Company', expected_site='synthetic.invalid')
        self.assertEqual(json.loads(response.data), snapshot)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('attachment;', response.headers['Content-Disposition'])

    def test_mismatched_site_rejected_by_real_capture(self):
        with self.assertRaises(ValueError):
            api.download(company='Synthetic Company', expected_site='wrong.invalid')
        frappe.get_all.assert_not_called()

    def test_capture_failure_never_becomes_download(self):
        with patch.object(api, 'capture', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                api.download(company='Synthetic Company', expected_site='synthetic.invalid')

if __name__ == '__main__':
    unittest.main()
