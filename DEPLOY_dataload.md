# DarkBrown data load — generated 7 Sep 2026

Unzip over the repo ROOT (the folder containing `darkbrown/`), overwrite.
Delete this .md before committing.

## Data files -> darkbrown/patches/
  buildings_payload.json    22 buildings, 296 units
  customers.json            599 tenant names
  tenancies.csv             219 signed agreements
  portfolio_history.csv     1,773 rent rows  (5,283,008 charged / 4,822,794 received)
  owner_rent_history.csv    145 rows          (3,669,500 accrued / 3,459,500 paid)
  opening_arrears.csv       header only - the rent history carries the arrears
  pdc_outgoing.csv          432 cheques, 13,820,500
  pdc_name_map.csv          cheque payee -> supplier
  pdc_building_map.csv      empty; fill in if a cheque needs a building override
  tenancy_name_map.csv      empty; fill in for any tenant that will not name-match
  arrears_name_map.csv      empty
  history_jul2026.csv       163 rows for the MD dashboard trend charts
  opex_journal.csv          3,060 expense lines, 3,209,553.15

## Code
  darkbrown/api/cutover.py                   step descriptions updated to the new counts
  darkbrown/patches/load_portfolio_history.py  EXPECTED_COLLECTED 5,158,806 -> 4,822,794
  darkbrown/patches/seed_pdc_outgoing.py       EXPECTED_TOTAL 538,000 -> 13,820,500
  darkbrown/utils/chart_of_accounts.py         adds "Key Money - Other"
  darkbrown/patches/load_opex.py               NEW - posts the expenses as one
                                               journal a month to Historical
                                               Cutover Control

## Order
Run the cutover dry run first. It reports without writing:
    bench --site erp.darkbrown.qa execute darkbrown.api.cutover.run_dry
Then the Data screen, or run_load.

Expenses now load as step 5 of the cutover. To check first:
    bench --site erp.darkbrown.qa execute darkbrown.patches.load_opex.dry_run
