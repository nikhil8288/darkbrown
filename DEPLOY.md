# DEPLOY — cutover gate fixes (supersedes DEPLOY_residuals.md)

Overlay zip. Unzip over the repo root so the four paths below land in place,
commit, push, and let Frappe Cloud deploy. Nothing here touches the shell,
any doctype, or any figure.

    darkbrown/__init__.py                            version bump only
    darkbrown/api/cutover.py                         ledger-clean gate
    darkbrown/patches/load_portfolio_headlease.py    step 6 preflight gate
    verify/cutover_gate.py                           new — the harness

No deletions, so there is no DELETE_THESE.txt this time.

## Confirm it actually landed

`darkbrown.__version__` goes **2.0.0 → 2.0.1**. That is the whole point of the
bump — run the check before you run the load:

    bash check_darkbrown.sh <site>

If it still prints `darkbrown 2.0.0`, the deploy did not reach the server and
nothing below is on it. Do not run the load until it says 2.0.1.

---

## 1. Step 6 aborted on a site with nothing wrong with it

`load_portfolio_headlease.run` asked whether the preflight list was empty:

    if problems or not ok or pre:        # <- any entry at all

`_preflight` returned `(what, why)` pairs with no severity on them, and one of
those entries is the perpetual-inventory note — which describes itself, in its
own text, as a warning rather than a blocker. The line this loader builds uses
a service item (`_ledger_common.item` sets `is_stock_item = 0`), so no
warehouse is ever needed. On any company with perpetual inventory switched on,
`pre` was never empty, so step 6 aborted every time and the cost side of the
P&L never loaded — income with no cost of sales, a 100% margin on a business
whose whole point is the spread.

Entries are now `(severity, what, why)`, severity is `blocker` or `warning`,
and the gate filters:

    if problems or not ok or _blockers(pre):

The dry run prints the two groups under separate headings, so a warning still
gets read — it just no longer stops the load. `dry_run()` returns `blockers`
and `warnings` counts alongside the existing keys; `ok` now means "no blockers"
rather than "no entries".

### Also fixed here: preflight only ever checked one building

The loop ended in an unconditional `break`, so it validated the head lease and
landlord of the **first** building on the sheet and returned. `_head_lease`
throws, and `run` commits as it goes, so a head lease missing on the seventh
building surfaced as a traceback with six buildings already posted — the exact
failure preflight exists to get in front of. It now walks every building on
the sheet, deduplicated, and names each one that is missing something.

This is a slightly wider change than you asked for. I made it because without
it the severity fix would have let a load through that preflight had not
actually checked, which is worse than the abort it replaces. Revert just that
loop if you would rather keep the change minimal.

## 2. `run_load` refused the re-run it promises is safe

`cutover._ledger_state` decided whether the ledger was clean by looking for
`[AK12-HIST-INV-` and `[AK12-HL-INV-` in invoice remarks. Correct for the
pilot; wrong from the moment steps 5 and 6 were rewired to the portfolio
loaders, which write `DB-HIST-INV` and `DB-HL-INV`.

So after any partial portfolio load, every invoice the pack had just written
counted as foreign, `clean` went false, and `run_load` returned
`aborted: ledger not empty` — telling you to clear the ledger from the bench.
The sequencer's own promise ("each loader skips what already exists, so a
re-run after a failure is safe") could not be taken up. On a 1,782-row load
that is a bad trap to leave armed.

Tags are now read off the loaders (`INV_TAG`) rather than hardcoded, with the
literals as fallback if a loader is not on the server, and the AK12 pilot tags
still accepted so a site carrying AK-12 rows is not condemned by them.

## 3. Verify before you load

    python3 verify/cutover_gate.py        # 18 checks, expect 0 failed

It imports the real modules against `verify/stub_frappe.py` and drives them
with a real CSV at the path the shipped loader reads, so a pass means the
shipped file behaves — not a replica of it. Before/after on the same fixture:

    BEFORE  healthy site, perpetual inventory ON   preflight=[perpetual inventory]        aborts=True
    BEFORE  head lease missing on building 7       preflight=[perpetual inventory]        aborts=True
    AFTER   healthy site, perpetual inventory ON   preflight=[perpetual inventory]        aborts=False
    AFTER   head lease missing on building 7       preflight=[head lease, perpetual...]   aborts=True

Note the BEFORE rows: the old preflight never even noticed the missing head
lease. It aborted both times, for the same wrong reason.

Also still green after these changes: `python3 -m compileall darkbrown/`,
all 54 doctype JSONs parse, and `node verify/routes.js` — 25/25 role x seed
states, 0 broken routes.

---

## Still open — not in this zip

* **Journal entries are counted foreign wholesale.** `_ledger_state` adds
  every submitted Journal Entry to `foreign`. The opex journal you post to
  Historical Cutover Control is a Journal Entry, so loading opex first and
  re-running cutover will still abort. Left alone deliberately: I do not know
  whether you want that one tagged and exempted, or whether opex is always
  meant to land after the cutover. Say which and it is a small change.

* **The count discrepancy is untouched.** 1,782 expected vs 1,773 invoices /
  1,741 receipts is in the step 5 data, not in these gates. Nothing here will
  move those numbers.

* **135 assumed payment dates** still print their warning. Unchanged — the
  P&L is right either way, the cash flow is not right until the cheque book
  lands.
