"""Synthetic identity and October-activation checks, not ERP integration tests."""
import unittest
from darkbrown.migration.assemble import merge_masters, contract_review


class AssemblyTests(unittest.TestCase):
    def test_merge_retains_both_sources(self):
        a = {'doctype': 'Customer', 'name': 'one', 'values': {'customer_name': 'Test'}, 'source': [{'row': 1}]}
        b = {**a, 'source': [{'row': 2}]}
        self.assertEqual(merge_masters([a], [b])[0]['source'], [{'row': 1}, {'row': 2}])

    def test_conflicting_party_rejected(self):
        a = {'doctype': 'Customer', 'name': 'one', 'values': {'customer_name': 'Test'}, 'source': [{'row': 1}]}
        with self.assertRaises(ValueError):
            merge_masters([a], [{**a, 'values': {'customer_name': 'Other'}}])

    def test_current_tenant_does_not_activate_previous_tenant(self):
        masters = [
            {'doctype': 'Unit', 'name': 'A-R-01', 'values': {'unit_no': 'R-01'}},
            {'doctype': 'Tenancy Agreement', 'name': 'contract', 'source': [{'row': 2}],
             'values': {'building': 'A', 'unit': 'A-R-01', 'tenant': 'Previous',
                        'monthly_rent': '100', 'start_date': '2026-01-01', 'end_date': '2027-01-01'}}]
        event = {'kind': 'rent_invoice', 'service_period': '2026-09', 'building': 'A',
                 'unit': 'R-01', 'party': 'Current', 'amount': '100', 'source': [{'row': 3}]}
        self.assertEqual(contract_review(masters, [event])[0]['reason'], 'different_september_party')
        event['party'] = 'Previous'
        self.assertEqual(contract_review(masters, [event])[0]['reason'], 'exact_current_match_signed_pack_still_required')
        with self.assertRaises(ValueError):
            contract_review(masters, [event, event])


if __name__ == '__main__':
    unittest.main()
