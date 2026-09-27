# DarkBrown finance screen fixes

Based on `main` commit `dfbc7be` (27 September 2026). Copy the included `darkbrown/` and `verify/` paths into the same paths in the GitHub repository, then commit and deploy. Keep the directory structure. The two DocType JSON changes require Frappe migration during deployment.

## Changes

- Invoice list: building and unit search/filter and a Unit column, drawn from the invoice run line. The boot list now includes up to the latest 1,000 invoices; if it reaches that limit the screen says so.
- Payment: initial amount from the selected invoice balance (or tenant open balance); explicit method selection; optional reference with a stable internal reference for a blank reference and protection against a repeated form submission.
- Deposit batch: server-backed posted cash receipts and incoming cheques, with source-derived tenant/unit/amount. No manual matching step. Bank destination starts blank and must be a valid company bank account. Banking an already-posted cash receipt creates a bank debit and cash credit, without another Payment Entry. Receipts that cannot resolve to one unit are withheld and counted for an unrestricted Accounts user.
- Expense: select a unit within the selected building or Whole building; server checks the unit/building pair. The register shows unit attribution and pages through all entries. The common-cost split table is removed from this screen.

## Source checks run

`python verify/finance_audit_fixes.py` — 7 passed.
`python verify/harness.py` — 141 passed, 0 failed.
Python compilation, JSON validation, browser script parsing, `git diff --check` — passed.

These are source/stub checks. A Frappe Cloud run is required to verify DocType migration, posting and browser behavior on the deployed build.

## Focused post-deployment check with synthetic records

1. Open Invoices: filter building and unit, search an invoice or tenant, open a row, and record a partial payment. Verify amount starts at that invoice balance and method starts empty. Save with no reference; verify one Payment Entry and a generated `DBR-...` internal reference. Refresh and check balance.
2. Record a Cash receipt linked to one unit. Open Create deposit batch: only posted, unbanked cash receipts and incoming cheques should appear, with tenant, building, unit, and amount already populated. The bank selector should be blank. Create a batch and have a different user mark it banked. Confirm one Bank Entry journal debits the selected bank and credits Cash for the receipt amount, with no second tenant Payment Entry.
3. Record a building expense once for one unit and once for Whole building. Check the unit column and journal. Try a unit from another building via the API: the save must be refused. Inspect Expenses > Lifetime and navigate the pages.
4. On a scope-limited Accounts user, confirm the deposit picker and expense unit choices contain only permitted buildings. Preserve existing cheque clearing and bank statement matching behavior.

Do not use real tenant cash for the first post-deployment check; the new cash-to-bank Journal Entry has not yet been validated in the actual Frappe runtime.
