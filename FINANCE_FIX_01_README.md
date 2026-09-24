# DarkBrown finance fix 01 — review and deployment

Base checkout: `ddfa2ffb04b42c6fbece8260f41db0f6929fe0cd`  
Local branch: `fix/finance-audit-20260924`  
No repository push or deployment was performed by this package. The ZIP paths are relative to the repository root, including `darkbrown/...` and `verify/...`; they are not flattened. Apply on this base or review and merge conflicts against newer main before deployment.

## Repairs in this package

- Receipt register now distinguishes Draft, Issued and Cancelled. Its value, unallocated total and method counts use submitted receipts only; canceled and draft records stay visible. It scopes tenant records before paging, caps only the displayed rows and computes full scoped totals.
- New cash-mode collections default to the validated Cash ledger rather than the default bank. Cash lines posted through an explicit bank deposit batch retain their bank destination. The collector is the authenticated user, stored on the Payment Entry remark.
- A direct receipt requires a reference, serializes submissions by tenant and rejects an exact submitted duplicate of tenant, date, reference, amount and method. Direct cheque-mode recording is denied; clearing the cheque posts its payment once.
- Expense Entry server validation rejects Petty Cash as a payment source; the expense dropdown hides that account and the migration-only Historical Cutover Control. Use the dedicated petty-cash movement workflow for petty spending.
- Common-cost allocation now conserves two-decimal QAR amounts to the dirham with deterministic remainder distribution. Expense, receipt, petty and books views expose decimals rather than rounding those amounts away. Finance boot/API amount helpers retain two decimal places.
- Receipt/expense form dates derive from the current browser date. The expense modal redraws after its chart loads. Petty headline figures use a complete server summary, and its displayed movement balance uses the backend running balance even above 200 rows.
- Custom books page through GL Entry beyond the old 20,000-row cutoff, while journal row presentation remains separately capped.

## Verification completed before deployment

| Check | Result |
|---|---|
| `python verify/finance_audit_fixes.py` | 6 synthetic/stub scenarios pass: receipt state and totals, 301 receipts with scope, cash routing and duplicate, petty guard, dirham allocation, 20,001 GL rows |
| `python verify/harness.py` | 141 pass, 0 fail |
| `python verify/files_api.py` | 19 pass, 0 fail |
| `python verify/head_lease_foundation.py` | 2 pass |
| Python compile + inline JavaScript syntax + `git diff --check` | Pass |

Pre-existing, still failing: `verify/security_boundaries.py` stops on the Documentation/landlords role-matrix expectation; `verify/notes_api.py` has a missing account in its test fixture; `verify/tenancy_foundation.py` has a stale literal Cash setup assertion. No test expectations were weakened or edited to hide these failures. Source/stub passes are not deployed ERPNext proof.

## Post-deployment acceptance checks

Use new clearly marked synthetic references; keep prior `FIN-AUD-20260924-A` records until the audit cleanup. Reload the custom ERP after deployment and verify:

1. Old audit receipt `ACC-PAY-2026-00007` is Issued; `00008` Cancelled; amendment `00008-1` Draft. That fixture set contributes only **30.55** to issued value. The actual aggregate also includes unrelated receipts.
2. Submit a new 0.01 or 30.55 cash receipt using an unused tenant/reference. Verify native Payment Entry debits the configured Cash ledger, not Qatar National Bank; verify its authenticated collector remark. Submit the identical request again and confirm it is rejected with no additional GL transaction.
3. Submit a bank-transfer receipt and verify a bank debit. Submit a cash deposit batch with its explicit bank account and check that banked cash still reaches the selected bank.
4. Try Petty Cash through the expense form and native Expense Entry; both should refuse it. Enter a dedicated petty movement and reconcile its register with the new GL movement. The **existing 5.25** mismatch from `EXP-03029` remains until a separately reviewed correction/cleanup; this code patch does not rewrite history.
5. Revisit Expense allocations with 0.01, 12.35 and 45.80 synthetic pools; allocated building shares must sum to the original amount. Inspect P&L, Balance Sheet, Cash Flow, receipt and petty views for two-decimal arithmetic.
6. Exercise a larger isolated dataset around the receipt 300, petty 200 and books 20,000 boundaries. This stub check did not load 20,001 transactions into the deployed site.
7. Recheck the cold-load expense form and the default receipt date in the deployed browser.

Do not treat this package as final finance sign-off. The independent statement cash-flow query has its own volume limits; building-scope policy for company-wide books remains unsettled; dashboard metrics, head-lease accrual posting gap, incomplete owner/journal features, and full invoice/credit/refund/cheque lifecycle tests are still open. Prior incorrect cash routing and petty ledger differences are historical data and require deliberate reconciliation. The original audit report lists the full backlog and cleanup manifest.
