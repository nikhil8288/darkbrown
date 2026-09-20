# Step 2 — tenancy and accounting foundation evidence

Status: **DEPLOYED; PARTIALLY RUNTIME VERIFIED**. The Step 2 source is on
`main`, the final code image is active, and an explicit in-place migration
succeeded. The source/stub suite and the runtime checks listed as PASS below
are complete. Step 2 is not marked complete because the fresh five-role run,
active-overlap, lifecycle-service and post-activation GL checks remain
unverified against the new synthetic records.

## Baseline before runtime mutation

- GitHub `main` at start: `ffce1c893edac2875963dcfc9ca5d2048d329c38`.
- Initially deployed DarkBrown: `d4284b79d067abb1684aa36b4143ac8946ddcff5`.
- Frappe Framework: 15.120.1 (`9f8ae9cd25b6735be345da6cc12e9f5a96050c68`).
- ERPNext: 15.121.2 (`df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`).
- Installed apps: Frappe, ERPNext and DarkBrown on their documented branches.
- Visible migration state before Step 2: Success.
- Current visible backup at baseline: Success, 15 September 2026 03:30. No
  backup contents or access URL were opened or recorded.
- Bench and site: Active. The bench Processes view returned no rows, so
  individual worker and scheduler state remains unverified.

Email delivery, bank/payment integrations and OCR were not enabled. Existing
`SEC-T01` accounts and records were not changed or deleted. Runtime records in
this evidence use only `S2-20260916-*` identifiers and generated agreement
series.

## Narrow implementation

- Building validates stable unique naming, landlord Supplier classification,
  QAR Company and immutable accounting ownership once dependent records exist.
  Cost Center creation is part of the Building transaction and linked deletion
  or rename is refused safely.
- Units are unique within a Building, cannot be moved across Buildings after
  dependent history exists, and derive occupancy from live agreements without
  overwriting operational Not Ready/maintenance states.
- Head Lease validates Building/landlord/Company/Cost Center consistency,
  dates, non-negative terms, lifecycle transitions, signed-document approval
  and overlapping live obligations. It never posts GL entries.
- Tenancy Agreement derives Building and Company from Unit, validates the
  classified ERPNext Customer, QAR-only monetary terms, dates, payment mode and
  frequency, documentation, explicit transitions and overlapping pending/live
  periods. Activation changes occupancy only and creates no invoice, deposit
  record or GL entry.
- Amendments preserve the prior value and use the target controller; renewals
  create a linked replacement without overwriting the original; termination
  requires a reason and preserves history.
- Permission hooks cover Buildings, Units, Head Leases, Tenancy Agreements,
  Agreement Amendments, landlord Suppliers and tenant Customers. Server-side
  role, native DocType, Building User Permission and sensitive-field controls
  remain in force.
- Loaders classify ERPNext parties and stage agreement imports for review;
  imported `Active` text is never treated as authorization.
- `accounting_setup.ensure_launch_foundation()` idempotently reuses suitable
  ERPNext leaves and adds only proven missing semantic leaves for rent income,
  security-deposit liability, tenant recharge and cheque holding. Existing
  valid Cash mode mappings are preserved and Cheque is mapped to the cheque
  holding leaf. No Bank Account, tax template, voucher or GL Entry is created.

## Accounting event map for later posting steps

ERPNext standard documents and General Ledger remain the system of record.
Nothing in Step 2 implements these postings.

| Business event | Future ERPNext document | Debit | Credit | Step 2 behavior |
| --- | --- | --- | --- | --- |
| Tenant rent billing | Sales Invoice | Tenant receivable | Rental income | Deferred |
| Landlord rent obligation | Purchase Invoice | Head Lease rent expense with Building Cost Center | Landlord payable | Deferred |
| Security deposit received | Payment Entry after cleared receipt | Bank/cash clearing | Security-deposit liability | No posting on agreement activation |
| Security deposit refund | Payment Entry | Security-deposit liability | Bank/cash clearing | Deferred |
| Security deposit deduction | Approved Journal Entry or invoice allocation | Security-deposit liability | Receivable/approved recovery income | Deferred |
| Tenant recharge | Sales Invoice | Tenant receivable | Tenant recharge income/clearing | Deferred |
| Maintenance expense | Purchase Invoice or Expense Claim | Maintenance expense with Building Cost Center | Payable/clearing | Deferred |
| Cash receipt | Payment Entry | Cash clearing | Tenant receivable | Deferred |
| Cheque received | Operational cheque record only | None | None | Must not post |
| Cheque deposited/cleared | Payment Entry at approved clearance | Bank/cheque clearing | Tenant receivable | Deferred |
| Bounced cheque | Cancel/reverse clearance plus approved charge document | Tenant receivable/bank-charge expense as applicable | Bank/cheque clearing | Deferred |
| Opening receivable | Opening Invoice Creation Tool / controlled opening Sales Invoice | Tenant receivable | Temporary opening account | Deferred; no CSV ledger load |
| Opening payable | Controlled opening Purchase Invoice | Temporary opening account | Landlord payable | Deferred; no CSV ledger load |

## Source/static proof

- Python compile: PASS.
- `git diff --check`: PASS.
- Controller/service inspection: PASS for Building, Unit, Head Lease, Tenancy
  Agreement, amendment, renewal, termination, permissions, hooks and loaders.
- OCR remains disabled in interface and server; no client-only bypass added.

## Stub/unit-test proof

| Check | Result |
| --- | --- |
| `verify/tenancy_foundation.py` | 13 passed |
| `verify/security_boundaries.py` | 8 passed |
| `verify/harness.py` | 48 passed, 0 failed |
| `verify/files_api.py` | 19 passed, 0 failed |
| `verify/notes_api.py` | 11 passed, 0 failed |

Total: **99 passed**. The harness intentionally exercises failing wipe gates
before its final PASS summary; those diagnostic lines are not failures.

## Actual Frappe runtime proof

The pre-live site was used only with clearly labelled synthetic records.

| Runtime claim | Result | Evidence |
| --- | --- | --- |
| Classified landlord Supplier, two Buildings and two Units created normally | PASS | Normal Desk UI; both Buildings received distinct linked Cost Centers |
| Classified tenant Customer and draft tenancy created normally | PASS | Normal Desk UI; Building derived from Unit; initial status remained Draft |
| Explicit Draft to Pending Approval transition | PASS | Normal Desk UI; version trail recorded the transition |
| Activation requires approval documentation | PASS | Tenancy activation rejected without signed pack; Head Lease activation rejected without signed document |
| Private synthetic attachment upload | PASS | Normal Desk private-file control uploaded and linked the labelled synthetic placeholder; no API or database bypass |
| Successful tenancy activation and occupancy transition | PASS | Authorized normal Desk workflow activated the synthetic agreement; its linked Unit became Occupied |
| Successful Head Lease activation | PASS | Authorized normal Desk workflow activated the synthetic Head Lease after linking the private placeholder |
| Overlapping tenancy on one Unit | PASS | Duplicated overlapping Pending Approval agreement rejected before insert |
| Negative monetary value | PASS | Negative monthly rent rejected before mutation |
| Draft Head Lease | PASS | Created normally with landlord/Building/Company and derived Cost Center; remained Draft |
| Non-active occupancy | PASS | Unit remained Vacant after draft/pending workflows |
| Draft/pending tenancy and draft Head Lease create no GL | PASS | Sanitized read-only query returned PASS for zero GL rows tied to the synthetic parties/Cost Centers |
| Cost Center and Unit linkage | PASS | Sanitized read-only query returned PASS for two distinct Building Cost Centers and two Unit/Building links |
| QAR, fiscal year, hierarchy and control accounts | PASS | Sanitized read-only accounting audit |
| Rent income, head-lease expense, deposit liability, tenant recharge, maintenance and Cash/Cheque holding | PASS | Sanitized read-only accounting audit |
| Cash and Cheque mode account mappings | PASS | Sanitized read-only accounting audit |
| Zero-tax launch configuration | PASS | No enabled sales-tax template in sanitized audit |
| Default Bank Account | FAIL / OWNER INPUT REQUIRED | No default exists; Step 2 deliberately did not manufacture bank details |

## Claims not proved at runtime

- Overlapping active Head Leases: **SOURCE/STUB ONLY**. The signed-document
  transport and a successful activation are now proved, but no second
  overlapping synthetic Head Lease was created during this controlled pass.
- Invalid date, unsupported currency and mismatched Building mutation:
  **SOURCE/STUB ONLY**. The normal UI derives/locks Building and Company; the
  server validators are covered by the source/stub suite.
- Five-role checks against the new `S2-*` records: **SOURCE/STUB ONLY**. The
  existing `SEC-T01` credentials were not available and were not reset. Step 1
  runtime evidence still covers five-role field and Building scope on the same
  deployed permission architecture.
- Successful amendment, renewal and termination of an activated agreement:
  **SOURCE/STUB ONLY**. Activation is now proved; the three lifecycle services
  still need their own controlled runtime pass.
- Activated tenancy and Head Lease create no GL: **SOURCE/STUB ONLY for the
  activated state**. The original sanitized read-only runtime query proves
  draft/pending tenancy and draft Head Lease created zero GL rows; controller
  and unit tests prove the activated transitions do not create accounting
  documents, but the sanitized runtime GL query was not rerun after the two
  successful activations.
- Individual worker and scheduler processes: **UNVERIFIED**; the cloud process
  list exposed no rows.

## Deployment proof

- Step 2 code was deployed from `main` through Frappe Cloud.
- Two intermediate explicit migrations stopped on safe configuration conflicts:
  first, no exact English Cash leaf; second, an existing valid Cash mode mapping.
  The implementation was narrowed to reuse ERPNext's account type and preserve
  the valid mapping rather than create a duplicate or overwrite it.
- Final deployed DarkBrown code SHA:
  `4be2284b503c105081bb5cc3736a7df6fa73f010`.
- Frappe and ERPNext stayed at the baseline versions; no upgrade was performed.
- Final in-place migration: Success, 16 September 2026 12:04, duration 8s,
  with skip-failing-patches disabled.
- Site and bench returned Active after migration.

## Unresolved risks and gates

1. Provide or configure the real default ERPNext Bank Account through an
   owner-approved operational process; do not invent bank details.
2. Run the active Head Lease overlap, amendment, renewal, termination and
   post-activation GL checks with synthetic records.
3. Re-run the new-record matrix under Maintenance, Documentation, Accounts,
   Building-A-scoped General Manager and Managing Director sessions without
   changing the existing `SEC-T01` credentials.
4. Confirm worker and scheduler state through an available runtime surface.
5. Repository history still contains prior operational CSV exposure. The
   owner decision in `docs/launch/history-containment.md` remains unexecuted.
6. Existing `SEC-T01` and new `S2-*` synthetic records remain intentionally in
   place pending separate cleanup authorization.

## Resulting SHAs

- GitHub Step 2 code SHA: `4be2284b503c105081bb5cc3736a7df6fa73f010`.
- Deployed DarkBrown code SHA: `4be2284b503c105081bb5cc3736a7df6fa73f010`.
- A later evidence-only commit may make GitHub `main` newer than the deployed
  code image; it does not change executable code.
