# Statements — profit and loss, balance sheet, cash flow

Overlay unpacks over the repo root. Four files, one new and three changed.

    darkbrown/api/statements.py                          new
    darkbrown/shell/index.html                           changed
    darkbrown/www/managing_director_dashboard/index.py   changed  (now a redirect)
    darkbrown/www/managing_director_dashboard/index.html changed  (1759 lines -> 25)

Nothing is deleted, so the overlay applies cleanly with no `git rm` step.

No doctype, no custom field, no fixture. **No `bench migrate` needed for this
overlay** — nothing here touches the schema. (The migrate still pending for the
bank statement classification fields is a separate matter and unaffected.)

## Deploy

    git pull
    bench build
    bench clear-cache
    bench restart

## What was actually missing

The shell already carried a "Profit and loss" card and a "Balance sheet" card.
Both sat *below* the `if(c.state==='ok') return trialLive(...)` line inside
`ROUTES.trial`, so they were reachable only in the prototype, and both were
built from twenty hardcoded account codes (`4010`, `5010`, `1100`…) rather than
from the company's own chart. Live, `trialLive()` renders a trial balance and
stops. Anoop would have opened the books and found one statement out of three,
and the two he could see in a demo would have been keyed to a chart of accounts
that is not his.

There was no cash flow anywhere. The only thing carrying that name is the MD
dashboard's twelve-month forward projection (`api.charts` C1), which is a
forecast of expected tenant inflow against committed head-lease outflow. It is
not a statement and does not reconcile to the ledger.

## The three endpoints

All on `darkbrown.api.statements`, all `guard(MD, GM, ACC)`, all read-only.
ERPNext owns the ledger; this module runs queries over `GL Entry` and `Account`
and writes nothing.

    profit_and_loss(frm=None, to=None)
    balance_sheet(as_on=None)
    cash_flow(frm=None, to=None)

The default window is the fiscal year to date where the site has fiscal years,
and twelve months back where it does not.

## Four decisions Anoop should know about

**The balance sheet carries a line called "Profit for the unclosed period".**
It is not a plug. Every posting balances, so assets plus expenses equal
liabilities plus equity plus income; rearranged, assets equal liabilities plus
equity plus income less expense. That last term is the profit still sitting in
the trading accounts because no Period Closing Voucher has swept it into
retained earnings. Without the line the statement is out by exactly the year's
result. Once he runs a period close, the line goes to nil on its own and the
same amount appears in retained earnings — the statement still balances, which
is the test that it was right in the first place.

**The profit and loss excludes Period Closing Vouchers.** They are the sweep,
not trading. A window spanning a close would otherwise count that period twice.

**The cash flow is direct, not indirect.** ERPNext's own Cash Flow report is
indirect and reads a Cash Flow Mapper that this site has never configured, so
it would return a shape with nothing in it. This one takes every voucher that
moved a Cash or Bank account in the window, and allocates that voucher's net
cash across its other legs in proportion to their size. A transfer between two
bank accounts has no other legs and nets to nothing, so it correctly vanishes
rather than inflating both sides.

**Every bucket shows the accounts behind it.** Classification is deliberately
shallow: Equity is financing, the capitalised asset types (Fixed Asset,
Accumulated Depreciation, Capital Work in Progress) are investing, everything
else is operating. For a business that head-leases buildings and sublets units
that is very nearly all of it. Two accounts are the likely arguments — tenant
deposits held, and shareholder current accounts once Stage 2I lands. Both
currently read operating. Moving either is a change to the account's
`account_type` in ERPNext, not a change to this screen.

## Reconciliation is stated, not assumed

The balance sheet prints assets against liabilities plus equity and says
whether it balances. The cash flow prints opening plus the three buckets
against closing cash and says whether it reconciles. When either fails the
screen shows a red banner naming the amount rather than rendering as though
nothing is wrong. Closing cash on the cash flow is the same figure the balance
sheet shows for the Cash and Bank accounts; if those two disagree, one of them
is wrong and both will say so.

## One thing fixed on the way past

`roleCan()` let Documentation and Maintenance navigate to the books screens
(`coa`, `ledger`, `journal`, `trial`, `account`) even though every endpoint
behind them is `guard(MD, GM, ACC)` on the server. They got a SERVER ERROR card
rather than a locked door. A `BOOKS` list now gates those five plus the three
new screens to MD, GM and Accounts. The server was always the authority and is
unchanged; this only stops the nav from putting a door where there is no room.

## Verification run before delivery

- `compileall` clean across the app; all 53 JSON files parse.
- Guard audit: 120 whitelisted endpoints, 114 guarded directly, the 6 known
  deprecated shims delegating to the guarded `api.finance`.
- The real `statements.py` executed against a stubbed Frappe and a synthetic
  ledger — not a replica of the logic, the shipped module. Hand-computed
  expectations for all three statements matched to the riyal; the balance sheet
  balanced and the cash flow reconciled.
- Edge cases proven: a Period Closing Voucher (P&L unchanged, unclosed profit
  falls to nil, balance sheet still balances), an empty ledger (no crash, no
  divide-by-zero on margin), and role guards (MD/GM/ACC allowed, DOC/MNT
  blocked on all three).
- `node --check` on the shell script; jsdom sweep of the three screens driving
  the real `router()` — not `dispatchEvent`, which swallows a throwing route —
  across live payloads, loading, server error, empty ledger, deliberately
  unbalanced books, demo mode and all five roles.
- Full regression: all 46 nav routes x 2 modes x 5 roles, 460 renders, no
  throws, no `NaN`, no unresolved template literals.
- The retired dashboard exercised against the stub: guest to login with a
  bounce-back to `/darkbrown`, and MD, Accounts and Documentation all to
  `/darkbrown#/dash`. The page body carries no reference to `md_dashboard`,
  `api.charts`, `api.attention`, `get_all` or `get_overview`, and
  `api.attention` still imports for the shell seed.
- Rename verified by render, not by grep alone: the staff screen shows
  Anoop M., the journal screen carries no invented poster, and the string
  "Fatima N." appears nowhere in the shell.

## The second MD surface is closed

`www/managing_director_dashboard/` was a whole second MD dashboard reading
`md_dashboard.get_all`, `charts.*` and `attention.*`. The shell calls none of
those — it is driven by one `api.app.refresh` payload. Two surfaces computing
the same portfolio down two different code paths agree only by accident, and
the moment real records land they were going to disagree in front of Khayaz.

`auth.py` has sent every business role to `/darkbrown` since V2 and its comment
already claimed this page "has been removed". It had not been: the route still
resolved, so a bookmark or a browser-restored tab still opened it. The page is
now a redirect to `/darkbrown#/dash` — server-side, plus a meta-refresh and a
`location.replace` in the 25-line fallback body in case a cached response skips
the redirect. Guests go to the login page and bounce back to the shell rather
than to the old URL.

The Python is left in place on purpose. `api.attention` is live — `app._attention`
calls `get_attention` for the boot payload — and `api.md_dashboard` and
`api.charts` are read-only and harmless once unlinked. Deleting them is a
separate decision from closing the second door, and an overlay cannot delete
anyway.

## The invented posting user is gone

Journal detail rendered `j.by || 'Fatima N.'` in three places, so a voucher with
no recorded poster was attributed to a named person. That is the one thing this
codebase is most careful never to do. It now reads an em-dash.

The demo staff persona itself has been renamed: 22 occurrences of "Fatima N."
are now "Anoop M.", including the `STF-00001` record whose title is
"Accountant". The prototype already uses the real Documentation name (Aisha R.),
so an accountant persona under a different name was the exact confusion worth
removing. Two "Fatima" strings are deliberately left: the generated-tenant first
name pool in the shell, and the demo tenant "Fatima Zahra Bennani" in
`demo/dataset.py`. Neither implies an accountant. If you would rather the demo
persona kept a distinct fictional name, it is a single string replace to undo.

## Still open, unchanged by this overlay

Rent-free treatment is still Anoop's call. These statements read whatever the
ledger was posted on and will follow the decision either way; nothing here
restates anything.

The wider cutover blockers are untouched by this overlay: the unit inventory
reconciliation, the PDC sheet questions, the building-code rekeying and the
`bench migrate` pending for the bank statement classification fields.
