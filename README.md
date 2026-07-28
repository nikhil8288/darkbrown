# DarkBrown V2

Property management platform for DarkBrown Real Estate. Standalone — nothing
from V1 is carried across.

## Shape

The **prototype is the application**. It is served whole at `/darkbrown`, and
every business role lands there on login. Frappe's desk stays at `/app` for
Administrator only, for data admin.

ERPNext owns the ledger. No DocType here writes a GL entry directly.

    browser ──► /darkbrown ──► renderer.py ──► shell/index.html
                                   │              (prototype, unmodified
                                   │               except for five splices)
                                   └── injects window.DB_SEED

`api/app.py` reads real records and returns them in the exact array shapes the
prototype already renders — BUILDINGS, UNITS, CASES, JOBS, MOVEOUT. Where a
module has no data yet it is omitted, and that screen keeps its demonstration
values rather than showing zeros.

## Wired to live data

| Module | Reads | Writes |
|---|---|---|
| Portfolio | buildings, units, occupancy, void, arrears, head-lease | onboarding wizard, unit status |
| Operations | collection cases, maintenance, move-out | contact log, escalation, job lifecycle, move-out steps |

Everything else — Finance, Documents, Planning, Owners, Command Centre — still
renders from the prototype's own seeded values.

## Schema

26 DocTypes across agreements, finance, collections, operations, documents,
utilities and settings. Landlords are Suppliers and tenants are Customers with
identity fields layered on; there is no separate party master.

## Install

    bench get-app darkbrown /path/to/darkbrown
    bench --site <site> install-app darkbrown
    bench --site <site> migrate
    bench build --app darkbrown

Then sign in and go to `/darkbrown`.
