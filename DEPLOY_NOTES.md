# DarkBrown consolidated finance update — 27 September 2026

This consolidated package supersedes the earlier finance ZIP files from this session. It is based on `nikhil8288/darkbrown` main commit `dfbc7be`. Copy the files with their paths intact into the repository, deploy the code, and run the normal Frappe migration. DocType JSON changed; do not upload the ZIP itself into GitHub as a single file.

## Finance workflow

- Invoices can be searched and filtered by building and unit. Tenant payments default to the selected invoice or tenant balance, start with an empty method, and allow an empty reference.
- A tenant cheque is received in Record payment with its number, drawn-on bank, cheque date, received date, selected invoice where applicable, and optional private JPG/PNG image. Receiving it does not pay the invoice. The separate Cheques navigation remains hidden.
- Deposit batches offer posted cash receipts and received tenant cheques with tenant, building, unit and amount copied from the source. The destination bank starts empty; a private deposit slip image is optional. Banking moves posted cash from Cash to Bank and presents cheques without posting tenant receipts.
- Cash deposit Bank Entries now carry the slip number (or the batch ID when the slip number is blank) and the banking date as ERPNext's required reference fields. This fixes the "Reference No & Reference Date is required for Bank Entry" error when marking a batch banked.
- Importing a bank statement reconciles a uniquely matched, exact-amount batch and posts its cheque receipts once, on the bank date. A cheque cannot be marked cleared directly without a matched statement. Ambiguous or unmatched lines stay open for review. Older matched batches with pending cheques can be completed from their batch page.
- Landlord Payments lists every landlord and building with outstanding posted bills, including landlords with no bill. Active Head Lease agreements generate and submit one monthly Purchase Invoice per lease and month, using the agreement rent, rent-free days, start/end dates, and building cost centre. Billing starts **1 October 2026**, the agreed real-data opening date. The migration hook fills the current month from that date; the daily scheduler handles subsequent months and safe retries. Draft and manual issue actions are removed from the app. Any existing unsubmitted bill is posted automatically only if its landlord, company, amount, single rent line, expense account and cost centre agree with the lease; otherwise it is flagged **Needs review**. Payments can be made later or partially, while the bill remains outstanding. Cash, bank transfer and cheque are supported. Paid from bank offers the two usual company banks plus Other bank. Other bank must already be configured as a company Bank Account with a bank ledger; the payment does not invent an account or an intercompany transfer.
- An outgoing landlord cheque requires its number and date, accepts an optional private JPG/PNG image, records a single supplier Payment Entry against the chosen bill at issuance, and is marked cleared when its bank debit matches the imported statement. The cleared state never posts the payment a second time.
- Expenses can be assigned to a unit or the Whole building. The expense register shows its entries and unit; the common-cost split panel is removed.

Historical cheque records are preserved. No existing financial records are deleted by this package.

## Checks

- `python verify/finance_audit_fixes.py`: 20 focused source/stub checks passed.
- `python verify/harness.py`: 132 passed, 0 failed. Nine old standalone cheque-register checks stay deferred because that module remains hidden.
- Python compilation, DocType JSON parsing, JavaScript syntax, and `git diff --check` passed.

The local checks do not run against a live Frappe database. Before the real-data import, check that the active Head Lease agreements, landlord Suppliers, cost centres and Head Lease Rent expense account are correct. After deployment and migration, confirm that no September landlord bill was created; on or after 1 October, confirm that each eligible lease has exactly one submitted bill for the month with the agreed amount and that Landlord Payments shows its outstanding balance. Record a partial synthetic payment and confirm the remaining balance; verify a repeat generation does not create another bill. Also use synthetic records to verify image upload, bank mapping, a tenant cheque through a deposit and statement match, and an outgoing landlord cheque matched to its bank debit before processing real payments. Billing failures are logged per building and do not block other buildings.
