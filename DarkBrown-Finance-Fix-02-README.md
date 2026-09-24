# DarkBrown finance fix 02 — receipt review and cash collector

Apply this incremental patch **after** Fix 01 (deployed GitHub `main` commit `1eb865686437defecdf93c3dd228d496ee0c4e82`). The ZIP retains repository-root paths. Copy its three files to the matching paths in the repository, commit and push, then deploy with the normal Frappe procedure. Do not flatten the folders. Reload the custom ERP with a fresh query string to avoid a cached old shell.

## Files

- `darkbrown/api/finance.py` — enable ERPNext Payment Entry Custom Remarks when saving an authenticated cash collector. ERPNext otherwise overwrites the proposed collection note during validation.
- `darkbrown/shell/index.html` — keep the visible receipt Review and payment Allocation summaries in sync as fields are entered, show two decimal places in the review and confirmation, and allow two-decimal input. Escape free text displayed in the receipt review.
- `verify/finance_audit_fixes.py` — verify the persisted cash collector flag in the synthetic regression suite.

## Live acceptance after deploying Fix 02

1. With an unused synthetic reference, enter a **QAR 0.01 cash receipt**. Before submitting, the Review must show `QAR 0.01` and the exact collection slip. The confirmation must show `QAR 0.01`. Native submitted Payment Entry must debit `Cash - DBR` and show the authenticated collector in Custom Remarks. Confirm the receipt register and cash flow each move by QAR 0.01. Do not reuse `FIN-FIX-20260924-A-C01`.
2. With another unused reference, enter **QAR 11.23 bank transfer**. Review must show `QAR 11.23` and the bank statement reference before submitting. Verify the native bank ledger receives the debit. The prior attempt was **not submitted**, so `FIN-FIX-20260924-A-B01` remains unused; the saved browser draft is optional.
3. Check an exact duplicate is rejected; check the trial balance and balance sheet differences remain zero and the cash flow closing balance equals opening plus movement.

## Verified before this package

`python verify/finance_audit_fixes.py`: 6 pass; `python verify/harness.py`: 141 pass / 0 fail; inline JavaScript `node --check`, Python compilation and `git diff --check`: pass. These checks do not substitute for the two fresh posting tests above.

The deployed Fix 01 live test created only one new submitted receipt: `ACC-PAY-2026-00009`, cash **QAR 0.01**, tenant `S2-20260916-TENANT-A`, reference `FIN-FIX-20260924-A-C01`, on 24 September 2026. It is unallocated and debits `Cash - DBR`. The duplicate request was rejected without a second receipt. On that live state, issued receipts were 4 with value **QAR 4,630.56**; one draft and two cancelled remained excluded. The trial balance balanced at **QAR 12,357,554.19** per side, balance sheet difference **QAR 0.00**, September profit **QAR 166,618.70**, and cash flow reconciled **QAR 4,500.00 + 99.51 = 4,599.51**. Expense register **40.25 direct + 28.70 common = 68.95**; 27 common-cost shares sum to **51.05** including historical petty expenses.

The prior bank receipt submission was rejected by automatic action review because the form's visible Review still said QAR 0 and omitted its statement reference even though the inputs held QAR 11.23 and the reference. No bank receipt was submitted; this patch repairs the review before another posting attempt. Cash collector persistence and refreshed review remain awaiting deployed verification. The historical ledger still contains a **Cash In Hand -79.99** balance and a **Historical Cutover Control -1,572,276.33** balance. Those require separately reviewed data reconciliation in the later cleanup; this code patch does not rewrite accounting history. See the original ERP finance audit report for the wider open backlog.
