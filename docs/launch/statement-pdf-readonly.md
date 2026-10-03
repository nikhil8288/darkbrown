# QNB and Doha Bank statement PDF validation

This release replaces the live pasted-row form with a private PDF upload and
read-only validation. It accepts the supplied digital QNB and Doha Bank layouts
only. The PDF reader validates page numbering, transaction dates, every running
balance, and QNB's printed debit/credit and opening/closing totals. Doha's
wrapped decimal places are reconstructed before validation. Scanned or unknown
layouts stop with a review error. No OCR service is enabled in this release.

The server checks the File permission and private flag before reading bytes,
then looks for one configured company Bank Account with the statement's exact
account number. It reports transactions before the agreed 1 October 2026
cutover as historical and checks later lines for possible overlap with existing
imports. The endpoint neither creates a Bank Statement Import nor clears a
cheque, changes a batch, or posts to the ledger.

The two supplied attachments are parser samples only. They contain 224 QNB
transactions over 42 pages and 97 Doha Bank transactions over five pages. All
are dated before the cutover. The existing pasted-row import key would collapse
10 genuine repeated QNB rows and one Doha row. That write endpoint remains
unchanged but is no longer offered by the live upload form. A future write path
requires persisted PDF source identity, per-row running-balance identity,
duplicate-file and overlapping-period protection, matching and an actionable
exception queue. It must be tested with synthetic records on a disposable
Frappe bench before enabling financial effects.

## Local evidence

- `python verify/statement_pdf.py <QNB.pdf> <Doha.pdf>`: complete page, row,
  balance and printed-total validation; wrapped decimals; genuine repeated
  rows; removing a page from either PDF rejects the file.
- `python verify/statement_preview.py`: role check before file access, private
  file enforcement, company bank mapping, historical cutoff and overlap flag.
- `python verify/security_boundaries.py`: eight existing access checks pass.
- `python verify/finance_audit_fixes.py`: existing focused finance checks pass.
- `node --check` of the shell's extracted script and
  `node verify/reporting_periods.js` pass.

No real bank PDF, account number, transaction, credential, or imported
operational record is included in this repository. Runtime checks after
deployment should use an authorized session and remain read-only; do not
upload the supplied statements to production as test data.
