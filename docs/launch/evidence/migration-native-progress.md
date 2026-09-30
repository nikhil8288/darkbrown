# Historical migration implementation checkpoint

Actual site verification, 30 September 2026:

- Frappe Cloud Administrator login is authorised and working.
- System Console verifies the target company and QAR currency.
- Synthetic native Sales Invoice 100 / receipt Journal Entry 60 leaves 40 due.
- Synthetic native Purchase Invoice 100 / supplier-payment Journal Entry 60
  leaves 40 payable. Debits and credits reconcile.
- Cancelling both settlement journals restores invoice/bill outstanding to 100.
- Explicit rollback and absence checks pass for synthetic parties, accounts,
  invoices, bills, GL Entries and Payment Ledger Entries.
- The console script is in `verify/frappe_console_accounting.py`. Commit was
  unchecked. This is a native posting check, not a backup-restoration test or
  an end-to-end cleanup rehearsal.

Implemented locally, not deployed:

- Rent, collection and advance-application compiler with preserved lineage.
- Owner-charge compiler and supported aggregate owner settlements. Returned
  source amounts are held, not marked paid.
- Expense-category compiler using original cells plus explicit accountant
  corrections. Expense counterparts remain provisional where funding and
  liability matching have not been established.
- Source master compiler, including the approved physical-building-number
  correction separating TWR-39 from TWR-16.
- Native voucher importer, reconstruction metadata, historical receipt view,
  historical landlord-bill view, and invoice building/unit labels.
- Exact-record reset implementation remains unexecuted. Combined transaction
  orchestration, final batch assembly, deployment and execution remain open.

The user approved the TWR-only F-to-R room alias. The compiler now applies it
to unit, party and contract identities, preserving subdivisions and original
source provenance. Non-TWR room prefixes are unchanged. Combined private batch
assembly and contract/current-occupancy conflict review are implemented. The
batch remains non-executable until full execution preflight is complete.

Seven explicitly labelled historical clearing accounts were created and saved
on the authorized target through native Account documents. No voucher or ledger
posting occurred. These accounts do not establish reconciled bank, payroll,
supplier or opening balances. The System Console was restored to Commit off.

The new read-only batch preflight verifies account, item, cost-centre, metadata
and master-link requirements. It does not prove native submission or restoration.

All source workbooks, identities, real amounts and derived private batches stay
outside the public repository. No real migration documents have been posted;
no dummy business data has been removed. Partial batches are denied by the
native import entry point.
