# AK-12 clean rebuild — revision 5

Empty the site, load one building with its 8 units, 9 tenants (7 current,
2 former), 11 agreements and nine months of real invoices and receipts, then
prove the result. One module runs it all: `darkbrown/patches/ak12_rebuild.py`.

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
revision-5 copy. If `check` does not print `REVISION 5` and `READY`, the
deploy did not land and nothing else is worth trying.

**Second cause, once the first is fixed:** the site was never actually empty.
`demo.purge` only deletes Customers flagged `db_is_tenant`; the abandoned
full-portfolio load left ~270 unflagged, so every purge walked past them.
`reset` flags every party first, then purges wide, then sweeps the data
doctypes the purge does not list (Historical Monthly PL and seven others).

---

## Deploy

1. Unzip `ak12_rebuild_r5.zip` over the **repo root** — the folder that
   contains `darkbrown/` and `setup.py`. Everything lands under
   `darkbrown/patches/` and `darkbrown/api/`. Nothing to delete.
2. GitHub Desktop must show **exactly these 11 changes** — 3 new, 8 modified:

   ```
   new       darkbrown/patches/ak12_rebuild.py
   new       darkbrown/patches/load_ak12_history.py
   new       darkbrown/patches/ak12_history.csv
   modified  darkbrown/patches/tenancies.csv
   modified  darkbrown/patches/customers.json
   modified  darkbrown/patches/opening_arrears.csv
   modified  darkbrown/patches/import_tenancies.py
   modified  darkbrown/patches/load_customers.py
   modified  darkbrown/patches/seed_opening_arrears.py
   modified  darkbrown/patches/DEPLOY.md
   modified  darkbrown/api/cutover.py
   ```

   Fewer means the unzip went to the wrong folder. New files are unticked
   by default in some GitHub Desktop versions — tick all 11. Commit. Push.
   Deploy.
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

The four steps also exist separately (`check`, `reset`, `load`, `verify`)
and every one is safe to repeat: `reset` on an empty site removes nothing,
`load` on a loaded site creates nothing.

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
Sales Invoice          69       Nov-2025 to Jul-2026, opening invoices
Payment Entry          69
charged        256,400.00
collected      255,800.00
outstanding        600.00       all Amani Guesmi, G-01B
```

Verified before packaging by running the shipped modules — the real
`demo/purge.py`, `load_customers`, `load_buildings`, `import_tenancies`,
`load_ak12_history`, the real `TenancyAgreement` controller — against a
stubbed site carrying your current state (272 Customers, 2 flagged, AK-12
already loaded, 3 old arrears invoices, 40 Historical PL rows). Reset left
zero of everything; load produced the table above; a second `load` created
nothing. The same `check` run against a clone of the repo as it is now
prints `OLD` on six files and `NOT READY`, which is the point.

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

## The next building

Send the same workbook shape. `customers.json`, `buildings_payload.json`,
`tenancies.csv` and the history CSV are lists — the next building appends
to them, and `EXPECT` in `ak12_rebuild.py` and the two control totals in
`load_ak12_history.py` move with it. `check` and `verify` then prove that
load the same way.
