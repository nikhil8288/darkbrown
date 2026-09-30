# Offline cleanup lifecycle rehearsal

This addition runs locally without Frappe, SQL, Redis, network, or API writes.
It is not an executor. Do not deploy merely to use this tool.
The existing inventory, cleanup_plan, approval and cutover guards are unchanged.

## Input and output

Use the private schema-v2 inventory and an explicit proposed selection. Each
selection entry requires doctype, name, reason, and source_record_checksum.
The optional wrapper is an object with a selection array. Keep both outside Git.

From the repository root, run Python with these arguments (substitute private paths):

```text
python -m darkbrown.migration.sequence PRIVATE_INVENTORY.json PRIVATE_SELECTION.json --site EXACT_SITE_NAME --company EXACT_COMPANY_NAME --output NEW_PRIVATE_REHEARSAL.json
```

The output path must not exist and must be outside every Git checkout. Site,
company, inventory checksum, row checksums, counts and selection identity are
validated. The result includes a deterministic selection checksum, parent/native
voucher groups, a partial dependency order, exact circular components, unresolved
edges, and blockers. Execution remains false, including on a blocker-free input.

## Lifecycle rules

- Child rows inherit their owning native document operation. They are not deletes.
- GL, Payment Ledger and Stock Ledger rows bind to their voucher and are never
  independent deletion operations. Actual cancellation/deletion effects require
  installed-version integration tests, including ERPNext immutable ledger behavior.
- A selected voucher with an unselected ledger/child member is blocked.
- Protected setup, wrong-company records and October-or-later posting dates block.
- Retained incoming references, missing targets, missing/invalid ownership and
  every source inventory error remain blockers; queue errors are never cleared by
  a historical browser observation.
- Cyclic groups and their downstream nodes are withheld from the complete order.
  A native cancellation order can differ from the link-based deletion order;
  neither is claimed proven by this offline graph.
- No automatic link clearing, ignore_links, direct GL deletion, truncate, scheduler
  pause, permission changes, deployment hooks or new HTTP endpoints are added.

## Recovery and integration evidence still required

Before any production cleanup proposal becomes executable, produce an isolated
restore of the site's database and public/private files on the installed app
versions. Verify restored company, settings, permissions, attachments, voucher
counts and ledger totals. Keep outbound mail/integrations off during that test.
Rehearse approved cancellation/deletion, rollback or checkpoint recovery after
injected failures, and backup restoration. Native posted imports need balanced
ledgers, report reconciliation, duplicate-free identical rerun, and correction
posting tests. Do not describe offline Python tests as evidence of these gates.

The migration window must block site writes and future job enqueueing, inspect
current/pending/deferred/scheduled/retry work, drain or explicitly resolve it,
and restore the exact prior settings after reconciliation. Never stop shared
bench workers indiscriminately. Final approval binds exact source/selection/
plan and backup identities; an old inventory or stale queue view cannot authorize
execution. The October exception and synthetic-user quarantine need exact scoped
review, not blanket date or security-rule changes.

## Verification

16 synthetic cleanup-sequence tests plus 18 existing migration-review regressions
passed locally. No native ERP lifecycle or restore tests have run.

## Lifecycle follow-up

`darkbrown.migration.lifecycle_review.propose(snapshot, rehearsal)` adds offline,
record-checksummed advice for the reviewed installed commits. Version changes
fail closed. It never clears the original blockers or enables execution.

At the reviewed ERPNext commit, Customer.on_trash clears primary contact/address
and calls Frappe delete_contact_and_address. An exclusively customer-linked contact
can therefore belong to the customer's native cleanup. Shared contacts and
user-linked contacts are held. These hooks still need installed integration tests.
The reviewed Cheque/Deposit Batch and Move Out Case/Security Deposit pairs receive
exact backlink-clear proposals only for draft-status records and matching Link
metadata. No runtime setter or endpoint is introduced.

Controller review also identifies non-Draft tenancy and active head-lease deletion
holds. Never set all agreements to Draft or remove normal operational guards as a
shortcut. Expense Entry cancellation cancels its linked Journal Entry; the future
executor must account for that side effect and re-read state rather than cancel
it twice or reuse stale original checksums.

### Cost-centre protection correction

`darkbrown.utils.cost_center.guard_cost_center_delete` still rejects deletion when
active GL rows reference a building's cost centre. When deletion is otherwise
permitted it now retains the Cost Center; it no longer cascades deletion into
accounting setup. A replacement Building can reuse that dimension through the
existing create_building_cost_center path. Normal building/unit/agreement guards
remain in force. There is no data migration, cleanup job or posting in this patch.

The code ZIP now includes this runtime protection fix as well as offline tooling.
Apply the repository-relative files and deploy through the normal GitHub/Frappe
Cloud process when ready. Deployment itself does not start cleanup. Previously
issued private inventories and proposed scopes stay outside GitHub.

Verification: 3 controller-retention tests, 8 lifecycle-proposal tests, 16 sequence
tests and 18 existing migration-review tests passed (45 total). All are synthetic
or local regressions, not installed ERP integration or backup-restoration proof.

Reviewed upstream sources:
- https://github.com/frappe/erpnext/blob/4aee12e16c664897571457c007aaa95b8364bbbb/erpnext/selling/doctype/customer/customer.py
- https://github.com/frappe/frappe/blob/8f801ade016078685c3165c96e38f84f249f5309/frappe/contacts/address_and_contact.py
