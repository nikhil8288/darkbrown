# AK-12 only — load set

Every file replaces its namesake in `darkbrown/patches/`. Nothing else in the
portfolio is referenced. Add the next building by appending to these same files.

| File | Contents |
|---|---|
| `buildings_payload.json` | 1 building, 8 units, 1 head lease |
| `tenancies.csv` | 7 agreements |
| `opening_arrears.csv` | 3 rows, 600.00 total |
| `customers.json` | 7 tenants |
| `tenancy_name_map.csv` | header only |
| `arrears_name_map.csv` | header only |
| `seed_opening_arrears.py` | `EXPECTED_TOTAL` reset 124,202.00 → 600.00 |

## Why the .py file is in here

`seed_opening_arrears.run()` aborts if the CSV total does not equal
`EXPECTED_TOTAL`. It was 124,202.00 for the whole portfolio. Left alone it would
refuse the AK-12 file. Raise it every time you add a building.

## Deploy

1. Copy all seven files into `darkbrown/patches/`.
2. Commit in GitHub Desktop — tick every file, including the two name maps.
3. Deploy to `erp.darkbrown.qa`.
4. `#/data` → **Check** → **Dry run** → **Load for real**. Not Seed, not Rebuild.

## Expected result

23 buildings → 1. 305 units → 8. 266 tenancies → 7. Arrears 124,202.00 → 600.00.
The dry run will report those figures; anything else means the wrong file landed.

## Load order

Customers → Buildings and units → Tenancies → Arrears. The sequencer stops on the
first failure rather than continuing into a second, more confusing one.

## Adding the next building

Append to all four data files, then bump `EXPECTED_TOTAL` to the new arrears sum.
Two rules on `opening_arrears.csv`: the seeder tags invoices `[SEED-ARREARS-nnn]`
by row position, so **append only** — never insert, reorder or delete a row that
has already been loaded, or it re-posts as a duplicate invoice.

Tenancies are keyed on `(unit, start_date)`, so a re-run skips what it already
created. That also means a corrected start date reads as a new agreement: if a
tenancy is already live and its start date changes, delete the existing record
before reloading.

## Open on AK-12

- **F-01 and G-01B renewals.** Both agreements expired (31-May-2026, 30-Jun-2026)
  and both references end in `RN01`. Rent was collected on both through Jul-2026,
  so an `RN02` exists on paper. Loaded `Active` on the documented dates so
  occupancy is right today, but the expiry job will flip them and the units will
  read Vacant until the renewals are loaded.
- **Four units have no contract terms** — F-02, G-01, O-01, P-01. Tenant name and
  rent only; rents verified against nine months of receipts, dates are
  placeholders.
- **Building still missing** municipality, floors, parking spaces, lift. Off the
  title deed.
- **Water account 938533** has no home. `Building` has no water field and
  `Unit.water_meter_no` is per-unit, not a building account.
- **P-02 is genuinely vacant** from Jul-2026, not a missing agreement. No tenancy
  row, and that is correct.
- **For Anoop:** G-01A rent dropped 3400 → 3000 on the tenant change in Mar-2026;
  confirm that was agreed. Advances sat on G-01A (3000, Apr–Jun) and P-01 (2500,
  Apr–May).
