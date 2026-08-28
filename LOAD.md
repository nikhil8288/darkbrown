# Loading the cutover data

Unpacks over the repo root. Everything lands in `darkbrown/patches/`.

    darkbrown/patches/tenancies.csv            266 live agreements
    darkbrown/patches/opening_arrears.csv       56 rows, 124,202.00
    darkbrown/patches/buildings_payload.json    23 buildings, 305 units
    darkbrown/patches/customers.json           432 tenant names
    darkbrown/patches/load_buildings.py        new — no bulk building importer existed
    darkbrown/patches/load_customers.py        new — no bulk customer importer existed
    darkbrown/patches/seed_opening_arrears.py  changed — EXPECTED_TOTAL reset
    darkbrown/patches/tenancy_name_map.csv     empty, and should stay empty
    darkbrown/patches/arrears_name_map.csv     empty, and should stay empty

## Why the bridge exists

The pack is built for reading and the importers are built for loading, and their
column contracts are not the same. Three gaps had to be closed:

**No bulk building or customer importer existed.** `portfolio.onboard_building` is
one atomic wizard call per building; `import_tenancies` refuses to auto-create a
Customer by design, because a typo would otherwise become a party with a ledger.
So 23 buildings, 305 units and 432 customers had no route in. Two new scripts
drive the existing endpoints rather than working around them.

**The old `opening_arrears.csv` was keyed on the superseded TWAR convention.** It
used room numbers as `R-nn`; the ledger — and therefore the unit master — uses
`F-nn`. 17 of its 65 unit keys would not have resolved. Regenerated through the
pack's unit master, so the mismatch cannot recur.

**`seed_opening_arrears.py` had `EXPECTED_TOTAL = 216519.00` hardcoded, and
`run()` aborts when the CSV disagrees.** That figure came from a July extraction
that does not tie to the current accounts. It is now 124,202.00, the Net Rent Due
at 31-Jul-26 control from REVENUE_WORKING. The guard is kept, not removed — it
still stops the run if the CSV drifts.

The name maps are empty on purpose. Customers are created with exactly the names
the pack normalised, so the importers' exact-name matching resolves every row
without a single override. Both were dry-run against the real modules: 266 of 266
tenancies clean, 56 of 56 arrears matched, zero unmatched names.

## Order

Purge comes **before** the load, not after — the purge removes tenant Customers
along with everything else, so loading first would delete the work. Step 1 is
what makes that safe.

    # 1. Back up first. This is the only undo.
    bench --site erp.darkbrown.qa backup --with-files

    # 2. Deploy
    git pull
    bench migrate          # the bank statement classification fields are pending
    bench build && bench clear-cache && bench restart

    # 3. See what the test data actually is
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.preview

    # 4. Remove it. wide=True because this site has only ever held Darkbrown data.
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.purge \
      --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA', 'wide': True}"

    # 5. Confirm it is empty — open Balance Sheet in the app. Everything should
    #    read zero and still say Balanced. A residual here means the purge left
    #    ledger behind, and you want to know that now rather than later.

    # 6. Tenants. Read 92_tenant_name_review.csv BEFORE this step.
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.run

    # 7. Buildings and units
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.run

    # 8. Tenancies
    bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.run

    # 9. Opening arrears
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.run

Never press **Seed** or **Rebuild** on the Data screen at `#/data` after step 4.
Those lay the demo portfolio back down. Purge is the only button you want there.

Every step has a dry run. Run it, read it, and only then run the real one. Each
loader is idempotent — a building or customer that already exists is skipped,
never merged — so a partial failure is safe to re-run.

## What to check when it is done

- Monthly rent roll **725,650**. The dry run computes this from the CSV and it
  matches the figure the business already knows, which is the strongest single
  check that the tenancy book landed correctly.
- Opening arrears **124,202** across 56 rows.
- 23 buildings, 305 units, 432 customers, 266 active tenancies.
- Balance sheet says Balanced; cash flow says Reconciled.
- Every tenancy will show `missing_items` and `activation_route = Routed for
  Approval`, because no QID or signed pack is in the system yet. That is not a
  fault — it is the worklist for the documentation drive, and it is why the
  tenancies were loaded Active rather than left to default to Pending Approval.

## What this does not load

Be clear-eyed about the gap before you go live:

- **No postdated cheque book, no security cheque register.** Source workbooks
  were not in the set. To be entered from the physical cheques.
- **No expense, accrual, other-income or owner-cheque history.** Pack files
  13–18 and 09 have no importer — `import_history` reads only
  `history_jul2026.csv`. The opening accrual journal at 31-Jul-26 (260,951.35),
  the owner rent balance (210,000) and the deposit liability (72,225) all still
  need posting. That is an opening journal Anoop can enter, or another importer.
- **One tenancy held back**, in `99_tenancies_held_back.csv`: MQ-56/P-01, a
  named tenant at nil rent for July only. Per AMM's own rule that is a vacant
  unit rather than a tenancy, and the importer refuses a zero rent. Confirm the
  rent or confirm the unit is vacant, then create it by hand.
- **266 placeholder expiry dates.** The ledger gives the month a tenancy was
  last seen, never the agreement expiry. Each end date is the annual anniversary
  of its real start date, rolled past cutover, and every row says so in `notes`.
  These get corrected as the signed agreements are scanned.
