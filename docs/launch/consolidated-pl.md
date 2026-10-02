# Consolidated P&L

The approved desktop matrix transposes P&L heads into columns and buildings
into rows, with one section per selected month. Standard P&L stays available
in the adjacent tab. Accounting date controls now show Starting month,
Ending month and Apply filters without the redundant preset button strip.

Revenue and expense values come from company-currency posted GL entries,
excluding cancelled entries and Period Closing Vouchers. The same account
classification drives both views. Head Lease Rent is separate from the
remaining Cost of Sales; gross and net results retain losses and reversals.
Cost centres inherit their building through the cost-centre hierarchy.
Unmapped and NULL cost centres remain in a separate company row. No common
cost allocation, synthetic financial data or ledger writes are introduced.

The report compares its range income, gross, expense, net and expense-group
totals against the independent Standard P&L account aggregation. A mismatch
blocks the matrix. Source completeness qualifications remain visible.

Each cell selects its exact month, building cost centres and account group.
Gross and net drilldowns show signed contributions. Source postings are
paged in sets of 100, while totals and entry counts include the full selection.
Source links retain exact voucher type and identifier. Back restores the
selected range, ledger page and matrix horizontal position. Applying a new
range from a cell returns to the consolidated matrix.

Portfolio-wide MD, GM and Accounts access is required. Explicitly scoped
users and nonfinancial roles cannot read this company report.

## Verification before deployment

- `python verify/consolidated_pl.py`: monthly contra entries, losses, expense
  mapping, separate head rent, cost-centre descendants, company NULL costs,
  independent reconciliation rejection, page beyond 400 entries, role/scope
  denial and no mutations.
- `node verify/consolidated_pl.js`: actual shell matrix, two month controls,
  selected-range total, signed loss display, exact source selection,
  pagination and Back with horizontal scroll.
- Accounts Home and reporting-period Python and DOM checks passed.
- Eight security boundary checks passed.
- Route regression: 2,130 renders across five roles and six seed states;
  30 combinations passed, no rendering failures.

These synthetic checks do not establish source expense completeness. Live
deployment and ledger reconciliation evidence is recorded separately without
posting confidential amounts or party identities into this repository.
