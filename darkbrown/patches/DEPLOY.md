# AK-12 clean rebuild — revision 10

Empty the site, load one building with its 8 units, 9 tenants (7 current,
2 former), 11 agreements and nine months of real invoices and receipts, then
prove the result. One module runs it all: `darkbrown/patches/ak12_rebuild.py`.

---

## Do this first

Purging from inside the ERP will never work, however many times the repo is
updated. That button goes through ERPNext's document layer, and these eight
invoices are orphaned — their supplier was deleted by an earlier purge, so
cancelling them raises an exception and every purge catches it and moves on.
Deploying new code does not change what that button does.

The wipe has to run outside the document layer. There are two ways, and the
first needs no command line:

### Route 1 — deploy, and it clears itself (recommended)

Unzip this pack, commit, push, then update the site in Frappe Cloud exactly
the way you already have been. Frappe runs `bench migrate` as part of that,
and `darkbrown.patches.wipe_ledger_once` is now registered in `patches.txt`,
so it runs automatically during the deploy and clears the ledger by direct
table delete. In the deploy log you will see:

```
  [wipe_ledger_once] no buildings, 16 GL rows: clearing the stale cutover ledger.
  removed       8  Purchase Invoice
  removed      16  GL Entry
  GL Entry rows remaining: 0
  [wipe_ledger_once] done - the ledger is empty.
```

Then load, from the Data screen (Load for real) or the bench.

It is guarded twice, so it cannot ever hurt you later: it refuses if the site
has **any** Building record, and refuses if the pack's own rent invoices are
posted. The moment AK-12 loads, Building becomes 1 and the patch is inert
forever — verified, including with the Patch Log ignored. Frappe also records
it so it does not run twice in the first place.

### Route 2 — if you have a shell

```
bench --site erp.darkbrown.qa execute darkbrown.patches.wipe_ledger.preview
bench --site erp.darkbrown.qa execute darkbrown.patches.wipe_ledger.run
```

`preview` changes nothing. Or paste `WIPE_CONSOLE.txt` into
`bench --site erp.darkbrown.qa console`, which uses no DarkBrown code at all
and therefore works even if a deploy never landed.

### Why direct deletes

`frappe.db.delete` issues a DELETE against the table. Nothing is validated, no
link is re-read, no controller runs. An orphan is just a row. That is blunt,
and it is right only because this is a cutover site with nothing worth
preserving — everything it should hold is in the CSVs beside this file. Do not
reuse it after go-live.

**What survives:** Company, chart of accounts, cost centres, fiscal years,
items, users, roles, DBR Settings, Document Requirements, Staff Members.
Customers and Suppliers go only if they carry the DarkBrown tenant/landlord
flag.

Verified against a reproduction of your exact site — 8 purchase invoices,
182,000, supplier already deleted so nothing will cancel. The patch clears it
during migrate, a second migrate does nothing, the load then produces income
256,400, cost 162,000, net 94,400, balance sheet balanced, cash flow
reconciled, and running the patch again after that refuses.

---

## The console route in detail

Three rounds of fixing the purge have all failed the same way, and the reason
is that they were all fixes to the same wrong idea: that a document can be
removed by asking ERPNext to remove it. It cannot, once it is orphaned.
Cancelling a Purchase Invoice re-reads its supplier to build the GL reversal.
An earlier purge deleted that supplier. So cancel raises, the purge catches
the exception and moves on, and the invoice stays. Better catching does not
help. Neither does another deploy — and the deploy has been the least
reliable link in this whole chain.

So: **stop asking ERPNext.** Delete the rows.

```
bench --site erp.darkbrown.qa console
```

Paste the whole of `darkbrown/patches/WIPE_CONSOLE.txt`. It uses no DarkBrown
code, so it works whether or not any of my previous packs ever reached the
server. `frappe.db.delete` issues a DELETE against the table: nothing is
validated, no link is re-read, no controller runs. An orphan is just a row.

It prints what it will remove, removes it, then re-counts. The last line must
read:

```
  GL Entry rows remaining: 0
```

Then load, which does need the pack on the server:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.check
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.load
```

`check` will tell you plainly whether the files are there. If it says `OLD` or
`MISSING`, the deploy is the problem and always was — but the ledger will
already be clean by then, which is the part that has been stuck.

If you'd rather not paste into a console, the same code ships as a module:
`bench --site erp.darkbrown.qa execute darkbrown.patches.wipe_ledger.run`
(and `.preview` first, which changes nothing). That route does need the deploy.

**What survives:** Company, chart of accounts, cost centres, fiscal years,
items, users, roles, DBR Settings, Document Requirements, Staff Members.
Transactions do not survive, and Customers and Suppliers go only if they carry
the DarkBrown tenant/landlord flag. This is the right tool only because the
site is a cutover site with nothing worth preserving — everything it should
hold is in the CSVs beside it. Do not reach for it on a live ledger.

Verified against a reproduction of your exact site — 8 purchase invoices,
182,000, supplier already deleted so nothing will cancel. The pasted file
takes the GL to zero, and the load then produces income 256,400, cost 162,000,
net 94,400, balance sheet balanced, cash flow reconciled.

---

## What revision 8 fixed

You purged and 182,000 stayed on the books: eight landlord purchase invoices,
Landlord Rent 182,000 Dr, Creditors 182,000 Cr, on a site with no buildings and
no units. That is the same bug as revision 7 found, one layer deeper.

Revision 7 added Purchase Invoice to the purge. That was necessary and not
sufficient, because those eight are now **orphans**: the purge deleted the
supplier they were written against, and cancelling an invoice re-reads its
supplier to build the GL reversal. So the cancel throws, the purge catches the
exception, prints a line, and moves on — leaving the invoice and its ledger
rows in place. A purge that reports success and leaves 182,000 behind.

`reset` now has a fourth step. After the purge it counts live GL entries, and
for anything still posting it tries the correct cancel-then-delete path first;
only if that raises does it mark the voucher cancelled and delete its GL and
Payment Ledger rows directly. Each forced removal prints the voucher and the
reason it would not cancel, so nothing disappears quietly. That blunt path
exists only inside `reset`, where the whole ledger is going anyway.

Then `reset` re-counts and refuses to say "site is empty" unless the count is
zero. Verified against a reproduction of your exact site: 8 invoices, 182,000,
supplier already deleted — old purge leaves all 8, revision 8 forces all 8,
GL to zero, load produces the correct statements.

Your sequence from here is unchanged:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_doctor.run
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.rebuild \
    --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
```

Expect to see `cancelled 0, forced 8, stuck 0` in the reset step, then
`GL Entry (live) 0`. If any line says `stuck`, send it to me — that is a
voucher that defeated both paths and I would want to see why.

---

## What revision 7 fixed

The revision-6 load ran but the site was never reset, so the general ledger is
three eras stacked on top of each other. Your screenshot is the proof, and the
figures on it are all explainable:

| What the GL showed | Where it came from |
|---|---|
| 256,400 in **Temporary Opening**, income 0 | the 69 **revision-5** rent invoices, still `is_opening = Yes` |
| **Landlord Rent 401,000**, Creditors 401,000, 17 purchase invoices dated 18-Jul-26, all "No Remarks" | the abandoned **portfolio-wide** landlord run — one invoice per building, from before this pack |
| 155 journals | 69 + 69 (revision 5) + 17 (legacy). None of revision 6's own vouchers are on there at all |

I reproduced that exact ledger — 913,200 debits, 913,200 credits, every account
matching — and confirmed two faults, both mine:

**1. `load` did not check the ledger before running.** The loaders are
idempotent by design: every rent invoice carries `[AK12-HIST-INV-nnn]`, so when
revision 6 ran onto a site that still had the revision-5 invoices, it found all
69 tags present and skipped all 69. It reported success and changed nothing.
`check` looks at files and site settings; it never looked at the GL. `verify`
would have caught it, but the Data screen button doesn't call `verify`.

Now `load` reads the ledger first and refuses when it finds vouchers this pack
did not write, naming each kind. So does the Data screen button. A ledger made
*only* of this pack's own vouchers is treated as a half-finished load and
resumed instead — a crash partway through is still recoverable.

**2. The purge never covered Purchase Invoice.** `demo/purge.py` swept Payment
Entry, Journal Entry and Sales Invoice. That omission was invisible while
nothing in the app posted a purchase invoice — revision 6 made it post them,
and I did not extend the purge to match. Those 17 legacy landlord invoices
would have survived a "successful" reset and put their whole 401,000 back on
the P&L. Fixed, and `reset` now finishes by counting live GL entries and
refusing to report success while a single one remains.

**Also new: `ak12_doctor.py`.** Read-only, creates and changes nothing. It
reads every voucher, sorts it into revision 6 / revision 5 / legacy, and says
in plain terms what is wrong. Run it any time a screen shows a number you don't
believe, and send me the output rather than a screenshot:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_doctor.run
```

On your current site it will print, among other things:

```
  1. Temporary Opening holds 256,400.00. That is revision-5 opening invoices;
     income reads zero until they are gone.
  2. 69 rent invoices are revision-5 opening entries. Revision 6 will SKIP them
     (their tag already exists), so loading again fixes nothing.
  3. 17 landlord invoices totalling 401,000.00 are NOT from this pack.
  4. There are landlord invoices and no landlord payments.
```

**One cosmetic thing I did not change.** On the trial balance, Temporary
Opening shows a credit of 256,400 but the balance column labels it `256,400
Dr`. The balance is being labelled by the account's natural side rather than
its actual one, so an asset holding a credit reads backwards. It only shows up
when something is already wrong, and after this load nothing sits there. Say if
you want it fixed properly.

---

## What revision 6 fixed

The records were right; the ledger under them was not. General ledger, journal
entries, trial balance, P&L, balance sheet and cash flow all read wrong, and
none of it was `api/statements.py` — that module queries the GL honestly, there
was just nothing right in the GL to find. Two causes, both in how revision 5
loaded:

**1. The rent posted as opening entries.** I set `is_opening = "Yes"` on all 69
invoices, which parks the debit in Temporary Opening and recognises no income.
That was the correct call while the manual Excel books still owned Nov-2025 to
Jul-2026 — posting income twice is worse. But you then emptied the site, so
AK-12 *is* the whole ledger and there is nothing left to double-count against.
The result was a P&L reading zero income, 256,400 stranded in Temporary Opening
on the trial balance, and a balance sheet netting itself to nothing.

Now they post as real income: item `Rent`, account **Rental Income**, the
building's cost centre, posted on the 1st and due on the 5th — the same shape
`api.finance` uses for a live invoice run, so August onward books identically.

**2. The head-lease cost was never in the ledger at all.** Not historically,
not going forward. Nothing in the application posts it: `Head Lease.payments`
is a schedule the cheque screens read, the MD dashboard counts unpaid Purchase
Invoices, and no code path anywhere creates one. So the P&L had revenue and no
cost of sales, and the spread — the only number this business turns on — could
not appear on any statement. `load_ak12_headlease.py` posts the nine months as
Purchase Invoices against AL MADAR (account **Head Lease Rent**) with matching
payments.

Both accounts are created on first run if they don't exist, filed under Direct
Income and Direct Expenses.

### What the statements read now

```
TRIAL BALANCE as at 2026-07-31        debit         credit
  Bank                             255,800.00    162,000.00
  Debtors                          256,400.00    255,800.00
  Creditors                        162,000.00    162,000.00
  Rental Income                            —     256,400.00
  Head Lease Rent                  162,000.00            —
                                   836,200.00    836,200.00   balanced

P&L  Nov-2025 → Jul-2026
  Rental Income                    256,400.00
  Head Lease Rent                 (162,000.00)
  Net                               94,400.00    margin 36.8%

BALANCE SHEET as at 2026-07-31
  Debtors                              600.00
  Bank                              93,800.00
  Assets                            94,400.00
  Equity (unclosed profit)          94,400.00    balanced, difference 0.00

CASH FLOW  opening 0.00 → closing 93,800.00     reconciles
  Operating   93,800.00   (Debtors 255,800.00, Creditors -162,000.00)
```

`verify` now runs those real endpoints and checks every figure, including that
the balance sheet balances, the cash flow reconciles, and Temporary Opening is
empty. Counting records only proved the load ran; this proves the ledger is
right.

**One thing to correct before you trust the cash flow.** The workbook has no
landlord payment history, so `ak12_headlease.csv` assumes each month was paid
on its accrual date, and says so in every row. The P&L is right either way —
accrual doesn't care when it was paid — but the cash flow and the payables
balance are only right once `paid_on`, `paid_amount` and `mode` come from the
landlord cheque book. Edit that CSV and re-run; rows with `paid_on` left blank
stay payable.

---

## Why the last three loads failed

**The fixes never reached the server.** I cloned `nikhil8288/darkbrown` fresh
this afternoon. `darkbrown/patches/` holds revision 2 of the load set:

- `tenancies.csv` still starts with a byte-order mark (`EF BB BF`)
- `import_tenancies.py` still opens it with `open(path)` — no encoding
- `load_ak12_history.py`, `ak12_history.csv`, `full_reset.py` are not there

So on every attempt `_rows()` read the first header as `\ufefftenant_name`,
`r.get("tenant_name")` returned `None` on all seven rows, the importer
refused every one, and the building came up with 8 units and no tenants —
exactly your screenshot. Revisions 3 and 4 fixed that; they were never
committed. Whether the zip unpacked to the wrong folder or GitHub Desktop
had the new files unticked, the result is the same: a deploy that changes
nothing and looks like a load that ran.

That is the failure this pack is built around. `check` reads the files
actually on the server and refuses to say READY unless each one is the
revision-10 copy. If `check` does not print `REVISION 10` and `READY`, the
deploy did not land and nothing else is worth trying.

**Second cause, once the first is fixed:** the site was never actually empty.
`demo.purge` only deletes Customers flagged `db_is_tenant`; the abandoned
full-portfolio load left ~270 unflagged, so every purge walked past them.
`reset` flags every party first, then purges wide, then sweeps the data
doctypes the purge does not list (Historical Monthly PL and seven others).

---

## Deploy

1. Unzip `ak12_rebuild_r10.zip` over the **repo root** — the folder that
   contains `darkbrown/` and `setup.py`. Everything lands under
   `darkbrown/patches/` and `darkbrown/api/`. Nothing to delete.
2. GitHub Desktop must show **exactly these 11 changes** — 3 new, 8 modified:

   ```
   new       darkbrown/patches/wipe_ledger_once.py
   modified  darkbrown/patches.txt
   new       darkbrown/patches/wipe_ledger.py
   new       darkbrown/patches/WIPE_CONSOLE.txt
   new       darkbrown/patches/ak12_doctor.py
   modified  darkbrown/patches/ak12_rebuild.py
   modified  darkbrown/patches/DEPLOY.md
   modified  darkbrown/api/cutover.py
   modified  darkbrown/demo/purge.py
   ```

   plus the revision-6 files if that deploy never landed — `check` will tell
   you. Fewer changes than expected means the unzip went to the wrong folder.
   New files are unticked by default in some GitHub Desktop versions — tick
   everything. Commit. Push. Deploy.
3. On the bench:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.check
```

Read it. Every file line must say `ok`; the verdict must say `READY`.
`OLD` on any line means step 2 did not land — go back to it. Then:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.ak12_rebuild.rebuild \
    --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
```

That runs check → reset → load → verify and stops at the first thing that
fails, printing why. The last block must read `ALL OK - AK-12 is loaded.`
with every line `ok`. Copy the whole output to me if anything else appears.

The four steps also exist separately (`check`, `reset`, `load`, `verify`),
plus `ak12_doctor.run`. `reset` on an empty site removes nothing. `load` on a
correctly loaded site creates nothing; on a site with foreign vouchers it now
refuses and tells you what it found. **Do not run `load` on its own to fix a
wrong ledger — it cannot. Only `reset` clears one.** That is what went wrong
this time.

The Data screen (`#/data` → Dry run / Load for real) now includes the
payment-history step and works on an already-reset site. It cannot reset;
that stays on the bench, deliberately.

---

## What you should see

```
Building                1       AK-12, head lease 216,000/yr to 30-Nov-2026
Unit                    8       7 Occupied, P-02 Vacant
Supplier                1       AL MADAR REAL ESTATE W.L.L
Customer                9       7 current tenants + Paracholakuzhi + Barouni
Tenancy Agreement      11       7 live, 4 expired (history)
Sales Invoice          69       rent, Nov-2025 to Jul-2026
Purchase Invoice        9       head-lease cost, same window
Payment Entry          78       69 receipts + 9 landlord payments
charged        256,400.00
collected      255,800.00
receivable         600.00       all Amani Guesmi, G-01B
accrued        162,000.00
paid_landlord  162,000.00
payable              0.00
```

then the statements block above, every line `ok`.

Verified against a reproduction of the broken ledger in your screenshot:
913,200 on each side, Landlord Rent 401,000, Temporary Opening 256,400, 155
journals. Against that, revision 7's `load` refuses and names all four
problems, the Data screen button refuses, `reset` takes the GL to zero
including the 17 legacy purchase invoices, and the reload produces the
statements above. A load crashed halfway is separately confirmed to resume.

Verified before packaging by running the shipped modules — the real
`demo/purge.py`, `load_customers`, `load_buildings`, `import_tenancies`,
`load_ak12_history`, `load_ak12_headlease`, the real `TenancyAgreement`
controller, the real `Building` cost-centre hook out of `hooks.py`, and the
real `api.statements` and `api.accounting` endpoints against a GL the stub
posts by double entry — against a
stubbed site carrying your current state (272 Customers, 2 flagged, AK-12
already loaded, 3 old arrears invoices, 40 Historical PL rows). Reset left
zero of everything; load produced the table above; a second `load` created
nothing. The same `check` run against your currently deployed revision-5 tree prints
`OLD` on `load_ak12_history.py`, `MISSING` on the three new files and
`NOT READY`, which is the point.

---

## The tenancy book — read this, some of it needs a decision

The workbook has signed terms for 3 of 8 units. Two of those three have
**expired** (F-01 on 31-May-2026, G-01B on 30-Jun-2026) with the tenant
still paying. Left as they were, the nightly job would flip both to Expired
and void the units — the same "everything Void" screen you have now, but
for a real reason. So:

| Unit | Rows | Status | Basis |
|---|---|---|---|
| F-01 | RN01 Jun-25→May-26 | Expired | signed, `DBI/AK12/F01/121-RN01/25` |
| F-01 | **RN02 placeholder** Jun-26→May-27 | Active | tenant still paying 5,000 — **RN02 needs scanning** |
| F-02 | Nov-25→Oct-26 | Active | **placeholder** — no contract in the master |
| G-01 | Nov-25→Oct-26 | Active | **placeholder** — no contract in the master |
| G-01A | Paracholakuzhi Nov-25→Dec-25 | Expired | prior tenant, receipt span |
| G-01A | Abdul Azeez Mar-26→Feb-27 | Active | signed, `DB/AK12/G01-A/930/26` |
| G-01B | RN01 Jan-26→Jun-26 | Expired | signed, `DB/AK12/G01-B/151/RN01/25` |
| G-01B | **RN02 placeholder** Jul-26→Dec-26 | Active | tenant still paying — **RN02 needs scanning**; 3,200 on paper, 3,000 paid |
| O-01 | Nov-25→Oct-26 | Active | **placeholder** — no contract in the master |
| P-01 | Nov-25→Oct-26 | Active | **placeholder** — no contract in the master |
| P-02 | Barouni Nov-25→Jun-26 | Expired | vacated Jul-2026, receipt span |

Every placeholder says so in its `notes` field. Six placeholder agreements
are the worklist for Aisha: F-01 RN02, G-01B RN02, and the four units with
no contract at all. Rents on all of them are verified against nine months of
receipts, so invoicing is right even where the dates are not.

**For Anoop:** the 69 invoices post as opening entries (`is_opening = Yes`,
Temporary Opening, no revenue account). Receivable and receipts are real;
income is not recognised, because those months belong to the manual books.
AK-12 therefore shows no ERP revenue before Aug-2026. July-2026 is in this
history — do **not** also run `run_july_billing` for AK-12. First live
invoice run is August.

**Also for Anoop:** G-01A rent fell 3,400 → 3,000 on the tenant change.
Confirm it was agreed, not a typo in the book.

---

## Still missing on the building

Municipality, floors, parking, lift — none in this workbook; they come off
the title deed. Water account 938533 has no field to live in (`Building` has
Kahramaa electricity only). Say if you want a custom field for it.

---

## The landlord side has no live counterpart yet

This pack loads the head-lease *history*. Going forward, `api.finance`
generates the tenant invoices for a month but nothing generates the matching
landlord Purchase Invoice — so from August the P&L will show rent income and
no rent cost until that exists. Two ways to close it, your call:

- a monthly job that raises the Purchase Invoice from each active Head Lease,
  mirroring `build_invoice_run` — the same review-then-issue shape, so Anoop
  approves the landlord side the way he approves the tenant side; or
- keep it manual in ERPNext and accept the P&L is only right after someone
  enters it.

Say which and I'll build it. Until then, the August P&L needs the landlord
invoice entered by hand or the spread will read 100% margin.

---

## The next building

Send the same workbook shape, plus the head-lease rent and, if you have it,
the landlord payment dates. `customers.json`, `buildings_payload.json`,
`tenancies.csv`, `ak12_history.csv` and `ak12_headlease.csv` are all lists —
the next building appends to them, and `EXPECT`, `EXPECT_STATEMENTS` and the
control totals in the two loaders move with it. `check` and `verify` then
prove that load the same way, statements included.
