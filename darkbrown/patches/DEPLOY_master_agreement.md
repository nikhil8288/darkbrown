# DarkBrown cutover pack — revenue, owner rent, opex and key money

Unpacks over the repo root into `darkbrown/patches/`, replacing the AK-12-only
files there now.

    customers.json                       365 tenant names
    buildings_payload.json               23 buildings, 305 units, 22 head leases, 13 landlords
    tenancies.csv                        442 agreements (266 Active, 176 Expired)
    portfolio_history.csv                1,782 month-rows of tenant rent
    owner_rent_history.csv               99 month-rows of owner rent
    keymoney_history.csv                 25 rows, 1,419,551
    opex_journal.csv                     35 expense lines, 3,209,553.50
    96_vacancy_and_unresolved_rows.csv   126 ledger rows with no party
    97_open_items.csv                    10 items needing a decision
    98_master_grid_vs_ledger.csv         where the master workbook drifted
    99_tenancies_held_back.csv           3 rows the importer will refuse

No code changes in the pack. Column contracts come from
`import_tenancies.COLUMNS`, `load_buildings`, `load_customers`,
`portfolio.onboard_building`, `load_ak12_history` and the doctype JSONs.

## It reconciles

    tenant rent charged        5,283,008
    less collected             5,158,806
    outstanding                  124,202     <- ties to the pending control

    owner rent posted          3,669,500     <- ties to the P&L COGS line
    less paid                  3,459,500
    outstanding                  210,000     <- ties to the owner balance

    key money                  1,419,551     <- ties to its P&L opex line
    opex, all 35 lines         3,209,553.50  <- ties to the P&L opex total

Every control in the pack ties to a figure the business already knows. The
revenue side did not tie in the last drop; the reason is below.

## The revenue source changed, and that is what fixed it

Last drop the rent history came off the month grid in
`Master_Agreement_revenue_FINAL.xlsx`, which totalled 5,321,625 and left 38,617
unexplained against the 124,202 pending control.

`P_L_as_on_31_July_2026.xlsx` carries the line-level ledger the grid was built
from — 1,908 rows, one per unit per month. It totals **5,306,783**, which is
exactly the P&L revenue line, and it self-reconciles:

    RENT           5,306,783
    RECEIVED       4,838,469
    Advance          240,250
    Previous Due    -103,862
    Net Rent Due     124,202

`RENT − (RECEIVED + Advance − Previous Due Rcvd)` gives 124,202 to the fils.
The grid had drifted from its own source by 14,842. The history is now built
from the ledger, and `98_master_grid_vs_ledger.csv` shows the per-building
difference so it can be corrected at source.

Two sets of ledger rows are set aside, which is why the history posts 5,283,008
rather than 5,306,783:

- **125 rows labelled VACANT or EMPTY**, 19,275 charged and 11,175 received.
  There is no party to invoice.
- **One row, TV-20/F-02 Sep-2025, 4,500.** No tenancy in the master book covers
  that unit in that month.

Both are in `96_vacancy_and_unresolved_rows.csv`. Resolve them and the history
posts the full 5,306,783.

## Unit inventory is back to 305

The revenue ledger carries four units the master book never saw, all of them
vacancy rows only: TV-27/CABIN, TV-68/0-02, TWR-20/F-14 and TWR-20/F-16. Added
as Vacant with no asking rent. 301 + 4 = the 305 that loaded before.

## Order

Back up first; that is the only undo. Purge before loading.

    bench --site erp.darkbrown.qa backup --with-files

    bench --site erp.darkbrown.qa execute darkbrown.demo.run.purge \
      --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA', 'wide': True}"

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_customers.run

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_buildings.run

    bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.run

Head leases come in with the buildings — `onboard_building` creates one in the
same atomic pass when `annual_rent` and `start_date` are present.

Do not run `seed_opening_arrears`. Its CSV is empty and `EXPECTED_TOTAL` is
0.00, which is correct — arrears now come out of the rent history as charged
minus collected. Running both books the 124,202 twice.

## What to check when it lands

    Customer             365
    Supplier              13
    Building              23
    Unit                 305
    Head Lease            22
    Tenancy Agreement    442   (266 Active)

Rent roll 729,600 a month, head-lease rent 479,000, spread 250,600.

---

# OPEX

Per your instruction there is no monthly breakup, so the 35 P&L lines post as
one journal dated 31-Jul-2026 against **Historical Cutover Control**, exactly as
they read. `opex_journal.csv` carries a `treatment` column:

| Treatment | Lines | Amount | |
|---|---:|---:|---|
| `post` | 31 | 1,284,132.15 | to the control account |
| `excluded` | 1 | 1,419,551.00 | key money, posted per building instead |
| `hold` | 3 | 505,870.35 | not cash — needs Anoop |
| | **35** | **3,209,553.50** | ties to the P&L |

**Three lines are held back rather than routed to the control account, because
they never moved cash and posting them there would misstate the cutover
balance:**

- **ACCRUED EXPENSES 260,951.35.** This is a liability at 31-Jul-26, not a
  payment — salary 58,600, Kahramaa 92,151, wifi 4,449, software 7,610.35,
  Shakama maintenance 75,000 and the rest, per the Accrual sheet. It wants an
  accrued-expenses credit, not the cash control account.
- **DEPRECIATION FURNITURE AND FITTINGS 244,919.00.** Non-cash. Belongs against
  accumulated depreciation.
- **SHARAF-CAPITAL — PRE OPERATIVE EXP 150,000.00.** The line names itself
  capital and pre-operative. Expense or capitalise is a decision, not an import.

Give me the account for each and they go in with the rest.

# Key money

1,419,551 across 25 rows, by property and month, tying to its P&L line. It is
excluded from the opex journal so it is not counted twice — the verifier checks
that the excluded line and the key money file are equal to the fils.

Two parts of it cannot reach a cost centre yet:

- **TWAR-10 VILLAS, 620,000** — one group line over ten buildings, the same
  allocation problem as the villa rent.
- **OTHER PROPERTIES, 207,301** — Gharafa, Shakama and Aziziya, which are not
  among the 23 and have no cost centre. Remarks name them: Shakama 120K + 4.43K
  and Aziziya 50K in Dec-25, Shakama 20K and Aziziya 3K in Mar-26, Shakama 2,871
  in Jul-26.

The 592,250 across the eleven named portfolio buildings posts cleanly.

---

# The owner side

## Landlords

Thirteen across 23 buildings. Three own more than one:

| Landlord | Buildings |
|---|---|
| Al Adekhar Real Estate Company WLL | TWR-12, 16, 17, 19, 20, 35, 37, 39, 45, 58 |
| Abdulaziz Ibrahim A H Al-Ajail | TV-66, TV-68 |
| Mohd Ibrahim A E Al-Naemi | UG-169, UG-180 |

Eighteen head leases carry a landlord deposit, 544,000 in total, of which
320,000 is the ten villas at 32,000 each. DAJ-21, MR-130, MT-21, TV-20 and
UG-180 have none stated.

## Two duplicate labels the source resolves itself

`Owner_Agreement_Buildings` labels rows 5 and 9 of the ten-villa block both
**MARKHIYA 16**, with TWR-39 nowhere. `Owner_Rent_Pending` lists the same ten in
the same order with building numbers and calls the ninth *MARKHIYA 16 (Building
39)*. The lease dates confirm two distinct agreements. Mapped by position:

    row 5  ->  TWR-16   ends 2028-04-30   rent-free Mar-Apr 2026
    row 9  ->  TWR-39   ends 2028-09-30   rent-free Aug-Sep 2026

Same 16,000 either way, so the group total is unaffected; only the expiry and
rent-free window swap.

## UG-180 has no owner agreement

OAR-012 is grouped UG-169/180 at 30,000 a month, but the contract covers Umm
Guwailina 169 only and the workbook declined to split it. UG-180 loads 15 units
and 103,500 of revenue against no cost side.

## The ten-villa split is solved, not assumed

The group posts 640,000 as one line. Applying the contract instead — 16,000 a
month per villa from Mar-2026, less each villa's own rent-free window —
reproduces the source month for month:

    month      contractual   source posted
    2026-03         96,000          96,000
    2026-04         96,000               0
    2026-05        160,000         160,000
    2026-06        144,000         144,000
    2026-07        144,000         240,000
    TOTAL          640,000         640,000

Three of the five months match exactly and the total ties to the fils. The only
difference is that April's 96,000 was posted by the source in July. It is
accrued here in April, which is the month it relates to.

So `owner_rent_history.csv` is per building across 22 buildings, and villa rent
reaches its own cost centre. Nothing had to be assumed.

## Rent-free is not modelled

TV-27 two months, TV-66 and TV-68 one each, UG-20 seven days, plus four
staggered two-month windows across the villas. `Head Lease.rent_free_days`
exists but `onboard_building` does not pass it. As-incurred versus straight-line
is still open, and the villa windows alone are twenty building-months at 16,000.

## Umm Lakhba or Dafna

The owner agreements place TWR-19, 20, 37, 45 and 58 in Umm Lakhba; the revenue
workbook calls them Dafna. Document-as-authority says the agreement wins, so
`area_name` is Umm Lakhba. That changes how they group on the MD dashboard —
worth a word with Khayaz first.

---

# The history loaders are in this pack

Two new modules, both generalised from the AK-12 ones and both bench-execute
only, never registered as patches.

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_portfolio_history.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_portfolio_history.run

    bench --site erp.darkbrown.qa execute darkbrown.patches.load_portfolio_headlease.dry_run
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_portfolio_headlease.run

`load_portfolio_history.py` — tenant rent. Changed from the AK-12 version in
three places: the CSV, five-digit tags instead of three (three overflows past
999 and 1,782 rows would have collided), and the cost centre. That last one was
the real defect: `cc = L.cost_center("AK-12")` resolved once for the whole run,
so every building's rent would have landed on AK-12's cost centre. It now
resolves per row from `r["building"]`, caches, and aborts up front naming any
building without one. Controls 5,283,008.00 charged and 5,158,806.00 collected.

`load_portfolio_headlease.py` — owner rent. The AK-12 version already resolved
the cost centre per row, so only the CSV, the tag width and the controls
changed, plus the check now covers paid as well as accrued: a CSV that ties on
cost but not on cash aborts. Controls 3,669,500.00 accrued and 3,459,500.00
paid, leaving the 210,000 payable.

Both were executed against a stubbed Frappe on the real CSVs — row counts, tag
uniqueness across all 1,782 rows, control totals and posting dates all check
out. `py_compile` alone would not have caught the cost-centre rewrite.

Still no importer for `opex_journal.csv` or `keymoney_history.csv`. Those wait
on the three held opex lines having accounts.

# Decisions taken while converting, all reversible

**Building names are the codes.** `AK-12`, not `Ain Khalid 12`.

**Unit types mapped to the BR vocabulary.** `1 BHK`, `1BHK`, `1 BK`,
`1 BHK - Furnished` → `1BR`; `2 BHK` → `2BR`; `3 BHK` → `3BR`; `STUDIO` →
`Studio`. `Not Stated` loads blank. Near-misses would have imported silently as
blank. TV-20/O-02 disagrees with itself and takes 1BR.

**Expiry dates.** 157 of the 266 live agreements have a real contractual end
past cutover and use it. The other 109 take the anniversary of their real start
rolled past cutover and say `PLACEHOLDER EXPIRY` in `notes`.

**Status.** Active where still running at 31-Jul-2026, Expired otherwise. No
unit holds two live tenancies.

**Seven tenant names differed only in capitalisation** and fold to one Customer
each on the caps spelling. Left alone they would have created two Customers per
person and then matched ambiguously.

**Tenant security deposits are contract amounts, not receipts.** The deposit
column is zero on every revenue row. The 163 contract amounts load onto the
agreement; no Security Deposit records are created.

**Payment mode left blank where the contract does not state one** — 281 rows,
which the importer defaults to Cheque. TV-20's head lease is Quarterly from its
posting pattern of 39,000 every third month; the other 21 are Monthly.

# Three tenancies held back

All nil rent, and `import_tenancies` refuses `monthly_rent <= 0`:

    MAR-0067  MQ-56/P-01   MAHESH MAHADEV JADHAV   Jul-2026 only
    MAR-0424  UG-20/F-05   NAVAS FAMILY            May-2026 only
    MAR-0427  UG-20/F-07   NAVAS FAMILY            Mar-Apr 2026

MQ-56/P-01 is the same row held back last time. Confirm the rent or confirm the
unit was vacant, then enter by hand.

# Still not in the pack

- **No cheque book and no security cheque register.** The owner workbook gives
  cheque counts but not numbers, dates or banks.
- **Other income 69,750 and the tenant deposit, old rent and advance rent
  schedules** on the OTHER INCOME sheet are not loaded — they need income and
  liability accounts naming first.
