# Preparation review fixes — 30 September 2026

Status: corrected preparation only. Execution remains disabled. No production
inventory, ERP integration or backup restoration was performed. No push/deploy.
Baseline: `6a47950f94db5011630dd00c7cb3611cbfc983fb`; branch
`codex/migration-preparation`; remote `nikhil8288/darkbrown`.

## Focused changes and regression evidence

| Finding | Fix | Synthetic regression |
| --- | --- | --- |
| Checks creating Overhead | Literal allowlist admits only audited `stage0_check`; request and queued worker deny every other legacy action. Worker has no commit or database error-log write and rolls back on exit. | Company/root Cost Center with no Overhead: every denied action leaves business/configuration store and mutation log unchanged; supported count worker also leaves both unchanged and never commits. |
| Selected child bypasses protection | Validate parent existence, parent type/table field ownership and explicit parent deletion; inherit company/cutover protection through parents and Link/Dynamic Link records. Retained/protected parents block children. | Reported company-B, 2026-10-02 invoice reproducer; retained parent, missing parent, invalid parentfield, protected parent, linked post-cutover document, and valid explicit parent-plus-child selection. |
| Singleton values omitted | Inventory v2 captures singleton Link/Dynamic Link values/discriminators and safe scalar settings using DB reads, without controller lifecycle calls. Singleton records are preserved. Secret field types/names are excluded before reading. | Retained singleton reference blocks deletion; changed reference or setting changes snapshot checksum; secret fields neither read nor exported; singleton deletion denied. |
| Stale/incomplete snapshot reuse | Require v2 and recompute inventory checksum before planning and approval validation. | Old-format inventory and modified singleton under stale checksum rejected. |

Commands: `python -X utf8 verify/migration_review_fixes.py` (18 tests),
`python -X utf8 verify/migration_preparation.py` (20 tests).
These exercise real application functions with synthetic data and mocked Frappe;
they do not prove installed database or ledger behavior.

Final local verification: **190 passed, 0 failed** across the 18 focused tests,
20 preparation tests, 132 existing harness checks and 20 finance regression
checks. Actual Frappe/ERP accounting tests: **not run**. The broad harness uses
negative fixtures whose printed `FAIL` text is expected; its final assertions
report 132 passed, 0 failed.

The focused hook regression executes `after_migrate` with mocked helpers and
asserts calls to `reconcile_custom_fields`, `seed_document_requirements`,
`seed_expense_chart`, `seed_accounting_foundation`, and commit, with no call to
`generate_head_lease_bills`. The nightly regression confirms `daily_long`
registration and the existing `finance.nightly` call to owner billing.
Schema patches, custom-field synchronization and ordinary billing are retained.

## Exact endpoint impact and supported operations

All HTTP methods below are under `/api/method/darkbrown.api.admin.`:

- `start`: now accepts only `stage0_check`. All `stage1`–`stage11` actions,
  all `_gate`, `_run`, `_reload`, plus `verify`, `purge`, `seed`, `rebuild`
  are denied. `stage0_gate` and `stage0_run` are denied too.
- `execute` is the non-whitelisted background target and enforces the same
  literal allowlist, including for already queued legacy jobs.
- `residual_sweep` remains denied regardless of confirmation text.
- `preview` and `residual_preview` retain count reads. `progress` reads cache;
  `clear` clears only cached status/log. They are not a complete migration graph.

The supported replacement for legacy migration checks is the non-whitelisted
bench function `darkbrown.migration.inventory.export`. There is no replacement
production cleanup endpoint in this release. The ordinary UI uses separate
finance/agreements/operations endpoints, not legacy Data actions. In particular,
`finance.build_invoice_run`, `submit_invoice_run`, `issue_invoice_run`,
`cancel_invoice_run`, `cancel_run_invoice`, receipt/cheque and owner bill paths
are unchanged in the replacement ZIP. Existing UI/stub harness and finance
regressions cover those paths; no live browser/UI result is claimed.

The earlier unvalidated tenant scheduling/deferred-revenue prototype was saved
privately and removed from this release. `finance.py` and `hooks.py` match the
baseline. This ZIP does not enable a new tenant scheduler or claim accounting
completion. Existing owner scheduling remains active in ordinary operations.

## Reconstruction continuation

`python -m darkbrown.migration.owner_review <private-cached-evidence-directory>`
continues from the existing hash-bound extraction without re-extracting sources.
It separates historical owner charge candidates from revised payable control
snapshots, records revision differences, and preserves unresolved combined
periods, missing amounts, supplier/lease joins and settlement evidence as gates.
Its output is private and non-postable; review snapshots never become extra bills.
Synthetic regressions cover blank/combined-period and revision non-duplication.
The private review output records actual source counts; no source data is in this ZIP.

Correction routing stays within installed application design: unissued Invoice
Runs use `cancel_invoice_run`; issued invoices require the guarded
`cancel_run_invoice` lifecycle and a reviewed replacement. Historical source
revisions remain review-only changes, never direct updates to submitted amounts
or GL rows. A migration adjustment register and its installed-ERP verification
are still outstanding, as are complete owner/expense/payroll/asset mappings.

## Required actual ERP evidence — not run

On a disposable site matching the production inventory, run each approved
synthetic import/billing case, then capture the persisted voucher IDs, docstatus,
invoice links, amounts, outstanding, GL Entry rows and Payment Ledger Entry rows.
Run the identical operation again and assert zero new documents, zero added or
changed GL/PLE rows, unchanged allocations/outstanding, and identical TB/P&L/BS
and party balances. Counts alone are insufficient. Store normalized row hashes
and financial totals for both runs, keyed by voucher and economic event.

Also test concurrent workers, failure after document insertion before commit,
resume after commit, and revised sources. Revised sources must stop for review;
approved corrections must create exactly one linked reversal/replacement through
native lifecycle APIs, then become idempotent on retry. Test bill/receipt/advance/
deposit and cheque paths separately. These are required integration acceptance
cases, not results or an implemented migration posting runner.

Restore database and public/private files into a separate disposable site; check
document/ledger fingerprints, access, attachments and reports. Keep production
credentials/encryption keys out of returned logs and code archives.

Production inventory is needed for exact Company, installed versions, actual
links/counts and configuration. A disposable environment is needed for ledger
idempotency, native cancellation dependencies and restore proof. Neither gap
authorizes production cleanup/posting or can be replaced with stub tests.
