# DarkBrown finance update — 27 September 2026

This consolidated package supersedes both earlier finance ZIP files. It is based on `nikhil8288/darkbrown` main commit `dfbc7be`. Preserve the directory structure when adding these files to the GitHub repository. Deploy the code and run the normal Frappe migration because DocType JSON files changed. Do not add the ZIP itself as a repository file.

## What changed

- Invoice list: search and filter by building and unit, with a Unit column.
- Payment: amount starts at the selected invoice balance (or the tenant's open balance), method starts blank, and reference is optional. Cheque is no longer a selectable payment method.
- Cheques: navigation, direct routes, entry forms, Accounts home widgets, and cheque dashboard widgets are deferred. New cheque logging is rejected by the server. Historical cheque records remain stored for audit; no data is deleted. Cheque terms in an agreement may be managed in the manual register without requiring an in-app cheque count for activation.
- Deposit batches: candidates come from posted, unbanked cash receipts. Tenant, unit, building, and amount are read from the receipt; new batches reject cheque lines. Destination bank starts blank. The optional JPG/PNG deposit slip image uploads privately, attaches to the saved batch, and appears on its detail page. The person who prepared a batch may bank it without entering a reason. Banking transfers existing cash receipts from Cash to Bank without posting another tenant payment. Old draft batches containing cheques remain visible but cannot be banked in the app while the cheque workflow is deferred.
- Expenses: unit within building or Whole building; unit attribution in the register; paged lifetime entries; no common-cost split table on the entry screen.

## Checks performed

- `python verify/finance_audit_fixes.py`: 10 passed, including cheque deferral, same-person banking, new-batch cheque rejection, and private slip attachment.
- `python verify/harness.py`: 132 passed, 0 failed. Nine checks for the deferred cheque workflow were skipped and remain in the file for its return.
- Python compilation, DocType JSON validation, JavaScript syntax parsing, and `git diff --check`: passed.

These are local source and stub checks. Confirm upload, migration, permissions, and cash-to-bank posting on the deployed Frappe site with synthetic records before using real cash.
