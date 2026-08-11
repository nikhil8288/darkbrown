# Batch 5 — portfolio, operations, documents and finance wired

Supersedes every earlier overlay. Copy the contents of the zip over the repo
root in GitHub Desktop, commit, push. Frappe Cloud redeploys on push.

**`bench migrate` is required.** Bank Statement Line gains classification
fields and three doctypes have a Select-options fix. Nothing else in this
batch touches data.

`DELETE_THESE.txt` is unchanged from batch 4 and is not in this zip — if you
have not run those two `git rm` lines yet, they still apply.

---

## What was not wired, and now is

| Screen | Was | Now reads |
|---|---|---|
| Chart of accounts | prototype's 20 fixed accounts | `Account` + `GL Entry` |
| General ledger | invented postings | `GL Entry`, windowed |
| Journal entries | invented postings | `GL Entry` grouped by voucher |
| Trial balance | sums of the inventions | server sum as at a date |
| Account detail | invented postings | `GL Entry` for that account |
| Vault | a generated file list | `Document Register` + `Document Archive` |
| Receipts | an array the browser filled | `Payment Entry` |
| Receipt detail | "not wired" | `Payment Entry` + its allocations |
| Utilities | `units × 420` and `units × 350` | `Utility Bill` + allocations |
| Reconciliation | a fixed 148 / 139 / 9 | `Bank Statement Import` + lines |

Portfolio had no unwired screens. Its two dead drill-throughs are fixed:
the arrears alert now opens Cases and the loss-making-building alert opens
Buildings — both previously pointed at routes that do not exist.

## New endpoints (12, all guarded)

    accounting.books              MD, GM, Accounts
    accounting.voucher            MD, GM, Accounts
    accounting.trial_balance      MD, GM, Accounts
    utilities.overview            all five roles
    utilities.bills               all five roles
    utilities.meters              all five roles
    documents.vault               MD, GM, Accounts, Documentation
    documents.preview             MD, GM, Accounts, Documentation
    finance.receipts              MD, GM, Accounts
    finance.receipt               MD, GM, Accounts
    cashdesk.reconciliation       MD, Accounts
    cashdesk.classify_line        MD, Accounts

## How the heavy screens load

None of these is on the morning path, so none is in the boot payload — a
login should not pay for the ledger. They fetch the first time their screen
is opened and are held until a write invalidates them. Three states are kept
distinct: reading, server error, and empty. A call that raised is not a clean
book, which is the same rule the dashboard gate already follows.

## Decisions taken

**D81 — `classify_line` tags, it does not post.** You did not answer the
question, so this is the default and it is reversible. Tagging a bank line as
a shareholder drawing takes it out of the operating outflow immediately and
writes nothing to the ledger. The prototype's D68 text says the owner current
account entry is written in the same save; that cannot be honoured yet,
because the posting account is Q21 and the owners module is Stage 2I. An
entry against an account nobody has agreed is a guess in the ledger, which is
the one place a guess must not go. The classification is durable, so the
posting run reads it once Q21 is settled. **If you want the posting in the
same save instead, that is a small change once Q21 is answered.**

**D82 — recovered means invoiced.** On Utilities, an allocation line counts
as recovered only when it carries a Sales Invoice. An allocation worked out
and never billed is the gap the screen exists to show, so it counts as
unrecovered.

**D83 — no reserve floor on the reconciliation screen.** The denominator is
Q11. What is shown instead is the classified equity value that is out of the
cost base, which is the input the floor needs.

## Defects found on the way

- `cashdesk.unmatched_summary` divided its value by 1,000, so the Command
  Centre's unmatched panel printed thousandths of a riyal under a QAR label.
  Against the whole-riyal rule. Fixed, and the three `k()` calls on the
  receipts screen with it.
- Three doctype JSONs carried a literal backslash-n instead of a newline in
  their Select options — `Bank Statement Line` (direction, status),
  `Bank Statement Import` (status), `Weekly Closing` (status). Each rendered
  as one option in the desk. The API writes straight to the DB so nothing
  broke in the app, but any validation against options would reject good
  values. Fixed in all three; this is why migrate is needed.
- `fdate()` assumed a Date. The server sends ISO strings, so the vault's age
  filter compared `NaN` and silently passed every row. Both now coerce.
- `acc()` returned `undefined` for a code outside the chart and the ledger
  threw on render. Real charts get renumbered; it returns a placeholder now.

## Verification run before packaging

- `python3 -m compileall` over `darkbrown/` — clean
- 53 JSON files parsed; zero literal-backslash-n options remaining
- stubbed-Frappe harness importing the shipped modules: 106 whitelisted
  endpoints, 0 without a `guard()` call; role matrix printed above verified
  by execution, not by reading
- jsdom sweep of all 69 routes in three modes (demo, live-empty,
  live-populated): 0 threw, 0 rendered blank
- jsdom sweep with stubbed server payloads: all 10 rewired screens plus the
  receipt detail route render from server data, none falls back to NOT WIRED

## After deploying

1. `bench migrate`.
2. Open **Reconciliation**. With no import it says so. Import a real QNB or
   Doha Bank statement — this has never been run against a real one and it is
   a go-live gate.
3. Open **Chart of accounts**. If the trial balance says the ledger does not
   balance, that is an ERPNext question before it is a Darkbrown one.
4. Open **Utilities**. It will be empty until a Utility Bill is entered.
   Empty is honest; the old screen's figures were not.
