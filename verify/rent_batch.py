"""Synthetic compiler checks: monetary meaning, missing identity, duplicates."""
import copy
import unittest
from darkbrown.migration.rent_batch import compile_rent, party_key, unit_key
from darkbrown.migration.native_import import validate_batch


def fixture():
    return [{'aggregation': 'none', 'evidence': [{
        'economic_event_key': 'one', 'identity': {'building': 'A', 'unit': 'F-01', 'tenant_name': 'Test Tenant'},
        'service_period': '2026-07', 'rent_amount': '1000.00',
        'source': {'source_file': 'synthetic.xlsx', 'source_sha256': 'synthetic', 'worksheet': 'Rent', 'row': 2},
        'source_amounts': {'recorded_received': '600.00', 'advance_applied': '200.00',
                          'previous_due_received_adjustment': '-100.00', 'net_due': '100.00', 'security': None}
    }]}]


MAPPING = {'receivable': 'AR', 'rent_income': 'Rent', 'collections_clearing': 'Clearing',
           'tenant_advances': 'Advances', 'company': 'Synthetic', 'site': 'test.invalid',
           'cost_centers': {'A': 'A'}, 'territory': 'Test'}


class CompilerTests(unittest.TestCase):
    def test_exact_accounting_meaning(self):
        b = compile_rent(fixture(), MAPPING)
        self.assertTrue(validate_batch(b))
        self.assertEqual(b['controls']['planned_rent_due'], '100.00')
        self.assertEqual([e['kind'] for e in b['events']], ['rent_invoice', 'collection', 'collection', 'journal'])
        self.assertEqual(sum(float(e['amount']) for e in b['events'] if e['kind'] == 'collection'), 700)
        self.assertEqual(b['events'][-1]['lines'][0]['account'], 'Advances')

    def test_missing_tenant_is_held(self):
        data = fixture(); data[0]['evidence'][0]['identity']['tenant_name'] = None
        b = compile_rent(data, MAPPING)
        self.assertEqual(b['events'], [])
        self.assertEqual(len(b['exceptions']), 1)
        self.assertEqual(b['controls']['source_rent'], '1000.00')

    def test_no_guessing_blank_receipt(self):
        data = fixture(); a = data[0]['evidence'][0]['source_amounts']
        a.update(recorded_received=None, net_due='700')
        b = compile_rent(data, MAPPING)
        self.assertEqual(len([e for e in b['events'] if e['kind'] == 'collection']), 1)

    def test_duplicate_fails(self):
        with self.assertRaises(ValueError):
            compile_rent(fixture() + fixture(), MAPPING)

    def test_inconsistent_due_fails(self):
        data = fixture(); data[0]['evidence'][0]['source_amounts']['net_due'] = '101'
        with self.assertRaises(ValueError): compile_rent(data, MAPPING)

    def test_repeat_stable(self):
        self.assertEqual(compile_rent(fixture(), MAPPING), compile_rent(fixture(), MAPPING))

    def test_alias_preserves_subunit(self):
        self.assertEqual(unit_key('F01/1'), 'F-01/1')
        self.assertNotEqual(unit_key('F03/1'), unit_key('F031'))
        a = {'building': 'A', 'unit': 'F01', 'tenant_name': 'Same Person'}
        b = dict(a, unit='F-01')
        self.assertEqual(party_key(a), party_key(b))
        self.assertNotEqual(party_key(a), party_key(dict(a, building='B')))

    def test_approved_twr_alias_is_scoped(self):
        self.assertEqual(unit_key('F03/1', 'TWR-39'), 'R-03/1')
        self.assertEqual(unit_key('F03/1', 'TV-20'), 'F-03/1')
        self.assertNotEqual(unit_key('F03/1', 'TWR-39'), unit_key('R031', 'TWR-39'))
        a = {'building': 'TWR-39', 'unit': 'F03/1', 'tenant_name': 'Same Person'}
        self.assertEqual(party_key(a), party_key(dict(a, unit='R-03/1')))


if __name__ == '__main__': unittest.main()
