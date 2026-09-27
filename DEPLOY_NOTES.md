# DarkBrown finance update — 27 September 2026

This consolidated package supersedes all earlier finance ZIP files from this session. It is based on `nikhil8288/darkbrown` main commit `dfbc7be`. Keep the paths inside this ZIP when copying its files into the GitHub repository; do not upload the ZIP itself into GitHub. Deploy the code and run the normal Frappe migration because DocType JSON files changed.

## Changes

- Invoices: search and filter by building and unit, with a Unit column.
- Tenant payments: amount starts at the invoice or tenant balance, method starts blank, and reference is optional. Cheque is available in Record payment. Keep the cheque in the manual register until the bank confirms it cleared, then select Cheque, choose the actual bank, tick the confirmation, and post one Payment Entry against the invoice. The separate cheque register remains deferred, and new in-app cheque logging is blocked.
- Landlord Payments: a Finance menu screen shows building, landlord, amount, bill, and status for generated Head Lease Purchase Invoices. Use Draft monthly rent to create a bill; GM/MD may issue a draft bill; MD/Accounts may Record payment on an issued outstanding bill. Partial payments reduce that specific bill. Bank transfer and cleared cheque require choosing the paying bank. Cash uses the cash ledger. Cheque is recorded only after bank confirmation. The former schedule-only `pay_head_lease` action is disabled because it marked a row paid without a ledger payment.
- Deposit batches: candidates come from posted, unbanked cash receipts, with tenant, building, unit, and amount taken from the source receipt. New batches reject cheque lines. The destination bank starts empty. A JPG/PNG deposit slip image can optionally be attached privately. The person who prepared a batch may bank it without an override reason. Banking transfers already-posted cash receipts from Cash to Bank without a second tenant payment. Old draft cheque batches remain visible but cannot be banked through the deferred cheque workflow.
- Expenses: attribute an expense to a unit within the chosen building or the Whole building; the register shows unit and paged lifetime entries; the common-cost split table is removed from this screen.

Historical cheque records are preserved for audit. No database records are deleted by this package.

## Checks performed

- `python verify/finance_audit_fixes.py`: 16 focused source/stub checks passed.
- `python verify/harness.py`: 132 passed, 0 failed; nine obsolete checks for the deferred cheque register were skipped and remain in the harness for its return.
- Python compilation, DocType JSON validation, JavaScript syntax parsing, and `git diff --check`: passed.

These checks do not execute the live Frappe posting or file upload path. After deployment, use synthetic records to confirm cheque payment posting after clearance, a landlord bill's issue and partial payment, building-scoped visibility, cash/bank account mapping, and optional slip upload before processing real payments.
