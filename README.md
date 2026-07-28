# DarkBrown V2

Property management platform for DarkBrown Real Estate, built on Frappe/ERPNext.

ERPNext owns the ledger. No DocType in this app writes a GL entry directly;
invoicing and receipts go through Sales Invoice and Payment Entry so there is
one set of books.

## What is here

| Area | DocTypes |
|---|---|
| Portfolio | Building, Unit, Utility Meter |
| Agreements | Head Lease (+ payment schedule), Tenancy Agreement (+ charges), Agreement Amendment |
| Finance | Invoice Run (+ lines), Cheque, Cheque Book, Deposit Batch (+ lines), Security Deposit |
| Collections | Collection Case (+ invoices, contact log) |
| Operations | Move Out Case (+ meter readings), Maintenance Request (+ cost lines) |
| Documents | Document Register, Document Requirement, Party Document |
| Utilities | Utility Bill (+ allocations) |
| Settings | DBR Settings |

Landlords are Suppliers and tenants are Customers, each with identity fields
layered on. There is no separate party master.

## What is stubbed

Command Centre, Planning, and Owners and Shareholders exist as desk pages that
state what they will hold and what they are waiting on. They are deliberately
last: a dashboard over an unsettled workflow shows the wrong number
confidently.

## Install

    bench get-app darkbrown /path/to/darkbrown
    bench --site <site> install-app darkbrown
    bench --site <site> migrate
    bench build --app darkbrown

## Scheduled work

    daily_long   collection case sweeps, agreement and document expiry,
                 cheque presentation warnings
    cron 04:00   invoicing reminder on the configured generation day
