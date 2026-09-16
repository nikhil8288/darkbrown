# Step 2 — tenancy and accounting foundation evidence

Status: **SOURCE COMPLETE; RUNTIME/DEPLOYMENT BLOCKED**. The narrow Step 2
implementation and source/stub regressions pass. The pre-live site changed from
Active to Suspended during execution, so no post-change deployment, migration,
accounting configuration inspection or synthetic runtime matrix is claimed.

## Baseline established before mutation

- GitHub `main`: `ffce1c893edac2875963dcfc9ca5d2048d329c38`.
- Deployed DarkBrown: `d4284b79d067abb1684aa36b4143ac8946ddcff5`.
- Frappe Framework: 15.120.1 (`9f8ae9cd25b6735be345da6cc12e9f5a96050c68`).
- ERPNext: 15.121.2 (`df8b7f9648c2ec4da12db8c4022edc8dd1018c6b`).
- Installed apps: Frappe, ERPNext and DarkBrown on `main`.
- Last visible site migration: Success, 15 September 2026 23:40.
- Current backup: Success, 15 September 2026 03:30. No backup URL or contents
  were opened or recorded.
- Bench `bench-42102-000183-f2-uae`: Active. Its Processes view returned no
  process rows, so individual worker health and scheduler state are unverified.
- Site `darkbown.u.frappe.cloud`: initially Active, then reported Suspended on
  16 September 2026. SQL Playground did not offer the suspended site.

No runtime data was changed. Email delivery, bank/payment integrations and OCR
were not enabled. Existing `SEC-T01` accounts and records were not deleted.

## Narrow implementation

- Building validates a stable case-insensitive name, valid landlord Supplier,
  QAR Company and immutable Company once dependent records exist. Linked
  records block deletion.
- Cost Center creation now fails the Building transaction when Company/root
  hierarchy is missing; it no longer leaves a Building without its dimension.
- Unit uniqueness, Building immutability, history-preserving deletion and
  derived occupancy are server-enforced.
- Head Lease validates landlord/Company/Cost Center consistency, non-negative
  terms, explicit lifecycle transitions, signed-document approval and
  date-range overlap. Draft/activation create no ledger records.
- Tenancy Agreement derives Building and Company from Unit, enforces QAR,
  tenant classification, dates, non-negative terms, payment vocabulary,
  explicit transitions, approval documentation and overlapping pending/live
  date ranges.
- Agreement creation no longer self-activates and no longer manufactures a
  held Security Deposit. Activation changes occupancy only. Billing and GL
  remain outside Step 2.
- Renewal creates a linked replacement without expiring or overwriting the
  original before approval. Termination requires a reason. Amendments are
  restricted to approved fields, capture the actual prior value and save
  through the target controller so invariants cannot be bypassed.
- Building-scoped query/detail controls now cover Head Lease, Agreement
  Amendment, landlord Suppliers and tenant Customers while preserving normal
  non-DarkBrown parties.
- Synthetic loaders classify existing parties but stage imported Head Leases
  and Tenancy Agreements for review. Imported “Active” text is not treated as
  authorization.
- Workflow copy and prototype behavior no longer claim self-activation or
  create illustrative deposit/head-lease journal entries.
- `accounting_foundation.audit()` is read-only. It reports Company currency,
  fiscal year, Cost Center hierarchy, required semantic accounts, payment
  modes and enabled sales-tax templates without balances or party data.

## Accounting event map (future posting steps)

ERPNext standard documents and General Ledger remain the system of record.
Nothing in this Step 2 implementation posts these entries.

| Business event | Future ERPNext document | Debit | Credit | Step 2 behavior |
| --- | --- | --- | --- | --- |
| Tenant rent billing | Sales Invoice | Tenant receivable | Rental income | Not implemented |
| Landlord rent obligation | Purchase Invoice | Head Lease Rent expense, Building Cost Center | Landlord payable | Not implemented |
| Security deposit received | Payment Entry at cleared receipt | Bank/cash clearing | Security Deposits Held liability | No record or GL on agreement activation |
| Deposit refund | Payment Entry | Security Deposits Held liability | Bank/cash clearing | Not implemented |
| Deposit deduction | Journal Entry or approved invoice allocation | Security Deposits Held liability | Receivable/approved recovery income | Not implemented |
| Tenant recharge | Sales Invoice | Tenant receivable | Tenant recharge income/clearing | Not implemented |
| Maintenance expense | Purchase Invoice/Expense Claim | Building Maintenance expense, Building Cost Center | Payable/clearing | Not implemented |
| Cash receipt | Payment Entry into cash clearing | Cash clearing | Tenant receivable | Deferred to payment stage |
| Cheque received | Cheque operational record only | None | None | Must create no GL |
| Cheque deposited/cleared | Payment Entry at approved clearance | Bank/cheque clearing | Tenant receivable | Deferred to payment stage |
| Bounced cheque | Cancel/reverse clearance plus approved charge document | Tenant receivable/bank charge expense as applicable | Bank/cheque clearing | Deferred to payment stage |
| Opening receivable | ERPNext Opening Invoice Creation Tool / controlled opening Sales Invoice | Tenant receivable | Temporary opening account | Deferred; no CSV ledger load |
| Opening payable | Controlled opening Purchase Invoice | Temporary opening account | Landlord payable | Deferred; no CSV ledger load |

Account names are semantic roles, not permission to create duplicates. Existing
ERPNext control accounts must be reused where suitable. A DarkBrown-specific
leaf is added only after the read-only runtime audit proves the role is missing.
Zero-tax launch behavior means billing documents will carry no tax template or
tax rows; this is not yet runtime-verified.

## Source/static proof

- Python compile: PASS.
- `git diff --check`: PASS.
- Controller/service inspection: PASS for Building, Unit, Head Lease, Tenancy
  Agreement, amendments, renewals, termination, permission hooks and loaders.
- Step 1 HTML/OCR boundary assertions: PASS.

## Stub/unit-test proof

| Check | Result | Evidence class |
| --- | --- | --- |
| `verify/tenancy_foundation.py` | 8 passed | Synthetic controller/service stub |
| `verify/security_boundaries.py` | 8 passed | Step 1 synthetic security regression |
| `verify/harness.py` | 48 passed, 0 failed | Existing source/stub regression |
| `verify/files_api.py` | 19 passed, 0 failed | Existing source/stub regression |
| `verify/notes_api.py` | 11 passed, 0 failed | Existing source/stub regression |

The harness intentionally exercises failing wipe gates before its final PASS
summary; those diagnostic lines are not test failures.

## Actual Frappe runtime proof

No post-change runtime claims. The pre-live site became Suspended before
deployment, and the read-only SQL surface did not offer it for sanitized
configuration inspection. Consequently the two-Building/five-role synthetic
matrix, zero-GL comparison, accounting configuration audit and normal-workflow
checks remain **BLOCKED**, not passed.

## Deployment proof

Not yet available. Source must not be described as deployed until Frappe Cloud
shows the resulting DarkBrown SHA and successful build/migrate/site update.

## Unresolved risks and gates

1. Restore the pre-live site to Active and verify worker/scheduler health.
2. Run the read-only accounting audit; configure only proven missing roles.
3. Deploy the resulting GitHub SHA and stop on any build/migration issue.
4. Run the required synthetic two-Building/five-role matrix and compare GL Entry
   counts before/after draft and activation.
5. Repository history still contains prior operational CSV exposure. The
   unexecuted owner decision remains in `docs/launch/history-containment.md`.
6. Existing `SEC-T01` records remain intentionally untouched pending separate
   cleanup authorization.

## Resulting SHAs

- GitHub `main`: pending source commit/push.
- Deployed DarkBrown: `d4284b79d067abb1684aa36b4143ac8946ddcff5`
  (unchanged; Step 2 not deployed).
