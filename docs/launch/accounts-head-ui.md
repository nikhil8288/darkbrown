# Accounts Head financial overview

Scope: approved desktop overview in the existing ERP skin, on the existing
Accounts role. This does not create users, split Accounts into Head/Support,
post financial transactions, or change role permissions. MD and GM can open
Accounts overview from navigation; other roles cannot. A login with explicit
Building permissions is denied company-wide overview totals by the server.

Starting and ending months are inclusive. The current month stops at today's
date. P&L and movements span the selected range; cash, deposits, statements
and ageing use its ending date. Latest unit occupancy is explicitly labelled
as current operational status because historical occupancy is not inferred.

The overview uses the existing P&L, balance sheet and cash-flow APIs. Monthly
and building breakdowns aggregate non-cancelled trading GL entries, excluding
Period Closing Vouchers. Company/unassigned costs remain visible; building
results do not invent overhead allocation. Monthly totals must reconcile to
the P&L before the overview renders. Historical reporting qualifications stay
visible. Historical Cutover Control remains excluded from cash and bank.

Receivables/payables use ERPNext's ReceivablePayableReport in company currency
with report-date balances and due-date ageing. Credits/advances remain signed
and separate from positive ageing. Differences against GL control accounts
are flagged. The existing arrears pack also uses this dated read, rather than
today's invoice outstanding_amount when a past date was requested.

Month selections are carried into financial drilldowns. In-app Back uses
browser history and restores the prior route, URL filters, ledger/report
filter state and scroll. Journal detail reads the exact voucher from the
server instead of falling back to the first cached posting.

## Verification before deployment

- `python verify/accounts_home.py`: synthetic date, native-ageing adapter,
  credit/advance, loss, unassigned-cost and scoped-access checks pass.
- `NODE_PATH=<jsdom path> node verify/accounts_home.js`: synthetic DOM summaries,
  signed chart bars, month URLs, nested Back, filters, exact source reads and
  preset reset pass.
- Reporting-period Python/JS checks, security boundaries, invoice register,
  all 30 route/role/data combinations, Python compilation, JS syntax and diff
  whitespace checks pass.
- Broad harness: 129 pass, 3 failures also present on untouched `2c7ad80`:
  missing local Werkzeug dependency, stale rent derivation assertion and guard
  scanner findings in pre-existing migration endpoints. Home suite: 36 pass,
  one pre-existing GM/data-tools assertion fails. These are not financial
  sign-off or native Frappe runtime evidence.

Deployment uses the existing main branch and Frappe Cloud bench. After release,
verify the actual overview against P&L and cash flow for a multi-month range,
check positive/credit ageing and any control difference, and retrace report →
source → report → overview using Back. No synthetic records are created on the
operational site for these checks.
