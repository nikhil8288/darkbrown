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

class CorrectionTests(unittest.TestCase):
    def test_private_override_binds_original_and_period(self):
        from decimal import Decimal
        from darkbrown.migration.expense_batch import approved_amount
        rule = {'7:2026-07': {'original': '10', 'approved': '12', 'approval_reference': 'Synthetic approval'}}
        self.assertTrue(approved_amount(7, '2026-07', Decimal('10'), Decimal('12'), rule))
        self.assertFalse(approved_amount(7, '2026-08', Decimal('10'), Decimal('12'), rule))
        self.assertFalse(approved_amount(7, '2026-07', Decimal('11'), Decimal('12'), rule))

    def test_native_currency_round_trip_preserves_idempotency(self):
        from types import SimpleNamespace
        from darkbrown.migration.native_import import same_master_value
        meta = SimpleNamespace(get_field=lambda field: SimpleNamespace(fieldtype='Currency'))
        self.assertTrue(same_master_value(meta, 'monthly_rent', 100.0, '100.00'))
        self.assertFalse(same_master_value(meta, 'monthly_rent', 101.0, '100.00'))


if __name__ == '__main__':
    unittest.main()
