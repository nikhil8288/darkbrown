# DarkBrown

Custom Frappe app for Dark Brown Real Estate.

Contains the **Managing Director Dashboard** — a native Frappe page at
`/app/md-dashboard`, role-restricted to Managing Director, wired to live DocTypes
(Tenant Rental Agreement, Landlord Contract, Building, Unit) and GL data
(Sales Invoice, Payment Entry, per-building Cost Centers).

## Install (Frappe Cloud)

1. Push this repo to GitHub.
2. Frappe Cloud → your bench → **Apps** → **Add App** → **From GitHub** → select this repo, branch `main`.
3. Once it appears, **Install** it on `darkbown.u.frappe.cloud`.
4. Site → **Actions → Clear Cache**, then hard-refresh (Ctrl+Shift+R).
5. Open `https://darkbown.u.frappe.cloud/app/md-dashboard`.

## Configure before first run

Edit `darkbrown/darkbrown/page/md_dashboard/md_dashboard.py`, top CONFIG block:
- `ACTIVE_AGR_STATUSES` — match your Tenant Rental Agreement status options.
- `_cost_center_for_building()` — match your per-building Cost Center names.

License: MIT
