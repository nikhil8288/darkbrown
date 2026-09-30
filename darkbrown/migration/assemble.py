"""Assemble private source compilers without asserting unresolved data is complete.

This is an offline transformation. It never resets a site or posts documents.
"""
import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from darkbrown.migration.evidence import digest, outside_repo
from darkbrown.migration.rent_batch import compile_rent
from darkbrown.migration.master_batch import compile_masters
from darkbrown.migration.owner_batch import compile_owners
from darkbrown.migration.expense_batch import compile_expenses
from darkbrown.migration.native_import import validate_batch


MASTER_ORDER = {'Supplier': 0, 'Customer': 1, 'Building': 2, 'Unit': 3,
                'Head Lease': 4, 'Tenancy Agreement': 5}
EVENT_ORDER = {'rent_invoice': 0, 'owner_bill': 0, 'collection': 1,
               'supplier_payment': 1, 'journal': 2}


def merge_masters(*collections):
    merged = {}
    for collection in collections:
        for master in collection:
            key = (master['doctype'], master['name'])
            if key not in merged:
                merged[key] = {**master, 'source': list(master['source'])}
                continue
            old = merged[key]
            if old['values'] != master['values']:
                raise ValueError('Conflicting master values; identity requires review')
            for source in master['source']:
                if source not in old['source']:
                    old['source'].append(source)
    return sorted(merged.values(), key=lambda x: (MASTER_ORDER[x['doctype']], x['name']))


def contract_review(masters, rent_events):
    units = {m['name']: m['values'] for m in masters if m['doctype'] == 'Unit'}
    current = {}
    for event in rent_events:
        if event['kind'] != 'rent_invoice' or event['service_period'] != '2026-09':
            continue
        key = (event['building'], event['unit'])
        if key in current:
            raise ValueError('Multiple September rent records for one physical room')
        current[key] = event
    result = []
    covered = set()
    for master in masters:
        if master['doctype'] != 'Tenancy Agreement':
            continue
        v = master['values']; unit = units[v['unit']]
        key = (v['building'], unit['unit_no']); event = current.get(key)
        covered.add(key)
        if not event:
            reason = 'no_september_rent'
        elif event['party'] != v['tenant']:
            reason = 'different_september_party'
        elif Decimal(event['amount']) != Decimal(str(v['monthly_rent'])):
            reason = 'different_rent'
        elif not (v['start_date'] <= '2026-10-01' <= v['end_date']):
            reason = 'contract_not_current_at_cutover'
        else:
            reason = 'exact_current_match_signed_pack_still_required'
        result.append({'agreement': master['name'], 'building': key[0], 'unit': key[1],
                       'reason': reason, 'source': master['source'],
                       'september_source': event['source'] if event else None})
    for key, event in sorted(current.items()):
        if key not in covered:
            result.append({'agreement': None, 'building': key[0], 'unit': key[1],
                           'reason': 'september_occupancy_without_master_contract',
                           'source': event['source']})
    return result


def assemble(rows, groups, mapping):
    rent = compile_rent(groups, mapping)
    operational = compile_masters(rows, groups, mapping)
    owner = compile_owners(rows, mapping, operational['building_suppliers'])
    expense = compile_expenses(rows, mapping)
    masters = merge_masters(operational['masters'], rent['masters'])
    events = sorted(rent['events'] + owner['events'] + expense['events'],
                    key=lambda e: (EVENT_ORDER[e['kind']], e['posting_date'], e['key']))
    review = contract_review(masters, rent['events'])
    result = {
        'schema_version': 1, 'site': mapping['site'], 'company': mapping['company'],
        'masters': masters, 'events': events,
        'exceptions': rent['exceptions'] + operational['exceptions'] + owner['exceptions'] + expense['exceptions'],
        'contract_review': review,
        'controls': {'rent': rent['controls'], 'owner': owner['controls'],
                     'non_owner_expenses': expense['non_owner_expenses'],
                     'master_counts': dict(Counter(m['doctype'] for m in masters)),
                     'event_counts': dict(Counter(e['kind'] for e in events)),
                     'contract_review_counts': dict(Counter(r['reason'] for r in review))},
        'source_coverage': 'Supported rent, recorded collections, owner charges, recorded owner settlements and expense category facts. Remaining bank/payable/opening-balance reconciliation is not represented as complete.',
        'scope': 'combined_historical_reconstruction_pending_execution_preflight',
        'complete_replacement': False,
        'blocking_items': ['execution_account_preflight', 'exact_dummy_reset_scope',
                           'atomic_execution_and_recovery_verification',
                           'remaining_settlement_and_opening_balance_reconciliation',
                           'october_contract_activation_review'],
    }
    result['batch_checksum'] = digest(result)
    validate_batch(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--rent-preview', required=True)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    outside_repo(destination)
    rows = [json.loads(line) for line in Path(args.evidence).read_text().splitlines() if line.strip()]
    result = assemble(rows, json.loads(Path(args.rent_preview).read_text()),
                      json.loads(Path(args.mapping).read_text()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2))
    destination.chmod(0o600)
    # Do not print identities, financial amounts or source rows to public logs.
    print('Private combined batch written; execution remains blocked pending preflight.')


if __name__ == '__main__':
    main()
