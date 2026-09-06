# DEPLOY — vacancy rename, filterable stat boxes, expense chart and allocation

Repo-root overlay. Unzip over a clean checkout of `main`, commit, push, deploy.
Eleven files, three of them new. This zip supersedes every prior one.

Nothing here deletes a file, so there is no `DELETE_THESE.txt` this time.

```
darkbrown/install.py                                        changed
darkbrown/api/app.py                                        changed
darkbrown/api/reports.py                                    changed
darkbrown/api/statements.py                                 changed
darkbrown/api/expenses.py                                   NEW
darkbrown/utils/chart_of_accounts.py                        NEW
darkbrown/utils/allocation.py                               NEW
darkbrown/darkbrown/doctype/expense_entry/__init__.py       NEW
darkbrown/darkbrown/doctype/expense_entry/expense_entry.json NEW
darkbrown/darkbrown/doctype/expense_entry/expense_entry.py  NEW
darkbrown/shell/index.html                                  changed
```

## Order of operations

1. Deploy the zip.
2. `bench --site darkbrown.u.frappe.cloud migrate`
3. Open **Expenses** in the nav and press **Record an expense**. If the head
   dropdown has entries, the chart built. If it says no head exists yet, the
   migrate did not run.

Step 2 is not optional. The DocType and the chart both land on migrate, and
until it runs the Expenses screen has nothing to offer. The form says so in
plain words rather than showing an empty dropdown.

## Verify before trusting it

Run these from a shell in the app directory. Both are self-contained.

- Route sweep (jsdom): 74 routes, all five periods on all eight accounts
  screens, every filter combination, and a check that no user-facing "void"
  survives anywhere.
- Allocation and chart tests (stubbed Frappe, against the shipped modules):
  35 unique heads, 2,000 random splits tying back exactly, live-building date
  logic, and the P&L grouping arithmetic.

Both were clean when this zip was cut.

---

## 1. Void is now Vacant

Display only. `Unit.status` already stored `Vacant`; it was `api/app.py`'s
`UNIT_STATE` map that turned it into "Void" on the way to the screen. No data
migration, no field change, nothing to backfill.

Renamed: the status chip, "Void days" → "Vacant days" everywhere it appears,
"Void pipeline" → "Vacancy pipeline", "Rent lost to voids" → "Rent lost to
vacancy", the Occupancy report title, and the portfolio-plan section.

**Left alone on purpose:** the cheque action "Cancel — void it, never
presented". That is a different word meaning a different thing.

Wire keys are untouched, as agreed — `vd`, `voids`, `_void_days` and the DOM
ids still read `void`. Renaming those means changing the API and the shell in
lockstep for nothing the user can see.

## 2. The stat boxes filter

Clicking a box filters the table beneath it and highlights the box. Clicking
it again clears. The filter is written into the hash — `#/units?st=Vacant` —
which is what makes it survive a refresh; the URL does not change when you
reload, so neither does the filter. The back button now steps through filters
too, and the URL can be sent to someone else.

| Screen | Filters | Left inert |
|---|---|---|
| Buildings | Buildings (all), Expiring in 90 days | Units, Landlords, Head-lease cost |
| Units | Total, Occupied, Vacant, On notice | — |
| Tenants | Tenants (all), Current, Late, In arrears | — |
| Landlords | Landlords (all), No identity on file, No bank account | Buildings covered |
| Agreements | Agreements (all), Active, Expiring in 60 days, Expired | Annual value |

A filtered table shows a chip saying what is being hidden, and its footer
reads "6 of 305 units" rather than "6 units". A table that is filtered without
saying so reads as a smaller portfolio.

## 3. The expense chart

Thirty-five heads, built from the mapping workbook, under five P&L groups.
Created on migrate, idempotent, safe to re-run.

| Group | Heads | Basis |
|---|---|---|
| Cost of Sales | 10 | all Building |
| Staff Cost | 7 | 5 Common, 2 Building (Salary Watchmen, Temporary Staff) |
| Operating Expenses | 14 | all Common |
| Depreciation and Amortisation | 2 | all Common |
| Bank and Finance Charges | 2 | all Common |

**Four places the workbook could not decide for itself.** Each is a one-line
rename in `utils/chart_of_accounts.py` if you disagree.

1. **SHARAF-PERSONAL EXPENSES** mapped to "Marketing Expenses", which is also
   where ADVERTISEMENT goes — but one is Common/OPEX and the other is
   Building/COGS. One account cannot be both, so it has its own head, "Sharaf
   Personal Expenses". Rename it to whatever it should actually be called.
2. **SHARAF-CAPITAL PRE-OPERATIVE EXP** → "Administrative Expenses", in the
   Depreciation group because that is what the sheet said. The name reads
   oddly there, but it is pre-operative spend being written off, so the group
   is right even if the label is not.
3. **BANK CHARGES** now sits in the Bank Charges group rather than OPEX. The
   sheet said OPEX, but you created a Bank Charges group and put the insurance
   in it; leaving the account literally called Bank Charges outside it made no
   sense.
4. **The group is named "Bank and Finance Charges"**, not "Bank Charges". An
   ERPNext account name is unique per company and your chart already has a
   *leaf* called Bank Charges. A group and a leaf sharing a name means the
   leaf silently resolves to the group, the chart builds without complaint,
   the entry screen offers the head, and ERPNext refuses the posting only at
   submit — after the accountant has keyed it. The statement prints the label
   "Bank charges", so nothing user-facing changes. `_ensure_account` now
   refuses to build at all rather than ship that failure mode again.

Also applied, per your answers: Other Maintenance moved to OPEX and made
Common and renamed off "Building Maintenance"; Food and Office expenses stay
as one account, "Utility Expenses"; Transportation-Waste stays building-
specific under Building Maintenance; Key Money is COGS on a building; the
misspelt heads are corrected to "Maintenance".

## 4. How the common cost divides

A building cost posts to that building's cost centre. A common cost posts to
the **Overhead** cost centre and stays there — the ledger says what actually
happened and no synthetic journal is written.

The split happens in the reporting layer, month by month:

- **Who shares:** buildings that are Active or on Notice Period. Where the
  dates are recorded, a building must also have been handed over before the
  month ended and not exited before it began — so a building that opened in
  May does not carry March's salary.
- **Weight:** the monthly rent on the head lease covering that month.
- **Rounding:** whole riyals, largest-remainder. Every share is an integer and
  the shares add back to the pool exactly. The odd riyal goes to whichever
  buildings were rounded down hardest rather than to nobody, which is how a
  reconciliation starts failing for a reason no one can find.
- **Nobody live that month:** the cost stays on Overhead, is reported as
  unallocated, and is named on the Expenses screen rather than quietly dropped.

The per-building P&L pack now carries **Direct cost** and **Allocated
overhead** as separate columns, and margin is net of both. Every building's
margin moves — that is the point, and it was your call.

## 5. Recording an expense

New **Expenses** entry in the Finance nav. Accounts, GM and MD only, matching
`guard(MD, GM, ACC)` on the server.

The head is the only choice that matters. Everything downstream falls out of
it: the cost centre, whether a building is even asked for, whether the cost
reaches one building's margin or all of them. The form reads the basis back
off the chart and shows it *before* the save. Someone keying a salary cannot
pin it to one building; someone keying a lift repair cannot leave it
unattributed.

Settled by **Bank**, **Cash** or **Unpaid**. Unpaid credits the supplier's
payable account, so the cost lands in the right month whether or not the money
has moved. **Petty cash is deliberately absent** — the float has its own
screen and keying it in both places would double the spend.

Saving submits the Expense Entry, which posts a Journal Entry. Cancelling the
entry cancels the journal. The record exists rather than the screen posting a
journal directly because a journal is two account codes and cannot answer what
gets asked later: which building, whose bill, where the receipt is, who keyed
it.

The screen's second card shows how the common pool actually divided, per
building. Someone will ask why their building is carrying nine thousand of
salary, and the answer needs to be on the screen.

## 6. The P&L has a gross margin

It was income, then every expense account in one flat list — a ledger dump. It
could not say whether a bad month was the leases or the office, and in a
sublease business those are different problems with different fixes.

Now: Revenue, Cost of sales, **Gross margin**, then Staff cost, Operating,
Depreciation, Bank charges, Net result. Gross margin is the arbitrage spread
before anyone is paid to run the business.

An expense account sitting under none of the five groups — the head-lease
loaders create theirs under Direct Expenses — lands in a final "Other
expenses" section rather than vanishing. That is the only behaviour that keeps
the statement adding up.

The shell falls back to the old flat shape if the server has not been updated,
so an out-of-step deploy prints a plainer statement rather than a stack trace.

## 7. Period filters on the Accounts screens

The same five buttons as the Command Centre, on Chart of Accounts, General
Ledger, Journal Entries, Trial Balance, P&L, Balance Sheet, Cash Flow and
Expenses.

The two month buttons follow the **current and previous month** off the real
calendar rather than a fixed Jul/Jun pair. Quarter and YTD follow the
January–December fiscal year. Lifetime is everything posted.

Every window **ends today at the latest**. A balance sheet headed "as at 30
September" on the seventh of September is not off by a rounding — it is a
different statement from the one anybody asked for.

Balance Sheet and Chart of Accounts are point-in-time, so they read the
period's end date rather than a window. The choice rides in the hash like the
list filters, so it survives a reload.

---

## Known and deliberate

- **The loaders still write to the old chart.** `opex_journal.csv` and
  `load_portfolio_history.py` post to "Head Lease Rent" on the Historical
  Cutover Control and know nothing about the five groups or the Overhead
  centre. You said data is a separate pass, so they are untouched. Anything
  loaded before they are rewired lands in the old shape.
- **`Head Lease Rent` may already exist under Direct Expenses.** The chart
  builder does not move an account that has postings against it — reparenting
  something with a ledger history is a decision for a person, not for an
  unattended migrate. `ensure_chart()` returns a `misplaced` list naming any
  such account so the move is deliberate. Until it moves, it prints under
  "Other expenses" rather than Cost of sales.
- **Depreciation is Common** until there is an asset register that can say
  which building an asset sits in.
- **The demo shell has no expenses.** The Expenses screen says LIVE ONLY
  rather than inventing a cost base, because a made-up cost base would flatter
  or damn every building's margin on nothing.
