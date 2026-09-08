# DarkBrown fix pack — Anoop's trial balance review + MD dashboard

Unzip over the repo root. Commit, push, let Frappe Cloud deploy, then run the
commands below in order.

Built against `1736aac`. Note that is not `58a792f` — check that is the commit
you expect to be live.

---

## What is in here

| File | Fixes |
|---|---|
| `darkbrown/patches/portfolio_history.csv` | Point 1 — advance and prior-due receipts |
| `darkbrown/patches/load_portfolio_history.py` | Point 1 — control total |
| `darkbrown/patches/reclass_cutover_credits.py` | Point 2 — expense credit leg |
| `darkbrown/patches/reclass_pl_groups.py` | Points 3, 4, 5 — P&L classification |
| `darkbrown/patches/tenancy_exceptions.csv` | The 65 tenancies with no live agreement |
| `darkbrown/patches/check_head_leases.py` | The "31 Jul 27" lease-end problem |

---

## Deploy order

Each step is `dry_run` first. Read the output. Only then `run`.

### 1 — Receipts (point 1)

```
bench --site erp.darkbrown.qa execute darkbrown.patches.load_portfolio_history.dry_run
```

Must print rent 5,306,783.00 and collected 5,182,581.00. If it prints
4,838,469.00 the old CSV is still on the server — the deploy did not land.

Because the history is already loaded, the receipts have to be rebuilt, not
topped up. Reverse the existing `AK12-HIST-` receipts before re-running, or
the 344,112 lands twice.

### 2 — Expense credits (point 2)

```
bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_cutover_credits.dry_run
bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_cutover_credits.run
```

If `dry_run` reports zero rows, the tags in `TAGS` do not match what actually
posted the expenses. Open one of those journals, read its `user_remark`, add
the marker. Zero rows means the search missed, not that the books are clean.

### 3 — P&L classification (points 3, 4, 5)

```
bench --site erp.darkbrown.qa execute darkbrown.utils.chart_of_accounts.ensure_chart
bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_pl_groups.dry_run
bench --site erp.darkbrown.qa execute darkbrown.patches.reclass_pl_groups.run
```

**Keep the `dry_run` output.** It prints each account's current parent, which
is the only record of how to reverse this.

### 4 — Head leases

```
bench --site erp.darkbrown.qa execute darkbrown.patches.check_head_leases.report
```

Reports only. See "Cannot be fixed from data I have" below.

### 5

```
bench --site erp.darkbrown.qa migrate
```

Then re-run `load_portfolio_history.dry_run` and confirm 124,202 outstanding.

---

## Decisions the code could not make

**Point 1 was a CSV defect, not a loader defect.** `load_portfolio_history`
already documents `collected = Received + Advance − Previous Due Rcvd`. The
CSV was generated with `Received` alone. 153 of 1,780 rows amended; no row now
has `collected` exceeding `rent`, so nothing over-allocates. Lands exactly on
Anoop's 124,202.

**Point 2 does not name the wrong account.** It finds credit legs on
historical vouchers and moves whatever it finds. A hardcoded source would miss
any voucher that used a different one. It posts a correcting journal rather
than editing submitted GL entries — both legs are balance sheet, so the P&L
does not move.

**Points 3–5 needed no chart change.** `chart_of_accounts.HEADS` already puts
Building Maintenance, Commission on Sales, Marketing Expenses and Key Money -
Other in Cost of Sales, and Salary in Staff Cost. `ensure_chart()` deliberately
refuses to reparent existing accounts on an unattended migrate, so it recorded
them as misplaced and left them under Other Expense. `reclass_pl_groups` is
the attended half. Reparenting moves the whole history with the account; no
journal is written.

`ALIASES` maps Owner Rent → Head Lease Rent, plus the workbook's
"Building Maintanance" spelling. If Anoop's account names differ, add to
that dict rather than renaming accounts on the site.

---

## Cannot be fixed from data I have

**Head lease dates.** Nothing in the repo or in any file you have sent carries
a head lease start or end date. The Tenancy Master is tenant agreements. All 22
buildings reading 31 Jul 2027 is a placeholder somebody typed once, and it
drives the 90-day renewal alert (`api/number_cards.py:81`) and the buildings
screen expiry filter. These have to be entered from the signed head lease
contracts.

Separately: `buildings_payload.json` has no `head_lease` block, and
`portfolio.onboard_building` only creates a Head Lease when `annual_rent` and
`start_date` are both present. So the loaders in this repo create none, and
rebuilding the site from the repo would produce a portfolio with no head
leases at all. Add the block when you enter the real dates.

**The 65 exceptions.** `tenancy_exceptions.csv` — 63 tenancies lapsed on or
before 8 Sep 2026 with no renewal anywhere in Tenancy Master v28, plus 2 live
tenancies with no agreement on file. QAR 206,300 of monthly rent. I have not
guessed at renewals: I checked all 220 master agreements against the 63 lapsed
and found zero live renewals, so these have genuinely ended or the renewals
were never documented. That is Anoop's call, not the loader's.

This is what is really behind AK-12 showing 3,000 and OG-48 showing zero. Both
are correct as displayed. AK-12 has 7 tenancies of which 6 ended by 31 Jul;
OG-48's 18 all ended the same day.

**Building codes in the master are wrong for 15 rows.** Every agreement
referenced `DB/DAF39/...` is labelled `TWR-16` in the Building Code column, and
TWR-39 has no rows at all. Corrected via the contract reference when building
the exceptions list, and the correction is self-validating: after it, all 219
matched tenancies agree with the master on both end date and rent, with zero
discrepancies. Before it, 10 rows disagreed. Worth fixing in the source
workbook so v29 does not carry it forward. Two TWR-19 rows carry DAF16
references and have the same problem.

---

## Not touched

- The QAR 401,796 building-basis split still parked on Overhead. Separate
  item from point 5's 208,608 — do not conflate them.
- Row-level building restriction for managers.
- Anoop's Head Lease permission fix.
