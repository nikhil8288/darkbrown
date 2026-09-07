# DEPLOY — complete build 2.0.1

This is the whole repo, not an overlay. Replace your working copy's contents
with it (keep your `.git`), commit, push.

Diff against `5a09442`, the last commit that built successfully:

    pyproject.toml                                   version 2.0.0 -> 2.0.1
    darkbrown/__init__.py                            version 2.0.0 -> 2.0.1
    darkbrown/api/cutover.py                         ledger-clean gate
    darkbrown/patches/load_portfolio_headlease.py    step 6 preflight gate
    verify/cutover_gate.py                           new — the harness
    DEPLOY.md                                        this file

Four source files. No doctype, no shell, no hooks, no figure is touched. No
deletions, so no DELETE_THESE.txt.

## Read this before you deploy

**This build does not fix the pre-build validation failure, because I still do
not know what that failure is.** What it fixes is the version inconsistency I
introduced in `ab5cc20` — `pyproject.toml` said 2.0.0 while `__init__.py` said
2.0.1 — plus the three cutover bugs the previous zip carried.

Frappe Cloud's pre-build validation reads `requires-python` from
`pyproject.toml`, the node engine from `package.json`, and `required_apps`
from `hooks.py`. This build changes none of those, exactly as `ab5cc20`
changed none of them. If those three inputs are what the validator rejected,
this build will fail the same way.

### Isolate it first — two minutes, and it answers the question

Redeploy `5a09442` from the Deploys screen. That commit built and shipped
before.

* **`5a09442` fails too** — the bench changed, not the app. Look at the
  Dependencies tab (Python and Node versions against `requires-python =
  ">=3.10"`) and at the pending bench update behind the "Update Available"
  badge. Nothing in this zip will help and pushing it again wastes a cycle.
* **`5a09442` builds** — it is something in my commit, and the Issues tab text
  will name which input it objected to. Send it and I will fix the actual
  thing.

## Confirm the deploy landed

`darkbrown.__version__` and the wheel metadata now both read **2.0.1**:

    bash check_darkbrown.sh <site>

Still 2.0.0 means the deploy did not reach the server. If you would rather not
rely on the version, this works regardless:

    grep -c "_pack_tags" apps/darkbrown/darkbrown/api/cutover.py
    grep -c "BLOCKER" apps/darkbrown/darkbrown/patches/load_portfolio_headlease.py

Expect 2 and 7.

---

## The three fixes

### 1. Step 6 aborted on a site with nothing wrong with it

`load_portfolio_headlease.run` asked whether the preflight list was empty:

    if problems or not ok or pre:        # <- any entry at all

`_preflight` returned `(what, why)` pairs with no severity, and one entry is
the perpetual-inventory note — which describes itself, in its own text, as a
warning rather than a blocker. The line this loader builds uses a service item
(`_ledger_common.item` sets `is_stock_item = 0`), so no warehouse is ever
needed. On any company with perpetual inventory on, `pre` was never empty, so
step 6 aborted every time and the cost side of the P&L never loaded — income
with no cost of sales, a 100% margin on a business whose whole point is the
spread.

Entries are now `(severity, what, why)` and the gate filters:

    if problems or not ok or _blockers(pre):

The dry run prints blockers and warnings under separate headings, so a warning
still gets read. `dry_run()` returns `blockers` and `warnings` counts; `ok` now
means "no blockers" rather than "no entries".

### 2. Preflight only ever checked one building

The loop ended in an unconditional `break`, so it validated the first
building's head lease and landlord and returned. `_head_lease` throws and `run`
commits as it goes, so a head lease missing on the seventh building surfaced
as a traceback with six already posted — the exact failure preflight exists to
prevent. It now walks every building on the sheet, deduplicated, naming each
one that is missing something.

Wider than you asked for. Without it the severity fix would let a load through
that preflight had not actually checked, which is worse than the abort it
replaces. Revert just the loop if you want it minimal.

### 3. `run_load` refused the re-run it promises is safe

`cutover._ledger_state` looked for `[AK12-HIST-INV-` and `[AK12-HL-INV-` in
invoice remarks. Correct for the pilot, wrong once steps 5 and 6 were rewired
to the portfolio loaders, which write `DB-HIST-INV` and `DB-HL-INV`. Every
invoice the pack had just written counted as foreign, `clean` went false, and
`run_load` returned `aborted: ledger not empty`. Tags are now read off the
loaders' `INV_TAG` with the literals as fallback, and the AK12 pilot tags are
still accepted.

## Verify before you load

    python3 verify/cutover_gate.py        # 18 checks, expect 0 failed

It imports the real modules against `verify/stub_frappe.py` and drives them
with a real CSV at the path the shipped loader reads, so a pass means the
shipped file behaves. Before and after on the same fixture:

    BEFORE  healthy site, perpetual ON      preflight=[perpetual inventory]     aborts=True
    BEFORE  head lease missing on bldg 7    preflight=[perpetual inventory]     aborts=True
    AFTER   healthy site, perpetual ON      preflight=[perpetual inventory]     aborts=False
    AFTER   head lease missing on bldg 7    preflight=[head lease, perpetual]   aborts=True

The BEFORE rows are the point: the old preflight never noticed the missing
head lease. It aborted both times for the same wrong reason.

Also green on this build: `python3 -m compileall darkbrown/`, all 54 doctype
JSONs parse, `flit_core` produces `darkbrown-2.0.1.dist-info`, and
`node verify/routes.js` — 25/25 role x seed states, 0 broken routes.

## Still open — deliberately not in this build

* **Journal entries count as foreign wholesale.** `_ledger_state` adds every
  submitted Journal Entry to `foreign`. Your opex journal to Historical
  Cutover Control is a Journal Entry, so loading opex first and re-running
  cutover will still abort. I do not know whether you want that one tagged and
  exempted or whether opex always lands after the cutover. Say which.

* **The 1,782 vs 1,773 / 1,741 count discrepancy** is in the step 5 data, not
  in these gates. Nothing here moves those numbers.

* **135 assumed payment dates** still print their warning. The P&L is right
  either way; the cash flow is not until the cheque book lands.
