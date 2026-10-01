# Accounts Head financial overview

Scope: approved desktop overview in the existing ERP skin, on the existing
Accounts role. This does not create users, split Accounts into Head/Support,
post financial transactions, or change role permissions. MD and GM can open
Accounts overview from navigation; other roles cannot. A login with explicit
Building permissions is denied company-wide overview totals by the server.

Starting and ending months are inclusive. The current month stops at today's
date. P&L and movements span the selected range; cash, deposits, statements
and ageing use its ending date. Latest occupancy uses the shared source-observation projection, including newer
operational changes and active agreements, rather than migration default unit
statuses. Unknown units remain explicit. Historical occupancy is not inferred.

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
filter state and scroll. Standard report selections and date/building filters also
use URL state and a range-specific cache. Encoded record names retain history. Journal detail reads the exact voucher from the
server instead of falling back to the first cached posting. Account detail now
pages that account's GL entries directly, with complete totals independent of
the 400-voucher company-wide journal cache.

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

## Post-deployment verification (2026-10-02 IST)

The deployed UI was checked read-only using the existing administrator session.
The Accounts role preview opens the financial overview from Home; this is UI
routing evidence, not a separate Accounts user's permission acceptance test.

- Multi-month overview income, expenses and net result agree with the live P&L.
- The rental-income account has more postings than the former global voucher
  cache limit. Its complete totals agree with the statement; pagination keeps
  those totals and displays the next distinct page of source postings.
- A source link from the second ledger page opens the requested Sales Invoice,
  with matching identity and balanced debit/credit lines.
- Back retraces source, second ledger page, first ledger page, P&L and overview;
  the month range, pagination and previous scroll position are restored.
- Live payables detail agrees with its overview and due-date ageing buckets.
  Dated receivables and occupancy agreement were also checked during release.
- Live cash-flow opening plus movement equals closing and agrees with the
  overview. Posted Cash/Bank balances currently contain no historical cash
  position; the existing opening-balance/settlement qualification stays visible.
- Desktop styling uses the existing brown sidebar, ivory background, beige
  panels, white summary cards and emerald links.
- Focused Python overview/period and security checks pass. Focused JS overview
  and period checks pass; all 30 route/role/data combinations pass.

No operational transactions or user permissions were changed during these
checks. The Accounts Head UI release is complete. Imported historical accounts
remain provisional; UI agreement with posted reports is not source-data or
financial-close sign-off. Accounts Support and the six-role user setup remain
outside this approved UI release.
