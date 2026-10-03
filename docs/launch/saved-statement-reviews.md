# Saved statement reviews

Validated private PDFs now create private File-backed review snapshots, scoped
to the current company and user. The Reconciliation screen lists these after
refresh and shows all original rows, including historical and repeated rows.
Identical PDF bytes reopen the existing snapshot. A new export is compared
with saved rows including the running balance; possible overlaps are flagged
without deleting rows. A deterministic File name prevents duplicate snapshots.
Concurrent transaction collisions may require retrying the upload.

Only uniquely mapped active company Bank Accounts are accepted. The legacy
mutating statement import endpoint is denied on the server as well as being
absent from the PDF UI. No review creates GL entries, invoices, receipts,
clearance dates, opening balances, or Bank Statement Import records. Historical
rows before 1 October 2026 remain review-only. Candidate links are dated
snapshots, not current confirmations or posted reconciliation.

Local checks: eight synthetic persistence/access/duplicate boundary tests in
`verify/statement_review.py`; preview and candidate planner suites; Python
compile and extracted JavaScript syntax checks. The three authorized private
PDF samples also pass the parser's running-balance validation. These are local
checks, not proof of a real Frappe File persistence round trip. Runtime rollout
must verify that separately without posting financial transactions.

Private PDFs and their financial contents are deliberately excluded from Git.
